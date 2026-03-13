import os
import random
import re
import string
import importlib
import logging
import difflib
import json
import unicodedata
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, Iterable, Optional, Tuple

try:
	import requests
except Exception:
	requests = None
import db

logger = logging.getLogger(__name__)

try:
	voice = importlib.import_module("voice")
except Exception as direct_import_error:
	try:
		voice = importlib.import_module("bot_empanadas.voice")
	except Exception as package_import_error:
		voice = None
		logger.warning(
			"No se pudo cargar el modulo de voz (voice / bot_empanadas.voice): %s | %s",
			direct_import_error,
			package_import_error,
		)


ESTADOS = {
	"inicio",
	"bienvenida",
	"tipo_servicio",
	"seleccion_producto",
	"datos_evento",
	"cantidad",
	"metodo_entrega",
	"solicitar_ubicacion",
	"metodo_pago",
	"preguntar_factura",
	"datos_fiscales",
	"confirmacion",
	"completado",
	"evaluar_entrega",
	"evaluar_producto",
}


MODISMOS_SEGUROS = [
	"Ay que chimba,",
	"Listo parce,",
	"Buena nota,",
	"Dale que si mi rey/reina,",
]


BOT_REPLY_MODE = (os.getenv("BOT_REPLY_MODE", "texto") or "texto").strip().lower()
LLM_FALLBACK_ENABLED = (os.getenv("LLM_FALLBACK_ENABLED", "0") or "0").strip().lower() in {"1", "true", "yes", "on"}
LLM_BASE_URL = (os.getenv("LLM_BASE_URL", "https://api.openai.com") or "https://api.openai.com").rstrip("/")
LLM_MODEL = (os.getenv("LLM_MODEL", "gpt-4o-mini") or "gpt-4o-mini").strip()
LLM_API_KEY = (os.getenv("LLM_API_KEY", "") or "").strip()
LLM_LOCAL_ENABLED = (os.getenv("LLM_LOCAL_ENABLED", "1") or "1").strip().lower() in {"1", "true", "yes", "on"}
LLM_LOCAL_BASE_URL = (os.getenv("LLM_LOCAL_BASE_URL", "http://localhost:11434") or "http://localhost:11434").rstrip("/")
LLM_LOCAL_MODEL = (os.getenv("LLM_LOCAL_MODEL", "phi3:mini") or "phi3:mini").strip()


def _now_iso():
	return datetime.utcnow().isoformat()


def _normalizar_texto(texto):
	raw = (texto or "").strip().lower()
	norm = unicodedata.normalize("NFKD", raw)
	without_accents = "".join(ch for ch in norm if not unicodedata.combining(ch))
	return re.sub(r"\s+", " ", without_accents).strip()


def _es_error(value):
	return isinstance(value, dict) and bool(value.get("error"))


def _as_dict(value: Any) -> Dict[str, Any]:
	return value if isinstance(value, dict) else {}


def _numero_desde_from(from_num):
	raw = from_num or ""
	return raw.replace("whatsapp:", "").strip()


def _guardar_sesion(whatsapp_id, estado, datos_temp):
	payload = {
		"ultima_actualizacion": _now_iso(),
		**(datos_temp or {}),
	}
	result = db.guardar_sesion_bot(whatsapp_id=whatsapp_id, estado=estado, datos_temp=payload)
	if _es_error(result):
		raise RuntimeError(result["error"])
	return result


def _obtener_sesion(whatsapp_id):
	session_data = db.obtener_sesion_bot(whatsapp_id)
	if _es_error(session_data):
		raise RuntimeError(session_data["error"])
	return session_data


def _obtener_o_crear_cliente(whatsapp_id):
	result = db.obtener_o_crear_cliente(whatsapp_id)
	if _es_error(result):
		raise RuntimeError(result["error"])
	return result


def _to_float(value, default=0.0):
	if value is None:
		return default
	if isinstance(value, Decimal):
		return float(value)
	try:
		return float(value)
	except (TypeError, ValueError):
		return default


def _obtener_catalogo_productos() -> Iterable[Dict[str, Any]]:
	productos = db.obtener_productos(solo_pedibles=True)
	if _es_error(productos):
		raise RuntimeError(productos["error"])
	if isinstance(productos, list):
		return [p for p in productos if isinstance(p, dict)]
	return []


def _menu_texto(productos):
	if not productos:
		return "Hoy no tengo menu cargado en DB, pero te puedo tomar evento o dejarte en espera."

	lines = ["Menu del dia:"]
	for p in productos:
		nombre = p.get("nombre", "Empanada")
		variante = p.get("variante", "")
		precio = _to_float(p.get("precio"), 0)
		lines.append(f"- {nombre} {variante}: ${precio:.2f} MXN")
	return "\n".join(lines)


def _voice_transcribir_audio(media_url):
	if not media_url or not voice:
		if not media_url:
			logger.info("Audio omitido: no llego media_url")
		elif not voice:
			logger.warning("Audio omitido: modulo voice no disponible")
		return ""

	logger.info("Intentando transcripcion de audio desde media_url=%s", media_url)

	candidates = [
		"transcribir_audio_desde_url",
		"transcribir_audio",
		"transcribe_audio",
		"whisper_transcribir",
	]

	for name in candidates:
		fn = getattr(voice, name, None)
		if callable(fn):
			try:
				text = fn(media_url)
				if isinstance(text, str):
					clean = text.strip()
					logger.info("Transcripcion con %s: longitud=%s texto=%r", name, len(clean), clean)
					return clean
				return ""
			except Exception as exc:
				logger.warning("Error transcribiendo audio con %s: %s", name, exc)
				continue
	logger.warning("No se pudo transcribir audio con ningun adaptador de voz")
	return ""


def _voice_generar_audio(texto):
	if not texto or not voice:
		return None

	candidates = [
		"generar_audio_respuesta",
		"generar_audio",
		"text_to_speech",
		"tts_generar",
	]
	for name in candidates:
		fn = getattr(voice, name, None)
		if callable(fn):
			try:
				result = fn(texto)
				if isinstance(result, dict):
					filename = result.get("audio_filename") or result.get("filename")
					if filename:
						return filename
				if isinstance(result, str):
					return os.path.basename(result)
			except Exception:
				continue
	return None


