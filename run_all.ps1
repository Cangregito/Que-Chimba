param(
    [string]$DbHost = "localhost",
    [string]$DbPort = "5432",
    [string]$DbName = "que_chimba",
    [string]$DbUser = "postgres",
    [PSCredential]$DbCredential,
    [string]$N8nWebhookUrl = "http://localhost:5678/webhook/pedido-alerta",
    [switch]$SkipDocker,
    [switch]$ShowDemoCreds
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = $PSScriptRoot
$bridgeDir = Join-Path $root "baileys_bridge"
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$flaskApp = Join-Path $root "bot_empanadas\app.py"
$bridgeEnv = Join-Path $bridgeDir ".env"
$bridgeEnvExample = Join-Path $bridgeDir ".env.example"

function Write-Info([string]$msg) {
    Write-Host "[INFO] $msg" -ForegroundColor Cyan
}

function Write-Ok([string]$msg) {
    Write-Host "[OK]   $msg" -ForegroundColor Green
}

function Write-Warn([string]$msg) {
    Write-Host "[WARN] $msg" -ForegroundColor Yellow
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

if (-not (Test-Path -LiteralPath $bridgeDir)) {
    throw "No encontre la carpeta 'baileys_bridge'. Ejecuta este script desde la raiz del proyecto."
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "No encontre Python del entorno virtual en '.venv\\Scripts\\python.exe'."
}

if (-not (Test-Path -LiteralPath $flaskApp)) {
    throw "No encontre bot_empanadas\\app.py."
}

# Resuelve credenciales sin hardcodear secretos en el script.
if (-not $DbCredential) {
    $envDbPassword = [Environment]::GetEnvironmentVariable("DB_PASSWORD")
    if (-not [string]::IsNullOrWhiteSpace($envDbPassword)) {
        $securePasswordFromEnv = ConvertTo-SecureString -String $envDbPassword -AsPlainText -Force
        $DbCredential = New-Object System.Management.Automation.PSCredential($DbUser, $securePasswordFromEnv)
    }
}

if (-not $DbCredential) {
    $securePasswordPrompt = Read-Host -Prompt "Ingresa DB_PASSWORD" -AsSecureString
    $DbCredential = New-Object System.Management.Automation.PSCredential($DbUser, $securePasswordPrompt)
}

$dbUserResolved = if ([string]::IsNullOrWhiteSpace($DbCredential.UserName)) { $DbUser } else { $DbCredential.UserName }
$dbPasswordPlain = Convert-SecureStringToPlain -SecureValue $DbCredential.Password
if ([string]::IsNullOrWhiteSpace($dbPasswordPlain)) {
    throw "DB_PASSWORD es obligatoria. Define DB_PASSWORD en el entorno o ingresala al ejecutar."
}

# Exporta variables para que todos los procesos hijos (incluyendo validaciones) usen el mismo contexto.
$env:DB_HOST = $DbHost
$env:DB_PORT = $DbPort
$env:DB_NAME = $DbName
$env:DB_USER = $dbUserResolved
$env:DB_PASSWORD = $dbPasswordPlain
$env:N8N_PEDIDO_WEBHOOK_URL = $N8nWebhookUrl
$env:TTS_LANG = if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable("TTS_LANG"))) { "es" } else { [Environment]::GetEnvironmentVariable("TTS_LANG") }
$env:TTS_TLD = if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable("TTS_TLD"))) { "com.co" } else { [Environment]::GetEnvironmentVariable("TTS_TLD") }

if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable("FLASK_SECRET"))) {
    $env:FLASK_SECRET = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
    Write-Warn "FLASK_SECRET no estaba configurado. Se genero uno temporal para esta sesion."
}

Write-Info "Validando conexion a PostgreSQL (${DbHost}:${DbPort}/${DbName}) con usuario '$dbUserResolved'..."
$dbCheckCode = @"
import os
import psycopg2

conn = psycopg2.connect(
    host=os.environ['DB_HOST'],
    port=int(os.environ['DB_PORT']),
    dbname=os.environ['DB_NAME'],
    user=os.environ['DB_USER'],
    password=os.environ['DB_PASSWORD'],
)
conn.close()
print('DB_OK')
"@

Push-Location $root
try {
    & $venvPython -c $dbCheckCode | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "No fue posible validar conexion a PostgreSQL. Verifica DB_USER/DB_PASSWORD/DB_NAME y que PostgreSQL este levantado."
    }
}
finally {
    Pop-Location
}

Write-Ok "Conexion a PostgreSQL validada."

if (-not (Test-Path -LiteralPath $bridgeEnv) -and (Test-Path -LiteralPath $bridgeEnvExample)) {
    Copy-Item -LiteralPath $bridgeEnvExample -Destination $bridgeEnv
    Write-Info "Se creo baileys_bridge/.env desde .env.example"
}

if (-not $SkipDocker) {
    Write-Info "Levantando n8n con docker compose..."
    Push-Location $root
    try {
        docker compose up -d | Out-Host
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Warn "Se omite docker compose por parametro -SkipDocker"
}

Write-Info "Iniciando Baileys bridge en una ventana nueva..."
$bridgeCmd = "Set-Location -LiteralPath '$bridgeDir'; npm start"
Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy", "Bypass",
    "-Command", $bridgeCmd
) | Out-Null

Write-Info "Iniciando Flask en una ventana nueva..."
# Pasa variables por entorno heredado para no exponer secretos en linea de comandos.

$flaskCmd = "Set-Location -LiteralPath '$root'; & '$venvPython' '$flaskApp'"
Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy", "Bypass",
    "-Command", $flaskCmd
) | Out-Null

Write-Info "Esperando unos segundos para validar servicios..."
Start-Sleep -Seconds 6

function Test-Health([string]$url) {
    try {
        $r = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 4
        return @{ ok = $true; body = ($r | ConvertTo-Json -Depth 4 -Compress) }
    }
    catch {
        return @{ ok = $false; body = $_.Exception.Message }
    }
}

$flaskHealth = Test-Health "http://127.0.0.1:5000/health"
$bridgeHealth = Test-Health "http://127.0.0.1:3001/health"

if ($flaskHealth.ok) {
    Write-Ok "Flask responde en http://127.0.0.1:5000/health -> $($flaskHealth.body)"
}
else {
    Write-Warn "Flask aun no responde: $($flaskHealth.body)"
}

if ($bridgeHealth.ok) {
    Write-Ok "Baileys responde en http://127.0.0.1:3001/health -> $($bridgeHealth.body)"
}
else {
    Write-Warn "Baileys aun no responde: $($bridgeHealth.body)"
}

Write-Host "" 
Write-Host "URLs:" -ForegroundColor White
Write-Host "- Flask:   http://localhost:5000" -ForegroundColor White
Write-Host "- Baileys: http://localhost:3001/health" -ForegroundColor White
Write-Host "- n8n:     http://localhost:5678" -ForegroundColor White
Write-Host "" 
if ($ShowDemoCreds) {
    Write-Host "Bootstrap de usuarios del panel:" -ForegroundColor White
    Write-Host "- Define ADMIN_DEFAULT_PASSWORD" -ForegroundColor White
    Write-Host "- Define COCINA_DEFAULT_PASSWORD" -ForegroundColor White
    Write-Host "- Define REPARTIDOR_DEFAULT_PASSWORD" -ForegroundColor White
    Write-Host ""
}
Write-Warn "Si Baileys sale connected=false, escanea el QR en la ventana de Baileys."
