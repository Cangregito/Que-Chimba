import os

import requests


def normalize_whatsapp_id(raw_value):
    raw = (raw_value or "").strip()
    if raw.startswith("whatsapp:"):
        raw = raw.replace("whatsapp:", "", 1)
    return raw


def normalize_ticket_destination(raw_value):
    raw = normalize_whatsapp_id(raw_value)
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    if not digits:
        return ""
    if len(digits) == 10:
        return f"52{digits}"
    return digits


def summarize_items_for_alert(items):
    if not isinstance(items, list) or not items:
        return "sin productos"

    parts = []
    for item in items:
        if not isinstance(item, dict):
            continue
        producto = item.get("producto") or item.get("nombre") or f"producto_id={item.get('producto_id', '?')}"
        cantidad = item.get("cantidad", 1)
        parts.append(f"{producto} x{cantidad}")

    return ", ".join(parts) if parts else "sin productos"





def send_text_whatsapp(app, destino, texto):
    bridge_url = app.config.get("BAILEYS_BRIDGE_URL", "")
    if not bridge_url:
        return {"error": "BAILEYS_BRIDGE_URL no configurado."}

    bridge_token = app.config.get("BAILEYS_BRIDGE_API_TOKEN", "")
    headers = {"Content-Type": "application/json"}
    if bridge_token:
        headers["x-bridge-token"] = bridge_token

    try:
        resp = requests.post(
            f"{bridge_url}/api/send-text",
            json={"to": destino, "text": texto},
            timeout=10,
            headers=headers,
        )
    except Exception as exc:
        return {"error": f"No se pudo conectar al bridge de WhatsApp: {exc}"}

    try:
        payload = resp.json()
    except Exception:
        payload = {}

    if not resp.ok or payload.get("ok") is not True:
        msg = payload.get("error") or f"Bridge respondio HTTP {resp.status_code}"
        return {"error": str(msg)}

    return {"ok": True}


def send_audio_whatsapp(app, destino, audio_path, caption="", default_public_base_url="http://localhost:5000"):
    bridge_url = app.config.get("BAILEYS_BRIDGE_URL", "")
    if not bridge_url or not audio_path:
        return {"error": "BAILEYS_BRIDGE_URL o audio_path no configurados."}

    bridge_token = app.config.get("BAILEYS_BRIDGE_API_TOKEN", "")
    headers = {"Content-Type": "application/json"}
    if bridge_token:
        headers["x-bridge-token"] = bridge_token

    audio_filename = os.path.basename(str(audio_path))
    base_url = app.config.get("PUBLIC_BASE_URL") or default_public_base_url
    audio_url = f"{base_url}/audio/{audio_filename}"

    try:
        resp = requests.post(
            f"{bridge_url}/api/send-audio",
            json={"to": destino, "audioUrl": audio_url, "caption": caption},
            timeout=10,
            headers=headers,
        )
    except Exception as exc:
        return {"error": f"No se pudo enviar audio al bridge: {exc}"}

    try:
        payload = resp.json()
    except Exception:
        payload = {}

    if not resp.ok or payload.get("ok") is not True:
        msg = payload.get("error") or f"Bridge respondio HTTP {resp.status_code}"
        return {"error": str(msg)}

    return {"ok": True}
