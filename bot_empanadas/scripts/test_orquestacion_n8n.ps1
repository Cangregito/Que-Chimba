param(
    [string]$FlaskBaseUrl = "http://localhost:5000",
    [string]$N8nBaseUrl = "http://localhost:5678",
    [Nullable[bool]]$UseTestWebhook
)

$ErrorActionPreference = "Stop"
$useTestWebhookEnabled = if ($null -eq $UseTestWebhook) { $true } else { [bool]$UseTestWebhook }

function Write-Step {
    param([string]$Message)
    Write-Host "`n=== $Message ===" -ForegroundColor Cyan
}

function Invoke-JsonPost {
    param(
        [string]$Url,
        [hashtable]$Body
    )

    return Invoke-RestMethod -Method Post -Uri $Url -ContentType "application/json" -Body ($Body | ConvertTo-Json -Depth 8)
}

function Assert-TcpPort {
    param(
        [string]$HostName,
        [int]$Port,
        [string]$ServiceName
    )

    $probe = Test-NetConnection $HostName -Port $Port -WarningAction SilentlyContinue
    if (-not $probe.TcpTestSucceeded) {
        throw "No hay conexion TCP a $ServiceName en ${HostName}:$Port. Levanta ese servicio e intenta de nuevo."
    }
}

Write-Step "0) Pre-flight de conectividad local"
Assert-TcpPort -HostName "localhost" -Port 5000 -ServiceName "Flask"
if (-not $useTestWebhookEnabled) {
    Assert-TcpPort -HostName "localhost" -Port 5678 -ServiceName "n8n"
}

Write-Step "1) Verificando health de Flask"
$health = Invoke-RestMethod -Method Get -Uri "$FlaskBaseUrl/health"
$health | ConvertTo-Json -Depth 5

Write-Step "2) Obteniendo catalogo de productos para crear pedido real"
try {
    $productosResp = Invoke-RestMethod -Method Get -Uri "$FlaskBaseUrl/api/productos"
}
catch {
    throw "No se pudo consultar /api/productos. Causa probable: PostgreSQL apagado o credenciales DB invalidas. Detalle original: $($_.Exception.Message)"
}

if (-not $productosResp.ok -or -not $productosResp.data -or $productosResp.data.Count -lt 1) {
    throw "No hay productos disponibles en /api/productos (o la API no pudo leer PostgreSQL)."
}

$producto = $productosResp.data[0]
$productoId = $producto.producto_id
$productoNombre = if ($producto.nombre) { $producto.nombre } else { "producto" }

Write-Host "Producto usado para prueba: ID=$productoId Nombre=$productoNombre" -ForegroundColor Yellow

Write-Step "3) Probando endpoint /api/logs directo"
$logBody = @{
    pedido_id  = 999999
    canal      = "whatsapp"
    destino    = "cocina"
    tipo       = "individual"
    mensaje    = "TEST DIRECTO LOG DESDE SCRIPT"
    total      = 123.45
    direccion  = "Av. Demo 123"
}

$logResp = Invoke-JsonPost -Url "$FlaskBaseUrl/api/logs" -Body $logBody
$logResp | ConvertTo-Json -Depth 6

Write-Step "4) Creando pedido para disparar webhook automatico a n8n"
$pedidoBody = @{
    whatsapp_id = "whatsapp:+525500001111"
    metodo_pago = "efectivo"
    tipo        = "evento"
    direccion   = "Calle Evento 456, Ciudad Juarez"
    items       = @(
        @{
            producto_id    = $productoId
            cantidad       = 3
            precio_unitario = [double]$producto.precio
            producto       = $productoNombre
        }
    )
}

$pedidoResp = Invoke-JsonPost -Url "$FlaskBaseUrl/api/pedidos" -Body $pedidoBody
$pedidoResp | ConvertTo-Json -Depth 10

if (-not $pedidoResp.ok) {
    throw "La creacion del pedido no devolvio ok=true"
}

$pedidoId = $pedidoResp.data.pedido_id
$total = $pedidoResp.data.total

Write-Host "Pedido creado correctamente. pedido_id=$pedidoId total=$total" -ForegroundColor Green

Write-Step "5) (Opcional) Disparo manual al webhook de n8n para validar conectividad"
$webhookPath = if ($useTestWebhookEnabled) { "webhook-test/pedido-alerta" } else { "webhook/pedido-alerta" }
$n8nWebhookUrl = "$N8nBaseUrl/$webhookPath"

$n8nPayload = @{
    id = $pedidoId
    productos = "$productoNombre x3"
    total = [double]$total
    direccion = "Calle Evento 456, Ciudad Juarez"
    tipo = "evento"
}

try {
    $n8nResp = Invoke-JsonPost -Url $n8nWebhookUrl -Body $n8nPayload
    Write-Host "Webhook n8n respondio correctamente:" -ForegroundColor Green
    $n8nResp | ConvertTo-Json -Depth 8
}
catch {
    Write-Warning "No se pudo contactar el webhook n8n en $n8nWebhookUrl"
    Write-Warning "Detalle: $($_.Exception.Message)"
}

Write-Step "6) Resultado"
Write-Host "Si el workflow de n8n esta activo y BAILEYS_BRIDGE_URL esta correcto, ya debio enviarse alerta a cocina y admin (por tipo=evento)." -ForegroundColor Magenta
Write-Host "Tambien debes ver registros en la tabla log_notificaciones." -ForegroundColor Magenta
