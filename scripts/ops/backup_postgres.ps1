param(
    [string]$DbHost = "localhost",
    [string]$DbPort = "5432",
    [string]$DbName = "que_chimba",
    [string]$DbUser = "postgres",
    [System.Security.SecureString]$DbPassword,
    [string]$PgBinDir = "",
    [string]$BackupRoot = "",
    [string]$MirrorRoot = "",
    [string]$LogRoot = "",
    [string]$AlertWebhookUrl = "",
    [string]$AlertWhatsAppTo = "",
    [string]$BridgeUrl = "",
    [string]$BridgeApiToken = "",
    [switch]$EnableOneDriveMirror,
    [string]$OneDriveBackupRoot = "Backups\QueChimba",
    [int]$OneDriveDailyRetentionDays = 7,
    [int]$OneDriveWeeklyRetentionDays = 28,
    [switch]$AlertOnSuccess,
    [int]$RetentionDays = 14,
    [int]$KeepLatest = 30
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
if ([string]::IsNullOrWhiteSpace($MirrorRoot)) {
    $MirrorRoot = [Environment]::GetEnvironmentVariable("OPS_MIRROR_ROOT")
}
if ([string]::IsNullOrWhiteSpace($LogRoot)) {
    $LogRoot = Join-Path $PSScriptRoot "..\..\logs\ops"
}

$null = New-Item -ItemType Directory -Path $BackupRoot -Force
$null = New-Item -ItemType Directory -Path $LogRoot -Force

$logFile = Join-Path $LogRoot ("backup-postgres-" + (Get-Date -Format "yyyy-MM") + ".log")

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
            component = "postgres-backup"
            status = $Status
            message = $Message
            timestamp = (Get-Date).ToString("o")
            db = $DbName
            host = $DbHost
            port = $DbPort
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

        $text = "[QC BACKUP/$Status] $Message"
        $body = @{ to = $AlertWhatsAppTo; text = $text } | ConvertTo-Json -Depth 4
        Invoke-RestMethod -Method Post -Uri ($resolvedBridgeUrl + "/api/send-text") -Headers $headers -Body $body | Out-Null
    }
    catch {
        Write-Log "WARN" ("No se pudo enviar alerta WhatsApp: " + $_.Exception.Message)
    }
}

function Get-OneDrivePath {
    $candidates = @(
        [Environment]::GetEnvironmentVariable("OneDrive"),
        [Environment]::GetEnvironmentVariable("OneDriveConsumer"),
        [Environment]::GetEnvironmentVariable("OneDriveCommercial"),
        (Join-Path $env:USERPROFILE "OneDrive"),
        (Join-Path $env:USERPROFILE "OneDrive - Personal")
    )

    foreach ($path in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace($path) -and (Test-Path -LiteralPath $path)) {
            return $path
        }
    }

    $regRoot = "HKCU:\Software\Microsoft\OneDrive\Accounts"
    if (Test-Path -LiteralPath $regRoot) {
        $accounts = Get-ChildItem -LiteralPath $regRoot -ErrorAction SilentlyContinue
        foreach ($account in $accounts) {
            $folder = (Get-ItemProperty -Path $account.PSPath -Name "UserFolder" -ErrorAction SilentlyContinue).UserFolder
            if (-not [string]::IsNullOrWhiteSpace($folder) -and (Test-Path -LiteralPath $folder)) {
                return $folder
            }
        }
    }

    return ""
}

function Test-OneDriveSpace([string]$OneDrivePath, [long]$RequiredBytes = 0, [int]$MinFreeMB = 500) {
    if ([string]::IsNullOrWhiteSpace($OneDrivePath) -or -not (Test-Path -LiteralPath $OneDrivePath)) {
        return $false
    }

    try {
        $driveName = (Get-Item -LiteralPath $OneDrivePath).PSDrive.Name
        if ([string]::IsNullOrWhiteSpace($driveName)) {
            return $false
        }
        $drive = Get-PSDrive -Name $driveName -ErrorAction Stop
        $minimum = [Math]::Max([long]$RequiredBytes, [long]$MinFreeMB * 1MB)
        return [long]$drive.Free -ge $minimum
    }
    catch {
        return $false
    }
}