def _armar_respuesta(texto, opciones):
	prefijo = random.choice(MODISMOS_SEGUROS)
	cuerpo = f"{prefijo} {texto}".strip()
	if opciones:
		cuerpo = f"{cuerpo}\n\nOpciones:\n{opciones}"

	# En WhatsApp Sandbox el audio puede fallar por media URL; texto es mas estable.
	if BOT_REPLY_MODE == "audio":
		audio_filename = _voice_generar_audio(cuerpo)
		if audio_filename:
			return {
				"tipo": "audio",
				"audio_filename": audio_filename,
				"contenido": cuerpo,
			}

	return {
		"tipo": "texto",
		"contenido": cuerpo,
	}


def _extraer_cantidad(texto):
	t = _normalizar_texto(texto)
	match = re.search(r"\b(\d{1,3})\b", t)
	if not match:
		number_words = {
			"un": 1,
			"uno": 1,
			"una": 1,
			"dos": 2,
			"tres": 3,
			"cuatro": 4,
			"cinco": 5,
			"seis": 6,
			"siete": 7,
			"ocho": 8,
			"nueve": 9,
			"diez": 10,
			"once": 11,
			"doce": 12,
			"trece": 13,
			"catorce": 14,
			"quince": 15,
			"dieciseis": 16,
			"diecisiete": 17,
			"dieciocho": 18,
			"diecinueve": 19,
			"veinte": 20,
			"veintiuno": 21,
			"veintidos": 22,
			"veintitres": 23,
			"veinticuatro": 24,
			"veinticinco": 25,
			"veintiseis": 26,
			"veintisiete": 27,
			"veintiocho": 28,
			"veintinueve": 29,
			"treinta": 30,
			"docena": 12,
			"media docena": 6,
			"par": 2,
		}

		if "media docena" in t:
			return 6

		tokens = re.findall(r"[a-z]+", t)
		for idx in range(len(tokens)):
			if idx + 1 < len(tokens):
				two = f"{tokens[idx]} {tokens[idx + 1]}"
				if two in number_words:
					return number_words[two]
			word = tokens[idx]
			if word in number_words:
				return number_words[word]

		return None

	return int(match.group(1))


def _es_afirmativo(texto):
	t = _normalizar_texto(texto)
	if not t:
		return False
	claves = {
		"si",
		"s",
		"ok",
		"va",
		"dale",
		"listo",
		"confirmar",
		"confirmado",
		"correcto",
		"de acuerdo",
		"asi es",
		"hazlo",
		"procede",
	}
	return any(k in t for k in claves)


def _es_negativo(texto):
	t = _normalizar_texto(texto)
	if not t:
		return False
	claves = {"no", "negativo", "cancelar", "cancelado", "nel"}
	return any(k in t for k in claves)


def _llm_disponible() -> bool:
	return bool(LLM_FALLBACK_ENABLED and LLM_API_KEY and requests is not None)


def _llm_local_disponible() -> bool:
	return bool(LLM_LOCAL_ENABLED and LLM_LOCAL_MODEL and requests is not None)


def _parsear_bool_flexible(value: Any) -> Optional[bool]:
	if isinstance(value, bool):
		return value
	if isinstance(value, str):
		t = _normalizar_texto(value)
		if t in {"true", "si", "yes", "1"}:
			return True
		if t in {"false", "no", "0"}:
			return False
	return None


def _extraer_slots_llm(texto: str) -> Dict[str, Any]:
	if not (texto or "").strip():
		return {}

	if requests is None:
		logger.warning("IA fallback deshabilitada: no esta instalado 'requests'")
		return {}

	local_slots = _extraer_slots_llm_local(texto)
	if local_slots:
		return local_slots

	if not _llm_disponible():
		return {}

	system_prompt = (
		"Eres un extractor de entidades para pedidos por WhatsApp. "
		"Devuelve SOLO JSON valido sin markdown."
	)
	user_prompt = (
		"Extrae campos de este mensaje de cliente para pedido de empanadas. "
		"Usa null si no aplica.\n"
		"Campos esperados: tipo_servicio(individual|evento|null), producto(carne|pollo|null), "
		"cantidad(numero|null), metodo_entrega(domicilio|recoger_tienda|null), "
		"metodo_pago(efectivo|mercadopago|null), requiere_factura(boolean|null), "
		"confirmar(boolean|null), cancelar(boolean|null), notas_evento(string|null).\n"
		f"Mensaje: {texto}"
	)

	payload = {
		"model": LLM_MODEL,
		"temperature": 0,
		"messages": [
			{"role": "system", "content": system_prompt},
			{"role": "user", "content": user_prompt},
		],
		"response_format": {"type": "json_object"},
	}

	headers = {
		"Authorization": f"Bearer {LLM_API_KEY}",
		"Content-Type": "application/json",
	}

	try:
		resp = requests.post(f"{LLM_BASE_URL}/v1/chat/completions", headers=headers, json=payload, timeout=12)
		resp.raise_for_status()
		body = resp.json()
		content = (((body.get("choices") or [{}])[0].get("message") or {}).get("content") or "{}").strip()
		data = json.loads(content)
		if not isinstance(data, dict):
			return {}
		return data
	except Exception as exc:
		logger.warning("LLM fallback no disponible o fallo de parseo: %s", exc)
		return {}


def _extraer_slots_llm_local(texto: str) -> Dict[str, Any]:
	if not _llm_local_disponible():
		return {}

	prompt = (
		"Extrae entidades de pedido de empanadas y responde SOLO JSON valido. "
		"Sin markdown ni texto adicional. "
		"Campos: tipo_servicio(individual|evento|null), producto(carne|pollo|null), "
		"cantidad(numero|null), metodo_entrega(domicilio|recoger_tienda|null), "
		"metodo_pago(efectivo|mercadopago|null), requiere_factura(boolean|null), "
		"confirmar(boolean|null), cancelar(boolean|null), notas_evento(string|null). "
		f"Mensaje: {texto}"
	)

	payload = {
		"model": LLM_LOCAL_MODEL,
		"prompt": prompt,
		"stream": False,
		"format": "json",
		"options": {"temperature": 0},
	}

	try:
		resp = requests.post(f"{LLM_LOCAL_BASE_URL}/api/generate", json=payload, timeout=8)
		resp.raise_for_status()
		body = resp.json()
		content = (body.get("response") or "{}").strip()
		data = json.loads(content)
		if isinstance(data, dict):
			return data
		return {}
	except Exception as exc:
		logger.info("LLM local (Ollama) no disponible o sin parseo: %s", exc)
		return {}


