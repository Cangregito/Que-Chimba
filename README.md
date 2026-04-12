# Que Chimba

Sistema local para gestionar pedidos de empanadas por WhatsApp con back-end Flask, base de datos PostgreSQL, paneles web operativos y automatizaciones con n8n.

Este README esta actualizado al estado actual del repositorio.

## 1. Que hace el proyecto hoy

El sistema cubre de punta a punta la operacion del negocio:

- Recepcion de mensajes de clientes por WhatsApp (texto y audio)
- Transcripcion de notas de voz (Whisper local)
- Respuestas en texto o audio (edge-tts y fallback)
- Gestion de clientes, pedidos, inventario, compras, pagos y auditoria en PostgreSQL
- Paneles web para administracion, cocina y repartidor
- Campanas y tickets de soporte
- Integracion de pagos con MercadoPago
- Automatizaciones externas con n8n

## 2. Arquitectura actual

Cliente WhatsApp
-> Baileys Bridge (Node.js + Express)
-> Flask app (API + Web + Webhooks)
-> PostgreSQL / STT / TTS / MercadoPago / n8n

## 3. Stack tecnologico real

- Python 3.x con Flask
- PostgreSQL 16
- Node.js 20+ con Express y Baileys
- Whisper local (openai-whisper)
- edge-tts, gTTS y ElevenLabs (segun configuracion)
- FFmpeg para procesamiento de audio
- n8n en Docker
- Frontend server-side con templates HTML

Nota importante:

- El transporte principal de WhatsApp ya no es Twilio. El flujo activo va por Baileys Bridge.
- Aun pueden existir dependencias o rastros legacy en algunos archivos, pero el camino operativo actual es Baileys.

## 4. Estructura del repositorio

- README.md: este documento
- docker-compose.yml: stack de n8n
- run_all.ps1: script de arranque y validaciones locales
- queries_jurado.sql: consultas para presentacion
- templates/: landing principal publica
- n8n/workflows/: flujos de automatizacion
- baileys_bridge/: puente WhatsApp
- bot_empanadas/: aplicacion principal Flask

Dentro de bot_empanadas:

- app.py: composicion principal, seguridad, registro de rutas y error handlers
- bot.py: logica conversacional
- db.py: capa de datos y consultas SQL
- voice.py: STT/TTS/audio
- payments.py: integracion de pagos
- routes/common_routes.py
- routes/order_routes.py
- routes/report_routes.py
- routes/admin_routes.py
- routes/marketing_support_routes.py
- routes/webhook_routes.py
- routes/audit_parser_routes.py
- services/api_response.py
- services/request_security.py
- services/whatsapp_service.py
- sql/schema.sql: esquema de base de datos
- templates/: paneles web internos

## 5. Endpoints y dominios funcionales

El registro de rutas se hace por modulos, manteniendo contratos HTTP existentes:

- Common: health, login/logout, paginas y endpoints publicos
- Orders: pedidos, estado, bitacora, confirmacion, repartidor
- Reports: KPIs, reportes y exportacion
- Admin: productos, insumos, recetas, usuarios
- Marketing/Support: campanas, conteo de clientes, empleados, tickets
- Webhooks: entrada de WhatsApp y bridge
- Audit/Parser: auditorias y administracion de reglas/parser

## 6. Requisitos

- Python 3.11 o superior
- Node.js 20 o superior
- PostgreSQL 16
- FFmpeg disponible en PATH
- Docker Desktop (para n8n)

## 7. Instalacion local

1. Entorno Python

PowerShell:

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r bot_empanadas\requirements.txt

1. Dependencias del bridge

PowerShell:

Set-Location baileys_bridge
npm install
Copy-Item .env.example .env
Set-Location ..

1. Base de datos

Crear base que_chimba y luego ejecutar:

PowerShell:

psql -U postgres -d que_chimba -f bot_empanadas\sql\schema.sql

## 8. Variables de entorno clave

Aplicacion Flask / Bot:

- DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
- SENSITIVE_DATA_KEY (obligatoria en produccion para cifrado en reposo de GPS y datos fiscales)
- FLASK_SECRET, PORT, FLASK_DEBUG
- SESSION_COOKIE_SECURE, SESSION_COOKIE_SAMESITE
- PUBLIC_BASE_URL
- N8N_PEDIDO_WEBHOOK_URL
- BAILEYS_BRIDGE_URL
- BAILEYS_BRIDGE_API_TOKEN
- BAILEYS_WEBHOOK_TOKEN
- MP_ACCESS_TOKEN, MP_SANDBOX
- WHISPER_MODEL
- TTS_PROVIDER
- ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL_ID
- BOT_REPLY_MODE

Bridge Baileys (baileys_bridge/.env):

