# Baileys Bridge

Puente Node.js (Express + Baileys) que conecta WhatsApp con el back-end Flask de Que Chimba.

Este documento refleja el comportamiento actual de [index.js](index.js).

## 1. Responsabilidad del servicio

El bridge hace cuatro cosas principales:

- Mantiene la sesion de WhatsApp Web con Baileys.
- Recibe mensajes entrantes (texto, audio, imagen, video, documento).
- Publica esos eventos hacia Flask en `POST /webhook/baileys`.
- Entrega al cliente final la respuesta generada por Flask (texto o nota de voz).

## 2. Flujo operativo

```text
WhatsApp
  -> Baileys (socket)
  -> Express bridge
  -> Flask webhook (/webhook/baileys)
  -> respuesta { tipo, contenido, audio_url? }
  -> envio a cliente por WhatsApp
```

Detalles actuales del flujo:

- El bridge ignora mensajes de grupos y estados.
- Los adjuntos se guardan temporalmente en `media_tmp/` y se exponen en `/media/*`.
- Si Flask falla, el bridge intenta responder con un mensaje de fallback.

## 3. Requisitos

- Node.js 20 o superior.
- Una sesion de WhatsApp disponible para escanear QR.
- Flask disponible en la URL configurada en `FLASK_BAILEYS_WEBHOOK_URL`.

## 4. Instalacion local

```powershell
Set-Location baileys_bridge
npm install
Copy-Item .env.example .env
```

## 5. Variables de entorno

Archivo base: [.env.example](.env.example)

Variables usadas por el bridge:

- `BAILEYS_BRIDGE_PORT`: puerto HTTP del bridge. Default: `3001`.
- `FLASK_BAILEYS_WEBHOOK_URL`: endpoint Flask receptor de mensajes. Default: `http://localhost:5000/webhook/baileys`.
- `BAILEYS_WEBHOOK_TOKEN`: token opcional que el bridge envia a Flask en header `x-bridge-token`.
- `BAILEYS_BRIDGE_API_TOKEN`: token opcional para proteger endpoints internos `/api/*` del bridge.
- `BAILEYS_PUBLIC_BASE_URL`: URL base publica para servir media temporal. Default: `http://localhost:<PORT>`.
- `BAILEYS_AUTH_DIR`: directorio de credenciales Baileys. Default: `auth`.
- `BAILEYS_MEDIA_DIR`: directorio de media temporal. Default: `media_tmp`.
- `BAILEYS_MEDIA_TTL_HOURS`: horas de vida de archivos en media temporal. Default: `24`.
- `BAILEYS_MEDIA_CLEANUP_MINUTES`: frecuencia de limpieza automatica. Default: `30`.
- `LOG_LEVEL`: nivel de log para pino. Default: `info`.

## 6. Ejecucion

```powershell
npm start
```

Durante el arranque:

1. Levanta Express en el puerto configurado.
2. Inicializa el socket Baileys y muestra QR si no hay sesion valida.
3. Crea `auth/` y `media_tmp/` si no existen.
4. Inicia limpieza periodica de media temporal.

## 7. Endpoints expuestos

### GET /health

Estado basico del servicio y conexion de Baileys.

Respuesta ejemplo:

```json
{
  "ok": true,
  "connected": true,
  "user": {}
}
```

### POST /api/send-text

Envia texto a un destino.

Body:

```json
{
  "to": "52XXXXXXXXXX",
  "text": "mensaje"
}
```

### POST /api/send-audio

Envia nota de voz descargando audio desde `audioUrl`.

Body:

```json
{
  "to": "52XXXXXXXXXX",
  "audioUrl": "https://.../audio/archivo.ogg",
  "caption": "opcional"
}
```

### POST /api/send-options

Envia botones de opcion rapida (maximo 3).

Body:

```json
{
  "to": "52XXXXXXXXXX",
  "text": "Selecciona una opcion",
  "options": [
    "Pollo",
    "Carne",
    "Mixta"
  ]
}
```

### Autenticacion de endpoints internos

- Si `BAILEYS_BRIDGE_API_TOKEN` esta vacio, `/api/*` acepta solicitudes sin token.
- Si `BAILEYS_BRIDGE_API_TOKEN` tiene valor, cada solicitud a `/api/*` debe incluir header `x-bridge-token` con ese valor.

## 8. Contrato con Flask

Payload enviado a Flask (`POST FLASK_BAILEYS_WEBHOOK_URL`):

```json
{
  "whatsapp_id": "5216560000000",
  "whatsapp_jid": "5216560000000@s.whatsapp.net",
  "mensaje": "hola",
  "media_url": "http://localhost:3001/media/archivo.ogg",
  "media_type": "audio/ogg; codecs=opus",
  "media_kind": "audio",
  "latitude": null,
  "longitude": null,
  "message_id": "ABC123",
  "reply_id": "opt_pollo"
}
```

Headers hacia Flask:

- `Content-Type: application/json`
- `x-bridge-token: <BAILEYS_WEBHOOK_TOKEN>` (solo si fue configurado)

Respuesta esperada desde Flask:

```json
{
  "ok": true,
  "data": {
    "tipo": "texto",
    "contenido": "Listo parce"
  }
}
```

Respuesta de audio:

```json
{
  "ok": true,
  "data": {
    "tipo": "audio",
    "contenido": "Te mando la nota de voz",
    "audio_url": "http://localhost:5000/audio/archivo.ogg"
  }
}
```

## 9. Estructura relevante

```text
baileys_bridge/
|- index.js
|- package.json
|- .env.example
|- auth/
`- media_tmp/
```

- `auth/`: estado de sesion de WhatsApp (multi-file auth).
- `media_tmp/`: archivos temporales descargados de mensajes entrantes.

## 10. Problemas comunes

### No aparece QR o no conecta

- Verifica version de Node (`node -v`) y dependencias (`npm install`).
- Si la sesion quedo corrupta, elimina `auth/` y reinicia.

### Flask no recibe mensajes

- Revisa `FLASK_BAILEYS_WEBHOOK_URL`.
- Si Flask valida token, confirma `BAILEYS_WEBHOOK_TOKEN`.
- Verifica conectividad entre puertos locales (3001 -> 5000).

### Falla envio por /api/* con 401

- Si definiste `BAILEYS_BRIDGE_API_TOKEN`, envia header `x-bridge-token` correcto.

### Audio no se entrega

- Verifica que `audio_url` sea accesible desde el host del bridge.
- El bridge descarga audio con timeout de 30s; revisa latencia y disponibilidad.

## 11. Notas de stack

- Este bridge es el transporte activo de WhatsApp para el proyecto.
- Referencias antiguas a Twilio no aplican para el flujo actual de produccion local.
