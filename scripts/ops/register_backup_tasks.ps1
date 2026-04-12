param(
    [string]$TaskPrefix = "QueChimba",
    [string]$BackupScriptPath = "",
    [string]$VerifyScriptPath = "",
    [string]$BackupArguments = "",
    [string]$VerifyArguments = "",
    [string]$BackupTime = "02:00",
    [string]$VerifyTime = "03:00",
    [string]$VerifyDay = "SUN"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($BackupScriptPath)) {
    $BackupScriptPath = Join-Path $PSScriptRoot "backup_postgres.ps1"
}
if ([string]::IsNullOrWhiteSpace($VerifyScriptPath)) {
    $VerifyScriptPath = Join-Path $PSScriptRoot "verify_restore_postgres.ps1"
}

if (-not (Test-Path -LiteralPath $BackupScriptPath)) {
    throw "No existe backup script: $BackupScriptPath"
}
if (-not (Test-Path -LiteralPath $VerifyScriptPath)) {
    throw "No existe verify script: $VerifyScriptPath"
}

$backupTaskName = "$TaskPrefix-Postgres-Backup"
$verifyTaskName = "$TaskPrefix-Postgres-VerifyRestore"

$backupWrapper = Join-Path $PSScriptRoot "_scheduled_backup.cmd"
$verifyWrapper = Join-Path $PSScriptRoot "_scheduled_verify.cmd"

$backupWrapperContent = "@echo off`r`n" +
    "setlocal`r`n" +
    ('powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0backup_postgres.ps1" {0}' -f $BackupArguments).Trim() +
    "`r`nendlocal`r`n"
$verifyWrapperContent = "@echo off`r`n" +
    "setlocal`r`n" +
    ('powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0verify_restore_postgres.ps1" {0}' -f $VerifyArguments).Trim() +
    "`r`nendlocal`r`n"

Set-Content -LiteralPath $backupWrapper -Value $backupWrapperContent -Encoding ASCII
Set-Content -LiteralPath $verifyWrapper -Value $verifyWrapperContent -Encoding ASCII

Write-Host "[INFO] Registrando tarea diaria de backup: $backupTaskName"
$backupProc = Start-Process -FilePath "schtasks.exe" -ArgumentList @(
    "/Create",
    "/SC", "DAILY",
    "/TN", $backupTaskName,
    "/TR", ('"{0}"' -f $backupWrapper),
    "/ST", $BackupTime,
    "/F"
) -NoNewWindow -Wait -PassThru
if ($backupProc.ExitCode -ne 0) {
    throw "No se pudo registrar tarea: $backupTaskName"
}

Write-Host "[INFO] Registrando tarea semanal de verificacion: $verifyTaskName"
$verifyProc = Start-Process -FilePath "schtasks.exe" -ArgumentList @(
    "/Create",
    "/SC", "WEEKLY",
    "/D", $VerifyDay,
    "/TN", $verifyTaskName,
    "/TR", ('"{0}"' -f $verifyWrapper),
    "/ST", $VerifyTime,
    "/F"
) -NoNewWindow -Wait -PassThru
if ($verifyProc.ExitCode -ne 0) {
    throw "No se pudo registrar tarea: $verifyTaskName"
}

Write-Host "[OK] Tareas registradas correctamente."
Write-Host "[INFO] Para revisar:" 
Write-Host "       schtasks /Query /TN $backupTaskName /V /FO LIST"
Write-Host "       schtasks /Query /TN $verifyTaskName /V /FO LIST"
