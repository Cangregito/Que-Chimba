# Que Chimba

Sistema local para gestionar pedidos de empanadas colombianas por WhatsApp, con back-end en Flask, base de datos PostgreSQL, dashboards web y automatizaciones con n8n.

## Resumen

Este proyecto fue construido como entrega final de la materia Bases de Datos. El objetivo es digitalizar la operacion de un emprendimiento de empanadas en Ciudad Juarez con un flujo completo que cubre:

- recepcion de pedidos por WhatsApp
- transcripcion de notas de voz con Whisper local
- respuestas en texto o audio con TTS neural (edge-tts) y fallback a gTTS
- registro de clientes, pedidos, inventario, pagos y auditoria en PostgreSQL
- dashboards web para admin, cocina y repartidor
- automatizacion de alertas mediante n8n
- integracion de pago con MercadoPago Mexico

## Arquitectura actual

```text
Cliente WhatsApp
    |
    v
Baileys Bridge (Node.js)
    |
    v
Flask API + Web (Python)
    |
    +--> PostgreSQL
    +--> Whisper local
    +--> gTTS + FFmpeg
    +--> MercadoPago
    +--> n8n
```

## Tecnologias vigentes

| Capa | Tecnologia actual | Uso |
| --- | --- | --- |
| WhatsApp | Baileys + Express | Conexion local por QR y puente HTTP hacia Flask |
| Back-end | Python + Flask | Webhooks, API REST, vistas HTML y autenticacion |
| Base de datos | PostgreSQL 16 | Modelo relacional, auditoria, inventario y sesiones |
| STT | openai-whisper local | Transcripcion de notas de voz en espanol |
| TTS | edge-tts + gTTS fallback | Generacion de respuesta de audio con acento mas natural |
| Audio | FFmpeg | Conversion y normalizacion a OGG Opus |
| Dashboards | HTML + CSS + JS + Chart.js | Panel admin, cocina y repartidor |
| Pagos | MercadoPago Mexico | Preferencias de pago y webhook |
| Automatizacion | n8n en Docker | Alertas operativas y flujo de notificaciones |
| Control de versiones | Git + GitHub | Historial y respaldo del proyecto |

## Cambios importantes respecto a versiones anteriores

- Ya no se usa Twilio como transporte principal de WhatsApp.
- El canal actual de WhatsApp corre con Baileys en `baileys_bridge/`.
- `voice.py` ya no depende de `pydub` en runtime; usa FFmpeg via subprocess.
- TTS ahora prioriza `edge-tts` (voz neural) y hace fallback a `gTTS` si hay falla temporal.
- La autenticacion web ya no usa usuarios hardcodeados; ahora sale de PostgreSQL con `usuarios_sistema`.
- El proyecto incluye auditoria de seguridad y auditoria de negocio.

## Estructura real del proyecto

```text
.
├── README.md
├── docker-compose.yml
├── queries_jurado.sql
├── templates/
│   └── index.html
├── baileys_bridge/
│   ├── README.md
│   ├── index.js
│   ├── package.json
│   ├── package-lock.json
│   ├── .env.example
│   ├── auth/
│   └── media_tmp/
├── bot_empanadas/
│   ├── app.py
│   ├── bot.py
│   ├── db.py
│   ├── payments.py
│   ├── requirements.txt
│   ├── voice.py
│   ├── audios_temp/
│   ├── scripts/
│   ├── sql/
│   │   ├── schema.sql
│   │   └── log_notificaciones.sql
│   └── templates/
│       ├── admin.html
│       ├── cocina.html
│       ├── login.html
│       ├── pago_exitoso.html
│       ├── pago_fallido.html
│       ├── pago_pendiente.html
│       └── repartidor.html
└── n8n/
    └── workflows/
```

## Modulos principales

### `bot_empanadas/app.py`

Servidor Flask principal. Expone:

- landing publica
- login web
- paneles admin, cocina y repartidor
- endpoints REST para pedidos, inventario, auditoria y usuarios
- webhook `POST /webhook/baileys`

### `bot_empanadas/bot.py`

Maquina de estados del bot de WhatsApp. Maneja:

- flujo de pedido individual o evento
- parsing de texto y audio
- sesiones persistidas en PostgreSQL
- confirmacion, evaluaciones y cierre de pedido

### `bot_empanadas/db.py`

Capa de acceso a datos con `psycopg2`. Maneja:

- clientes y pedidos
- usuarios del sistema
- auditoria de seguridad y negocio
- inventario, compras y recetas
- reportes y KPIs del dashboard

### `bot_empanadas/voice.py`

Modulo de voz. Incluye:

- descarga de audio desde URL publica
- transcripcion con Whisper local
- generacion TTS con gTTS
- conversion a OGG Opus usando FFmpeg

### `baileys_bridge/index.js`

Puente WhatsApp. Hace lo siguiente:

- recibe mensajes desde Baileys
- guarda media temporal en `media_tmp/`
- manda payload JSON a Flask
- envia texto o audio de regreso al cliente

## Funcionalidad implementada

### WhatsApp

- pedidos por texto o nota de voz
- ubicacion GPS compartida por cliente
- respuestas con modismos colombianos seguros
- soporte para envio de texto y audio

