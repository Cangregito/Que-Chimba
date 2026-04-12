param(
    [string]$DbHost = "localhost",
    [string]$DbPort = "5432",
    [string]$DbName = "que_chimba",
    [string]$DbUser = "postgres",
    [System.Security.SecureString]$DbPassword,
    [string]$PgBinDir = "",
    [string]$BackupRoot = "",
    [string]$LogRoot = "",
    [string]$MirrorRoot = "",
    [string]$AlertWebhookUrl = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$backupScript = Join-Path $scriptDir "backup_postgres.ps1"
$verifyScript = Join-Path $scriptDir "verify_restore_postgres.ps1"

if (-not (Test-Path -LiteralPath $backupScript)) {
    throw "No existe script: $backupScript"
}
if (-not (Test-Path -LiteralPath $verifyScript)) {
    throw "No existe script: $verifyScript"
}

$common = @{
    DbHost = $DbHost
    DbPort = $DbPort
    DbUser = $DbUser
    DbPassword = $DbPassword
    PgBinDir = $PgBinDir
    BackupRoot = $BackupRoot
    LogRoot = $LogRoot
    AlertWebhookUrl = $AlertWebhookUrl
}

if (-not [string]::IsNullOrWhiteSpace($DbName)) {
    $common["DbName"] = $DbName
}
if (-not [string]::IsNullOrWhiteSpace($MirrorRoot)) {
    $common["MirrorRoot"] = $MirrorRoot
}

Write-Host "[INFO] DR drill: generando backup..." -ForegroundColor Cyan
& $backupScript @common -AlertOnSuccess
if ($LASTEXITCODE -ne 0) {
    throw "Fallo etapa de backup en DR drill."
}

$verifyParams = @{
    DbHost = $DbHost
    DbPort = $DbPort
    DbUser = $DbUser
    DbPassword = $DbPassword
    PgBinDir = $PgBinDir
    BackupRoot = $BackupRoot
    LogRoot = $LogRoot
    AlertWebhookUrl = $AlertWebhookUrl
}

Write-Host "[INFO] DR drill: verificando restore..." -ForegroundColor Cyan
& $verifyScript @verifyParams -AlertOnSuccess
if ($LASTEXITCODE -ne 0) {
    throw "Fallo etapa de restore verification en DR drill."
}

Write-Host "[OK] DR drill completado con exito." -ForegroundColor Green
