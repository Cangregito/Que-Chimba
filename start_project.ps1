param(
    [switch]$WithDocker,
    [switch]$WithRegression
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = $PSScriptRoot
$runAll = Join-Path $root "run_all.ps1"

if (-not (Test-Path -LiteralPath $runAll)) {
    throw "No se encontro run_all.ps1 en: $runAll"
}

$runParams = @{}

if (-not $WithDocker) {
    $runParams["SkipDocker"] = $true
}

if (-not $WithRegression) {
    $runParams["SkipRegressionTests"] = $true
}

Write-Host "[INFO] Iniciando proyecto con run_all.ps1..." -ForegroundColor Cyan
& $runAll @runParams
