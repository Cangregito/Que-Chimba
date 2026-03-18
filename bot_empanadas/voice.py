import os
import random
import subprocess
import tempfile
import uuid
import importlib
import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests
from gtts import gTTS

try:
    from elevenlabs import ElevenLabs, VoiceSettings
except Exception:
    ElevenLabs = None
    VoiceSettings = None

try:
    import edge_tts
except Exception:
    edge_tts = None


logger = logging.getLogger(__name__)

AUDIO_TEMP_DIR = Path(__file__).resolve().parent / "audios_temp"
AUDIO_TEMP_DIR.mkdir(parents=True, exist_ok=True)

FRASES_COLOMBIANAS = {
    "bienvenida": [
        "Ey parce, que mas. Bienvenido a Que Chimba, pidamos esas empanadas de una.",
        "Quiubo mi llave, llegaste a Que Chimba. Elige una opcion y hagamosle pues.",
        "Buenas mi rey/reina, aqui estamos al pie del canon. Dime si vas por pedido o evento.",
    ],
    "seleccion_producto": [
        "Bacano parce, tenemos carne y pollo a treinta y cinco. Manda cantidades y te lo armo.",
        "Listo mi llave, suelteme el combo: cuantas de carne, cuantas de pollo y si le metemos bebida.",
        "Que chimba, ya estamos cocinando antojo. Escriba su pedido completo y seguimos.",
    ],
    "confirmar_carrito": [
        "Buena nota parce, revise su carrito y me confirma si asi queda.",
        "Listo mi rey/reina, ya lo cuadre. Confirmamos o cambiamos algo.",
        "Uy que chimba va ese pedido. Mire el resumen y me dice si le damos confirmar.",
    ],
    "metodo_entrega": [
        "Dale parce, ahora elija como le queda mejor, domicilio o recoger en local.",
        "Listo mi llave, digame si se lo llevamos o si pasa por Que Chimba.",
        "Berraco, vamos bien. Elija metodo de entrega para cerrar este paso.",
    ],
    "solicitar_ubicacion": [
        "Hagamosle pues, comparta su ubicacion o escriba direccion completica para caerle.",
        "Buena nota, mi rey/reina, suelteme la ubicacion por WhatsApp y seguimos con pago.",
        "Parce, para no perdernos en la Juarez necesito su punto exacto. Mande ubicacion ahora.",
    ],
    "metodo_pago": [
        "Listo mi llave, como va a pagar, efectivo o tarjeta con link seguro.",
        "Bacano parce, toca cuadrar pago. Diga uno: efectivo o tarjeta.",
        "Que chimba, ya casi. Elija metodo de pago y le sigo con lo ultimo.",
    ],
    "preguntar_factura": [
        "Mi rey/reina, necesita factura o se va sin factura esta vez.",
        "Parce, antes de confirmar, me dice si requiere factura, si o no.",
        "Dale que si, pregunta rapida: le genero factura o no hace falta.",
    ],
    "datos_fiscales": [
        "Listo parce, paseme su RFC y razon social para facturar sin enredos.",
        "Buena nota, mi llave, vamos con datos fiscales paso a paso. Empecemos por el RFC.",
        "Hagamosle, mi rey/reina, deme los datos de factura y le cierro eso bonito.",
    ],
    "confirmacion": [
        "Perfecto parce, revise resumen final y confirmamos ese pedido de una.",
        "Listo mi llave, todo esta cuadrado. Si esta bien, confirme y salimos volando.",
        "Uy que chimba, ya quedo armado. Mire total, entrega y pago, y me confirma.",
    ],
    "completado": [
        "Ay que chimba parce, pedido confirmado en Que Chimba. Guarde su codigo y pendiente del reparto.",
        "Listo mi rey/reina, su pedido quedo confirmado. Guarde ese codigo de entrega y fresco.",
        "Bacano mi llave, ya entro a cocina. Tenga a la mano su codigo cuando llegue el repartidor.",
    ],
    "en_camino": [
        "Ey parce, buenas noticias, su pedido ya va en camino. Tenga listo su codigo.",
        "Mi llave, arrancamos moto. Su pedido va pa alla, tenga su codigo a la mano.",
        "Que chimba, ya salio el repartidor. Preparese que en nada le timbran.",
    ],
    "entrega_confirmada": [
        "Listo parce, entrega confirmada. Buen provecho y gracias por pedir en Que Chimba.",
        "Buena nota mi rey/reina, ya quedo entregado. Que disfrute esas empanadas.",
        "Dale mi llave, pedido entregado al cien. En un rato le pedimos su opinion.",
    ],
    "evaluar_entrega": [
        "Parce, del uno al cinco, como le fue con la rapidez de la entrega. Cuenteme.",
        "Mi rey/reina, regaleme una calificacion de entrega del uno al cinco.",
        "Buena nota, hagamos una mini encuesta. Marque su rating de entrega y seguimos.",
    ],
    "evaluar_producto": [
        "Buenos dias parce, del uno al cinco, como le parecieron las empanadas. Lo leo.",
        "Mi llave, cuenteme si estuvo bacano el sabor, califique del uno al cinco.",
        "Que mas mi rey/reina, cierre con broche de oro y deje su calificacion del producto.",
    ],
    "datos_evento": [
        "Berraco parce, para evento le ayudo de una. Digame cantidad, fecha y tipo.",
        "Que chimba esa celebracion, mi llave. Paseme datos del evento y se lo mando al admin.",
        "Listo mi rey/reina, armemos su cotizacion. Escriba personas, fecha y requisito especial.",
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
        "Ay parce, no te entendi bien. Me repites clarito y lo sacamos de una.",
        "Mi llave, hubo un enredo tecnico pequeno. Dame otro intento y seguimos bacano.",
        "Listo mi rey/reina, se me cruzaron los cables. Escribeme de nuevo para continuar.",
    ],
}

