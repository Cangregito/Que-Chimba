param(
    [string]$DbHost = "localhost",
    [string]$DbPort = "5432",
    [string]$DbName = "que_chimba",
    [string]$DbUser = "postgres",
    [System.Security.SecureString]$DbPassword,
    [string]$PgBinDir = "",
    [string]$BackupRoot = "",
    [string]$BackupFile = "",
    [string]$LogRoot = "",
    [switch]$DryRun,
    [switch]$SkipSafetyBackup,
    [string]$AlertWebhookUrl = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Convert-SecureStringToPlain([System.Security.SecureString]$SecureValue) {
    if (-not $SecureValue) {
        return ""
    }

    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

function Write-Log([string]$Level, [string]$Message) {
    $line = "{0} [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $Message
    Add-Content -Path $logFile -Value $line
    Write-Host $line
}

function Resolve-ExePath([string]$ExeName) {
    if (-not [string]::IsNullOrWhiteSpace($PgBinDir)) {
        $candidate = Join-Path $PgBinDir $ExeName
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    $cmd = Get-Command $ExeName -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    $roots = @("C:\Program Files\PostgreSQL", "C:\Program Files (x86)\PostgreSQL")
    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root)) {
            continue
        }
        $exeCandidates = Get-ChildItem -Path $root -Filter $ExeName -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match "\\bin\\" }
        $first = $exeCandidates | Select-Object -First 1
        if ($first) {
            return $first.FullName
        }
    }

    return ""
}

function Send-Alert([string]$Status, [string]$Message, [hashtable]$Extra = @{}) {
    if ([string]::IsNullOrWhiteSpace($AlertWebhookUrl)) {
        return
    }

    try {
        $payload = [ordered]@{
            system = "que-chimba"
            component = "postgres-rollback"
            status = $Status
            message = $Message
            timestamp = (Get-Date).ToString("o")
            dbName = $DbName
        }
        foreach ($k in $Extra.Keys) {
            $payload[$k] = $Extra[$k]
        }
        Invoke-RestMethod -Method Post -Uri $AlertWebhookUrl -ContentType "application/json" -Body ($payload | ConvertTo-Json -Depth 6) | Out-Null
    }
    catch {
        Write-Log "WARN" ("No se pudo enviar alerta webhook: " + $_.Exception.Message)
    }
}

function Escape-DbIdentifier([string]$Value) {
    return '"' + ($Value -replace '"', '""') + '"'
}

$DbPasswordPlain = Convert-SecureStringToPlain -SecureValue $DbPassword
if ([string]::IsNullOrWhiteSpace($DbPasswordPlain)) {
    $DbPasswordPlain = [Environment]::GetEnvironmentVariable("DB_PASSWORD")
}
if ([string]::IsNullOrWhiteSpace($DbPasswordPlain)) {
    throw "DbPassword no fue proporcionado y DB_PASSWORD no existe en entorno."
}

if ([string]::IsNullOrWhiteSpace($BackupRoot)) {
    $BackupRoot = Join-Path $PSScriptRoot "..\..\backups\postgres"
}
if ([string]::IsNullOrWhiteSpace($LogRoot)) {
    $LogRoot = Join-Path $PSScriptRoot "..\..\logs\ops"
}

$null = New-Item -ItemType Directory -Path $LogRoot -Force
$logFile = Join-Path $LogRoot ("rollback-postgres-" + (Get-Date -Format "yyyy-MM") + ".log")

$psqlExe = Resolve-ExePath -ExeName "psql.exe"
if ([string]::IsNullOrWhiteSpace($psqlExe)) {
    throw "No se encontro 'psql.exe'. Ajusta PATH o usa -PgBinDir."
}

if ([string]::IsNullOrWhiteSpace($BackupFile)) {
    $candidates = Get-ChildItem -Path $BackupRoot -Filter "backup_*.zip" -File |
        Sort-Object LastWriteTime -Descending
    $selected = $candidates | Select-Object -Skip 1 -First 1
    if (-not $selected) {
        $selected = $candidates | Select-Object -First 1
    }
    if (-not $selected) {
        throw "No hay backups disponibles en $BackupRoot"
    }
    $BackupFile = $selected.FullName
}

if (-not (Test-Path -LiteralPath $BackupFile)) {
    throw "El archivo de backup no existe: $BackupFile"
}

$backupBaseName = [System.IO.Path]::GetFileNameWithoutExtension($BackupFile)
$backupMetaFile = Join-Path (Split-Path -Parent $BackupFile) ($backupBaseName + ".json")
if (Test-Path -LiteralPath $backupMetaFile) {
    $backupMeta = Get-Content -LiteralPath $backupMetaFile -Raw | ConvertFrom-Json
    $expectedHash = [string]($backupMeta.sha256)
    if (-not [string]::IsNullOrWhiteSpace($expectedHash)) {
        $realHash = (Get-FileHash -LiteralPath $BackupFile -Algorithm SHA256).Hash
        if ($realHash -ne $expectedHash) {
            throw "Checksum SHA256 no coincide para el backup seleccionado."
        }
    }
}
else {
    Write-Log "WARN" "El backup no tiene metadata .json asociada; se continua con verificacion minima."
}

$timestamp = Get-Date -Format "yyyyMMddHHmmss"
$restoreDb = ("qc_rollback_restore_" + $timestamp).ToLower()
$safetyDb = ($DbName + "_pre_rollback_" + $timestamp).ToLower()
$tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("qc_rollback_" + [Guid]::NewGuid().ToString("N"))
$null = New-Item -ItemType Directory -Path $tmpDir -Force
$prevPgPassword = [Environment]::GetEnvironmentVariable("PGPASSWORD")
$swapped = $false

