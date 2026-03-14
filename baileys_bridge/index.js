const express = require("express");
const path = require("path");
const fs = require("fs");
const axios = require("axios");
const pino = require("pino");
const qrcode = require("qrcode-terminal");
const dotenv = require("dotenv");
const { Boom } = require("@hapi/boom");
const {
  default: makeWASocket,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  DisconnectReason,
  downloadMediaMessage,
} = require("@whiskeysockets/baileys");

dotenv.config();

const logger = pino({ level: process.env.LOG_LEVEL || "info" });

const PORT = Number(process.env.BAILEYS_BRIDGE_PORT || 3001);
const FLASK_WEBHOOK_URL = (process.env.FLASK_BAILEYS_WEBHOOK_URL || "http://localhost:5000/webhook/baileys").trim();
const FLASK_WEBHOOK_TOKEN = (process.env.BAILEYS_WEBHOOK_TOKEN || "").trim();
const BRIDGE_API_TOKEN = (process.env.BAILEYS_BRIDGE_API_TOKEN || "").trim();
const AUTH_DIR = path.resolve(__dirname, process.env.BAILEYS_AUTH_DIR || "auth");
const MEDIA_DIR = path.resolve(__dirname, process.env.BAILEYS_MEDIA_DIR || "media_tmp");
const PUBLIC_BASE_URL = (process.env.BAILEYS_PUBLIC_BASE_URL || `http://localhost:${PORT}`).replace(/\/$/, "");

if (!fs.existsSync(AUTH_DIR)) {
  fs.mkdirSync(AUTH_DIR, { recursive: true });
}
if (!fs.existsSync(MEDIA_DIR)) {
  fs.mkdirSync(MEDIA_DIR, { recursive: true });
}

const app = express();
app.use(express.json({ limit: "5mb" }));
app.use("/media", express.static(MEDIA_DIR, { maxAge: "1h" }));

function requireBridgeToken(req, res, next) {
  if (!BRIDGE_API_TOKEN) {
    return next();
  }
  const incoming = String(req.headers["x-bridge-token"] || "").trim();
  if (incoming !== BRIDGE_API_TOKEN) {
    return res.status(401).json({ ok: false, error: "Token de bridge invalido" });
  }
  return next();
}

let sock = null;

function toJid(numberOrJid) {
  const raw = String(numberOrJid || "").trim();
  if (!raw) {
    return "";
  }
  if (raw.includes("@")) {
    return raw;
  }
  const digits = raw.replace(/[^0-9]/g, "");
  return `${digits}@s.whatsapp.net`;
}

function toPlainNumber(jidOrNumber) {
  const raw = String(jidOrNumber || "").trim();
  if (!raw) {
    return "";
  }
  return raw.replace(/@.*/, "").replace(/[^0-9]/g, "");
}

function extractText(message) {
  return (
    message?.conversation ||
    message?.extendedTextMessage?.text ||
    message?.imageMessage?.caption ||
    message?.videoMessage?.caption ||
    ""
  );
}

function extractLocation(message) {
  const loc = message?.locationMessage;
  if (!loc) {
    return { latitude: null, longitude: null };
  }
  return {
    latitude: loc.degreesLatitude ?? null,
    longitude: loc.degreesLongitude ?? null,
  };
}

async function saveIncomingMedia(msg) {
  const message = msg?.message;
  const hasAudio = Boolean(message?.audioMessage);
  const hasImage = Boolean(message?.imageMessage);
  const hasVideo = Boolean(message?.videoMessage);
  const hasDocument = Boolean(message?.documentMessage);

  if (!hasAudio && !hasImage && !hasVideo && !hasDocument) {
    return { mediaUrl: null, mediaType: null };
  }

  const mediaType = hasAudio
    ? "audio"
    : hasImage
      ? "image"
      : hasVideo
        ? "video"
        : "document";

  const contentType =
    message?.audioMessage?.mimetype ||
    message?.imageMessage?.mimetype ||
    message?.videoMessage?.mimetype ||
    message?.documentMessage?.mimetype ||
    "application/octet-stream";

  const ext =
    contentType.includes("ogg") ? ".ogg" :
      contentType.includes("mpeg") || contentType.includes("mp3") ? ".mp3" :
        contentType.includes("wav") ? ".wav" :
          contentType.includes("jpeg") ? ".jpg" :
            contentType.includes("png") ? ".png" :
              contentType.includes("pdf") ? ".pdf" : ".bin";

  const buffer = await downloadMediaMessage(
    msg,
    "buffer",
    {},
    {
      logger,
      reuploadRequest: sock.updateMediaMessage,
    }
  );

  const filename = `${Date.now()}-${Math.random().toString(36).slice(2)}${ext}`;
  const localPath = path.join(MEDIA_DIR, filename);
  fs.writeFileSync(localPath, buffer);

  return {
    mediaUrl: `${PUBLIC_BASE_URL}/media/${filename}`,
    mediaType: contentType || mediaType,
  };
}

async function sendText(to, text) {
  if (!sock) {
    throw new Error("Baileys no esta conectado.");
  }
  const jid = toJid(to);
  if (!jid) {
    throw new Error("Numero destino invalido.");
  }
  await sock.sendMessage(jid, { text: String(text || "") });
}