function Copy-ToOneDrive([string]$ZipPath, [string]$JsonPath, [string]$Bucket = "daily") {
    $oneDrivePath = Get-OneDrivePath
    if ([string]::IsNullOrWhiteSpace($oneDrivePath)) {
        Write-Log "WARN" "OneDrive no detectado. Se omite copia en nube."
        return $false
    }

    if (-not (Test-Path -LiteralPath $ZipPath)) {
        Write-Log "ERROR" ("No existe ZIP para copiar a OneDrive: " + $ZipPath)
        return $false
    }

    $zipSize = (Get-Item -LiteralPath $ZipPath).Length
    if (-not (Test-OneDriveSpace -OneDrivePath $oneDrivePath -RequiredBytes $zipSize)) {
        Write-Log "WARN" "OneDrive sin espacio suficiente. Se omite copia en nube."
        return $false
    }

    $targetDir = Join-Path $oneDrivePath $OneDriveBackupRoot
    $targetDir = Join-Path $targetDir $Bucket

    try {
        $null = New-Item -ItemType Directory -Path $targetDir -Force

        $zipTarget = Join-Path $targetDir ([System.IO.Path]::GetFileName($ZipPath))
        Copy-Item -LiteralPath $ZipPath -Destination $zipTarget -Force

        if (Test-Path -LiteralPath $JsonPath) {
            $jsonTarget = Join-Path $targetDir ([System.IO.Path]::GetFileName($JsonPath))
            Copy-Item -LiteralPath $JsonPath -Destination $jsonTarget -Force
        }

        $localSize = (Get-Item -LiteralPath $ZipPath).Length
        $remoteSize = (Get-Item -LiteralPath $zipTarget -ErrorAction SilentlyContinue).Length
        if ($localSize -ne $remoteSize) {
            Write-Log "ERROR" ("Copia OneDrive incompleta. Local=" + $localSize + ", OneDrive=" + $remoteSize)
            return $false
        }

        Write-Log "INFO" ("Backup copiado a OneDrive (" + $Bucket + "): " + [System.IO.Path]::GetFileName($ZipPath))
        return $true
    }
    catch {
        Write-Log "WARN" ("No se pudo copiar backup a OneDrive: " + $_.Exception.Message)
        return $false
    }
}

function Remove-OneDriveExpired([string]$Bucket, [int]$RetentionDays) {
    if ($RetentionDays -le 0) {
        return
    }

    $oneDrivePath = Get-OneDrivePath
    if ([string]::IsNullOrWhiteSpace($oneDrivePath)) {
        return
    }

    $bucketDir = Join-Path (Join-Path $oneDrivePath $OneDriveBackupRoot) $Bucket
    if (-not (Test-Path -LiteralPath $bucketDir)) {
        return
    }

    try {
        $cutoff = (Get-Date).AddDays(-1 * [Math]::Abs($RetentionDays))
        $expired = Get-ChildItem -Path $bucketDir -Filter "backup_*.zip" -File |
            Where-Object { $_.LastWriteTime -lt $cutoff }

        foreach ($item in $expired) {
            $base = [System.IO.Path]::GetFileNameWithoutExtension($item.Name)
            Remove-Item -LiteralPath $item.FullName -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath (Join-Path $bucketDir ($base + ".json")) -Force -ErrorAction SilentlyContinue
            Write-Log "INFO" ("OneDrive eliminado por retencion (" + $Bucket + "): " + $item.Name)
        }
    }
    catch {
        Write-Log "WARN" ("No se pudo limpiar OneDrive/" + $Bucket + ": " + $_.Exception.Message)
    }
}

