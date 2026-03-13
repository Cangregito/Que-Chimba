# Baileys Bridge

Puente Node.js que conecta WhatsApp Web con el back-end Flask de Que Chimba.

## Objetivo

Este servicio reemplaza el transporte anterior de WhatsApp y ahora cumple tres funciones:

- recibir mensajes entrantes desde Baileys
- guardar media entrante temporalmente en `media_tmp/`
- reenviar el mensaje al webhook Flask `POST /webhook/baileys`
- enviar al cliente la respuesta que Flask genere en texto o audio

## Flujo actual

```text
WhatsApp
  -> Baileys
  -> Express bridge
  -> Flask /webhook/baileys
  -> respuesta { tipo, contenido, audio_url? }
  -> bridge envia texto o audio al cliente
```

## Archivos principales

```text
baileys_bridge/
├── index.js
├── package.json
├── package-lock.json
├── .env.example
├── .gitignore
├── README.md
├── auth/
└── media_tmp/
```

## Requisitos

- Node.js 20+
- una sesion de WhatsApp disponible para escanear QR
- Flask corriendo en `http://localhost:5000` o la URL que configures

## Instalacion

```powershell
Set-Location baileys_bridge
npm install
Copy-Item .env.example .env
```

## Variables de entorno

Archivo base: `.env.example`

```text
BAILEYS_BRIDGE_PORT=3001
FLASK_BAILEYS_WEBHOOK_URL=http://localhost:5000/webhook/baileys
BAILEYS_PUBLIC_BASE_URL=http://localhost:3001
BAILEYS_AUTH_DIR=auth
BAILEYS_MEDIA_DIR=media_tmp
LOG_LEVEL=info
```

### Descripcion de cada variable

- `BAILEYS_BRIDGE_PORT`: puerto HTTP del bridge
- `FLASK_BAILEYS_WEBHOOK_URL`: endpoint Flask que procesa mensajes
- `BAILEYS_PUBLIC_BASE_URL`: URL base para servir media temporal
- `BAILEYS_AUTH_DIR`: carpeta donde Baileys guarda credenciales de sesion
- `BAILEYS_MEDIA_DIR`: carpeta temporal para audios, imagenes y documentos entrantes
- `LOG_LEVEL`: nivel de logs para `pino`

## Ejecucion

```powershell
npm start
```

Al iniciar:

1. el servidor Express levanta en el puerto configurado
2. Baileys solicita QR si no hay sesion guardada
3. escaneas el QR desde WhatsApp
4. el bridge queda listo para recibir y contestar mensajes

## Endpoints expuestos

### `GET /health`

Devuelve estado del bridge y si Baileys esta conectado.

Respuesta esperada:

```json
{
  "ok": true,
  "connected": true,
  "user": {}
}
```

### `POST /api/send-text`

Envia texto a un cliente.

```json
{
  "to": "52XXXXXXXXXX",
  "text": "mensaje"
}
```

### `POST /api/send-audio`

Envia una nota de voz usando una URL publica servida por Flask.

```json
{
  "to": "52XXXXXXXXXX",
  "audioUrl": "https://.../audio/archivo.ogg",
  "caption": "opcional"
}
```

## Integracion con Flask

El bridge manda a Flask un payload como este:

```json
{
  "whatsapp_id": "5216560000000",
  "mensaje": "hola",
  "media_url": "http://localhost:3001/media/archivo.ogg",
  "media_type": "audio/ogg; codecs=opus",
  "latitude": null,
  "longitude": null,
  "message_id": "ABC123"
}
```

Y espera una respuesta como esta:

```json
{
  "ok": true,
  "data": {
    "tipo": "texto",
    "contenido": "Listo parce"
  }
}
```

O bien:

```json
{
  "ok": true,
  "data": {
    "tipo": "audio",
    "contenido": "Ay que chimba",
    "audio_url": "http://localhost:5000/audio/archivo.ogg"
  }
}
```

## Carpetas generadas en runtime

- `auth/`: credenciales de la sesion de WhatsApp
- `media_tmp/`: archivos entrantes guardados temporalmente

Ambas carpetas estan ignoradas por Git y se pueden regenerar.

## Problemas comunes

### El QR no aparece

- revisa que `npm install` haya terminado correctamente
- confirma que usas Node.js 20+
- borra `auth/` si la sesion anterior quedo inconsistente

### Flask no responde

- revisa `FLASK_BAILEYS_WEBHOOK_URL`
- confirma que Flask este corriendo y responda en `/health`

### El audio no sale

- confirma que Flask este sirviendo la URL de `audio_url`
- revisa que `PUBLIC_BASE_URL` del back-end apunte a una URL accesible
- verifica que el archivo `.ogg` exista en `bot_empanadas/audios_temp/`

## Estado actual del stack

- Si ves referencias viejas a Twilio en otra documentacion, ya no aplican a este bridge.
- El transporte principal de WhatsApp en el proyecto actual es Baileys.