def _enriquecer_datos_desde_entrada(entrada: str, datos_temp: Dict[str, Any], usar_llm: bool = False) -> Dict[str, Any]:
	datos = _as_dict(datos_temp)
	text = _normalizar_texto(entrada)

	if not text:
		return datos

	if any(k in text for k in ["evento", "cotizacion", "catering", "mayoreo", "fiesta"]):
		datos["tipo_servicio"] = datos.get("tipo_servicio") or "evento"
	elif any(k in text for k in ["individual", "pedido", "quiero pedir", "quiero", "dame", "pedir", "pido", "normal", "personal", "para llevar", "domicilio", "recoger"]):
		datos["tipo_servicio"] = datos.get("tipo_servicio") or "individual"

	catalogo = list(_obtener_catalogo_productos())
	if not datos.get("producto_id"):
		producto = _producto_desde_texto(text, catalogo)
		if producto:
			datos["producto_id"] = producto.get("producto_id")
			datos["producto_nombre"] = f"{producto.get('nombre', '')} {producto.get('variante', '')}".strip()
			datos["precio_unitario"] = _to_float(producto.get("precio"), 0)

	if not datos.get("cantidad"):
		qty = _extraer_cantidad(text)
		if qty and qty > 0:
			datos["cantidad"] = qty

	if not datos.get("metodo_entrega"):
		if any(k in text for k in ["domicilio", "delivery", "mandar", "casa", "enviar"]):
			datos["metodo_entrega"] = "domicilio"
		elif any(k in text for k in ["recoger", "recojo", "para llevar", "paso por", "voy por", "tienda", "local"]):
			datos["metodo_entrega"] = "recoger_tienda"

	if not datos.get("metodo_pago"):
		if "efectivo" in text:
			datos["metodo_pago"] = "efectivo"
		elif any(k in text for k in ["tarjeta", "credito", "debito", "mercadopago", "mercado pago", "transferencia"]):
			datos["metodo_pago"] = "mercadopago"

	if "factura" in text and "requiere_factura" not in datos:
		if any(k in text for k in ["sin factura", "no factura", "no quiero factura"]):
			datos["requiere_factura"] = False
		elif any(k in text for k in ["con factura", "si factura", "quiero factura"]):
			datos["requiere_factura"] = True

	# Si se detectó producto pero tipo_servicio sigue vacío, asumir individual (default para empanadas).
	if datos.get("producto_id") and not datos.get("tipo_servicio"):
		datos["tipo_servicio"] = "individual"

	logger.info("Slots locales tras enriquecimiento: %s", {k: v for k, v in datos.items() if k not in {"ultimo_audio_transcrito"}})

	if usar_llm:
		slots = _extraer_slots_llm(text)
		if slots:
			logger.info("Slots LLM detectados: %s", slots)

			tipo_servicio = _normalizar_texto(slots.get("tipo_servicio") or "")
			if tipo_servicio in {"individual", "evento"}:
				datos["tipo_servicio"] = tipo_servicio

			producto_llm = _normalizar_texto(slots.get("producto") or "")
			if producto_llm and not datos.get("producto_id"):
				producto = _producto_desde_texto(producto_llm, catalogo)
				if producto:
					datos["producto_id"] = producto.get("producto_id")
					datos["producto_nombre"] = f"{producto.get('nombre', '')} {producto.get('variante', '')}".strip()
					datos["precio_unitario"] = _to_float(producto.get("precio"), 0)

			cantidad_llm = slots.get("cantidad")
			try:
				if cantidad_llm is not None and int(cantidad_llm) > 0:
					datos["cantidad"] = int(cantidad_llm)
			except (TypeError, ValueError):
				pass

			entrega_llm = _normalizar_texto(slots.get("metodo_entrega") or "")
			if entrega_llm in {"domicilio", "recoger_tienda"}:
				datos["metodo_entrega"] = entrega_llm

			pago_llm = _normalizar_texto(slots.get("metodo_pago") or "")
			if pago_llm in {"efectivo", "mercadopago"}:
				datos["metodo_pago"] = pago_llm

			req_fact = _parsear_bool_flexible(slots.get("requiere_factura"))
			if req_fact is not None:
				datos["requiere_factura"] = req_fact

			notas = slots.get("notas_evento")
			if isinstance(notas, str) and notas.strip() and not datos.get("notas_evento"):
				datos["notas_evento"] = notas.strip()

	return datos


def _inferir_estado_desde_datos(estado_actual: str, datos_temp: dict) -> str:
	"""
	Cuando el enriquecimiento de audio llenó slots de estados anteriores al actual,
	avanza el estado FSM al primer slot aún vacío en lugar de re-preguntar info ya dada.
	"""
	ESTADOS_INICIALES = {"inicio", "bienvenida", "tipo_servicio"}
	if estado_actual not in ESTADOS_INICIALES:
		return estado_actual
	if datos_temp.get("tipo_servicio") != "individual":
		return estado_actual
	if not datos_temp.get("producto_id"):
		# Tenemos tipo_servicio pero no producto → saltar a tipo_servicio para elegir sabor.
		return "tipo_servicio"
	if not datos_temp.get("cantidad"):
		return "cantidad"
	if not datos_temp.get("metodo_entrega"):
		return "metodo_entrega"
	if datos_temp.get("metodo_entrega") == "domicilio" and not datos_temp.get("direccion_id"):
		return "solicitar_ubicacion"
	if not datos_temp.get("metodo_pago"):
		return "metodo_pago"
	if "requiere_factura" not in datos_temp:
		return "preguntar_factura"
	if datos_temp.get("requiere_factura") is True and not datos_temp.get("datos_fiscales"):
		return "datos_fiscales"
	return "confirmacion"