function Invoke-Psql([string]$Database, [string]$Sql, [switch]$Raw) {
    $psqlCmdArgs = @(
        "-h", $DbHost,
        "-p", $DbPort,
        "-U", $DbUser,
        "-d", $Database,
        "-v", "ON_ERROR_STOP=1"
    )

    if ($Raw) {
        $psqlCmdArgs += @("-t", "-A")
    }

    $psqlCmdArgs += @("-c", $Sql)
    $output = & $psqlExe @psqlCmdArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        $tail = ($output | Select-Object -Last 10) -join "`n"
        throw "psql fallo en DB '$Database'. Detalle: $tail"
    }
    return ($output | Out-String).Trim()
}

try {
    [Environment]::SetEnvironmentVariable("PGPASSWORD", $DbPasswordPlain)
    Write-Log "INFO" ("Rollback solicitado sobre DB '" + $DbName + "' usando backup: " + $BackupFile)

    if (-not $SkipSafetyBackup) {
        $backupScript = Join-Path $PSScriptRoot "backup_postgres.ps1"
        if (Test-Path -LiteralPath $backupScript) {
            Write-Log "INFO" "Generando safety backup previo al rollback..."
            & $backupScript -DbHost $DbHost -DbPort $DbPort -DbName $DbName -DbUser $DbUser -BackupRoot $BackupRoot | Out-Null
        }
    }

    Expand-Archive -LiteralPath $BackupFile -DestinationPath $tmpDir -Force
    $sqlFile = Get-ChildItem -Path $tmpDir -Filter "*.sql" -File | Select-Object -First 1
    if (-not $sqlFile) {
        throw "No se encontro .sql dentro del backup zip"
    }

    Invoke-Psql -Database "postgres" -Sql ("CREATE DATABASE " + (Escape-DbIdentifier $restoreDb) + ";") | Out-Null
    Write-Log "INFO" ("DB temporal creada: " + $restoreDb)

    $restoreArgs = @(
        "-h", $DbHost,
        "-p", $DbPort,
        "-U", $DbUser,
        "-d", $restoreDb,
        "-v", "ON_ERROR_STOP=1",
        "-f", $sqlFile.FullName
    )
    $restoreOut = & $psqlExe @restoreArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        $tail = ($restoreOut | Select-Object -Last 10) -join "`n"
        throw "Restore SQL fallo. Detalle: $tail"
    }

    $tableCountText = Invoke-Psql -Database $restoreDb -Sql "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';" -Raw
    $tableCount = 0
    [void][int]::TryParse($tableCountText.Trim(), [ref]$tableCount)
    if ($tableCount -le 0) {
        throw "La DB restaurada no contiene tablas en schema public."
    }

    $rowCountText = Invoke-Psql -Database $restoreDb -Sql "SELECT COALESCE(SUM(n_live_tup), 0) FROM pg_stat_user_tables;" -Raw
    $rowCount = 0
    [void][int]::TryParse($rowCountText.Trim(), [ref]$rowCount)

    Write-Log "INFO" ("Restore temporal validado. Tablas=" + $tableCount + ", filas estimadas=" + $rowCount)

    if ($DryRun) {
        Write-Log "INFO" "DryRun activo: no se intercambiaron bases. El rollback es viable con este backup."
        Send-Alert -Status "ok" -Message "Rollback dry-run validado correctamente" -Extra @{ backupFile = $BackupFile; restoreDb = $restoreDb; tableCount = $tableCount; rowCount = $rowCount }
        return
    }

    Invoke-Psql -Database "postgres" -Sql ("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('" + $DbName + "', '" + $restoreDb + "') AND pid <> pg_backend_pid();") | Out-Null
    Invoke-Psql -Database "postgres" -Sql ("ALTER DATABASE " + (Escape-DbIdentifier $DbName) + " RENAME TO " + (Escape-DbIdentifier $safetyDb) + ";") | Out-Null
    Invoke-Psql -Database "postgres" -Sql ("ALTER DATABASE " + (Escape-DbIdentifier $restoreDb) + " RENAME TO " + (Escape-DbIdentifier $DbName) + ";") | Out-Null
    $swapped = $true

    Write-Log "INFO" ("Rollback aplicado con exito. DB anterior preservada como: " + $safetyDb)
    Send-Alert -Status "ok" -Message "Rollback aplicado correctamente" -Extra @{ backupFile = $BackupFile; preservedDb = $safetyDb }
}
catch {
    Write-Log "ERROR" $_.Exception.Message
    Send-Alert -Status "error" -Message $_.Exception.Message -Extra @{ backupFile = $BackupFile; restoreDb = $restoreDb }
    throw
}
finally {
    try {
        [Environment]::SetEnvironmentVariable("PGPASSWORD", $DbPasswordPlain)
        if (-not $swapped) {
            Invoke-Psql -Database "postgres" -Sql ("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '" + $restoreDb + "' AND pid <> pg_backend_pid();") | Out-Null
            Invoke-Psql -Database "postgres" -Sql ("DROP DATABASE IF EXISTS " + (Escape-DbIdentifier $restoreDb) + ";") | Out-Null
            Write-Log "INFO" "DB temporal eliminada"
        }
    }
    catch {
        Write-Log "WARN" "No se pudo limpiar la DB temporal automaticamente"
    }

    try {
        Remove-Item -LiteralPath $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    catch {
    }

    [Environment]::SetEnvironmentVariable("PGPASSWORD", $prevPgPassword)
}