_WHISPER_MODEL = None
_WHISPER_MODEL_NAME = (os.getenv("WHISPER_MODEL", "tiny") or "tiny").strip().lower()
_TTS_PROVIDER = (os.getenv("TTS_PROVIDER", "auto") or "auto").strip().lower()
_TTS_GTTS_LANG = (os.getenv("TTS_LANG", "es") or "es").strip()
_TTS_GTTS_TLD = (os.getenv("TTS_TLD", "com.co") or "com.co").strip().lower()
_TTS_EDGE_VOICE = (os.getenv("TTS_EDGE_VOICE", "es-CO-SalomeNeural") or "es-CO-SalomeNeural").strip()
_TTS_EDGE_RATE = (os.getenv("TTS_EDGE_RATE", "+0%") or "+0%").strip()
_TTS_EDGE_PITCH = (os.getenv("TTS_EDGE_PITCH", "+0Hz") or "+0Hz").strip()
_TTS_PROFILE_ENABLED = (os.getenv("TTS_PROFILE_ENABLED", "1") or "1").strip().lower() in {"1", "true", "yes", "on"}
_TTS_ELEVENLABS_API_KEY = (os.getenv("ELEVENLABS_API_KEY", "") or "").strip()
_TTS_ELEVENLABS_VOICE_ID = (os.getenv("ELEVENLABS_VOICE_ID", "") or "").strip()
_TTS_ELEVENLABS_MODEL_ID = (os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2") or "eleven_multilingual_v2").strip()


def _parse_float_env(name: str, default: float) -> float:
    raw = (os.getenv(name, str(default)) or str(default)).strip()
    try:
        return float(raw)
    except ValueError:
        return default


_TTS_ELEVENLABS_STABILITY = _parse_float_env("ELEVENLABS_STABILITY", 0.45)
_TTS_ELEVENLABS_SIMILARITY = _parse_float_env("ELEVENLABS_SIMILARITY", 0.85)
_TTS_ELEVENLABS_STYLE = _parse_float_env("ELEVENLABS_STYLE", 0.2)
_TTS_ELEVENLABS_SPEAKER_BOOST = (os.getenv("ELEVENLABS_SPEAKER_BOOST", "1") or "1").strip().lower() in {"1", "true", "yes", "on"}

logger.info(
    "TTS config cargada: provider=%s lang=%s tld=%s edge_voice=%s eleven_voice_set=%s",
    _TTS_PROVIDER,
    _TTS_GTTS_LANG,
    _TTS_GTTS_TLD,
    _TTS_EDGE_VOICE,
    bool(_TTS_ELEVENLABS_VOICE_ID),
)


def _load_whisper_model():
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        whisper_module = importlib.import_module("whisper")
        logger.info("Cargando Whisper model=%s", _WHISPER_MODEL_NAME)
        _WHISPER_MODEL = whisper_module.load_model(_WHISPER_MODEL_NAME)
    return _WHISPER_MODEL


def _get_twilio_auth() -> tuple[str, str]:
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    if not account_sid or not auth_token:
        raise ValueError("Faltan TWILIO_ACCOUNT_SID o TWILIO_AUTH_TOKEN en variables de entorno.")
    return account_sid, auth_token


def _get_basic_media_auth() -> Optional[tuple[str, str]]:
    username = (os.getenv("WHATSAPP_MEDIA_BASIC_USER", "") or "").strip()
    password = (os.getenv("WHATSAPP_MEDIA_BASIC_PASSWORD", "") or "").strip()
    if username and password:
        return username, password
    return None


def _resolver_auth_media(media_url: str) -> Optional[tuple[str, str]]:
    host = (urlparse(media_url).netloc or "").lower()
    if any(part in host for part in {"twilio.com", "api.twilio.com", "mms.twiliocdn.com"}):
        try:
            return _get_twilio_auth()
        except ValueError:
            return None
    return _get_basic_media_auth()


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


async def _edge_tts_save_async(texto: str, mp3_path: Path) -> None:
    texto_tts, rate, pitch = _preparar_texto_para_tts(texto)
    edge_tts_module = edge_tts
    if edge_tts_module is None:
        raise RuntimeError("edge_tts no esta disponible")

    communicator = edge_tts_module.Communicate(
        text=texto_tts,
        voice=_TTS_EDGE_VOICE,
        rate=rate,
        pitch=pitch,
    )
    await communicator.save(str(mp3_path))


def _inferir_perfil_locucion(texto: str) -> str:
    t = (texto or "").lower()
    if any(k in t for k in ["error", "falla", "no pude", "intenta de nuevo", "enredo tecnico"]):
        return "error"
    if any(k in t for k in ["confirmado", "folio", "codigo de entrega", "asi va tu pedido", "resumen"]):
        return "confirmacion"
    if any(k in t for k in ["ya llego", "fue entregado", "pedido entregado", "gracias por pedir"]):
        return "entrega"
    if any(k in t for k in ["bienvenido", "que mas", "hola", "arranquemos", "menu"]):
        return "bienvenida"
    return "neutral"


def _normalizar_pausas(texto: str) -> str:
    clean = " ".join(str(texto or "").split())
    clean = clean.replace(". ", ". ... ")
    clean = clean.replace(": ", ": ... ")
    clean = clean.replace("; ", ", ")
    clean = clean.replace("? ", "? ... ")
    clean = clean.replace("! ", "! ... ")
    return clean


def _preparar_texto_para_tts(texto: str) -> tuple[str, str, str]:
    if not _TTS_PROFILE_ENABLED:
        return str(texto or ""), _TTS_EDGE_RATE, _TTS_EDGE_PITCH

    perfil = _inferir_perfil_locucion(texto)
    texto_tts = _normalizar_pausas(texto)

    ajustes = {
        "bienvenida": ("+2%", "+2Hz"),
        "confirmacion": ("-2%", "+0Hz"),
        "entrega": ("+0%", "+1Hz"),
        "error": ("-4%", "-1Hz"),
        "neutral": (_TTS_EDGE_RATE, _TTS_EDGE_PITCH),
    }
    rate_delta, pitch_delta = ajustes.get(perfil, (_TTS_EDGE_RATE, _TTS_EDGE_PITCH))

    # Si el usuario configuro rate/pitch fijos, esos mandan.
    rate_final = _TTS_EDGE_RATE if _TTS_EDGE_RATE != "+0%" else rate_delta
    pitch_final = _TTS_EDGE_PITCH if _TTS_EDGE_PITCH != "+0Hz" else pitch_delta

    return texto_tts, rate_final, pitch_final


def _sintetizar_edge_tts(texto: str, mp3_path: Path) -> bool:
    if edge_tts is None:
        return False

    try:
        try:
            asyncio.run(_edge_tts_save_async(texto, mp3_path))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_edge_tts_save_async(texto, mp3_path))
            finally:
                loop.close()
        return mp3_path.exists() and mp3_path.stat().st_size > 0
    except Exception as exc:
        logger.warning("TTS neural edge fallo: %s", exc)
        return False


