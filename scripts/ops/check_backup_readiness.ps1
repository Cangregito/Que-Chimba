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
    [string]$AlertWebhookUrl = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($BackupRoot)) {
    $BackupRoot = Join-Path $PSScriptRoot "..\..\backups\postgres"
}
if ([string]::IsNullOrWhiteSpace($LogRoot)) {
    $LogRoot = Join-Path $PSScriptRoot "..\..\logs\ops"
}
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

$checks = New-Object System.Collections.Generic.List[object]

function Add-Check([string]$Name, [bool]$Ok, [string]$Detail) {
    $checks.Add([PSCustomObject]@{
        Check = $Name
        Ok = $Ok
        Detail = $Detail
    }) | Out-Null
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

function Test-WritePath([string]$PathToTest) {
    try {
        $null = New-Item -ItemType Directory -Path $PathToTest -Force
        $tmp = Join-Path $PathToTest (".__write_test_" + [Guid]::NewGuid().ToString("N") + ".tmp")
        Set-Content -LiteralPath $tmp -Value "ok" -Encoding UTF8
        Remove-Item -LiteralPath $tmp -Force
        return $true
    }
    catch {
        return $false
    }
}

$pgDumpPath = Resolve-ExePath -ExeName "pg_dump.exe"
$pgDumpDetail = if ($pgDumpPath) { $pgDumpPath } else { "No encontrado" }
Add-Check "pg_dump disponible" (-not [string]::IsNullOrWhiteSpace($pgDumpPath)) $pgDumpDetail

$psqlPath = Resolve-ExePath -ExeName "psql.exe"
$psqlDetail = if ($psqlPath) { $psqlPath } else { "No encontrado" }
Add-Check "psql disponible" (-not [string]::IsNullOrWhiteSpace($psqlPath)) $psqlDetail

$schtasks = Get-Command schtasks.exe -ErrorAction SilentlyContinue
$schtasksSource = if ($schtasks) { $schtasks.Source } else { "No encontrado" }
Add-Check "schtasks disponible" ($null -ne $schtasks) $schtasksSource

$backupWritable = Test-WritePath -PathToTest $BackupRoot
Add-Check "Escritura BackupRoot" $backupWritable $BackupRoot

$logWritable = Test-WritePath -PathToTest $LogRoot
Add-Check "Escritura LogRoot" $logWritable $LogRoot

if (-not [string]::IsNullOrWhiteSpace($MirrorRoot)) {
    $mirrorWritable = Test-WritePath -PathToTest $MirrorRoot
    Add-Check "Escritura MirrorRoot" $mirrorWritable $MirrorRoot
}
else {
    Add-Check "MirrorRoot configurado" $true "Opcional (no configurado)"
}

$dbPasswordPresent = -not [string]::IsNullOrWhiteSpace($DbPasswordPlain)
if ($dbPasswordPresent) {
    Add-Check "DB_PASSWORD disponible" $true "OK (oculta)"
}
else {
    Add-Check "DB_PASSWORD disponible" $false "Falta DB_PASSWORD"
}

if ($dbPasswordPresent -and -not [string]::IsNullOrWhiteSpace($psqlPath)) {
    $prev = [Environment]::GetEnvironmentVariable("PGPASSWORD")
    try {
        [Environment]::SetEnvironmentVariable("PGPASSWORD", $DbPasswordPlain)
        $psqlArgs = @("-h", $DbHost, "-p", $DbPort, "-U", $DbUser, "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-t", "-A", "-c", "SELECT 1;")
        $out = & $psqlPath @psqlArgs 2>&1
        if ($LASTEXITCODE -eq 0 -and (($out | Out-String).Trim() -match "1")) {
            Add-Check "Conexion PostgreSQL" $true ("{0}:{1} usuario={2}" -f $DbHost, $DbPort, $DbUser)
        }
        else {
            $tail = ($out | Select-Object -Last 3) -join " | "
            Add-Check "Conexion PostgreSQL" $false "Fallo conexion: $tail"
        }
    }
    catch {
        Add-Check "Conexion PostgreSQL" $false $_.Exception.Message
    }
    finally {
        [Environment]::SetEnvironmentVariable("PGPASSWORD", $prev)
    }
}
else {
    Add-Check "Conexion PostgreSQL" $false "Omitida (falta DB_PASSWORD o psql.exe)"
}

if (-not [string]::IsNullOrWhiteSpace($AlertWebhookUrl)) {
    try {
        $probe = @{ source = "que-chimba"; event = "readiness-check"; timestamp = (Get-Date).ToString("o") } | ConvertTo-Json
        Invoke-RestMethod -Method Post -Uri $AlertWebhookUrl -ContentType "application/json" -Body $probe | Out-Null
        Add-Check "Webhook de alertas" $true "Webhook responde"
    }
    catch {
        Add-Check "Webhook de alertas" $false ("No responde: " + $_.Exception.Message)
    }
}
else {
    Add-Check "Webhook de alertas" $true "Opcional (no configurado)"
}

$failed = @($checks | Where-Object { -not $_.Ok })

Write-Host ""
Write-Host "=== RESULTADO READINESS BACKUPS ===" -ForegroundColor Cyan
$checks | Format-Table -AutoSize
Write-Host ""

if ($failed.Count -gt 0) {
    Write-Host "FALTANTES / BLOQUEANTES:" -ForegroundColor Yellow
    foreach ($f in $failed) {
        Write-Host ("- " + $f.Check + ": " + $f.Detail)
    }
    exit 2
}

Write-Host "Todo listo para operar backups + verify + tareas." -ForegroundColor Green
exit 0