def _debe_confirmar_rapido(texto: str) -> bool:
	t = _normalizar_texto(texto)
	return any(k in t for k in ["confirm", "procede", "hazlo", "cerrar pedido", "finaliza", "finalizar", "dale"])


def _puede_cierre_rapido(datos_temp: Dict[str, Any]) -> bool:
	if not datos_temp.get("tipo_servicio"):
		return False
	if datos_temp.get("tipo_servicio") == "individual":
		required = ["producto_id", "cantidad", "metodo_entrega", "metodo_pago"]
		if any(not datos_temp.get(k) for k in required):
			return False
		if datos_temp.get("metodo_entrega") == "domicilio" and not datos_temp.get("direccion_id"):
			return False
	if "requiere_factura" not in datos_temp:
		return False
	if datos_temp.get("requiere_factura") is True and not datos_temp.get("datos_fiscales"):
		return False
	return True


def _extraer_lat_lng(body, latitude=None, longitude=None) -> Tuple[Optional[float], Optional[float]]:
	if latitude is not None and longitude is not None:
		try:
			return float(latitude), float(longitude)
		except (TypeError, ValueError):
			pass

	text = body or ""
	pattern = r"(-?\d{1,2}\.\d+)\s*[, ]\s*(-?\d{1,3}\.\d+)"
	match = re.search(pattern, text)
	if match:
		return float(match.group(1)), float(match.group(2))

	return None, None


def _columnas_existentes(conn, tabla):
	with conn.cursor() as cur:
		cur.execute(
			"""
			SELECT column_name
			FROM information_schema.columns
			WHERE table_schema = 'public' AND table_name = %s
			""",
			(tabla,),
		)
		rows = cur.fetchall()
	return {r[0] for r in rows}


def _insert_dinamico(tabla, data):
	conn = None
	try:
		conn = db.get_connection()
		cols_db = _columnas_existentes(conn, tabla)
		payload = {k: v for k, v in data.items() if k in cols_db}
		if not payload:
			return None

		keys = list(payload.keys())
		fields = ", ".join(keys)
		placeholders = ", ".join(["%s"] * len(keys))

		returning = None
		for candidate_id in [f"{tabla[:-1]}_id", "direccion_id", "fiscal_id", "pedido_id"]:
			if candidate_id in cols_db:
				returning = candidate_id
				break

		sql = f"INSERT INTO {tabla} ({fields}) VALUES ({placeholders})"
		if returning:
			sql += f" RETURNING {returning}"

		with conn.cursor() as cur:
			cur.execute(sql, [payload[k] for k in keys])
			rid = cur.fetchone()[0] if returning else None
		conn.commit()
		return rid
	except Exception:
		if conn:
			conn.rollback()
		return None
	finally:
		if conn:
			conn.close()


def _guardar_direccion_en_db(cliente_id, lat, lng):
	data = {
		"cliente_id": cliente_id,
		"latitud": lat,
		"longitud": lng,
		"alias": "Ubicacion WhatsApp",
		"direccion_texto": f"GPS {lat},{lng}",
		"referencia": "Compartida por cliente en WhatsApp",
		"principal": True,
		"actualizado_en": datetime.utcnow(),
	}
	return _insert_dinamico("direcciones_cliente", data)


def _guardar_datos_fiscales_en_db(cliente_id, datos_fiscales):
	data = {
		"cliente_id": cliente_id,
		"rfc": datos_fiscales.get("rfc"),
		"razon_social": datos_fiscales.get("razon_social"),
		"regimen_fiscal": datos_fiscales.get("regimen_fiscal"),
		"uso_cfdi": datos_fiscales.get("uso_cfdi"),
		"email": datos_fiscales.get("email"),
		"actualizado_en": datetime.utcnow(),
	}
	_insert_dinamico("datos_fiscales", data)


def _actualizar_pedido_opcional(pedido_id, payload):
	conn = None
	try:
		conn = db.get_connection()
		cols = _columnas_existentes(conn, "pedidos")
		updates = []
		values = []

		for key, value in payload.items():
			if key in cols:
				updates.append(f"{key} = %s")
				values.append(value)

		if not updates:
			return False

		values.append(pedido_id)
		with conn.cursor() as cur:
			cur.execute(f"UPDATE pedidos SET {', '.join(updates)} WHERE pedido_id = %s", values)
		conn.commit()
		return True
	except Exception:
		if conn:
			conn.rollback()
		return False
	finally:
		if conn:
			conn.close()


def _guardar_evaluacion(pedido_id, tipo, calificacion, comentario):
	payload = {
		"pedido_id": pedido_id,
		"tipo": tipo,
		"tipo_evaluacion": tipo,
		"calificacion": calificacion,
		"comentario": comentario,
		"creado_en": datetime.utcnow(),
	}
	_insert_dinamico("evaluaciones", payload)


def _parsear_factura(texto):
	# Formato esperado: RFC|RAZON SOCIAL|REGIMEN|USO_CFDI|EMAIL(opcional)
	parts = [p.strip() for p in (texto or "").split("|")]
	if len(parts) < 4:
		return None

	return {
		"rfc": parts[0],
		"razon_social": parts[1],
		"regimen_fiscal": parts[2],
		"uso_cfdi": parts[3],
		"email": parts[4] if len(parts) >= 5 else None,
	}


def _producto_desde_texto(texto, catalogo):
	t = _normalizar_texto(texto)
	if "carne" in t:
		for p in catalogo:
			blob = f"{p.get('nombre', '')} {p.get('variante', '')}".lower()
			if "carne" in blob:
				return p
	if "pollo" in t:
		for p in catalogo:
			blob = f"{p.get('nombre', '')} {p.get('variante', '')}".lower()
			if "pollo" in blob:
				return p

	# Si manda un id de producto
	qty = _extraer_cantidad(t)
	if qty is not None:
		for p in catalogo:
			if p.get("producto_id") == qty:
				return p

	# Correcciones comunes de transcripcion de voz.
	tokens = re.findall(r"[a-z]+", t)
	for token in tokens:
		if difflib.get_close_matches(token, ["carne"], n=1, cutoff=0.72):
			for p in catalogo:
				blob = f"{p.get('nombre', '')} {p.get('variante', '')}".lower()
				if "carne" in _normalizar_texto(blob):
					return p
		if difflib.get_close_matches(token, ["pollo"], n=1, cutoff=0.72):
			for p in catalogo:
				blob = f"{p.get('nombre', '')} {p.get('variante', '')}".lower()
				if "pollo" in _normalizar_texto(blob):
					return p

	return None


