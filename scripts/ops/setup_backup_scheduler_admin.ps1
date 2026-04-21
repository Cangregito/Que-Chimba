#Requires -Version 5.1
param(
    [string]$TaskPrefix  = "QueChimba",
    [string]$BackupTime  = "02:00",
    [string]$VerifyTime  = "03:00",
    [string]$VerifyDay   = "Sunday",
    [string]$RunAsUser   = "",
    [switch]$SkipTestRun
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Write-Host "=== Setup Backup Scheduler Profesional ===" -ForegroundColor Cyan
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) { Write-Host "[OK] Admin." -ForegroundColor Green } else { Write-Host "[INFO] No admin. Solo Paso 1 (XML patch)." -ForegroundColor Yellow }
$scriptDir      = Split-Path -Parent $MyInvocation.MyCommand.Path
$backupWrapper  = Join-Path $scriptDir "_scheduled_backup.cmd"
$verifyWrapper  = Join-Path $scriptDir "_scheduled_verify.cmd"
$backupTaskName = "$TaskPrefix-Postgres-Backup"
$verifyTaskName = "$TaskPrefix-Postgres-VerifyRestore"
foreach ($w in @($backupWrapper, $verifyWrapper)) { if (-not (Test-Path -LiteralPath $w)) { throw "No existe: $w" } }

Write-Host "" ; Write-Host "[PASO 1] XML patch (bateria + StartWhenAvailable)..." -ForegroundColor Cyan

function Set-XmlNode { param([xml]$doc, [System.Xml.XmlElement]$parent, [string]$localName, [string]$value)
    $ns = "http://schemas.microsoft.com/windows/2004/02/mit/task"
    $node = $parent[$localName]
    if (-not $node) {
        $node = $doc.CreateElement($localName, $ns)
        $parent.AppendChild($node) | Out-Null
    }
    $node.InnerText = $value
}

function Patch-TaskXml { param([string]$TaskName,[string]$WrapperPath)
    $rawXml = (schtasks /Query /XML /TN $TaskName 2>&1) -join "`n"
    if ($LASTEXITCODE -ne 0) { throw "No se pudo exportar XML de $TaskName" }
    [xml]$doc = $rawXml
    $s = $doc.Task.Settings
    Set-XmlNode $doc $s "DisallowStartIfOnBatteries" "false"
    Set-XmlNode $doc $s "StopIfGoingOnBatteries"     "false"
    Set-XmlNode $doc $s "StartWhenAvailable"          "true"
    Set-XmlNode $doc $s "MultipleInstancesPolicy"     "IgnoreNew"
    Set-XmlNode $doc $s "ExecutionTimeLimit"          "PT4H"
    Set-XmlNode $doc $s "WakeToRun"                   "false"
    $exec = $doc.Task.Actions.Exec
    if ($exec) { $exec.Command = "cmd.exe"; $exec.Arguments = "/c `"$WrapperPath`"" }
    $tmp = [System.IO.Path]::ChangeExtension([System.IO.Path]::GetTempFileName(),".xml")
    $doc.Save($tmp)
    $out = schtasks /Create /XML $tmp /TN $TaskName /F 2>&1
    $code = $LASTEXITCODE
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    if ($code -ne 0) { throw "Error reimportando $TaskName`: $($out -join " ")" }
    Write-Host "  [OK] $TaskName" -ForegroundColor Green
}

Patch-TaskXml -TaskName $backupTaskName -WrapperPath $backupWrapper
Patch-TaskXml -TaskName $verifyTaskName -WrapperPath $verifyWrapper

Write-Host "" ; Write-Host "[PASO 2] S4U + Highest (solo si admin)..." -ForegroundColor Cyan
if ($isAdmin) {
    if ([string]::IsNullOrWhiteSpace($RunAsUser)) {
        $lu = (Get-WmiObject Win32_ComputerSystem -EA SilentlyContinue).UserName
        $RunAsUser = if ($lu) { $lu } else { "$env:USERDOMAIN\$env:USERNAME" }
    }
    Write-Host "  Usuario: $RunAsUser" -ForegroundColor Cyan
    $principal = New-ScheduledTaskPrincipal -UserId $RunAsUser -LogonType S4U -RunLevel Highest
    foreach ($tn in @($backupTaskName,$verifyTaskName)) {
        try { Set-ScheduledTask -TaskName $tn -Principal $principal | Out-Null; Write-Host "  [OK] $tn - S4U/Highest" -ForegroundColor Green }
        catch { Write-Host "  [WARN] $tn`: $($_.Exception.Message)" -ForegroundColor Yellow }
    }
} else {
    Write-Host "  [INFO] Omitido. Para S4U: ejecutar como Administrador." -ForegroundColor Yellow
}

Write-Host "" ; Write-Host "=== Estado ===" -ForegroundColor Cyan
$rows = foreach ($tn in @($backupTaskName,$verifyTaskName)) {
    $t  = Get-ScheduledTask     -TaskName $tn -EA SilentlyContinue
    $ti = Get-ScheduledTaskInfo -TaskName $tn -EA SilentlyContinue
    if ($t) {
        [PSCustomObject]@{
            Tarea          = $tn -replace "$TaskPrefix-Postgres-",""
            LogonType      = $t.Principal.LogonType
            RunLevel       = $t.Principal.RunLevel
            BateriaOK      = ($t.Settings.DisallowStartIfOnBatteries -eq "false" -or $t.Settings.DisallowStartIfOnBatteries -eq $false)
            StartWhenAvail = ($t.Settings.StartWhenAvailable -eq "true" -or $t.Settings.StartWhenAvailable -eq $true)
            ProximoRun     = if ($ti.NextRunTime -gt [datetime]::Now) { $ti.NextRunTime.ToString("dd/MM HH:mm") } else { "?" }
        }
    }
}
$rows | Format-Table -AutoSize

if (-not $SkipTestRun) {
    Write-Host "[TEST] Backup via Task Scheduler..." -ForegroundColor Cyan
    Start-ScheduledTask -TaskName $backupTaskName
    $w = 0 ; while ($w -lt 50) { Start-Sleep 3; $w+=3; if ((Get-ScheduledTask -TaskName $backupTaskName -EA SilentlyContinue).State -ne "Running") { break } }
    $ti = Get-ScheduledTaskInfo -TaskName $backupTaskName
    if ($ti.LastTaskResult -eq 0) { Write-Host "[OK] Backup OK: $($ti.LastRunTime)" -ForegroundColor Green }
    else { Write-Host ("[WARN] 0x{0:X8} | {1}" -f [uint32]$ti.LastTaskResult, $ti.LastRunTime) -ForegroundColor Yellow }
}

Write-Host "" ; Write-Host "=== COMPLETADO ===" -ForegroundColor Green
Write-Host "  Backup:  $BackupTime diario | Verify: $VerifyTime cada $VerifyDay"
Write-Host "  Bateria no bloquea | StartWhenAvailable activo"
if ($isAdmin) { Write-Host "  S4U + Highest: activo (sin sesion requerida)" -ForegroundColor Green }
else          { Write-Host "  Para S4U: ejecutar como Administrador" -ForegroundColor Yellow }
Write-Host "  Logs: logs\ops\backup-postgres-yyyy-MM.log"
