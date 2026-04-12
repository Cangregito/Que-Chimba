param(
    [string]$TaskPrefix = "QueChimba",
    [string]$DbHost = "localhost",
    [string]$DbPort = "5432",
    [string]$DbName = "que_chimba",
    [string]$DbUser = "postgres",
    [string]$BackupTime = "02:00",
    [string]$VerifyTime = "03:00",
    [string]$VerifyDay = "SUN",
    [string]$MirrorRoot = "",
    [string]$AlertWhatsAppTo = "",
    [string]$AlertWebhookUrl = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$registerScript = Join-Path $scriptDir "register_backup_tasks.ps1"
$readinessScript = Join-Path $scriptDir "check_backup_readiness.ps1"

if (-not (Test-Path -LiteralPath $registerScript)) {
    throw "No existe script: $registerScript"
}
if (-not (Test-Path -LiteralPath $readinessScript)) {
    throw "No existe script: $readinessScript"
}

if ([string]::IsNullOrWhiteSpace($MirrorRoot)) {
    $oneDrive = [Environment]::GetEnvironmentVariable("OneDrive")
    if (-not [string]::IsNullOrWhiteSpace($oneDrive)) {
        $MirrorRoot = Join-Path $oneDrive "QueChimba\backups_mirror"
    }
    else {
        $MirrorRoot = Join-Path $scriptDir "..\..\backups_mirror"
    }
}

$null = New-Item -ItemType Directory -Path $MirrorRoot -Force

[Environment]::SetEnvironmentVariable("OPS_MIRROR_ROOT", $MirrorRoot, "User")
$env:OPS_MIRROR_ROOT = $MirrorRoot

if ([string]::IsNullOrWhiteSpace($AlertWhatsAppTo)) {
    $AlertWhatsAppTo = [Environment]::GetEnvironmentVariable("WHATSAPP_ADMIN")
}

$bridgeUrl = [Environment]::GetEnvironmentVariable("BAILEYS_BRIDGE_URL")
if ([string]::IsNullOrWhiteSpace($bridgeUrl)) {
    $bridgeUrl = "http://localhost:3001"
}

$bridgeToken = [Environment]::GetEnvironmentVariable("BAILEYS_BRIDGE_API_TOKEN")

$backupArgs = @(
    "-DbHost", $DbHost,
    "-DbPort", $DbPort,
    "-DbName", $DbName,
    "-DbUser", $DbUser,
    "-AlertOnSuccess"
)

$verifyArgs = @(
    "-DbHost", $DbHost,
    "-DbPort", $DbPort,
    "-DbUser", $DbUser,
    "-AlertOnSuccess"
)

if (-not [string]::IsNullOrWhiteSpace($AlertWebhookUrl)) {
    $backupArgs += @("-AlertWebhookUrl", ('"' + $AlertWebhookUrl + '"'))
    $verifyArgs += @("-AlertWebhookUrl", ('"' + $AlertWebhookUrl + '"'))
}

if (-not [string]::IsNullOrWhiteSpace($AlertWhatsAppTo)) {
    $backupArgs += @("-AlertWhatsAppTo", $AlertWhatsAppTo, "-BridgeUrl", $bridgeUrl)
    $verifyArgs += @("-AlertWhatsAppTo", $AlertWhatsAppTo, "-BridgeUrl", $bridgeUrl)

    if (-not [string]::IsNullOrWhiteSpace($bridgeToken)) {
        $backupArgs += @("-BridgeApiToken", $bridgeToken)
        $verifyArgs += @("-BridgeApiToken", $bridgeToken)
    }
}

$backupArgsText = ($backupArgs -join " ")
$verifyArgsText = ($verifyArgs -join " ")

Write-Host "[INFO] Ejecutando readiness antes de programar tareas..." -ForegroundColor Cyan
& $readinessScript -DbHost $DbHost -DbPort $DbPort -DbName $DbName -DbUser $DbUser -MirrorRoot $MirrorRoot -AlertWebhookUrl $AlertWebhookUrl
if ($LASTEXITCODE -ne 0) {
    throw "Readiness no cumplio prerequisitos."
}

Write-Host "[INFO] Registrando tareas con mirror y alertas..." -ForegroundColor Cyan
& $registerScript -TaskPrefix $TaskPrefix -BackupTime $BackupTime -VerifyTime $VerifyTime -VerifyDay $VerifyDay -BackupArguments $backupArgsText -VerifyArguments $verifyArgsText
if ($LASTEXITCODE -ne 0) {
    throw "No se pudieron registrar tareas."
}

Write-Host "[OK] Automatizacion configurada." -ForegroundColor Green
Write-Host ("[INFO] MirrorRoot: " + $MirrorRoot)
if (-not [string]::IsNullOrWhiteSpace($AlertWhatsAppTo)) {
    Write-Host ("[INFO] Alertas WhatsApp a: " + $AlertWhatsAppTo)
}
else {
    Write-Host "[WARN] WHATSAPP_ADMIN no configurado. Alertas por WhatsApp no activadas."
}
if (-not [string]::IsNullOrWhiteSpace($AlertWebhookUrl)) {
    Write-Host ("[INFO] AlertWebhookUrl: " + $AlertWebhookUrl)
}