def _aplicar_transiciones_programadas(estado, datos_temp):
	now = datetime.utcnow()

	if estado == "completado" and datos_temp.get("evaluar_entrega_en"):
		try:
			due = datetime.fromisoformat(datos_temp["evaluar_entrega_en"])
			if now >= due and not datos_temp.get("evaluar_entrega_enviada"):
				datos_temp["evaluar_entrega_enviada"] = True
				return "evaluar_entrega", datos_temp
		except ValueError:
			pass

	if estado == "evaluar_entrega" and datos_temp.get("evaluar_producto_en"):
		try:
			due = datetime.fromisoformat(datos_temp["evaluar_producto_en"])
			if now >= due and not datos_temp.get("evaluar_producto_enviada"):
				datos_temp["evaluar_producto_enviada"] = True
				return "evaluar_producto", datos_temp
		except ValueError:
			pass

	return estado, datos_temp


def generar_codigo_entrega():
	chars = string.ascii_uppercase + string.digits
	conn = None
	try:
		conn = db.get_connection()
		cols = _columnas_existentes(conn, "pedidos")
		if "codigo_entrega" not in cols:
			return "".join(random.choices(chars, k=6))

		with conn.cursor() as cur:
			for _ in range(25):
				code = "".join(random.choices(chars, k=6))
				cur.execute("SELECT 1 FROM pedidos WHERE codigo_entrega = %s LIMIT 1", (code,))
				if not cur.fetchone():
					return code
	except Exception:
		pass
	finally:
		if conn:
			conn.close()

	return "".join(random.choices(chars, k=6))


def _guardar_pedido_final(cliente, datos_temp):
	catalogo = list(_obtener_catalogo_productos())
	producto = None

	datos_temp = _as_dict(datos_temp)
	producto_id = datos_temp.get("producto_id")
	for p in catalogo:
		if p.get("producto_id") == producto_id:
			producto = p
			break

	if not producto:
		# Respaldo para eventos o si no se definio producto.
		producto = catalogo[0] if catalogo else {"producto_id": 1, "precio": 0, "nombre": "Evento", "variante": "Cotizacion"}

	cantidad = int(datos_temp.get("cantidad", 1))
	precio = _to_float(producto.get("precio"), 0)
	direccion_id = datos_temp.get("direccion_id")
	metodo_pago = datos_temp.get("metodo_pago", "efectivo")

	item = {
		"producto_id": producto.get("producto_id"),
		"cantidad": cantidad,
		"precio_unitario": precio,
	}

	creado = db.crear_pedido(
		cliente_id=cliente["cliente_id"],
		items=[item],
		direccion_id=direccion_id,
		metodo_pago=metodo_pago,
	)
	if _es_error(creado):
		raise RuntimeError(creado["error"])

	codigo = generar_codigo_entrega()
	_actualizar_pedido_opcional(
		creado["pedido_id"],
		{
			"codigo_entrega": codigo,
			"tipo_servicio": datos_temp.get("tipo_servicio"),
			"requiere_factura": bool(datos_temp.get("requiere_factura")),
			"notas": datos_temp.get("notas_evento") or datos_temp.get("comentarios"),
		},
	)

	return creado["pedido_id"], codigo


def _manejar_inicio(_text, datos_temp):
	texto = (
		"bienvenido a Que Chimba Empanadas. Te tomo el pedido completo por aqui "
		"y queda guardado en el sistema."
	)
	opciones = (
		"individual\n"
		"evento\n\n"
		"Flujo rapido:\n"
		"1) individual\n"
		"2) carne o pollo\n"
		"3) cantidad\n"
		"4) domicilio o recoger en tienda\n"
		"5) efectivo o tarjeta\n"
		"6) si/no factura\n"
		"7) confirmar"
	)
	return "tipo_servicio", datos_temp, _armar_respuesta(texto, opciones)


def _manejar_bienvenida(_text, datos_temp):
	texto = "cuentame si hoy quieres orden individual o cotizacion para evento."
	opciones = "1) individual\n2) evento"
	return "tipo_servicio", datos_temp, _armar_respuesta(texto, opciones)


def _manejar_tipo_servicio(text, datos_temp):
	t = _normalizar_texto(text)
	if "1" in t or any(k in t for k in ["individual", "pedido", "normal", "personal", "quiero pedir"]):
		datos_temp["tipo_servicio"] = "individual"
		catalogo = _obtener_catalogo_productos()
		texto = "de una, elige sabor de empanada."
		opciones = "carne\npollo\nmenu"
		if catalogo:
			opciones = f"carne\npollo\nmenu\n\n{_menu_texto(catalogo)}"
		return "seleccion_producto", datos_temp, _armar_respuesta(texto, opciones)

	if "2" in t or any(k in t for k in ["evento", "cotizacion", "catering", "fiesta", "mayoreo"]):
		datos_temp["tipo_servicio"] = "evento"
		texto = "perfecto, pasame datos del evento: fecha, zona y cantidad estimada."
		opciones = "Formato sugerido: fecha | zona | cantidad estimada"
		return "datos_evento", datos_temp, _armar_respuesta(texto, opciones)

	texto = "no te entendi bien en el tipo de servicio."
	opciones = "Responde: individual o evento"
	return "tipo_servicio", datos_temp, _armar_respuesta(texto, opciones)


def _manejar_datos_evento(text, datos_temp):
	datos_temp["notas_evento"] = text.strip() if text else ""
	qty = _extraer_cantidad(text)
	if qty:
		datos_temp["cantidad"] = qty
	else:
		datos_temp["cantidad"] = max(int(datos_temp.get("cantidad", 25)), 25)

	texto = "gracias, ya tengo tus datos para cotizar. Te pido metodo de pago preferido para dejar todo listo."
	opciones = "efectivo\ntarjeta"
	return "metodo_pago", datos_temp, _armar_respuesta(texto, opciones)