$pgDumpExe = Resolve-ExePath -ExeName "pg_dump.exe"
if ([string]::IsNullOrWhiteSpace($pgDumpExe)) {
    throw "No se encontro 'pg_dump.exe'. Ajusta PATH o usa -PgBinDir 'C:\Program Files\PostgreSQL\16\bin'."
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$sqlPath = Join-Path $BackupRoot ("backup_" + $DbName + "_" + $timestamp + ".sql")
$zipPath = Join-Path $BackupRoot ("backup_" + $DbName + "_" + $timestamp + ".zip")
$jsonPath = Join-Path $BackupRoot ("backup_" + $DbName + "_" + $timestamp + ".json")

$prevPgPassword = [Environment]::GetEnvironmentVariable("PGPASSWORD")
try {
    [Environment]::SetEnvironmentVariable("PGPASSWORD", $DbPasswordPlain)
    Write-Log "INFO" "Iniciando backup de '$DbName' en ${DbHost}:$DbPort"

    $dumpArgs = @(
        "--host", $DbHost,
        "--port", $DbPort,
        "--username", $DbUser,
        "--dbname", $DbName,
        "--no-owner",
        "--no-privileges",
        "--encoding", "UTF8",
        "--format", "plain",
        "--file", $sqlPath
    )

    $dumpOutput = & $pgDumpExe @dumpArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        $tail = ($dumpOutput | Select-Object -Last 10) -join "`n"
        throw "pg_dump fallo con codigo $LASTEXITCODE. Detalle: $tail"
    }

    Compress-Archive -LiteralPath $sqlPath -DestinationPath $zipPath -CompressionLevel Optimal -Force
    Remove-Item -LiteralPath $sqlPath -Force

    $hash = Get-FileHash -LiteralPath $zipPath -Algorithm SHA256
    $fileInfo = Get-Item -LiteralPath $zipPath
    $meta = [ordered]@{
        createdAt = (Get-Date).ToString("o")
        db = $DbName
        host = $DbHost
        port = $DbPort
        user = $DbUser
        backupFile = $fileInfo.Name
        backupPath = $fileInfo.FullName
        backupSizeBytes = $fileInfo.Length
        sha256 = $hash.Hash
        retentionDays = $RetentionDays
        keepLatest = $KeepLatest
    }
    $meta | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $jsonPath -Encoding UTF8

    Write-Log "INFO" ("Backup generado: " + $fileInfo.Name + " (" + $fileInfo.Length + " bytes)")

    $oneDriveDailyCopied = $false
    if ($EnableOneDriveMirror) {
        $oneDriveDailyCopied = Copy-ToOneDrive -ZipPath $zipPath -JsonPath $jsonPath -Bucket "daily"

        if ((Get-Date).DayOfWeek -eq [System.DayOfWeek]::Sunday) {
            $null = Copy-ToOneDrive -ZipPath $zipPath -JsonPath $jsonPath -Bucket "weekly"
        }
        if ((Get-Date).Day -eq 1) {
            $null = Copy-ToOneDrive -ZipPath $zipPath -JsonPath $jsonPath -Bucket "monthly"
        }

        Remove-OneDriveExpired -Bucket "daily" -RetentionDays $OneDriveDailyRetentionDays
        Remove-OneDriveExpired -Bucket "weekly" -RetentionDays $OneDriveWeeklyRetentionDays
    }

    if (-not [string]::IsNullOrWhiteSpace($MirrorRoot)) {
        $null = New-Item -ItemType Directory -Path $MirrorRoot -Force
        Copy-Item -LiteralPath $zipPath -Destination (Join-Path $MirrorRoot $fileInfo.Name) -Force
        Copy-Item -LiteralPath $jsonPath -Destination (Join-Path $MirrorRoot ([System.IO.Path]::GetFileName($jsonPath))) -Force
        Write-Log "INFO" ("Backup replicado en espejo: " + $MirrorRoot)
    }

    $cutoff = (Get-Date).AddDays(-1 * [Math]::Abs($RetentionDays))
    $expired = Get-ChildItem -Path $BackupRoot -Filter "backup_*.zip" -File |
        Where-Object { $_.LastWriteTime -lt $cutoff }

    foreach ($item in $expired) {
        $base = [System.IO.Path]::GetFileNameWithoutExtension($item.Name)
        Remove-Item -LiteralPath $item.FullName -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath (Join-Path $BackupRoot ($base + ".json")) -Force -ErrorAction SilentlyContinue
        Write-Log "INFO" ("Backup eliminado por antiguedad: " + $item.Name)
    }

    if ($KeepLatest -gt 0) {
        $allBackups = Get-ChildItem -Path $BackupRoot -Filter "backup_*.zip" -File |
            Sort-Object LastWriteTime -Descending

        $toRemove = $allBackups | Select-Object -Skip $KeepLatest
        foreach ($item in $toRemove) {
            $base = [System.IO.Path]::GetFileNameWithoutExtension($item.Name)
            Remove-Item -LiteralPath $item.FullName -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath (Join-Path $BackupRoot ($base + ".json")) -Force -ErrorAction SilentlyContinue
            Write-Log "INFO" ("Backup eliminado por politica KeepLatest: " + $item.Name)
        }
    }

    Write-Log "INFO" "Backup finalizado correctamente"
    if ($AlertOnSuccess) {
        Send-Alert -Status "ok" -Message "Backup finalizado correctamente" -Extra @{
            backupFile = $fileInfo.Name
            backupSizeBytes = $fileInfo.Length
            sha256 = $hash.Hash
            mirrorRoot = $MirrorRoot
            oneDriveMirrorEnabled = [bool]$EnableOneDriveMirror
            oneDriveDailyCopied = [bool]$oneDriveDailyCopied
        }
        Send-AlertWhatsApp -Status "ok" -Message ("Backup listo: " + $fileInfo.Name)
    }
}
catch {
    Write-Log "ERROR" $_.Exception.Message
    Send-Alert -Status "error" -Message $_.Exception.Message -Extra @{}
    Send-AlertWhatsApp -Status "error" -Message $_.Exception.Message
    throw
}
finally {
    [Environment]::SetEnvironmentVariable("PGPASSWORD", $prevPgPassword)
}