def _sintetizar_gtts(texto: str, mp3_path: Path) -> bool:
    try:
        texto_tts, _rate, _pitch = _preparar_texto_para_tts(texto)
        tts = gTTS(text=texto_tts, lang=_TTS_GTTS_LANG, tld=_TTS_GTTS_TLD, slow=False)
        tts.save(str(mp3_path))
        return mp3_path.exists() and mp3_path.stat().st_size > 0
    except Exception as exc:
        logger.warning("TTS gTTS fallo: %s", exc)
        return False


def _sintetizar_elevenlabs(texto: str, mp3_path: Path) -> bool:
    if ElevenLabs is None or VoiceSettings is None:
        logger.info("ElevenLabs deshabilitado: libreria no disponible")
        return False
    if not _TTS_ELEVENLABS_API_KEY or not _TTS_ELEVENLABS_VOICE_ID:
        logger.info("ElevenLabs deshabilitado: faltan ELEVENLABS_API_KEY o ELEVENLABS_VOICE_ID")
        return False

    try:
        texto_tts, _rate, _pitch = _preparar_texto_para_tts(texto)
        client = ElevenLabs(api_key=_TTS_ELEVENLABS_API_KEY)
        audio = client.text_to_speech.convert(
            text=texto_tts,
            voice_id=_TTS_ELEVENLABS_VOICE_ID,
            model_id=_TTS_ELEVENLABS_MODEL_ID,
            output_format="mp3_44100_128",
            voice_settings=VoiceSettings(
                stability=_TTS_ELEVENLABS_STABILITY,
                similarity_boost=_TTS_ELEVENLABS_SIMILARITY,
                style=_TTS_ELEVENLABS_STYLE,
                use_speaker_boost=_TTS_ELEVENLABS_SPEAKER_BOOST,
            ),
        )

        with mp3_path.open("wb") as f:
            if isinstance(audio, (bytes, bytearray)):
                f.write(audio)
            else:
                for chunk in audio:
                    if chunk:
                        f.write(chunk)

        return mp3_path.exists() and mp3_path.stat().st_size > 0
    except Exception as exc:
        logger.warning("TTS ElevenLabs fallo: %s", exc)
        return False


