param(
    [string]$DbHost = "localhost",
    [string]$DbPort = "5432",
    [string]$DbUser = "postgres",
    [System.Security.SecureString]$DbPassword,
    [string]$PgBinDir = "",
    [string]$BackupRoot = "",
    [string]$LogRoot = "",
    [string]$AlertWebhookUrl = "",
    [string]$AlertWhatsAppTo = "",
    [string]$BridgeUrl = "",
    [string]$BridgeApiToken = "",
    [switch]$AlertOnSuccess,
    [string]$BackupFile = "",
    [string]$RestoreDbPrefix = "qc_restore_verify"
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
$logFile = Join-Path $LogRoot ("verify-restore-postgres-" + (Get-Date -Format "yyyy-MM") + ".log")

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
            component = "postgres-restore-verify"
            status = $Status
            message = $Message
            timestamp = (Get-Date).ToString("o")
            dbHost = $DbHost
            dbPort = $DbPort
            dbUser = $DbUser
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

function Send-AlertWhatsApp([string]$Status, [string]$Message) {
    if ([string]::IsNullOrWhiteSpace($AlertWhatsAppTo)) {
        return
    }

    $resolvedBridgeUrl = if (-not [string]::IsNullOrWhiteSpace($BridgeUrl)) {
        $BridgeUrl
    }
    elseif (-not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable("BAILEYS_BRIDGE_URL"))) {
        [Environment]::GetEnvironmentVariable("BAILEYS_BRIDGE_URL")
    }
    else {
        "http://localhost:3001"
    }

    $resolvedBridgeUrl = $resolvedBridgeUrl.Trim().TrimEnd("/")
    if ([string]::IsNullOrWhiteSpace($resolvedBridgeUrl)) {
        return
    }

    $resolvedToken = if (-not [string]::IsNullOrWhiteSpace($BridgeApiToken)) {
        $BridgeApiToken
    }
    else {
        [Environment]::GetEnvironmentVariable("BAILEYS_BRIDGE_API_TOKEN")
    }

    try {
        $headers = @{ "Content-Type" = "application/json" }
        if (-not [string]::IsNullOrWhiteSpace($resolvedToken)) {
            $headers["x-bridge-token"] = $resolvedToken
        }

        $text = "[QC RESTORE/$Status] $Message"
        $body = @{ to = $AlertWhatsAppTo; text = $text } | ConvertTo-Json -Depth 4
        Invoke-RestMethod -Method Post -Uri ($resolvedBridgeUrl + "/api/send-text") -Headers $headers -Body $body | Out-Null
    }
    catch {
        Write-Log "WARN" ("No se pudo enviar alerta WhatsApp: " + $_.Exception.Message)
    }
}

$psqlExe = Resolve-ExePath -ExeName "psql.exe"
if ([string]::IsNullOrWhiteSpace($psqlExe)) {
    throw "No se encontro 'psql.exe'. Ajusta PATH o usa -PgBinDir 'C:\Program Files\PostgreSQL\16\bin'."
}

if ([string]::IsNullOrWhiteSpace($BackupFile)) {
    $latest = Get-ChildItem -Path $BackupRoot -Filter "backup_*.zip" -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $latest) {
        throw "No hay backups zip en $BackupRoot"
    }
    $BackupFile = $latest.FullName
}

if (-not (Test-Path -LiteralPath $BackupFile)) {
    throw "El archivo de backup no existe: $BackupFile"
}

$backupBaseName = [System.IO.Path]::GetFileNameWithoutExtension($BackupFile)
$backupMetaFile = Join-Path (Split-Path -Parent $BackupFile) ($backupBaseName + ".json")
if (Test-Path -LiteralPath $backupMetaFile) {
    try {
        $backupMeta = Get-Content -LiteralPath $backupMetaFile -Raw | ConvertFrom-Json
        $expectedHash = [string]($backupMeta.sha256)
        if (-not [string]::IsNullOrWhiteSpace($expectedHash)) {
            $realHash = (Get-FileHash -LiteralPath $BackupFile -Algorithm SHA256).Hash
            if ($realHash -ne $expectedHash) {
                throw "Checksum SHA256 no coincide para el backup seleccionado. Posible corrupcion del archivo."
            }
        }
    }
    catch {
        throw "No se pudo validar metadata/checksum del backup: $($_.Exception.Message)"
    }
}
else {
    Write-Log "WARN" "El backup no tiene metadata .json asociada; se continua sin checksum externo."
}

$tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("qc_restore_" + [Guid]::NewGuid().ToString("N"))
$null = New-Item -ItemType Directory -Path $tmpDir -Force

$timestamp = Get-Date -Format "yyyyMMddHHmmss"
$restoreDb = ($RestoreDbPrefix + "_" + $timestamp).ToLower()
$prevPgPassword = [Environment]::GetEnvironmentVariable("PGPASSWORD")

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
    Write-Log "INFO" "Iniciando verificacion de restore con backup: $BackupFile"

    Expand-Archive -LiteralPath $BackupFile -DestinationPath $tmpDir -Force
    $sqlFile = Get-ChildItem -Path $tmpDir -Filter "*.sql" -File | Select-Object -First 1
    if (-not $sqlFile) {
        throw "No se encontro .sql dentro del backup zip"
    }

    Invoke-Psql -Database "postgres" -Sql ("CREATE DATABASE `"$restoreDb`";") | Out-Null
    Write-Log "INFO" "DB temporal creada: $restoreDb"

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
    if ($rowCount -lt 0) {
        throw "No se pudo validar el volumen estimado de filas restauradas."
    }

    Write-Log "INFO" ("Verificacion OK. Tablas public detectadas: " + $tableCount)
    Write-Log "INFO" ("Filas estimadas restauradas: " + $rowCount)
    Write-Log "INFO" "Prueba de restore finalizada correctamente"
    if ($AlertOnSuccess) {
        Send-Alert -Status "ok" -Message "Restore verification finalizada correctamente" -Extra @{
            backupFile = $BackupFile
            restoreDb = $restoreDb
            tableCount = $tableCount
            rowCount = $rowCount
        }
        Send-AlertWhatsApp -Status "ok" -Message ("Restore OK sobre backup: " + [System.IO.Path]::GetFileName($BackupFile))
    }
}
catch {
    Write-Log "ERROR" $_.Exception.Message
    Send-Alert -Status "error" -Message $_.Exception.Message -Extra @{
        backupFile = $BackupFile
        restoreDb = $restoreDb
    }
    Send-AlertWhatsApp -Status "error" -Message $_.Exception.Message
    throw
}
finally {
    try {
        [Environment]::SetEnvironmentVariable("PGPASSWORD", $DbPasswordPlain)
        Invoke-Psql -Database "postgres" -Sql ("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '" + $restoreDb + "' AND pid <> pg_backend_pid();") | Out-Null
        Invoke-Psql -Database "postgres" -Sql ("DROP DATABASE IF EXISTS `"$restoreDb`";") | Out-Null
        Write-Log "INFO" "DB temporal eliminada"
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