### Base de datos

- clientes identificados por numero de WhatsApp
- sesiones de conversacion con expiracion
- pedidos y detalle de pedido
- datos fiscales
- inventario con movimientos y compras
- recetas por producto
- auditoria de seguridad
- auditoria de negocio

### Web

- landing con informacion del negocio y enlace directo a WhatsApp
- panel admin con KPIs, auditoria, usuarios, inventario y rentabilidad
- panel cocina con gestion operativa de pedidos
- panel repartidor con confirmacion de entrega

### Pagos y automatizacion

- efectivo o MercadoPago
- webhook de pago
- alertas operativas mediante n8n

## Requisitos locales

- Python 3.11+
- Node.js 20+
- PostgreSQL 16
- FFmpeg disponible en PATH
- Docker Desktop para n8n
- opcional: Ollama para enriquecimiento local con LLM
- opcional: ngrok para demo externa

## Instalacion rapida

### 1. Crear entorno Python

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r bot_empanadas\requirements.txt
```

### 2. Instalar bridge de WhatsApp

```powershell
Set-Location baileys_bridge
npm install
Copy-Item .env.example .env
Set-Location ..
```

### 3. Crear la base de datos

Primero crea la base `que_chimba` en PostgreSQL y luego ejecuta:

```powershell
psql -U postgres -d que_chimba -f bot_empanadas\sql\schema.sql
```

## Variables de entorno principales

### Flask / Python

```text
DB_HOST=localhost
DB_PORT=5432
DB_NAME=que_chimba
DB_USER=postgres
DB_PASSWORD=
FLASK_SECRET=
PORT=5000
FLASK_DEBUG=0
SESSION_COOKIE_SECURE=1
SESSION_COOKIE_SAMESITE=Lax
PUBLIC_BASE_URL=
N8N_PEDIDO_WEBHOOK_URL=http://localhost:5678/webhook/pedido-alerta
BAILEYS_BRIDGE_URL=http://localhost:3001
BAILEYS_BRIDGE_API_TOKEN=
BAILEYS_WEBHOOK_TOKEN=
ADMIN_DEFAULT_PASSWORD=
COCINA_DEFAULT_PASSWORD=
REPARTIDOR_DEFAULT_PASSWORD=
MP_ACCESS_TOKEN=
MP_SANDBOX=true
WHISPER_MODEL=tiny
TTS_PROVIDER=auto
TTS_EDGE_VOICE=es-CO-SalomeNeural
TTS_EDGE_RATE=+0%
TTS_EDGE_PITCH=+0Hz
TTS_PROFILE_ENABLED=1
BOT_REPLY_MODE=texto
WHATSAPP_MEDIA_BASIC_USER=
WHATSAPP_MEDIA_BASIC_PASSWORD=
```

### Baileys Bridge

Ver detalle en `baileys_bridge/.env.example`.

## Ejecucion local

### 1. Levantar bridge de WhatsApp

```powershell
Set-Location baileys_bridge
npm start
```

Escanea el QR desde el WhatsApp que usaras para la demo.

### 2. Levantar Flask

```powershell
$env:DB_HOST='localhost'
$env:DB_PORT='5432'
$env:DB_NAME='que_chimba'
$env:DB_USER='postgres'
$env:DB_PASSWORD='<tu-password-seguro>'
$env:FLASK_SECRET='<clave-larga-aleatoria>'
$env:ADMIN_DEFAULT_PASSWORD='<password-admin>'
$env:COCINA_DEFAULT_PASSWORD='<password-cocina>'
$env:REPARTIDOR_DEFAULT_PASSWORD='<password-repartidor>'
$env:BAILEYS_BRIDGE_API_TOKEN='<token-bridge>'
$env:BAILEYS_WEBHOOK_TOKEN='<token-webhook>'
$env:N8N_PEDIDO_WEBHOOK_URL='http://localhost:5678/webhook/pedido-alerta'
.\.venv\Scripts\python.exe bot_empanadas\app.py
```

### 3. Levantar n8n

```powershell
docker-compose up -d
```

### 4. Verificar servicios

- Flask: `http://localhost:5000/health`
- Baileys Bridge: `http://localhost:3001/health`
- n8n: `http://localhost:5678`

## Credenciales demo

Los usuarios base se crean automaticamente si no existen, usando estas variables:

- `ADMIN_DEFAULT_PASSWORD`
- `COCINA_DEFAULT_PASSWORD`
- `REPARTIDOR_DEFAULT_PASSWORD`

## Flujo de demo sugerido

1. Iniciar PostgreSQL, Flask, bridge y n8n.
2. Escanear QR del bridge.
3. Enviar mensaje o nota de voz al numero conectado.
4. Confirmar pedido desde cocina.
5. Revisar inventario, auditoria y dashboards.
6. Si aplica, abrir flujo de pago con MercadoPago.

## Notas academicas

- El enfoque principal del proyecto esta en el diseno y explotacion de la base de datos.
- `queries_jurado.sql` contiene consultas utiles para la presentacion.
- El sistema fue pensado para correr completamente local durante la demo.

## Licencia

Uso educativo.