async function sendAudioFromUrl(to, audioUrl, caption = "") {
  if (!sock) {
    throw new Error("Baileys no esta conectado.");
  }
  const jid = toJid(to);
  if (!jid) {
    throw new Error("Numero destino invalido.");
  }

  const response = await axios.get(String(audioUrl), {
    responseType: "arraybuffer",
    timeout: 30000,
  });

  await sock.sendMessage(jid, {
    audio: Buffer.from(response.data),
    mimetype: "audio/ogg; codecs=opus",
    ptt: true,
  });

  if (caption) {
    await sock.sendMessage(jid, { text: String(caption) });
  }
}

async function processIncomingMessage(msg) {
  if (!msg?.message) {
    return;
  }

  const key = msg.key || {};
  const remoteJid = key.remoteJid || "";
  if (!remoteJid || remoteJid === "status@broadcast" || remoteJid.endsWith("@g.us") || key.fromMe) {
    return;
  }

  const bodyText = extractText(msg.message);
  const { latitude, longitude } = extractLocation(msg.message);
  const { mediaUrl, mediaType } = await saveIncomingMedia(msg);

  const payload = {
    whatsapp_id: toPlainNumber(remoteJid),
    mensaje: bodyText,
    media_url: mediaUrl,
    media_type: mediaType,
    latitude,
    longitude,
    message_id: key.id || "",
  };

  let flaskData = null;
  try {
    const webhookHeaders = { "Content-Type": "application/json" };
    if (FLASK_WEBHOOK_TOKEN) {
      webhookHeaders["x-bridge-token"] = FLASK_WEBHOOK_TOKEN;
    }

    const flaskResp = await axios.post(FLASK_WEBHOOK_URL, payload, {
      timeout: 45000,
      headers: webhookHeaders,
    });

    flaskData = flaskResp?.data?.data || flaskResp?.data;
  } catch (error) {
    logger.error({ err: error?.message, payload }, "Error llamando webhook Flask");
    await sendText(payload.whatsapp_id, "Listo parce, tengo una falla temporal del sistema. Intenta de nuevo en un minuto.");
    return;
  }

  const tipo = String(flaskData?.tipo || "texto").toLowerCase();
  const contenido = String(flaskData?.contenido || "").trim();

  if (tipo === "audio" && flaskData?.audio_url) {
    try {
      await sendAudioFromUrl(payload.whatsapp_id, flaskData.audio_url, contenido);
      return;
    } catch (error) {
      logger.error({ err: error?.message }, "No se pudo enviar audio de respuesta");
    }
  }

  if (contenido) {
    await sendText(payload.whatsapp_id, contenido);
  }
}

app.get("/health", (_req, res) => {
  const connected = Boolean(sock?.user?.id);
  res.json({ ok: true, connected, user: sock?.user || null });
});

app.post("/api/send-text", requireBridgeToken, async (req, res) => {
  try {
    const to = req.body?.to;
    const text = req.body?.text;
    if (!to || !text) {
      return res.status(400).json({ ok: false, error: "to y text son obligatorios" });
    }

    await sendText(to, text);
    return res.json({ ok: true });
  } catch (error) {
    return res.status(500).json({ ok: false, error: String(error?.message || error) });
  }
});

app.post("/api/send-audio", requireBridgeToken, async (req, res) => {
  try {
    const to = req.body?.to;
    const audioUrl = req.body?.audioUrl;
    const caption = req.body?.caption || "";
    if (!to || !audioUrl) {
      return res.status(400).json({ ok: false, error: "to y audioUrl son obligatorios" });
    }

    await sendAudioFromUrl(to, audioUrl, caption);
    return res.json({ ok: true });
  } catch (error) {
    return res.status(500).json({ ok: false, error: String(error?.message || error) });
  }
});

async function startSocket() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version } = await fetchLatestBaileysVersion();

  sock = makeWASocket({
    version,
    auth: state,
    logger,
    printQRInTerminal: false,
    syncFullHistory: false,
    markOnlineOnConnect: false,
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", async (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      qrcode.generate(qr, { small: true });
      logger.info("Escanea el QR en WhatsApp para conectar Baileys.");
    }

    if (connection === "open") {
      logger.info({ user: sock.user }, "Baileys conectado");
      return;
    }

    if (connection === "close") {
      const statusCode = new Boom(lastDisconnect?.error)?.output?.statusCode;
      const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
      logger.warn({ statusCode, shouldReconnect }, "Conexion Baileys cerrada");

      if (shouldReconnect) {
        setTimeout(() => {
          startSocket().catch((err) => logger.error({ err: String(err) }, "Error reconectando Baileys"));
        }, 2000);
      }
    }
  });

  sock.ev.on("messages.upsert", async ({ messages }) => {
    if (!Array.isArray(messages) || !messages.length) {
      return;
    }

    for (const msg of messages) {
      try {
        await processIncomingMessage(msg);
      } catch (error) {
        logger.error({ err: error?.message }, "Error procesando mensaje entrante");
      }
    }
  });
}

app.listen(PORT, () => {
  logger.info(`Baileys bridge escuchando en puerto ${PORT}`);
  startSocket().catch((err) => logger.error({ err: String(err) }, "No se pudo iniciar Baileys"));
});