def _manejar_seleccion_producto(text, datos_temp):
	t = _normalizar_texto(text)
	catalogo = list(_obtener_catalogo_productos())

	if "menu" in t:
		texto = _menu_texto(catalogo)
		opciones = "Elige: carne o pollo"
		return "seleccion_producto", datos_temp, _armar_respuesta(texto, opciones)

	producto = _producto_desde_texto(t, catalogo)
	if not producto:
		texto = "todavia no identifique el sabor."
		opciones = "Responde: carne o pollo"
		return "seleccion_producto", datos_temp, _armar_respuesta(texto, opciones)

	datos_temp["producto_id"] = producto.get("producto_id")
	datos_temp["producto_nombre"] = f"{producto.get('nombre', '')} {producto.get('variante', '')}".strip()
	datos_temp["precio_unitario"] = _to_float(producto.get("precio"), 0)

	texto = "cuantas empanadas quieres?"
	opciones = "Escribe un numero. Ejemplo: 6"
	return "cantidad", datos_temp, _armar_respuesta(texto, opciones)


def _manejar_cantidad(text, datos_temp):
	qty = _extraer_cantidad(text)
	if not qty or qty <= 0:
		texto = "necesito una cantidad valida para seguir."
		opciones = "Ejemplo: 4"
		return "cantidad", datos_temp, _armar_respuesta(texto, opciones)

	datos_temp["cantidad"] = qty
	texto = "super, como prefieres la entrega?"
	opciones = "domicilio\nrecoger en tienda"
	return "metodo_entrega", datos_temp, _armar_respuesta(texto, opciones)


def _manejar_metodo_entrega(text, datos_temp):
	t = _normalizar_texto(text)

	if any(k in t for k in ["domicilio", "enviar", "mandar", "delivery", "casa"]):
		datos_temp["metodo_entrega"] = "domicilio"
		texto = "comparteme tu ubicacion GPS para el envio."
		opciones = "Manda ubicacion en WhatsApp o escribe: lat, lng"
		return "solicitar_ubicacion", datos_temp, _armar_respuesta(texto, opciones)

	if any(k in t for k in ["recoger", "tienda", "local", "llevar", "paso por", "voy por", "recojo"]):
		datos_temp["metodo_entrega"] = "recoger_tienda"
		texto = "listo, pasamos al pago."
		opciones = "efectivo\ntarjeta"
		return "metodo_pago", datos_temp, _armar_respuesta(texto, opciones)

	texto = "no logre identificar el metodo de entrega."
	opciones = "Responde: domicilio o recoger en tienda"
	return "metodo_entrega", datos_temp, _armar_respuesta(texto, opciones)


def _manejar_solicitar_ubicacion(text, datos_temp, cliente, latitude=None, longitude=None):
	lat, lng = _extraer_lat_lng(text, latitude=latitude, longitude=longitude)
	if lat is None or lng is None:
		texto = "aun no veo coordenadas validas."
		opciones = "Comparte ubicacion GPS o escribe: 31.690,-106.424"
		return "solicitar_ubicacion", datos_temp, _armar_respuesta(texto, opciones)

	datos_temp["latitud"] = lat
	datos_temp["longitud"] = lng

	direccion_id = _guardar_direccion_en_db(cliente["cliente_id"], lat, lng)
	if direccion_id:
		datos_temp["direccion_id"] = direccion_id

	texto = "ubicacion recibida, seguimos con metodo de pago."
	opciones = "efectivo\ntarjeta"
	return "metodo_pago", datos_temp, _armar_respuesta(texto, opciones)


def _manejar_metodo_pago(text, datos_temp):
	t = _normalizar_texto(text)
	if "efectivo" in t:
		datos_temp["metodo_pago"] = "efectivo"
	elif any(k in t for k in ["tarjeta", "mercadopago", "mercado pago", "credito", "debito", "transferencia"]):
		datos_temp["metodo_pago"] = "mercadopago"
	else:
		texto = "no detecte metodo de pago valido."
		opciones = "Responde: efectivo o tarjeta"
		return "metodo_pago", datos_temp, _armar_respuesta(texto, opciones)

	texto = "quieres factura?"
	opciones = "si\nno"
	return "preguntar_factura", datos_temp, _armar_respuesta(texto, opciones)


def _resumen_pedido(datos_temp):
	piezas = []
	tipo = datos_temp.get("tipo_servicio", "individual")
	piezas.append(f"Tipo: {tipo}")

	if datos_temp.get("producto_nombre"):
		piezas.append(f"Producto: {datos_temp['producto_nombre']}")
	if datos_temp.get("cantidad"):
		piezas.append(f"Cantidad: {datos_temp['cantidad']}")
	if datos_temp.get("metodo_entrega"):
		piezas.append(f"Entrega: {datos_temp['metodo_entrega']}")
	if datos_temp.get("metodo_pago"):
		piezas.append(f"Pago: {datos_temp['metodo_pago']}")

	return "\n".join(piezas)


def _manejar_preguntar_factura(text, datos_temp):
	t = _normalizar_texto(text)
	if _es_afirmativo(t) or t == "1":
		datos_temp["requiere_factura"] = True
		texto = "dale, pasame datos fiscales en este formato:\nRFC|RAZON SOCIAL|REGIMEN|USO_CFDI|EMAIL(opcional)"
		opciones = "Ejemplo: ABC123456T12|QUE CHIMBA SA DE CV|601|G03|correo@mail.com"
		return "datos_fiscales", datos_temp, _armar_respuesta(texto, opciones)

	if _es_negativo(t) or t in {"n", "0"}:
		datos_temp["requiere_factura"] = False
		resumen = _resumen_pedido(datos_temp)
		texto = f"asi va tu pedido:\n{resumen}"
		opciones = "confirmar\ncancelar"
		return "confirmacion", datos_temp, _armar_respuesta(texto, opciones)

	texto = "no te entendi en factura."
	opciones = "Responde: si o no"
	return "preguntar_factura", datos_temp, _armar_respuesta(texto, opciones)


