import os
import random
import tempfile
import uuid
import importlib
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from gtts import gTTS
from pydub import AudioSegment

AUDIO_TEMP_DIR = Path(__file__).resolve().parent / "audios_temp"
AUDIO_TEMP_DIR.mkdir(parents=True, exist_ok=True)

FRASES_COLOMBIANAS = {
    "bienvenida": [
        "Ey parce, que mas. Bienvenido a Que Chimba empanadas. Hagamosle con tu pedido.",
        "Buenas mi llave, aca en Que Chimba estamos listos pa atenderte con toda la buena nota.",
        "Que mas mi rey/reina, llegaste a Que Chimba. Dale que si y te armo el pedido rapidito.",
    ],
    "confirmacion_pedido": [
        "Uy que chimba de pedido, {nombre}. Te dejo confirmado: {productos}. Total: {total}.",
        "Listo mi rey/reina, ya te tome la orden de {productos}. Queda en {total}.",
        "Bacano parce, pedido confirmado para {nombre}. Van {productos} y el total es {total}.",
    ],
    "pedido_entregado": [
        "Buena nota, {nombre}. Ya llego tu pedidito. Disfrutalo y gracias por pedir en Que Chimba.",
        "Dale parce, tu pedido ya fue entregado. Que lo disfrutes bien berraco.",
        "Chevere mi llave, ya tienes tus empanadas contigo. Gracias por la confianza.",
    ],
    "error": [
        "Ay parce, no te entendi bien. Me repites porfa para ayudarte mejor.",
        "Mi llave, hubo un enredo tecnico pequeno. Dame otro intento y lo sacamos.",
        "Listo mi rey/reina, se me cruzaron los cables. Escribeme de nuevo y seguimos.",
    ],
}

_WHISPER_MODEL = None


def _load_whisper_model():
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        whisper_module = importlib.import_module("whisper")
        _WHISPER_MODEL = whisper_module.load_model("small")
    return _WHISPER_MODEL


def _get_twilio_auth() -> tuple[str, str]:
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    if not account_sid or not auth_token:
        raise ValueError("Faltan TWILIO_ACCOUNT_SID o TWILIO_AUTH_TOKEN en variables de entorno.")
    return account_sid, auth_token


def _detect_extension(url_twilio: str, content_type: str) -> str:
    ct = (content_type or "").lower()
    if "ogg" in ct:
        return ".ogg"
    if "amr" in ct:
        return ".amr"
    if "mpeg" in ct or "mp3" in ct:
        return ".mp3"
    if "wav" in ct:
        return ".wav"

    path = Path(url_twilio.split("?")[0])
    suffix = path.suffix.lower()
    if suffix in {".ogg", ".opus", ".amr", ".mp3", ".wav", ".m4a"}:
        return suffix
    return ".ogg"


def _safe_format(template: str, datos_dinamicos: Dict[str, Any]) -> str:
    base = {
        "nombre": "parce",
        "total": "pendiente",
        "productos": "tu pedido",
    }
    base.update({k: str(v) for k, v in (datos_dinamicos or {}).items()})
    return template.format(**base)


def _convert_to_wav(input_path: Path, output_path: Path) -> None:
    audio = AudioSegment.from_file(str(input_path))
    audio = audio.set_channels(1).set_frame_rate(16000)
    audio.export(str(output_path), format="wav")


def transcribir_audio(url_twilio: str) -> str:
    """
    Descarga audio desde Twilio con auth, convierte a WAV y transcribe con Whisper small en espanol.
    Retorna texto en minusculas y limpia archivos temporales.
    """
    if not url_twilio:
        return ""

    account_sid, auth_token = _get_twilio_auth()
    temp_input_path: Optional[Path] = None
    temp_wav_path: Optional[Path] = None

    try:
        response = requests.get(
            url_twilio,
            auth=(account_sid, auth_token),
            timeout=40,
            allow_redirects=True,
        )
        response.raise_for_status()

        extension = _detect_extension(url_twilio, response.headers.get("Content-Type", ""))
        with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as temp_input:
            temp_input.write(response.content)
            temp_input_path = Path(temp_input.name)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_wav:
            temp_wav_path = Path(temp_wav.name)

        _convert_to_wav(temp_input_path, temp_wav_path)

        model = _load_whisper_model()
        result = model.transcribe(str(temp_wav_path), language="es", fp16=False)
        text = (result.get("text") or "").strip().lower()
        return " ".join(text.split())

    except Exception:
        return ""

    finally:
        for file_path in (temp_input_path, temp_wav_path):
            if file_path and file_path.exists():
                try:
                    file_path.unlink()
                except OSError:
                    pass