- BAILEYS_BRIDGE_PORT
- FLASK_BAILEYS_WEBHOOK_URL
- BAILEYS_WEBHOOK_TOKEN
- BAILEYS_BRIDGE_API_TOKEN
- BAILEYS_PUBLIC_BASE_URL
- BAILEYS_AUTH_DIR
- BAILEYS_MEDIA_DIR
- LOG_LEVEL

### Matriz rapida de compatibilidad (run_all -> Flask -> Bridge)

Esta tabla resume como se propagan variables cuando arrancas con run_all.ps1.

| Variable | run_all.ps1 | Flask/Bot | Bridge |
| --- | --- | --- | --- |
| DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD | Las define/exporta y valida conexion a PostgreSQL | Consumidas por la app | No aplica |
| N8N_PEDIDO_WEBHOOK_URL | Se exporta desde parametro `-N8nWebhookUrl` | Consumida por webhooks de pedidos | No aplica |
| TTS_PROVIDER, TTS_LANG, TTS_TLD | Se exportan desde parametros `-Tts*` | Consumidas por voice.py/bot.py | No aplica |
| WHISPER_MODEL | Se normaliza a `large-v3` y se exporta | Consumida para STT | No aplica |
| ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL_ID | Se exportan y se muestran enmascaradas en logs | Consumidas por TTS cuando TTS_PROVIDER=elevenlabs | No aplica |
| BOT_REPLY_MODE | Se define default `audio` si no existe | Consumida por el bot para modo de respuesta | No aplica |
| LLM_LOCAL_ENABLED, LLM_LOCAL_BASE_URL, LLM_LOCAL_MODEL, LLM_LOCAL_TIMEOUT_SEC | Se exportan y se valida Ollama segun configuracion | Consumidas por parser/respuesta local | No aplica |
| FLASK_SECRET | Si falta, se genera temporal para la sesion | Consumida por Flask (sesion/seguridad) | No aplica |
| FLASK_BAILEYS_WEBHOOK_URL | No la setea directamente (vive en `.env` del bridge) | Expone endpoint receptor en `/webhook/baileys` | Consumida para enviar eventos a Flask |
| BAILEYS_WEBHOOK_TOKEN | No la setea directamente (vive en `.env` del bridge) | Valida token entrante en webhook de bridge (si esta configurado) | Se envia en header `x-bridge-token` hacia Flask |
| BAILEYS_BRIDGE_API_TOKEN | No la setea directamente (vive en `.env` del bridge) | Consumida al llamar APIs internas del bridge | Protege `/api/send-*` y `/api/send-options` |
| BAILEYS_BRIDGE_PORT, BAILEYS_PUBLIC_BASE_URL, BAILEYS_AUTH_DIR, BAILEYS_MEDIA_DIR | No las setea directamente (viven en `.env` del bridge) | No aplica | Configuran puerto, URL publica y directorios del bridge |

Notas:

- run_all.ps1 inicia Flask y bridge en ventanas separadas; no inyecta automaticamente las variables internas del bridge en su `.env`.
- Para tokens y puertos del bridge, la fuente de verdad es baileys_bridge/.env.

## 9. Ejecucion (modo recomendado)

La forma mas practica para demo local es usar el script:

PowerShell:

.\run_all.ps1

Este script:

- valida conexion a PostgreSQL
- prepara variables de entorno
- puede levantar/validar componentes necesarios
- ejecuta chequeos de consistencia para la demo

## 10. Ejecucion manual (alternativa)

1. Levantar bridge

PowerShell:

Set-Location baileys_bridge
npm start

1. Levantar Flask

PowerShell (desde raiz del repo):

.\.venv\Scripts\python.exe bot_empanadas\app.py

1. Levantar n8n

PowerShell:

docker-compose up -d

Servicios esperados:

- Flask: <http://localhost:5000/health>
- Bridge: <http://localhost:3001/health>
- n8n: <http://localhost:5678>

## 11. Pruebas y validaciones

Prueba de regresion principal del parser:

PowerShell:

.\.venv\Scripts\python.exe bot_empanadas\test_order_parser_regression.py

Validacion de sintaxis completa:

PowerShell:

.\.venv\Scripts\python.exe -m compileall -q bot_empanadas

## 12. Estado de la base de datos

El esquema incluye entidades para:

- catalogo de productos y precios
- inventario, proveedores y compras
- clientes, direcciones y datos fiscales
- pedidos, detalle y pagos
- sesiones de bot
- campanas
- usuarios del sistema por rol
- auditoria de seguridad
- auditoria de negocio

Archivo fuente:

- bot_empanadas/sql/schema.sql

## 13. Seguridad y operacion

- Tokens de bridge y webhook deben configurarse en ambientes reales
- FLASK_SECRET no debe quedar vacio fuera de desarrollo
- Revisar SESSION_COOKIE_SECURE y PUBLIC_BASE_URL en despliegues
- No exponer credenciales en commits ni en logs