def _convert_to_wav(input_path: Path, output_path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(input_path),
            "-ac", "1", "-ar", "16000",
            str(output_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def transcribir_audio(url_twilio: str) -> str:
    """
    Descarga audio desde Twilio con auth, convierte a WAV y transcribe con Whisper small en espanol.
    Retorna texto en minusculas y limpia archivos temporales.
    """
    if not url_twilio:
        return ""

    temp_input_path: Optional[Path] = None
    temp_wav_path: Optional[Path] = None

    try:
        auth = _resolver_auth_media(url_twilio)
        response = requests.get(
            url_twilio,
            auth=auth,
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

    return _generar_audio_desde_texto(texto_final)


def _generar_audio_desde_texto(texto: str) -> str:
    unique_id = str(uuid.uuid4())
    mp3_path = AUDIO_TEMP_DIR / f"{unique_id}.mp3"
    ogg_path = AUDIO_TEMP_DIR / f"{unique_id}.ogg"

    try:
        provider = _TTS_PROVIDER
        sintetizado = False
        proveedor_usado = ""

        if provider in {"auto", "elevenlabs"}:
            sintetizado = _sintetizar_elevenlabs(texto, mp3_path)
            if sintetizado:
                proveedor_usado = "elevenlabs"

        if not sintetizado and provider in {"auto", "edge", "elevenlabs"}:
            sintetizado = _sintetizar_edge_tts(texto, mp3_path)
            if sintetizado:
                proveedor_usado = "edge-tts"

        if not sintetizado and provider in {"auto", "edge", "gtts", "elevenlabs"}:
            sintetizado = _sintetizar_gtts(texto, mp3_path)
            if sintetizado:
                proveedor_usado = "gTTS"

        if not sintetizado:
            raise RuntimeError("No se pudo sintetizar audio con los proveedores disponibles")

        logger.info("TTS sintetizado con proveedor=%s (modo=%s)", proveedor_usado or "desconocido", provider)

        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(mp3_path),
                "-c:a", "libopus", "-ar", "16000", "-ac", "1", "-b:a", "24k",
                "-map_metadata", "-1",
                str(ogg_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
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