def generar_audio_colombiano(estado: str, datos_dinamicos: Optional[Dict[str, Any]] = None) -> str:
    """
    Genera un audio OGG Opus para WhatsApp usando una frase aleatoria segura por estado.
    """
    frases_estado = FRASES_COLOMBIANAS.get(estado) or FRASES_COLOMBIANAS["error"]
    frase_base = random.choice(frases_estado)
    texto_final = _safe_format(frase_base, datos_dinamicos or {})

    unique_id = str(uuid.uuid4())
    mp3_path = AUDIO_TEMP_DIR / f"{unique_id}.mp3"
    ogg_path = AUDIO_TEMP_DIR / f"{unique_id}.ogg"

    try:
        tts = gTTS(text=texto_final, lang="es", tld="com.mx", slow=False)
        tts.save(str(mp3_path))

        AudioSegment.from_mp3(str(mp3_path)).export(
            str(ogg_path),
            format="ogg",
            codec="libopus",
            parameters=["-ar", "16000", "-ac", "1", "-b:a", "24k", "-map_metadata", "-1"],
        )

        return str(ogg_path)

    finally:
        if mp3_path.exists():
            try:
                mp3_path.unlink()
            except OSError:
                pass


def _generar_audio_desde_texto(texto: str) -> str:
    unique_id = str(uuid.uuid4())
    mp3_path = AUDIO_TEMP_DIR / f"{unique_id}.mp3"
    ogg_path = AUDIO_TEMP_DIR / f"{unique_id}.ogg"

    try:
        tts = gTTS(text=texto, lang="es", tld="com.mx", slow=False)
        tts.save(str(mp3_path))

        AudioSegment.from_mp3(str(mp3_path)).export(
            str(ogg_path),
            format="ogg",
            codec="libopus",
            parameters=["-ar", "16000", "-ac", "1", "-b:a", "24k", "-map_metadata", "-1"],
        )
        return str(ogg_path)
    finally:
        if mp3_path.exists():
            try:
                mp3_path.unlink()
            except OSError:
                pass


def enviar_audio_whatsapp(to: str, ogg_path: str, ngrok_url: str, twilio_client):
    """
    Envia una nota de voz por WhatsApp usando Twilio apuntando al audio servido por Flask.
    """
    if not to:
        raise ValueError("El parametro 'to' es obligatorio.")
    if not ogg_path:
        raise ValueError("El parametro 'ogg_path' es obligatorio.")
    if not ngrok_url:
        raise ValueError("El parametro 'ngrok_url' es obligatorio.")

    ogg_file = Path(ogg_path)
    if not ogg_file.exists():
        raise FileNotFoundError(f"No existe el archivo de audio: {ogg_path}")

    base_url = ngrok_url.rstrip("/")
    media_url = f"{base_url}/audio/{ogg_file.name}"
    from_number = os.getenv("TWILIO_NUMBER", "").strip()
    if not from_number:
        raise ValueError("Falta TWILIO_NUMBER en variables de entorno.")

    return twilio_client.messages.create(
        from_=from_number,
        to=to,
        media_url=[media_url],
    )


# Compatibilidad con el bot actual.
def generar_audio(texto: str):
    return _generar_audio_desde_texto(texto)


def generar_audio_respuesta(texto: str):
    return generar_audio(texto)


def transcribir_audio_desde_url(url_twilio: str) -> str:
    return transcribir_audio(url_twilio)


def text_to_speech(texto: str):
    return generar_audio(texto)


def tts_generar(texto: str):
    return generar_audio(texto)