def _manejar_datos_fiscales(text, datos_temp, cliente):
	parsed = _parsear_factura(text)
	if not parsed:
		texto = "el formato no coincide."
		opciones = "Usa: RFC|RAZON SOCIAL|REGIMEN|USO_CFDI|EMAIL(opcional)"
		return "datos_fiscales", datos_temp, _armar_respuesta(texto, opciones)

	datos_temp["datos_fiscales"] = parsed
	_guardar_datos_fiscales_en_db(cliente["cliente_id"], parsed)

	resumen = _resumen_pedido(datos_temp)
	texto = f"perfecto, tengo datos fiscales y este es tu resumen:\n{resumen}"
	opciones = "confirmar\ncancelar"
	return "confirmacion", datos_temp, _armar_respuesta(texto, opciones)


def _manejar_confirmacion(text, datos_temp, cliente):
	t = _normalizar_texto(text)
	if _es_negativo(t):
		return "inicio", {}, _armar_respuesta("pedido cancelado. Cuando quieras arrancamos de nuevo.", "Escribe hola para iniciar")

	if "confirm" not in t and not _es_afirmativo(t):
		resumen = _resumen_pedido(datos_temp)
		texto = f"revisa tu pedido y confirmame:\n{resumen}"
		opciones = "confirmar\ncancelar"
		return "confirmacion", datos_temp, _armar_respuesta(texto, opciones)

	pedido_id, codigo_entrega = _guardar_pedido_final(cliente, datos_temp)
	datos_temp["pedido_id"] = pedido_id
	datos_temp["codigo_entrega"] = codigo_entrega
	datos_temp["evaluar_entrega_en"] = (datetime.utcnow() + timedelta(minutes=30)).isoformat()
	datos_temp["evaluar_producto_en"] = (datetime.utcnow() + timedelta(days=1)).isoformat()
	datos_temp["evaluar_entrega_enviada"] = False
	datos_temp["evaluar_producto_enviada"] = False

	texto = (
		f"pedido confirmado y guardado en DB con folio #{pedido_id}. "
		f"Tu codigo de entrega es: {codigo_entrega}"
	)
	opciones = "menu\nayuda"
	return "completado", datos_temp, _armar_respuesta(texto, opciones)


def _manejar_completado(_text, datos_temp):
	texto = "tu pedido ya esta en proceso. En breve te pedire evaluar la entrega y luego el producto."
	opciones = "menu\nayuda\ncancelar"
	return "completado", datos_temp, _armar_respuesta(texto, opciones)


def _manejar_evaluar_entrega(text, datos_temp):
	t = _normalizar_texto(text)
	cal = _extraer_cantidad(t)
	if not cal or cal < 1 or cal > 5:
		texto = "como calificas la entrega del 1 al 5?"
		opciones = "1 muy mala\n5 excelente"
		return "evaluar_entrega", datos_temp, _armar_respuesta(texto, opciones)

	pedido_id = datos_temp.get("pedido_id")
	_guardar_evaluacion(pedido_id, "entrega", cal, t)
	texto = "gracias por evaluar la entrega."
	opciones = "Te escribo manana para evaluar producto."
	return "evaluar_producto", datos_temp, _armar_respuesta(texto, opciones)


def _manejar_evaluar_producto(text, datos_temp):
	t = _normalizar_texto(text)
	cal = _extraer_cantidad(t)
	if not cal or cal < 1 or cal > 5:
		texto = "ultima pregunta: como calificas el producto del 1 al 5?"
		opciones = "1 muy malo\n5 brutal"
		return "evaluar_producto", datos_temp, _armar_respuesta(texto, opciones)

	pedido_id = datos_temp.get("pedido_id")
	_guardar_evaluacion(pedido_id, "producto", cal, t)
	texto = "mil gracias por tu feedback, buena nota. Cuando quieras pedimos de nuevo."
	opciones = "Escribe menu para ver sabores"
	return "inicio", {}, _armar_respuesta(texto, opciones)


def _respuesta_ayuda():
	texto = "te ayudo rapido: seguimos paso a paso para tomar pedido, pago y entrega."
	opciones = "menu\ncancelar\ncontinuar"
	return _armar_respuesta(texto, opciones)


def _respuesta_menu():
	menu = _menu_texto(list(_obtener_catalogo_productos()))
	return _armar_respuesta(menu, "Para ordenar escribe: individual")


