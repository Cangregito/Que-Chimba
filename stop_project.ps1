param(
    [switch]$WithDockerDown
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = $PSScriptRoot

function Stop-ProcessByCommandNeedle([string]$needle) {
    $needleText = (" " + [string]$needle + " ").Trim().ToLower()
    $procList = Get-CimInstance Win32_Process |
        Where-Object {
            $cmd = [string]($_.CommandLine)
            if ([string]::IsNullOrWhiteSpace($cmd)) { return $false }
            return $cmd.ToLower().Contains($needleText)
        }

    foreach ($m in $procList) {
        try {
            Stop-Process -Id $m.ProcessId -Force -ErrorAction Stop
            Write-Host "[OK]   Proceso detenido: PID $($m.ProcessId) -> $($m.Name)" -ForegroundColor Green
        }
        catch {
            Write-Host "[WARN] No se pudo detener PID $($m.ProcessId): $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
}

Write-Host "[INFO] Deteniendo procesos del proyecto..." -ForegroundColor Cyan

# Flask app en ventanas lanzadas por run_all.ps1
Stop-ProcessByCommandNeedle "bot_empanadas\\app.py"

# Bridge iniciado con npm start en carpeta baileys_bridge
Stop-ProcessByCommandNeedle "baileys_bridge"

if ($WithDockerDown) {
    Write-Host "[INFO] Ejecutando docker compose down..." -ForegroundColor Cyan
    Push-Location $root
    try {
        docker compose down | Out-Host
    }
    finally {
        Pop-Location
    }
}

Write-Host "[OK]   Flujo de apagado completado." -ForegroundColor Green