## 14. Notas de proyecto

- Proyecto academico orientado a administracion de bases de datos y operacion local controlada
- queries_jurado.sql contiene consultas utiles para revision y defensa

## 14.1 Backups y logs operativos (sin tocar logica funcional)

Se agrego un modulo operativo desacoplado para respaldos y bitacora tecnica en:

- scripts/ops/backup_postgres.ps1
- scripts/ops/verify_restore_postgres.ps1
- scripts/ops/register_backup_tasks.ps1

Objetivo:

- Respaldar PostgreSQL de forma automatica
- Verificar que los respaldos realmente restauran
- Guardar logs tecnicos de ejecucion
- No modificar rutas HTTP ni logica de negocio del bot

Uso manual rapido:

PowerShell:

.\scripts\ops\backup_postgres.ps1 -DbHost localhost -DbPort 5432 -DbName que_chimba -DbUser postgres

PowerShell (verificacion restore con ultimo backup):

.\scripts\ops\verify_restore_postgres.ps1 -DbHost localhost -DbPort 5432 -DbUser postgres

Nota:

- Ambos scripts toman DB_PASSWORD desde la variable de entorno si no se pasa por parametro.

Programacion automatica (Task Scheduler):

PowerShell:

.\scripts\ops\register_backup_tasks.ps1 -TaskPrefix QueChimba -BackupTime 02:00 -VerifyTime 03:00 -VerifyDay SUN

Artefactos generados:

- backups/postgres/*.zip: respaldo comprimido
- backups/postgres/*.json: metadatos con hash SHA-256
- logs/ops/*.log: bitacora de ejecucion

Retencion:

- backup_postgres.ps1 aplica limpieza por dias (RetentionDays) y por cantidad maxima (KeepLatest).
- Para operacion avanzada (alertas webhook, mirror, DR drill): ver docs/OPERACION_BACKUPS.md
- Para validar prerequisitos antes de automatizar: scripts/ops/check_backup_readiness.ps1

## 15. Licencia

Uso educativo.

## 16. Checklist rapido para demo/despliegue local

Usa esta lista para levantar todo de forma consistente antes de presentar.

### A. Pre-flight (una sola vez por maquina)

1. Tener instalado Python 3.11+, Node.js 20+, PostgreSQL 16, Docker Desktop y FFmpeg en PATH.
1. Crear entorno e instalar dependencias Python:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r bot_empanadas\requirements.txt
```

1. Instalar dependencias del bridge:

```powershell
Set-Location baileys_bridge
npm install
Copy-Item .env.example .env
Set-Location ..
```

1. Crear base de datos y aplicar esquema:

```powershell
psql -U postgres -d que_chimba -f bot_empanadas\sql\schema.sql
```

### B. Variables minimas antes de correr

1. Definir credenciales de DB (si no las pasas por prompt):

```powershell
$env:DB_PASSWORD = "tu_password"
```

1. Si usaras ElevenLabs, definir:

```powershell
$env:ELEVENLABS_API_KEY = "tu_api_key"
$env:ELEVENLABS_VOICE_ID = "tu_voice_id"
```

1. Revisar `baileys_bridge/.env` para tokens del bridge si aplican:

- `BAILEYS_WEBHOOK_TOKEN`
- `BAILEYS_BRIDGE_API_TOKEN`

### C. Arranque recomendado (todo en uno)

1. Ejecutar desde raiz:

```powershell
.\run_all.ps1
```

1. Si no quieres levantar Docker/n8n en esta corrida:

```powershell
.\run_all.ps1 -SkipDocker
```

1. Si solo quieres validar stack rapido sin tests de parser:

```powershell
.\run_all.ps1 -SkipRegressionTests
```

### D. Verificacion post-arranque

1. Flask responde en: <http://localhost:5000/health>
1. Bridge responde en: <http://localhost:3001/health>
1. n8n responde en: <http://localhost:5678> (si no usaste `-SkipDocker`)
1. En la ventana del bridge, escanear QR si `connected=false`.

### E. Diagnostico rapido si algo falla

1. Error DB: validar `DB_USER`, `DB_PASSWORD`, `DB_NAME` y que PostgreSQL este arriba.
1. Error QR/sesion WhatsApp: cerrar bridge, borrar `baileys_bridge/auth/` y reiniciar.
1. Error webhook Flask desde bridge: revisar `FLASK_BAILEYS_WEBHOOK_URL` y token `BAILEYS_WEBHOOK_TOKEN`.
1. Error audio/TTS: validar FFmpeg, `TTS_PROVIDER` y credenciales de ElevenLabs.
1. Error LLM local: validar Ollama (`ollama serve`, modelo disponible) o desactivar con `LLM_LOCAL_ENABLED=0`.