def procesar_mensaje(from_num, body, media_url=None, media_type=None, latitude=None, longitude=None):
	"""
	Procesa mensajes entrantes de WhatsApp (texto, audio, ubicacion) con FSM persistida en PostgreSQL.
	"""
	try:
		db.limpiar_sesiones_expiradas()

		whatsapp_id = _numero_desde_from(from_num)
		cliente = _obtener_o_crear_cliente(whatsapp_id)

		sesion = _obtener_sesion(whatsapp_id)
		if not sesion:
			estado = "inicio"
			datos_temp = {}
		else:
			estado = sesion.get("estado", "inicio")
			datos_temp = _as_dict(sesion.get("datos_temp"))

		if estado not in ESTADOS:
			estado = "inicio"

		texto_entrada = body or ""
		audio_attempted = False
		if media_url and (media_type or "").startswith("audio"):
			logger.info("Entrada con audio detectada: media_type=%s", media_type)
			audio_attempted = True
			transcrito = _voice_transcribir_audio(media_url)
			if transcrito:
				texto_entrada = transcrito
				datos_temp["ultimo_audio_transcrito"] = transcrito
		elif media_url and not body:
			# Si no llega media_type, intentamos de todos modos transcribir.
			logger.info("Entrada media sin media_type, intentando transcribir por compatibilidad")
			audio_attempted = True
			transcrito = _voice_transcribir_audio(media_url)
			if transcrito:
				texto_entrada = transcrito
				datos_temp["ultimo_audio_transcrito"] = transcrito

		if audio_attempted and not texto_entrada.strip():
			_guardar_sesion(whatsapp_id, estado, datos_temp)
			return _armar_respuesta(
				"no pude transcribir ese audio. Prueba con una nota de voz mas corta o escribeme el mensaje en texto.",
				"Ejemplo: individual",
			)

		entrada = _normalizar_texto(texto_entrada)

		# Enriquecimiento de slots para voz natural. El LLM es opcional por env vars.
		datos_temp = _enriquecer_datos_desde_entrada(
			entrada,
			datos_temp,
			usar_llm=audio_attempted,
		)

		# Auto-avanzar estado FSM cuando el audio ya lleno slots de etapas anteriores.
		if audio_attempted:
			estado_inferido = _inferir_estado_desde_datos(estado, datos_temp)
			if estado_inferido != estado:
				logger.info("Estado auto-avanzado: %s -> %s (slots: tipo=%s prod=%s cant=%s entrega=%s pago=%s factura=%s)",
					estado, estado_inferido,
					datos_temp.get("tipo_servicio"), datos_temp.get("producto_id"),
					datos_temp.get("cantidad"), datos_temp.get("metodo_entrega"),
					datos_temp.get("metodo_pago"), datos_temp.get("requiere_factura"))
				estado = estado_inferido

		if _debe_confirmar_rapido(entrada) and _puede_cierre_rapido(datos_temp):
			pedido_id, codigo_entrega = _guardar_pedido_final(cliente, datos_temp)
			datos_temp["pedido_id"] = pedido_id
			datos_temp["codigo_entrega"] = codigo_entrega
			datos_temp["evaluar_entrega_en"] = (datetime.utcnow() + timedelta(minutes=30)).isoformat()
			datos_temp["evaluar_producto_en"] = (datetime.utcnow() + timedelta(days=1)).isoformat()
			datos_temp["evaluar_entrega_enviada"] = False
			datos_temp["evaluar_producto_enviada"] = False
			_guardar_sesion(whatsapp_id, "completado", datos_temp)
			return _armar_respuesta(
				f"pedido confirmado y guardado en DB con folio #{pedido_id}. Tu codigo de entrega es: {codigo_entrega}",
				"menu\nayuda",
			)

		# Palabras clave globales.
		if "cancelar" in entrada:
			estado = "inicio"
			datos_temp = {}
			_guardar_sesion(whatsapp_id, estado, datos_temp)
			return _armar_respuesta("pedido cancelado y sesion reiniciada.", "Escribe hola para empezar")

		if entrada in {"hola", "buenas", "buenos dias", "inicio", "empezar"}:
			nuevo_estado, datos_temp, response = _manejar_inicio(entrada, {})
			_guardar_sesion(whatsapp_id, nuevo_estado, datos_temp)
			return response

		if "ayuda" in entrada:
			_guardar_sesion(whatsapp_id, estado, datos_temp)
			return _respuesta_ayuda()

		if "menu" in entrada:
			_guardar_sesion(whatsapp_id, estado, datos_temp)
			return _respuesta_menu()

		# Transiciones temporizadas.
		estado, datos_temp = _aplicar_transiciones_programadas(estado, datos_temp)

		if estado == "inicio":
			nuevo_estado, datos_temp, response = _manejar_inicio(entrada, datos_temp)

		elif estado == "bienvenida":
			nuevo_estado, datos_temp, response = _manejar_bienvenida(entrada, datos_temp)

		elif estado == "tipo_servicio":
			nuevo_estado, datos_temp, response = _manejar_tipo_servicio(entrada, datos_temp)

		elif estado == "datos_evento":
			nuevo_estado, datos_temp, response = _manejar_datos_evento(texto_entrada, datos_temp)

		elif estado == "seleccion_producto":
			nuevo_estado, datos_temp, response = _manejar_seleccion_producto(texto_entrada, datos_temp)

		elif estado == "cantidad":
			nuevo_estado, datos_temp, response = _manejar_cantidad(entrada, datos_temp)

		elif estado == "metodo_entrega":
			nuevo_estado, datos_temp, response = _manejar_metodo_entrega(entrada, datos_temp)

		elif estado == "solicitar_ubicacion":
			nuevo_estado, datos_temp, response = _manejar_solicitar_ubicacion(
				texto_entrada,
				datos_temp,
				cliente,
				latitude=latitude,
				longitude=longitude,
			)

		elif estado == "metodo_pago":
			nuevo_estado, datos_temp, response = _manejar_metodo_pago(entrada, datos_temp)

		elif estado == "preguntar_factura":
			nuevo_estado, datos_temp, response = _manejar_preguntar_factura(entrada, datos_temp)

		elif estado == "datos_fiscales":
			nuevo_estado, datos_temp, response = _manejar_datos_fiscales(texto_entrada, datos_temp, cliente)

		elif estado == "confirmacion":
			nuevo_estado, datos_temp, response = _manejar_confirmacion(texto_entrada, datos_temp, cliente)

		elif estado == "completado":
			# Si ya toca encuesta, preguntar encuesta aunque el usuario mande otra cosa.
			if datos_temp.get("evaluar_entrega_en") and datetime.utcnow() >= datetime.fromisoformat(datos_temp["evaluar_entrega_en"]):
				nuevo_estado = "evaluar_entrega"
				texto = "ya te entregamos, como calificas la entrega del 1 al 5?"
				response = _armar_respuesta(texto, "1 muy mala\n5 excelente")
			else:
				nuevo_estado, datos_temp, response = _manejar_completado(entrada, datos_temp)

		elif estado == "evaluar_entrega":
			nuevo_estado, datos_temp, response = _manejar_evaluar_entrega(entrada, datos_temp)

		elif estado == "evaluar_producto":
			nuevo_estado, datos_temp, response = _manejar_evaluar_producto(entrada, datos_temp)

		else:
			nuevo_estado = "inicio"
			datos_temp = {}
			response = _armar_respuesta("se reinicio tu flujo por seguridad.", "Escribe hola para continuar")

		_guardar_sesion(whatsapp_id, nuevo_estado, datos_temp)
		return response

	except Exception as exc:
		# Nunca rompemos el webhook; regresamos mensaje amable y mantenemos reintento sencillo.
		return {
			"tipo": "texto",
			"contenido": (
				"Listo parce, tuve un enredo tecnico momentaneo. "
				f"Intenta de nuevo en un momento. Detalle: {exc}"
			),
		}


def procesar_mensaje_whatsapp(whatsapp_id, mensaje, media_url=None, media_type=None, latitude=None, longitude=None):
	"""
	Alias compatible con app.py actual.
	"""
	return procesar_mensaje(
		from_num=whatsapp_id,
		body=mensaje,
		media_url=media_url,
		media_type=media_type,
		latitude=latitude,
		longitude=longitude,
	)
