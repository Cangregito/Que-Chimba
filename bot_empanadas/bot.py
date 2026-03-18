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
	"confirmar_carrito",
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


def _extraer_items_menu_oficial(texto: str) -> Dict[str, Any]:
	t = _normalizar_texto(texto)
	items = []
	try:
		catalogo = list(_obtener_catalogo_productos())
	except Exception:
		catalogo = []

	if not catalogo:
		return {"items": [], "total": 0}

	def _resolver_producto_por_alias(alias: str) -> Optional[Dict[str, Any]]:
		k = _normalizar_texto(alias)
		if not k:
			return None
		for p in catalogo:
			blob = _normalizar_texto(f"{p.get('nombre', '')} {p.get('variante', '')}")
			if k in blob:
				return p
		return None

	producto_carne = _resolver_producto_por_alias("carne")
	producto_pollo = _resolver_producto_por_alias("pollo")
	producto_agua = _resolver_producto_por_alias("agua")
	producto_refresco = _resolver_producto_por_alias("refresco")
	producto_jugo = _resolver_producto_por_alias("jugo")

	if not producto_carne and catalogo:
		producto_carne = catalogo[0]
	if not producto_pollo:
		for p in catalogo:
			if not producto_carne or p.get("producto_id") != producto_carne.get("producto_id"):
				producto_pollo = p
				break
	if not producto_pollo:
		producto_pollo = producto_carne

	def _push_item(producto: Optional[Dict[str, Any]], cantidad: int):
		if cantidad <= 0:
			return
		if not producto:
			return
		precio = _to_float(producto.get("precio"), 0)
		items.append(
			{
				"producto_id": producto.get("producto_id"),
				"nombre": producto.get("nombre", "Producto"),
				"variante": producto.get("variante", ""),
				"producto_nombre": f"{producto.get('nombre', '')} {producto.get('variante', '')}".strip(),
				"cantidad": int(cantidad),
				"precio_unit": float(precio),
			}
		)

	if "de cada" in t and any(x in t for x in ["carne", "pollo"]):
		m_total = re.search(r"\b(\d{1,3})\b", t)
		if m_total:
			total = int(m_total.group(1))
			mitad = max(total // 2, 1)
			resto = total - mitad
			if "carne" in t:
				_push_item(producto_carne, mitad)
			if "pollo" in t:
				_push_item(producto_pollo, max(resto, 1))

	patrones = [
		(r"(\d{1,3})\s*(?:de\s+)?carne", producto_carne),
		(r"(\d{1,3})\s*(?:de\s+)?pollo", producto_pollo),
		(r"(\d{1,3})\s*(?:de\s+)?agu(?:a|as)", producto_agua),
		(r"(\d{1,3})\s*(?:de\s+)?refresco(?:s)?", producto_refresco),
		(r"(\d{1,3})\s*(?:de\s+)?jugo(?:s)?", producto_jugo),
	]

	for patron, producto in patrones:
		for match in re.finditer(patron, t):
			_push_item(producto, int(match.group(1)))

	for producto in catalogo:
		aliases = []
		nombre = _normalizar_texto(producto.get("nombre") or "")
		variante = _normalizar_texto(producto.get("variante") or "")
		completo = _normalizar_texto(f"{producto.get('nombre', '')} {producto.get('variante', '')}")
		for alias in [completo, nombre, variante]:
			if alias and alias not in aliases and len(alias) >= 3:
				aliases.append(alias)
		for alias in aliases:
			patron = rf"(\d{{1,3}})\s*(?:de\s+)?{re.escape(alias)}(?:es|s)?\b"
			for match in re.finditer(patron, t):
				_push_item(producto, int(match.group(1)))

	if not items:
		for producto in catalogo:
			blob = _normalizar_texto(f"{producto.get('nombre', '')} {producto.get('variante', '')}")
			nombre = _normalizar_texto(producto.get("nombre") or "")
			variante = _normalizar_texto(producto.get("variante") or "")
			if any(alias and alias in t for alias in [blob, nombre, variante]):
				_push_item(producto, 1)

	consolidado: Dict[int, Dict[str, Any]] = {}
	for item in items:
		pid = int(item["producto_id"])
		if pid not in consolidado:
			consolidado[pid] = dict(item)
		else:
			consolidado[pid]["cantidad"] += int(item["cantidad"])

	items_final = [v for v in consolidado.values() if int(v.get("cantidad") or 0) > 0]
	total = int(sum(int(i["cantidad"]) * _to_float(i.get("precio_unit"), 0) for i in items_final))
	return {"items": items_final, "total": total}


def _formatear_carrito(items: list, total: int) -> str:
	try:
		catalogo = list(_obtener_catalogo_productos())
	except Exception:
		catalogo = []
	by_id = {int(p.get("producto_id") or 0): p for p in catalogo if int(p.get("producto_id") or 0) > 0}
	lineas = []
	for i in items:
		pid = int(i.get("producto_id") or 0)
		qty = int(i.get("cantidad") or 0)
		pu = _to_float(i.get("precio_unit"), 0)
		if qty <= 0:
			continue
		p = by_id.get(pid)
		nombre = i.get("nombre") or i.get("producto_nombre") or (p.get("nombre") if p else "Producto")
		variante = i.get("variante") or (p.get("variante") if p else "")
		etiqueta = f"{nombre} {variante}".strip()
		lineas.append(f"- {qty}x {etiqueta} ${qty * pu:.2f}")
	lineas.append(f"TOTAL: ${int(total)} MXN")
	return "\n".join(lineas)


def _validar_disponibilidad_producto(producto_id: Any, cantidad: Any) -> Optional[str]:
	try:
		resultado = db.obtener_disponibilidad_producto(producto_id=producto_id, cantidad=cantidad)
	except Exception as exc:
		logger.warning("No se pudo validar disponibilidad para producto_id=%s: %s", producto_id, exc)
		return "No pude validar existencias en este momento."

	if not isinstance(resultado, dict):
		return None
	if resultado.get("error"):
		return str(resultado.get("error"))
	if resultado.get("ok") is False:
		return str(resultado.get("error") or "Producto no disponible en este momento.")
	return None


def _validar_items_carrito(items: list) -> Optional[str]:
	for item in items or []:
		error = _validar_disponibilidad_producto(item.get("producto_id"), item.get("cantidad"))
		if error:
			return error
	return None


MODISMOS_SEGUROS = [
	"Ay que chimba,",
	"Listo parce,",
	"Buena nota,",
	"Dale que si,",
]

TRATO_POR_GENERO = {
	"mujer": "mi reina",
	"hombre": "mi rey",
	"neutro": "parce",
}


BOT_REPLY_MODE = (os.getenv("BOT_REPLY_MODE", "texto") or "texto").strip().lower()
LLM_FALLBACK_ENABLED = (os.getenv("LLM_FALLBACK_ENABLED", "0") or "0").strip().lower() in {"1", "true", "yes", "on"}
LLM_BASE_URL = (os.getenv("LLM_BASE_URL", "https://api.openai.com") or "https://api.openai.com").rstrip("/")
LLM_MODEL = (os.getenv("LLM_MODEL", "gpt-4o-mini") or "gpt-4o-mini").strip()
LLM_API_KEY = (os.getenv("LLM_API_KEY", "") or "").strip()
LLM_LOCAL_ENABLED = (os.getenv("LLM_LOCAL_ENABLED", "1") or "1").strip().lower() in {"1", "true", "yes", "on"}
LLM_LOCAL_BASE_URL = (os.getenv("LLM_LOCAL_BASE_URL", "http://localhost:11434") or "http://localhost:11434").rstrip("/")
LLM_LOCAL_MODEL = (os.getenv("LLM_LOCAL_MODEL", "phi3:mini") or "phi3:mini").strip()


def _get_timeout_env(name: str, default: float) -> float:
	raw = (os.getenv(name, str(default)) or str(default)).strip()
	try:
		value = float(raw)
		return value if value > 0 else default
	except ValueError:
		return default


LLM_REMOTE_TIMEOUT_SEC = _get_timeout_env("LLM_REMOTE_TIMEOUT_SEC", 20.0)
LLM_LOCAL_TIMEOUT_SEC = _get_timeout_env("LLM_LOCAL_TIMEOUT_SEC", 30.0)


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


def _actualizar_cliente_basico(cliente_id, nombre=None, apellidos=None, genero_trato=None):
	result = db.actualizar_cliente_basico(
		cliente_id=cliente_id,
		nombre=nombre,
		apellidos=apellidos,
		genero_trato=genero_trato,
	)
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
		limpios = [p for p in productos if isinstance(p, dict)]
		if limpios:
			return limpios

	productos_todos = db.obtener_productos(solo_pedibles=False)
	if _es_error(productos_todos):
		raise RuntimeError(productos_todos["error"])
	if isinstance(productos_todos, list):
		return [p for p in productos_todos if isinstance(p, dict)]
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


def _modo_respuesta(datos_temp: Optional[Dict[str, Any]] = None) -> str:
	datos = _as_dict(datos_temp)
	modo_turno = _normalizar_texto(datos.get("modo_respuesta_turno") or "")
	if modo_turno in {"audio", "texto"}:
		return modo_turno
	if BOT_REPLY_MODE == "audio":
		return "audio"
	return "texto"


def _armar_respuesta(texto, opciones, datos_temp: Optional[Dict[str, Any]] = None):
	prefijo = random.choice(MODISMOS_SEGUROS)
	cuerpo = f"{prefijo} {texto}".strip()
	if opciones:
		cuerpo = f"{cuerpo}\n\nOpciones:\n{opciones}"

	if _modo_respuesta(datos_temp) == "audio":
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


def _detectar_genero_desde_texto(texto: str) -> Optional[str]:
	t = _normalizar_texto(texto)
	if not t:
		return None

	patrones_mujer = [
		"soy mujer",
		"soy una mujer",
		"soy femenina",
		"soy senora",
		"soy chica",
		"soy dama",
		"trata me como mujer",
	]
	patrones_hombre = [
		"soy hombre",
		"soy un hombre",
		"soy masculino",
		"soy senor",
		"soy chico",
		"trata me como hombre",
	]

	if any(p in t for p in patrones_mujer):
		return "mujer"
	if any(p in t for p in patrones_hombre):
		return "hombre"
	return None


def _aplicar_preferencia_trato(entrada: str, datos_temp: Dict[str, Any]) -> Dict[str, Any]:
	datos = _as_dict(datos_temp)
	genero_detectado = _detectar_genero_desde_texto(entrada)
	if genero_detectado in {"mujer", "hombre", "neutro"}:
		datos["genero_trato"] = genero_detectado
	return datos


def _extraer_codigo_postal(texto: str) -> Optional[str]:
	t = texto or ""
	match = re.search(r"\b(\d{5})\b", t)
	if match:
		return match.group(1)
	return None


def _nombre_cliente_es_valido(nombre: Optional[str]) -> bool:
	t = (nombre or "").strip()
	if not t:
		return False
	n = _normalizar_texto(t)
	invalidos = {
		"cliente",
		"cliente whatsapp",
		"whatsapp",
		"sin nombre",
	}
	if n in invalidos:
		return False
	if len(n) < 2:
		return False
	return bool(re.search(r"[a-z]", n))


def _extraer_nombre_cliente(texto: str) -> Optional[str]:
	t = (texto or "").strip()
	if not t:
		return None

	norm = _normalizar_texto(t)
	patrones = [
		r"(?:me llamo|soy|mi nombre es|nombre[:\s]+)\s+([a-zA-Z\s]{2,60})",
	]
	for patron in patrones:
		match = re.search(patron, norm)
		if match:
			valor = match.group(1).strip()
			if _nombre_cliente_es_valido(valor):
				return " ".join(p.title() for p in valor.split())

	# Si no hay frase guia, intentamos usar el texto completo como nombre.
	if _nombre_cliente_es_valido(norm) and len(norm.split()) <= 5:
		return " ".join(p.title() for p in norm.split())
	return None


def _persistir_datos_cliente(cliente: Dict[str, Any], datos_temp: Dict[str, Any]) -> None:
	cliente_id = cliente.get("cliente_id")
	if not cliente_id:
		return
	nombre = datos_temp.get("cliente_nombre")
	apellidos = datos_temp.get("cliente_apellidos")
	genero = datos_temp.get("genero_trato")
	_actualizar_cliente_basico(cliente_id, nombre=nombre, apellidos=apellidos, genero_trato=genero)


def _trato_cliente(datos_temp: Dict[str, Any]) -> str:
	datos = _as_dict(datos_temp)
	genero = _normalizar_texto(datos.get("genero_trato") or "")
	if genero in {"mujer", "hombre"}:
		return TRATO_POR_GENERO[genero]
	return TRATO_POR_GENERO["neutro"]


def _armar_respuesta_comercial(texto: str, opciones: Optional[str], datos_temp: Dict[str, Any]) -> Dict[str, Any]:
	trato = _trato_cliente(datos_temp)
	prefijo = random.choice(MODISMOS_SEGUROS)
	texto_final = f"{trato}, {texto}" if trato else texto
	cuerpo = f"{prefijo} {texto_final}".strip()
	if opciones:
		cuerpo = f"{cuerpo}\n\nOpciones:\n{opciones}"

	if _modo_respuesta(datos_temp) == "audio":
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


def _detectar_intencion_comercial(texto: str) -> Optional[str]:
	t = _normalizar_texto(texto)
	if not t:
		return None

	es_pregunta = "?" in texto or any(
		t.startswith(pref)
		for pref in ["como", "cual", "que", "cuando", "donde", "cuanto", "precio", "horario"]
	)

	if any(k in t for k in ["precio", "cuanto", "costo", "vale"]):
		return "precio"
	if es_pregunta and any(k in t for k in ["horario", "abren", "cierran", "hora"]):
		return "horario"
	if es_pregunta and any(k in t for k in ["domicilio", "envio", "delivery", "zona"]):
		return "entrega"
	if es_pregunta and any(k in t for k in ["pago", "tarjeta", "mercadopago", "efectivo"]):
		return "pago"
	if es_pregunta and "factura" in t:
		return "factura"
	if es_pregunta and any(k in t for k in ["estado", "folio", "codigo"]):
		return "estado"
	if any(k in t for k in ["menu", "sabores", "que venden", "que hay"]):
		return "menu"
	return None


def _respuesta_intencion_comercial(intencion: str, datos_temp: Dict[str, Any]) -> Optional[Dict[str, Any]]:
	if intencion == "menu":
		menu = _menu_texto(list(_obtener_catalogo_productos()))
		return _armar_respuesta_comercial(menu, "Para ordenar escribe: individual", datos_temp)

	if intencion == "precio":
		cantidad = int(datos_temp.get("cantidad") or 1)
		precio = _to_float(datos_temp.get("precio_unitario"), 0.0)
		if precio > 0:
			total = precio * max(cantidad, 1)
			texto = f"te cotizo rapido: {cantidad} pieza(s) te quedan en ${total:.2f} MXN aprox."
			opciones = "Si te late, confirma sabor y cantidad"
		else:
			texto = "te paso precios al momento con menu actualizado y te cotizo exacto en 1 paso."
			opciones = "Escribe: menu"
		return _armar_respuesta_comercial(texto, opciones, datos_temp)

	if intencion == "horario":
		return _armar_respuesta_comercial(
			"te atendemos por este canal y te confirmo horario exacto segun tu zona al cerrar el pedido.",
			"Si quieres, arranco tu orden: individual",
			datos_temp,
		)

	if intencion == "entrega":
		return _armar_respuesta_comercial(
			"hacemos domicilio y tambien recoger en tienda. En domicilio te pedimos GPS para evitar errores.",
			"Responde: domicilio o recoger en tienda",
			datos_temp,
		)

	if intencion == "pago":
		return _armar_respuesta_comercial(
			"aceptamos efectivo y tarjeta por MercadoPago. El pedido queda registrado al confirmar.",
			"Responde: efectivo o tarjeta",
			datos_temp,
		)

	if intencion == "factura":
		return _armar_respuesta_comercial(
			"si facturamos. Si la necesitas, te pido RFC y datos fiscales en formato guiado.",
			"Responde: si factura o no factura",
			datos_temp,
		)

	if intencion == "estado":
		pedido_id = datos_temp.get("pedido_id")
		if pedido_id:
			texto = f"tu ultimo folio activo es #{pedido_id}. Si quieres, te ayudo a continuar el flujo sin perder datos."
		else:
			texto = "todavia no tengo un folio confirmado en esta sesion."
		return _armar_respuesta_comercial(texto, "Para iniciar orden escribe: individual", datos_temp)

	return None


def _normalizar_slots_llm(raw_slots: Dict[str, Any]) -> Dict[str, Any]:
	if not isinstance(raw_slots, dict):
		return {}

	slots: Dict[str, Any] = {}
	tipo_servicio = _normalizar_texto(raw_slots.get("tipo_servicio") or "")
	if tipo_servicio in {"individual", "evento"}:
		slots["tipo_servicio"] = tipo_servicio

	producto = raw_slots.get("producto")
	if isinstance(producto, str) and producto.strip():
		slots["producto"] = producto.strip()

	try:
		cantidad = raw_slots.get("cantidad")
		if cantidad is not None:
			cantidad_int = int(cantidad)
			if 1 <= cantidad_int <= 300:
				slots["cantidad"] = cantidad_int
	except (TypeError, ValueError):
		pass

	metodo_entrega = _normalizar_texto(raw_slots.get("metodo_entrega") or "")
	if metodo_entrega in {"domicilio", "recoger_tienda"}:
		slots["metodo_entrega"] = metodo_entrega

	metodo_pago = _normalizar_texto(raw_slots.get("metodo_pago") or "")
	if metodo_pago in {"efectivo", "mercadopago"}:
		slots["metodo_pago"] = metodo_pago

	req_fact = _parsear_bool_flexible(raw_slots.get("requiere_factura"))
	if req_fact is not None:
		slots["requiere_factura"] = req_fact

	confirmar = _parsear_bool_flexible(raw_slots.get("confirmar"))
	if confirmar is not None:
		slots["confirmar"] = confirmar

	cancelar = _parsear_bool_flexible(raw_slots.get("cancelar"))
	if cancelar is not None:
		slots["cancelar"] = cancelar

	notas = raw_slots.get("notas_evento")
	if isinstance(notas, str) and notas.strip():
		slots["notas_evento"] = notas.strip()[:240]

	genero_trato = _normalizar_texto(raw_slots.get("genero_cliente") or "")
	if genero_trato in {"mujer", "hombre"}:
		slots["genero_trato"] = genero_trato

	return slots


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
	if requests is None:
		return {}

	system_prompt = (
		"Eres un extractor de entidades para pedidos por WhatsApp. "
		"Devuelve SOLO JSON valido sin markdown. "
		"Nunca inventes datos faltantes; usa null cuando no exista evidencia."
	)
	user_prompt = (
		"Extrae campos de este mensaje de cliente para pedido de empanadas. "
		"Usa null si no aplica.\n"
		"Campos esperados: tipo_servicio(individual|evento|null), producto(carne|pollo|null), "
		"cantidad(numero|null), metodo_entrega(domicilio|recoger_tienda|null), "
		"metodo_pago(efectivo|mercadopago|null), requiere_factura(boolean|null), "
		"confirmar(boolean|null), cancelar(boolean|null), notas_evento(string|null), "
		"genero_cliente(mujer|hombre|null).\n"
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
		resp = requests.post(
			f"{LLM_BASE_URL}/v1/chat/completions",
			headers=headers,
			json=payload,
			timeout=LLM_REMOTE_TIMEOUT_SEC,
		)
		resp.raise_for_status()
		body = resp.json()
		content = (((body.get("choices") or [{}])[0].get("message") or {}).get("content") or "{}").strip()
		data = json.loads(content)
		return _normalizar_slots_llm(data)
	except Exception as exc:
		logger.warning("LLM fallback no disponible o fallo de parseo: %s", exc)
		return {}


def _extraer_slots_llm_local(texto: str) -> Dict[str, Any]:
	if not _llm_local_disponible():
		return {}
	if requests is None:
		return {}

	prompt = (
		"Extrae entidades de pedido de empanadas y responde SOLO JSON valido. "
		"Sin markdown ni texto adicional. "
		"Campos: tipo_servicio(individual|evento|null), producto(carne|pollo|null), "
		"cantidad(numero|null), metodo_entrega(domicilio|recoger_tienda|null), "
		"metodo_pago(efectivo|mercadopago|null), requiere_factura(boolean|null), "
		"confirmar(boolean|null), cancelar(boolean|null), notas_evento(string|null), "
		"genero_cliente(mujer|hombre|null). "
		"Si no hay evidencia directa usa null. "
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
		resp = requests.post(
			f"{LLM_LOCAL_BASE_URL}/api/generate",
			json=payload,
			timeout=LLM_LOCAL_TIMEOUT_SEC,
		)
		resp.raise_for_status()
		body = resp.json()
		content = (body.get("response") or "{}").strip()
		data = json.loads(content)
		return _normalizar_slots_llm(data)
	except Exception as exc:
		logger.info("LLM local (Ollama) no disponible o sin parseo: %s", exc)
		return {}


def _enriquecer_datos_desde_entrada(entrada: str, datos_temp: Dict[str, Any], usar_llm: bool = False) -> Dict[str, Any]:
	datos = _as_dict(datos_temp)
	text = _normalizar_texto(entrada)
	datos = _aplicar_preferencia_trato(text, datos)

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
		slots = _normalizar_slots_llm(_extraer_slots_llm(text))
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

			genero_slot = _normalizar_texto(slots.get("genero_trato") or "")
			if genero_slot in {"mujer", "hombre"}:
				datos["genero_trato"] = genero_slot

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


def _deberia_usar_llm(estado: str, entrada: str, datos_temp: Dict[str, Any], audio_attempted: bool) -> bool:
	# Para audio siempre intentamos IA si esta disponible.
	if audio_attempted:
		return _llm_local_disponible() or _llm_disponible()

	if not (_llm_local_disponible() or _llm_disponible()):
		return False

	t = _normalizar_texto(entrada)
	if len(t) < 2:
		return False

	estados_utiles = {
		"inicio",
		"bienvenida",
		"tipo_servicio",
		"seleccion_producto",
		"datos_evento",
		"cantidad",
		"metodo_entrega",
		"metodo_pago",
		"preguntar_factura",
		"confirmacion",
	}
	if estado not in estados_utiles:
		return False

	# Si ya tenemos casi todo para cierre, no gastamos llamada IA.
	if _puede_cierre_rapido(datos_temp):
		return False

	return True


def _faltan_slots_clave_por_estado(estado: str, datos_temp: Dict[str, Any]) -> bool:
	if estado in {"inicio", "bienvenida", "tipo_servicio"}:
		return not bool(datos_temp.get("tipo_servicio"))
	if estado == "seleccion_producto":
		return not bool(datos_temp.get("producto_id"))
	if estado == "datos_evento":
		return not bool(datos_temp.get("notas_evento") or datos_temp.get("cantidad"))
	if estado == "cantidad":
		return not bool(datos_temp.get("cantidad"))
	if estado == "metodo_entrega":
		return not bool(datos_temp.get("metodo_entrega"))
	if estado == "metodo_pago":
		return not bool(datos_temp.get("metodo_pago"))
	if estado == "preguntar_factura":
		return "requiere_factura" not in datos_temp
	return False


def _puede_cierre_rapido(datos_temp: Dict[str, Any]) -> bool:
	if not datos_temp.get("tipo_servicio"):
		return False
	if not _nombre_cliente_es_valido(datos_temp.get("cliente_nombre")):
		return False
	if datos_temp.get("tipo_servicio") == "individual":
		required = ["producto_id", "cantidad", "metodo_entrega", "metodo_pago"]
		if any(not datos_temp.get(k) for k in required):
			return False
		if datos_temp.get("metodo_entrega") == "domicilio" and not datos_temp.get("direccion_id"):
			return False
		if datos_temp.get("metodo_entrega") == "domicilio" and not _extraer_codigo_postal(datos_temp.get("codigo_postal") or ""):
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


def _guardar_direccion_en_db(cliente_id, lat, lng, codigo_postal=None):
	cp = _extraer_codigo_postal(codigo_postal or "")
	direccion = f"GPS {lat},{lng}"
	if cp:
		direccion = f"{direccion} CP:{cp}"
	data = {
		"cliente_id": cliente_id,
		"latitud": lat,
		"longitud": lng,
		"alias": "Ubicacion WhatsApp",
		"direccion_texto": direccion,
		"codigo_postal": cp,
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
			blob = _normalizar_texto(f"{p.get('nombre', '')} {p.get('variante', '')}")
			if "carne" in blob:
				return p
	if "pollo" in t:
		for p in catalogo:
			blob = _normalizar_texto(f"{p.get('nombre', '')} {p.get('variante', '')}")
			if "pollo" in blob:
				return p

	# Si manda un id de producto
	qty = _extraer_cantidad(t)
	if qty is not None:
		for p in catalogo:
			if p.get("producto_id") == qty:
				return p

	# Match directo por nombre/variante completo (o por fragmento relevante).
	for p in catalogo:
		blob = _normalizar_texto(f"{p.get('nombre', '')} {p.get('variante', '')}")
		if blob and (t == blob or t in blob or blob in t):
			return p

	# Match difuso por nombre de producto para tolerar typos/ASR.
	blobs = []
	for p in catalogo:
		blob = _normalizar_texto(f"{p.get('nombre', '')} {p.get('variante', '')}")
		if blob:
			blobs.append((blob, p))
	if blobs:
		candidatos = [b for b, _ in blobs]
		for guess in difflib.get_close_matches(t, candidatos, n=1, cutoff=0.72):
			for blob, p in blobs:
				if blob == guess:
					return p

	# Correcciones comunes de transcripcion de voz.
	tokens = re.findall(r"[a-z]+", t)
	for token in tokens:
		if difflib.get_close_matches(token, ["carne"], n=1, cutoff=0.72):
			for p in catalogo:
				blob = _normalizar_texto(f"{p.get('nombre', '')} {p.get('variante', '')}")
				if "carne" in _normalizar_texto(blob):
					return p
		if difflib.get_close_matches(token, ["pollo"], n=1, cutoff=0.72):
			for p in catalogo:
				blob = _normalizar_texto(f"{p.get('nombre', '')} {p.get('variante', '')}")
				if "pollo" in _normalizar_texto(blob):
					return p

	return None


def _producto_por_id(catalogo, producto_id):
	for p in catalogo:
		if p.get("producto_id") == producto_id:
			return p
	return None


def _guardar_alias_sabores(datos_temp, catalogo):
	if not catalogo:
		return

	carne = None
	pollo = None
	for p in catalogo:
		blob = _normalizar_texto(f"{p.get('nombre', '')} {p.get('variante', '')}")
		if not carne and any(k in blob for k in ["carne", "res", "beef"]):
			carne = p
		if not pollo and any(k in blob for k in ["pollo", "chicken"]):
			pollo = p

	if not carne and catalogo:
		carne = catalogo[0]
	if not pollo:
		for p in catalogo:
			if not carne or p.get("producto_id") != carne.get("producto_id"):
				pollo = p
				break
	if not pollo:
		pollo = carne

	if carne:
		datos_temp["alias_carne_producto_id"] = carne.get("producto_id")
	if pollo:
		datos_temp["alias_pollo_producto_id"] = pollo.get("producto_id")


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


def _normalizar_items_legacy(datos_temp):
	"""Construye datos_temp['items'] desde campos legacy de producto individual si no existe ya."""
	if datos_temp.get("items"):
		return
	producto_id = datos_temp.get("producto_id")
	if not producto_id:
		return
	cantidad = int(datos_temp.get("cantidad") or 1)
	precio_unit = _to_float(datos_temp.get("precio_unitario") or datos_temp.get("precio"), 0)
	if not precio_unit:
		# Intentar con catalogo DB (requiere receta).
		try:
			catalogo = list(_obtener_catalogo_productos())
			for p in catalogo:
				if p.get("producto_id") == producto_id:
					precio_unit = _to_float(p.get("precio"), 0)
					break
		except Exception:
			pass
	if not precio_unit:
		total = _to_float(datos_temp.get("total"), 0)
		if total > 0 and cantidad > 0:
			precio_unit = total / cantidad
	if not precio_unit:
		precio_unit = 0
	datos_temp["items"] = [
		{
			"producto_id": producto_id,
			"nombre": datos_temp.get("producto_nombre", "Producto"),
			"variante": datos_temp.get("variante", ""),
			"cantidad": cantidad,
			"precio_unit": precio_unit,
		}
	]
	datos_temp.setdefault("total", precio_unit * cantidad)


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


def _manejar_inicio(_text, datos_temp, cliente):
	datos = _as_dict(datos_temp)
	nombre_actual = datos.get("cliente_nombre") or cliente.get("nombre")
	if _nombre_cliente_es_valido(nombre_actual):
		datos["cliente_nombre"] = str(nombre_actual).strip()
		texto = "bienvenido a Que Chimba Empanadas. Te tomo el pedido completo por aqui y queda guardado en el sistema."
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
		return "tipo_servicio", datos, _armar_respuesta_comercial(texto, opciones, datos)

	texto = "antes de arrancar, dime tu nombre porfa para registrar bien tu orden."
	opciones = "Ejemplo: me llamo Ana Torres"
	return "bienvenida", datos, _armar_respuesta_comercial(texto, opciones, datos)


def _manejar_bienvenida(text, datos_temp):
	nombre = _extraer_nombre_cliente(text)
	if not nombre:
		texto = "necesito tu nombre para registrar el pedido sin errores."
		opciones = "Escribe tu nombre completo. Ejemplo: Carlos Rivera"
		return "bienvenida", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)

	datos_temp["cliente_nombre"] = nombre
	partes = nombre.split()
	if len(partes) > 1:
		datos_temp["cliente_apellidos"] = " ".join(partes[1:])

	texto = "perfecto, ya te tengo registrado. Cuentame si hoy quieres orden individual o cotizacion para evento."
	opciones = "1) individual\n2) evento"
	return "tipo_servicio", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)


def _manejar_tipo_servicio(text, datos_temp):
	t = _normalizar_texto(text)
	if "1" in t or any(k in t for k in ["individual", "pedido", "normal", "personal", "quiero pedir"]):
		datos_temp["tipo_servicio"] = "individual"
		catalogo = list(_obtener_catalogo_productos())
		_guardar_alias_sabores(datos_temp, catalogo)
		texto = "de una, elige un producto del menu."
		opciones = "menu"
		if catalogo:
			opciones = f"menu\n\n{_menu_texto(catalogo)}"
		return "seleccion_producto", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)

	if "2" in t or any(k in t for k in ["evento", "cotizacion", "catering", "fiesta", "mayoreo"]):
		datos_temp["tipo_servicio"] = "evento"
		texto = "perfecto, pasame datos del evento: fecha, zona y cantidad estimada."
		opciones = "Formato sugerido: fecha | zona | cantidad estimada"
		return "datos_evento", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)

	texto = "no te entendi bien en el tipo de servicio."
	opciones = "Responde: individual o evento"
	return "tipo_servicio", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)


def _manejar_datos_evento(text, datos_temp):
	datos_temp["notas_evento"] = text.strip() if text else ""
	qty = _extraer_cantidad(text)
	if qty:
		datos_temp["cantidad"] = qty
	else:
		datos_temp["cantidad"] = max(int(datos_temp.get("cantidad", 25)), 25)

	texto = "gracias, ya tengo tus datos para cotizar. Te pido metodo de pago preferido para dejar todo listo."
	opciones = "efectivo\ntarjeta"
	return "metodo_pago", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)


def _manejar_seleccion_producto(text, datos_temp):
	t = _normalizar_texto(text)
	catalogo = list(_obtener_catalogo_productos())
	_guardar_alias_sabores(datos_temp, catalogo)

	if "menu" in t:
		texto = _menu_texto(catalogo)
		opciones = "Escribe el producto que quieres"
		return "seleccion_producto", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)

	producto = _producto_desde_texto(t, catalogo)
	if not producto and "carne" in t:
		producto = _producto_por_id(catalogo, datos_temp.get("alias_carne_producto_id"))
	if not producto and "pollo" in t:
		producto = _producto_por_id(catalogo, datos_temp.get("alias_pollo_producto_id"))
	if not producto:
		texto = "todavia no identifique el producto que quieres."
		opciones = "Escribe el nombre del producto o manda: menu"
		return "seleccion_producto", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)

	datos_temp["producto_id"] = producto.get("producto_id")
	datos_temp["producto_nombre"] = f"{producto.get('nombre', '')} {producto.get('variante', '')}".strip()
	datos_temp["precio_unitario"] = _to_float(producto.get("precio"), 0)
	error_stock = _validar_disponibilidad_producto(datos_temp["producto_id"], 1)
	if error_stock:
		texto = f"ese producto no esta disponible ahorita. {error_stock}"
		opciones = "Escribe otro producto o menu"
		return "seleccion_producto", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)

	texto = "cuantas empanadas quieres?"
	opciones = "Escribe un numero. Ejemplo: 6"
	return "cantidad", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)


def _manejar_cantidad(text, datos_temp):
	qty = _extraer_cantidad(text)
	if not qty or qty <= 0:
		texto = "necesito una cantidad valida para seguir."
		opciones = "Ejemplo: 4"
		return "cantidad", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)

	if qty > 300:
		texto = "esa cantidad esta altisima para orden normal; te paso a cotizacion de evento para evitar errores."
		opciones = "Comparte fecha | zona | cantidad estimada"
		datos_temp["tipo_servicio"] = "evento"
		datos_temp["cantidad"] = qty
		return "datos_evento", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)

	datos_temp["cantidad"] = qty
	error_stock = _validar_disponibilidad_producto(datos_temp.get("producto_id"), qty)
	if error_stock:
		texto = f"con esa cantidad no tengo existencia suficiente. {error_stock}"
		opciones = "Prueba con una cantidad menor o elige otro producto"
		return "cantidad", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)
	texto = "super, como prefieres la entrega?"
	opciones = "domicilio\nrecoger en tienda"
	return "metodo_entrega", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)


def _manejar_metodo_entrega(text, datos_temp):
	t = _normalizar_texto(text)

	if any(k in t for k in ["domicilio", "enviar", "mandar", "delivery", "casa"]):
		datos_temp["metodo_entrega"] = "domicilio"
		texto = "comparteme tu ubicacion GPS para el envio."
		opciones = "Manda ubicacion en WhatsApp o escribe: lat, lng"
		return "solicitar_ubicacion", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)

	if any(k in t for k in ["recoger", "tienda", "local", "llevar", "paso por", "voy por", "recojo"]):
		datos_temp["metodo_entrega"] = "recoger_tienda"
		texto = "listo, pasamos al pago."
		opciones = "efectivo\ntarjeta"
		return "metodo_pago", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)

	texto = "no logre identificar el metodo de entrega."
	opciones = "Responde: domicilio o recoger en tienda"
	return "metodo_entrega", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)


def _manejar_solicitar_ubicacion(text, datos_temp, cliente, latitude=None, longitude=None):
	cp_texto = _extraer_codigo_postal(text)
	if cp_texto:
		datos_temp["codigo_postal"] = cp_texto

	if datos_temp.get("esperando_codigo_postal") and datos_temp.get("latitud") is not None and datos_temp.get("longitud") is not None:
		if not datos_temp.get("codigo_postal"):
			texto = "me falta el codigo postal para cerrar envio a domicilio."
			opciones = "Comparte CP de 5 digitos. Ejemplo: 32695"
			return "solicitar_ubicacion", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)

		direccion_id = _guardar_direccion_en_db(
			cliente["cliente_id"],
			datos_temp["latitud"],
			datos_temp["longitud"],
			codigo_postal=datos_temp.get("codigo_postal"),
		)
		if direccion_id:
			datos_temp["direccion_id"] = direccion_id
		datos_temp["esperando_codigo_postal"] = False
		texto = "ubicacion y codigo postal recibidos, seguimos con metodo de pago."
		opciones = "efectivo\ntarjeta"
		return "metodo_pago", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)

	lat, lng = _extraer_lat_lng(text, latitude=latitude, longitude=longitude)
	if lat is None or lng is None:
		texto = "aun no veo coordenadas validas."
		opciones = "Comparte ubicacion GPS o escribe: 31.690,-106.424"
		return "solicitar_ubicacion", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)

	datos_temp["latitud"] = lat
	datos_temp["longitud"] = lng
	datos_temp["esperando_codigo_postal"] = True

	if not datos_temp.get("codigo_postal"):
		texto = "ya tengo tu ubicacion fija. Ahora comparteme tu codigo postal (5 digitos) para registrar el envio exacto."
		opciones = "Ejemplo: 32695"
		return "solicitar_ubicacion", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)

	direccion_id = _guardar_direccion_en_db(cliente["cliente_id"], lat, lng, codigo_postal=datos_temp.get("codigo_postal"))
	if direccion_id:
		datos_temp["direccion_id"] = direccion_id
	datos_temp["esperando_codigo_postal"] = False

	texto = "ubicacion y codigo postal recibidos, seguimos con metodo de pago."
	opciones = "efectivo\ntarjeta"
	return "metodo_pago", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)


def _manejar_metodo_pago(text, datos_temp):
	t = _normalizar_texto(text)
	if "efectivo" in t:
		datos_temp["metodo_pago"] = "efectivo"
	elif any(k in t for k in ["tarjeta", "mercadopago", "mercado pago", "credito", "debito", "transferencia"]):
		datos_temp["metodo_pago"] = "mercadopago"
	else:
		texto = "no detecte metodo de pago valido."
		opciones = "Responde: efectivo o tarjeta"
		return "metodo_pago", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)

	texto = "quieres factura?"
	opciones = "si\nno"
	return "preguntar_factura", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)


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

	precio = _to_float(datos_temp.get("precio_unitario"), 0.0)
	cantidad = int(datos_temp.get("cantidad") or 0)
	if precio > 0 and cantidad > 0:
		piezas.append(f"Total estimado: ${precio * cantidad:.2f} MXN")

	return "\n".join(piezas)


def _manejar_preguntar_factura(text, datos_temp):
	t = _normalizar_texto(text)
	if _es_afirmativo(t) or t == "1":
		datos_temp["requiere_factura"] = True
		texto = "dale, pasame datos fiscales en este formato:\nRFC|RAZON SOCIAL|REGIMEN|USO_CFDI|EMAIL(opcional)"
		opciones = "Ejemplo: ABC123456T12|QUE CHIMBA SA DE CV|601|G03|correo@mail.com"
		return "datos_fiscales", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)

	if _es_negativo(t) or t in {"n", "0", "2"}:
		datos_temp["requiere_factura"] = False
		resumen = _resumen_pedido(datos_temp)
		texto = f"asi va tu pedido:\n{resumen}"
		opciones = "confirmar\ncancelar"
		return "confirmacion", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)

	texto = "no te entendi en factura."
	opciones = "Responde: si o no"
	return "preguntar_factura", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)


def _manejar_datos_fiscales(text, datos_temp, cliente):
	parsed = _parsear_factura(text)
	if not parsed:
		texto = "el formato no coincide."
		opciones = "Usa: RFC|RAZON SOCIAL|REGIMEN|USO_CFDI|EMAIL(opcional)"
		return "datos_fiscales", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)

	datos_temp["datos_fiscales"] = parsed
	_guardar_datos_fiscales_en_db(cliente["cliente_id"], parsed)

	resumen = _resumen_pedido(datos_temp)
	texto = f"perfecto, tengo datos fiscales y este es tu resumen:\n{resumen}"
	opciones = "confirmar\ncancelar"
	return "confirmacion", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)


def _manejar_confirmacion(text, datos_temp, cliente):
	t = _normalizar_texto(text)
	if _es_negativo(t):
		return "inicio", {}, _armar_respuesta_comercial("pedido cancelado. Cuando quieras arrancamos de nuevo.", "Escribe hola para iniciar", datos_temp)

	if "confirm" not in t and not _es_afirmativo(t):
		resumen = _resumen_pedido(datos_temp)
		texto = f"revisa tu pedido y confirmame:\n{resumen}"
		opciones = "confirmar\ncancelar"
		return "confirmacion", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)

	if not _nombre_cliente_es_valido(datos_temp.get("cliente_nombre") or cliente.get("nombre")):
		texto = "antes de confirmar necesito tu nombre para registrar la venta correctamente."
		opciones = "Escribe tu nombre completo. Ejemplo: Mariana Soto"
		return "bienvenida", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)

	if datos_temp.get("metodo_entrega") == "domicilio" and not _extraer_codigo_postal(datos_temp.get("codigo_postal") or ""):
		texto = "para domicilio me falta tu codigo postal exacto."
		opciones = "Comparte CP de 5 digitos. Ejemplo: 32695"
		datos_temp["esperando_codigo_postal"] = True
		return "solicitar_ubicacion", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)

	if datos_temp.get("metodo_pago") not in {"efectivo", "mercadopago"}:
		texto = "me falta metodo de pago valido para cerrar el pedido."
		opciones = "Responde: efectivo o tarjeta"
		return "metodo_pago", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)

	_persistir_datos_cliente(cliente, datos_temp)

	# Unificar con el flujo FSM nuevo: normalizar items legacy si aun no existen.
	_normalizar_items_legacy(datos_temp)

	try:
		resultado = db.crear_pedido_completo(cliente["cliente_id"], datos_temp)
		if isinstance(resultado, dict) and resultado.get("error"):
			raise RuntimeError(resultado["error"])
		pedido_id = resultado["pedido_id"]
		codigo_entrega = resultado["codigo_entrega"]
	except Exception as exc:
		logger.error("Error en _manejar_confirmacion al crear pedido: %s", exc)
		texto = f"hubo un problema al guardar el pedido ({exc}), intenta confirmarlo de nuevo."
		return "confirmacion", datos_temp, _armar_respuesta_comercial(texto, "confirmar\ncancelar", datos_temp)

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
	return "completado", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)


def _manejar_completado(_text, datos_temp):
	texto = "tu pedido ya esta en proceso. En breve te pedire evaluar la entrega y luego el producto."
	opciones = "menu\nayuda\ncancelar"
	return "completado", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)


def _manejar_evaluar_entrega(text, datos_temp):
	t = _normalizar_texto(text)
	cal = _extraer_cantidad(t)
	if not cal or cal < 1 or cal > 5:
		texto = "como calificas la entrega del 1 al 5?"
		opciones = "1 muy mala\n5 excelente"
		return "evaluar_entrega", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)

	pedido_id = datos_temp.get("pedido_id")
	_guardar_evaluacion(pedido_id, "entrega", cal, t)
	texto = "gracias por evaluar la entrega."
	opciones = "Te escribo manana para evaluar producto."
	return "evaluar_producto", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)


def _manejar_evaluar_producto(text, datos_temp):
	t = _normalizar_texto(text)
	cal = _extraer_cantidad(t)
	if not cal or cal < 1 or cal > 5:
		texto = "ultima pregunta: como calificas el producto del 1 al 5?"
		opciones = "1 muy malo\n5 brutal"
		return "evaluar_producto", datos_temp, _armar_respuesta_comercial(texto, opciones, datos_temp)

	pedido_id = datos_temp.get("pedido_id")
	_guardar_evaluacion(pedido_id, "producto", cal, t)
	texto = "mil gracias por tu feedback, buena nota. Cuando quieras pedimos de nuevo."
	opciones = "Escribe menu para ver sabores"
	return "inicio", {}, _armar_respuesta_comercial(texto, opciones, datos_temp)


def _respuesta_ayuda(datos_temp):
	texto = "te ayudo rapido: seguimos paso a paso para tomar pedido, pago y entrega."
	opciones = "menu\ncancelar\ncontinuar"
	return _armar_respuesta_comercial(texto, opciones, datos_temp)


def _respuesta_menu(datos_temp):
	menu = _menu_texto(list(_obtener_catalogo_productos()))
	return _armar_respuesta_comercial(menu, "Para ordenar escribe: individual", datos_temp)


def _respuesta_to_handler_output(response: Dict[str, Any], nuevo_estado: str) -> Dict[str, Any]:
	contenido = ""
	audio_filename = None
	if isinstance(response, dict):
		contenido = str(response.get("contenido") or "")
		audio_filename = response.get("audio_filename")
	return {
		"texto": contenido,
		"audio_path": audio_filename,
		"nuevo_estado": nuevo_estado,
	}


def handle_bienvenida(sesion: dict, mensaje: str, cliente: dict) -> dict:
	datos_temp = _as_dict(sesion.get("datos_temp"))
	t = _normalizar_texto(mensaje)
	if any(k in t for k in ["1", "pedir", "quiero", "orden"]):
		datos_temp["tipo"] = "orden"
		texto = "Bacano parce. Tengo menu dinamico desde el sistema. Digame que va a querer y cuantas."
		opciones = "Ejemplo: 3 de carne y 2 de pollo con 2 aguas"
		response = _armar_respuesta_comercial(texto, opciones, datos_temp)
		out = _respuesta_to_handler_output(response, "seleccion_producto")
		out["datos_temp"] = datos_temp
		return out
	if any(k in t for k in ["2", "evento", "fiesta", "boda"]):
		datos_temp["tipo"] = "evento"
		response = _armar_respuesta_comercial(
			"Listo mi llave, cuenteme para cuantas personas, fecha y si quiere carne, pollo o mitad y mitad.",
			"Ejemplo: 60 empanadas para el 25 de marzo, mitad y mitad",
			datos_temp,
		)
		out = _respuesta_to_handler_output(response, "datos_evento")
		out["datos_temp"] = datos_temp
		return out
	if any(k in t for k in ["3", "menu", "precios", "cuanto"]):
		menu = _menu_texto(list(_obtener_catalogo_productos()))
		response = _armar_respuesta_comercial(menu, "1) Pedir empanadas 2) Evento", datos_temp)
		out = _respuesta_to_handler_output(response, "bienvenida")
		out["datos_temp"] = datos_temp
		return out

	response = _armar_respuesta_comercial(
		"Ey parce, bienvenido a Que Chimba. Elija una opcion para arrancar.",
		"1) Quiero pedir empanadas\n2) Es para evento\n3) Ver menu y precios",
		datos_temp,
	)
	out = _respuesta_to_handler_output(response, "bienvenida")
	out["datos_temp"] = datos_temp
	return out


def handle_seleccion_producto(sesion: dict, mensaje: str, cliente: dict) -> dict:
	datos_temp = _as_dict(sesion.get("datos_temp"))
	extraccion = _extraer_items_menu_oficial(mensaje)
	items = extraccion.get("items") or []
	total = int(extraccion.get("total") or 0)
	if not items:
		response = _armar_respuesta_comercial(
			"No le entendi el pedido completo, parce. Digamelo con cantidades.",
			"Ejemplo: 3 de carne, 2 de pollo y 1 jugo",
			datos_temp,
		)
		out = _respuesta_to_handler_output(response, "seleccion_producto")
		out["datos_temp"] = datos_temp
		return out

	error_stock = _validar_items_carrito(items)
	if error_stock:
		response = _armar_respuesta_comercial(
			f"No puedo confirmar ese carrito ahorita. {error_stock}",
			"Prueba con otra cantidad, otro producto o escribe menu",
			datos_temp,
		)
		out = _respuesta_to_handler_output(response, "seleccion_producto")
		out["datos_temp"] = datos_temp
		return out

	datos_temp["items"] = items
	datos_temp["total"] = total
	resumen = _formatear_carrito(items, total)
	response = _armar_respuesta_comercial(
		f"Buena nota parce, confirme su carrito:\n{resumen}",
		"1) Si, esta bien\n2) Quiero cambiar algo",
		datos_temp,
	)
	out = _respuesta_to_handler_output(response, "confirmar_carrito")
	out["datos_temp"] = datos_temp
	return out


def handle_confirmar_carrito(sesion: dict, mensaje: str, cliente: dict) -> dict:
	datos_temp = _as_dict(sesion.get("datos_temp"))
	t = _normalizar_texto(mensaje)
	if any(k in t for k in ["1", "si", "confirm", "esta bien"]):
		response = _armar_respuesta_comercial(
			"Listo mi llave. Como prefiere recibir su pedido?",
			"1) Domicilio\n2) Recoger en local",
			datos_temp,
		)
		out = _respuesta_to_handler_output(response, "metodo_entrega")
		out["datos_temp"] = datos_temp
		return out
	if any(k in t for k in ["2", "cambiar", "editar"]):
		datos_temp.pop("items", None)
		datos_temp.pop("total", None)
		response = _armar_respuesta_comercial(
			"De una parce, ajustemoslo. Digame de nuevo productos y cantidades.",
			"Ejemplo: 2 de carne y 2 aguas",
			datos_temp,
		)
		out = _respuesta_to_handler_output(response, "seleccion_producto")
		out["datos_temp"] = datos_temp
		return out

	response = _armar_respuesta_comercial(
		"No le cache esa respuesta. Confirmamos o cambiamos?",
		"1) Si, esta bien\n2) Quiero cambiar algo",
		datos_temp,
	)
	out = _respuesta_to_handler_output(response, "confirmar_carrito")
	out["datos_temp"] = datos_temp
	return out


def handle_metodo_entrega(sesion: dict, mensaje: str, cliente: dict) -> dict:
	datos_temp = _as_dict(sesion.get("datos_temp"))
	nuevo_estado, nuevos_datos, response = _manejar_metodo_entrega(mensaje, datos_temp)
	out = _respuesta_to_handler_output(response, nuevo_estado)
	out["datos_temp"] = nuevos_datos
	return out


def handle_solicitar_ubicacion(sesion: dict, mensaje: str, cliente: dict) -> dict:
	datos_temp = _as_dict(sesion.get("datos_temp"))
	nuevo_estado, nuevos_datos, response = _manejar_solicitar_ubicacion(mensaje, datos_temp, cliente)
	out = _respuesta_to_handler_output(response, nuevo_estado)
	out["datos_temp"] = nuevos_datos
	return out


def handle_metodo_pago(sesion: dict, mensaje: str, cliente: dict) -> dict:
	datos_temp = _as_dict(sesion.get("datos_temp"))
	nuevo_estado, nuevos_datos, response = _manejar_metodo_pago(mensaje, datos_temp)
	out = _respuesta_to_handler_output(response, nuevo_estado)
	out["datos_temp"] = nuevos_datos
	return out


def handle_preguntar_factura(sesion: dict, mensaje: str, cliente: dict) -> dict:
	datos_temp = _as_dict(sesion.get("datos_temp"))
	nuevo_estado, nuevos_datos, response = _manejar_preguntar_factura(mensaje, datos_temp)
	out = _respuesta_to_handler_output(response, nuevo_estado)
	out["datos_temp"] = nuevos_datos
	return out


def handle_datos_fiscales(sesion: dict, mensaje: str, cliente: dict) -> dict:
	datos_temp = _as_dict(sesion.get("datos_temp"))
	nuevo_estado, nuevos_datos, response = _manejar_datos_fiscales(mensaje, datos_temp, cliente)
	out = _respuesta_to_handler_output(response, nuevo_estado)
	out["datos_temp"] = nuevos_datos
	return out


def handle_confirmacion(sesion: dict, mensaje: str, cliente: dict) -> dict:
	datos_temp = _as_dict(sesion.get("datos_temp"))
	t = _normalizar_texto(mensaje)

	if any(k in t for k in ["2", "cambiar", "editar"]):
		response = _armar_respuesta_comercial(
			"Dale parce, hacemos el ajuste. Vuelvame a pasar productos y cantidades.",
			"Ejemplo: 2 de carne y 1 jugo",
			datos_temp,
		)
		out = _respuesta_to_handler_output(response, "seleccion_producto")
		out["datos_temp"] = datos_temp
		return out

	if any(k in t for k in ["1", "si", "confirm", "acepto", "listo"]):
		response = _armar_respuesta_comercial(
			"Perfecto parce, voy a confirmar su pedido en sistema.",
			"Aguanteme un segundo y le comparto folio y codigo de entrega.",
			datos_temp,
		)
		out = _respuesta_to_handler_output(response, "completado")
		out["datos_temp"] = datos_temp
		return out

	items = datos_temp.get("items") or []
	total = int(datos_temp.get("total") or 0)
	resumen = _formatear_carrito(items, total) if items else "Aun no tengo items en carrito."
	response = _armar_respuesta_comercial(
		f"Revise su pedido final:\n{resumen}",
		"1) Si, confirmar pedido\n2) Quiero cambiar algo",
		datos_temp,
	)
	out = _respuesta_to_handler_output(response, "confirmacion")
	out["datos_temp"] = datos_temp
	return out


def handle_completado(sesion: dict, mensaje: str, cliente: dict) -> dict:
	datos_temp = _as_dict(sesion.get("datos_temp"))
	try:
		items = datos_temp.get("items") or []
		if not items:
			response = _armar_respuesta_comercial(
				"No encuentro el carrito para cerrar la orden. Armemoslo otra vez rapidito.",
				"Escriba productos y cantidades. Ejemplo: 3 de carne y 2 de pollo",
				datos_temp,
			)
			out = _respuesta_to_handler_output(response, "seleccion_producto")
			out["datos_temp"] = datos_temp
			return out

		result = db.crear_pedido_completo(cliente_id=cliente.get("cliente_id"), datos_temp=datos_temp)
		if _es_error(result):
			raise RuntimeError(result.get("error") or "No se pudo crear pedido completo")

		pedido_id = int(result.get("pedido_id") or 0)
		codigo = str(result.get("codigo_entrega") or "").strip().upper()
		nuevos_datos = {}

		if requests is not None and pedido_id > 0:
			try:
				requests.post(
					"http://localhost:5678/webhook/nuevo-pedido",
					json={
						"pedido_id": pedido_id,
						"items": items,
						"total": datos_temp.get("total"),
						"entrega": datos_temp.get("metodo_entrega") or datos_temp.get("entrega"),
						"cliente_whatsapp": cliente.get("whatsapp_id"),
					},
					timeout=6,
				)
			except Exception:
				# La notificacion no debe romper la confirmacion de compra.
				pass

		response = _armar_respuesta_comercial(
			f"Pedido #{pedido_id} confirmado. Tiempo estimado 20 a 30 minutos. Codigo de entrega: {codigo}",
			"Guarde ese codigo, el repartidor se lo pedira al entregar.",
			nuevos_datos,
		)
		out = _respuesta_to_handler_output(response, "completado")
		out["datos_temp"] = nuevos_datos
		return out
	except Exception:
		response = _armar_respuesta_comercial(
			"Ay parce, hubo un problemita. ¿Puede intentarlo en un momento?",
			"No perdi su carrito, intentemos confirmar otra vez.",
			datos_temp,
		)
		out = _respuesta_to_handler_output(response, "confirmacion")
		out["datos_temp"] = datos_temp
		return out


def handle_evaluar_entrega(sesion: dict, mensaje: str, cliente: dict) -> dict:
	datos_temp = _as_dict(sesion.get("datos_temp"))
	nuevo_estado, nuevos_datos, response = _manejar_evaluar_entrega(mensaje, datos_temp)
	out = _respuesta_to_handler_output(response, nuevo_estado)
	out["datos_temp"] = nuevos_datos
	return out


def handle_evaluar_producto(sesion: dict, mensaje: str, cliente: dict) -> dict:
	datos_temp = _as_dict(sesion.get("datos_temp"))
	nuevo_estado, nuevos_datos, response = _manejar_evaluar_producto(mensaje, datos_temp)
	out = _respuesta_to_handler_output(response, nuevo_estado)
	out["datos_temp"] = nuevos_datos
	return out


def handle_datos_evento(sesion: dict, mensaje: str, cliente: dict) -> dict:
	datos_temp = _as_dict(sesion.get("datos_temp"))
	nuevo_estado, nuevos_datos, response = _manejar_datos_evento(mensaje, datos_temp)
	out = _respuesta_to_handler_output(response, nuevo_estado)
	out["datos_temp"] = nuevos_datos
	return out


def handle_input_inesperado(sesion: dict, mensaje: str, cliente: dict) -> dict:
	datos_temp = _as_dict(sesion.get("datos_temp"))
	estado = (sesion.get("estado") or "bienvenida").strip().lower()
	texto = (
		"No te entendi del todo, parce. Te repito las opciones del paso actual para seguir sin enredos."
	)
	if estado in {"inicio", "bienvenida", "tipo_servicio"}:
		opciones = "1) Quiero pedir empanadas\n2) Es para evento\n3) Ver menu"
	elif estado == "seleccion_producto":
		opciones = "Escribe tu pedido. Ejemplo: 3 de carne y 2 de pollo"
	elif estado in {"confirmacion", "confirmar_carrito"}:
		opciones = "1) Confirmar\n2) Cambiar algo"
	elif estado == "metodo_entrega":
		opciones = "1) Domicilio\n2) Recoger"
	elif estado == "metodo_pago":
		opciones = "1) Efectivo\n2) Tarjeta"
	else:
		opciones = "Responde con una opcion valida del menu que te mostre."
	response = _armar_respuesta_comercial(texto, opciones, datos_temp)
	out = _respuesta_to_handler_output(response, estado)
	out["datos_temp"] = datos_temp
	return out


def process_message(whatsapp_id, tipo, texto, audio_path=None, lat=None, lng=None):
	"""
	Dispatcher principal compatible con contrato Tarea 1.
	"""
	try:
		db.limpiar_sesiones_expiradas()
		cliente = _obtener_o_crear_cliente(whatsapp_id)
		sesion = _obtener_sesion(whatsapp_id) or {"estado": "inicio", "datos_temp": {}}
		estado = str(sesion.get("estado") or "inicio").strip().lower()
		datos_temp = _as_dict(sesion.get("datos_temp"))

		if estado not in ESTADOS:
			estado = "inicio"

		mensaje = texto or ""
		audio_attempted = False
		tipo_normalizado = _normalizar_texto(tipo or "")
		if tipo_normalizado == "audio" and audio_path:
			audio_attempted = True
			transcrito = _voice_transcribir_audio(audio_path)
			if transcrito:
				mensaje = transcrito
				datos_temp["ultimo_audio_transcrito"] = transcrito

		if audio_attempted and not mensaje.strip():
			response = _armar_respuesta_comercial(
				"No pude transcribir ese audio, parce. Escribeme el pedido en texto y lo saco adelante.",
				"Ejemplo: 2 de carne y 1 jugo",
				datos_temp,
			)
			_guardar_sesion(whatsapp_id, estado, datos_temp)
			return {
				"texto": str(response.get("contenido") or ""),
				"audio_path": response.get("audio_filename"),
				"nuevo_estado": estado,
			}

		entrada = _normalizar_texto(mensaje)
		datos_temp_local = _enriquecer_datos_desde_entrada(entrada, datos_temp, usar_llm=False)
		usar_llm = _deberia_usar_llm(estado, entrada, datos_temp_local, audio_attempted)
		if usar_llm and _faltan_slots_clave_por_estado(estado, datos_temp_local):
			datos_temp = _enriquecer_datos_desde_entrada(entrada, datos_temp_local, usar_llm=True)
		else:
			datos_temp = datos_temp_local

		sesion_local = {"estado": estado, "datos_temp": datos_temp}
		handlers = {
			"inicio": handle_bienvenida,
			"bienvenida": handle_bienvenida,
			"tipo_servicio": lambda s, m, c: _wrap_tipo_servicio_handler(s, m, c),
			"seleccion_producto": handle_seleccion_producto,
			"confirmar_carrito": handle_confirmar_carrito,
			"datos_evento": handle_datos_evento,
			"cantidad": lambda s, m, c: _wrap_cantidad_handler(s, m, c),
			"metodo_entrega": handle_metodo_entrega,
			"solicitar_ubicacion": lambda s, m, c: _wrap_solicitar_ubicacion_handler(s, m, c, lat=lat, lng=lng),
			"metodo_pago": handle_metodo_pago,
			"preguntar_factura": handle_preguntar_factura,
			"datos_fiscales": handle_datos_fiscales,
			"confirmacion": handle_confirmacion,
			"completado": handle_completado,
			"evaluar_entrega": handle_evaluar_entrega,
			"evaluar_producto": handle_evaluar_producto,
		}

		handler = handlers.get(estado, handle_input_inesperado)
		resultado = handler(sesion_local, mensaje, cliente)
		nuevo_estado = str(resultado.get("nuevo_estado") or estado)
		nuevos_datos = _as_dict(resultado.get("datos_temp"))

		if nuevo_estado not in ESTADOS:
			nuevo_estado = estado

		# Generar audio colombiano de bienvenida al nuevo estado cuando hay transicion.
		audio_colombiano = None
		if voice and nuevo_estado != estado:
			try:
				audio_colombiano = voice.generar_audio_colombiano(
					nuevo_estado,
					{"pedido_id": nuevos_datos.get("pedido_id"), "nombre": cliente.get("nombre")},
				)
			except Exception as _exc_audio:
				logger.debug("generar_audio_colombiano omitido para estado %s: %s", nuevo_estado, _exc_audio)

		_guardar_sesion(whatsapp_id, nuevo_estado, nuevos_datos)
		return {
			"texto": str(resultado.get("texto") or ""),
			"audio_path": resultado.get("audio_path"),
			"audio_colombiano_path": audio_colombiano,
			"nuevo_estado": nuevo_estado,
		}

	except Exception:
		return {
			"texto": "Ay parce, tuvimos un problemita. ¿Puede intentarlo en un momento?",
			"audio_path": None,
			"nuevo_estado": "confirmacion",
		}


def _wrap_inicio_handler(sesion: dict, mensaje: str, cliente: dict) -> dict:
	datos_temp = _as_dict(sesion.get("datos_temp"))
	nuevo_estado, nuevos_datos, response = _manejar_inicio(mensaje, datos_temp, cliente)
	out = _respuesta_to_handler_output(response, nuevo_estado)
	out["datos_temp"] = nuevos_datos
	return out


def _wrap_tipo_servicio_handler(sesion: dict, mensaje: str, cliente: dict) -> dict:
	datos_temp = _as_dict(sesion.get("datos_temp"))
	nuevo_estado, nuevos_datos, response = _manejar_tipo_servicio(mensaje, datos_temp)
	out = _respuesta_to_handler_output(response, nuevo_estado)
	out["datos_temp"] = nuevos_datos
	return out


def _wrap_cantidad_handler(sesion: dict, mensaje: str, cliente: dict) -> dict:
	datos_temp = _as_dict(sesion.get("datos_temp"))
	nuevo_estado, nuevos_datos, response = _manejar_cantidad(mensaje, datos_temp)
	out = _respuesta_to_handler_output(response, nuevo_estado)
	out["datos_temp"] = nuevos_datos
	return out


def _wrap_solicitar_ubicacion_handler(sesion: dict, mensaje: str, cliente: dict, lat=None, lng=None) -> dict:
	datos_temp = _as_dict(sesion.get("datos_temp"))
	nuevo_estado, nuevos_datos, response = _manejar_solicitar_ubicacion(
		mensaje,
		datos_temp,
		cliente,
		latitude=lat,
		longitude=lng,
	)
	out = _respuesta_to_handler_output(response, nuevo_estado)
	out["datos_temp"] = nuevos_datos
	return out


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

		if _nombre_cliente_es_valido(cliente.get("nombre")) and not _nombre_cliente_es_valido(datos_temp.get("cliente_nombre")):
			datos_temp["cliente_nombre"] = str(cliente.get("nombre", "")).strip()
		if cliente.get("apellidos") and not datos_temp.get("cliente_apellidos"):
			datos_temp["cliente_apellidos"] = str(cliente.get("apellidos", "")).strip()
		if cliente.get("genero_trato") in {"mujer", "hombre", "neutro"} and not datos_temp.get("genero_trato"):
			datos_temp["genero_trato"] = cliente.get("genero_trato")

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
			datos_temp["modo_respuesta_turno"] = "audio"
			_guardar_sesion(whatsapp_id, estado, datos_temp)
			return _armar_respuesta_comercial(
				"no pude transcribir ese audio. Prueba con una nota de voz mas corta o escribeme el mensaje en texto.",
				"Ejemplo: individual",
				datos_temp,
			)

		modo_demo_audio = BOT_REPLY_MODE == "audio"
		datos_temp["modo_respuesta_turno"] = "audio" if (audio_attempted or modo_demo_audio) else "texto"

		entrada = _normalizar_texto(texto_entrada)
		datos_temp = _aplicar_preferencia_trato(entrada, datos_temp)

		# Estrategia hibrida: primero reglas locales, luego IA solo si faltan slots clave.
		datos_temp_local = _enriquecer_datos_desde_entrada(
			entrada,
			datos_temp,
			usar_llm=False,
		)
		usar_llm = _deberia_usar_llm(estado, entrada, datos_temp_local, audio_attempted)
		if usar_llm and _faltan_slots_clave_por_estado(estado, datos_temp_local):
			datos_temp = _enriquecer_datos_desde_entrada(
				entrada,
				datos_temp_local,
				usar_llm=True,
			)
		else:
			datos_temp = datos_temp_local

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
			_persistir_datos_cliente(cliente, datos_temp)
			_normalizar_items_legacy(datos_temp)
			try:
				resultado = db.crear_pedido_completo(cliente["cliente_id"], datos_temp)
				if isinstance(resultado, dict) and resultado.get("error"):
					raise RuntimeError(resultado["error"])
				pedido_id = resultado["pedido_id"]
				codigo_entrega = resultado["codigo_entrega"]
			except Exception as exc:
				logger.error("Error en cierre rapido al crear pedido: %s", exc)
				_guardar_sesion(whatsapp_id, "confirmacion", datos_temp)
				return _armar_respuesta_comercial(
					f"hubo un problema al guardar el pedido ({exc}), intenta confirmarlo de nuevo.",
					"confirmar\ncancelar",
					datos_temp,
				)
			datos_temp["pedido_id"] = pedido_id
			datos_temp["codigo_entrega"] = codigo_entrega
			datos_temp["evaluar_entrega_en"] = (datetime.utcnow() + timedelta(minutes=30)).isoformat()
			datos_temp["evaluar_producto_en"] = (datetime.utcnow() + timedelta(days=1)).isoformat()
			datos_temp["evaluar_entrega_enviada"] = False
			datos_temp["evaluar_producto_enviada"] = False
			_guardar_sesion(whatsapp_id, "completado", datos_temp)
			return _armar_respuesta_comercial(
				f"pedido confirmado y guardado en DB con folio #{pedido_id}. Tu codigo de entrega es: {codigo_entrega}",
				"menu\nayuda",
				datos_temp,
			)

		# Palabras clave globales.
		if "cancelar" in entrada:
			estado = "inicio"
			datos_temp = {}
			_guardar_sesion(whatsapp_id, estado, datos_temp)
			return _armar_respuesta_comercial("pedido cancelado y sesion reiniciada.", "Escribe hola para empezar", datos_temp)

		if entrada in {"hola", "buenas", "buenos dias", "inicio", "empezar"}:
			nuevo_estado, datos_temp, response = _manejar_inicio(entrada, {}, cliente)
			_guardar_sesion(whatsapp_id, nuevo_estado, datos_temp)
			return response

		if "ayuda" in entrada:
			_guardar_sesion(whatsapp_id, estado, datos_temp)
			return _respuesta_ayuda(datos_temp)

		if "menu" in entrada:
			_guardar_sesion(whatsapp_id, estado, datos_temp)
			return _respuesta_menu(datos_temp)

		if estado in {"inicio", "bienvenida", "completado"}:
			intencion = _detectar_intencion_comercial(texto_entrada)
			if intencion:
				respuesta_comercial = _respuesta_intencion_comercial(intencion, datos_temp)
				if respuesta_comercial:
					_guardar_sesion(whatsapp_id, estado, datos_temp)
					return respuesta_comercial

		# Transiciones temporizadas.
		estado, datos_temp = _aplicar_transiciones_programadas(estado, datos_temp)

		if estado == "inicio":
			nuevo_estado, datos_temp, response = _manejar_inicio(entrada, datos_temp, cliente)

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
				response = _armar_respuesta(texto, "1 muy mala\n5 excelente", datos_temp)
			else:
				nuevo_estado, datos_temp, response = _manejar_completado(entrada, datos_temp)

		elif estado == "evaluar_entrega":
			nuevo_estado, datos_temp, response = _manejar_evaluar_entrega(entrada, datos_temp)

		elif estado == "evaluar_producto":
			nuevo_estado, datos_temp, response = _manejar_evaluar_producto(entrada, datos_temp)

		else:
			nuevo_estado = "inicio"
			datos_temp = {}
			response = _armar_respuesta_comercial("se reinicio tu flujo por seguridad.", "Escribe hola para continuar", datos_temp)

		_guardar_sesion(whatsapp_id, nuevo_estado, datos_temp)
		return response

	except Exception as exc:
		# Nunca rompemos el webhook; regresamos mensaje amable y mantenemos reintento sencillo.
		return _armar_respuesta(
			"tuve un enredo tecnico momentaneo. Intenta de nuevo en un momento.",
			f"Detalle tecnico: {exc}",
			datos_temp if 'datos_temp' in locals() else None,
		)


def procesar_mensaje_whatsapp(whatsapp_id, mensaje, media_url=None, media_type=None, latitude=None, longitude=None):
	"""
	Puerta de entrada desde app.py. Enruta al nuevo dispatcher FSM (process_message)
	y convierte la salida al formato legacy {"tipo", "contenido", "audio_filename"}
	que app.py / webhook_baileys ya conoce; ademas incluye audio_colombiano_path.
	"""
	from_id = _numero_desde_from(whatsapp_id)

	# Determinar tipo de entrada para process_message.
	if media_url and (media_type or "").startswith("audio"):
		tipo = "audio"
		audio_path = media_url
	else:
		tipo = "text"
		audio_path = None

	resultado = process_message(
		whatsapp_id=from_id,
		tipo=tipo,
		texto=mensaje or "",
		audio_path=audio_path,
		lat=latitude,
		lng=longitude,
	)

	texto_salida = str(resultado.get("texto") or "")
	audio_path_salida = resultado.get("audio_path")
	audio_colombiano_path = resultado.get("audio_colombiano_path")

	if audio_path_salida:
		return {
			"tipo": "audio",
			"contenido": texto_salida,
			"audio_filename": os.path.basename(str(audio_path_salida)),
			"audio_colombiano_path": audio_colombiano_path,
		}

	return {
		"tipo": "texto",
		"contenido": texto_salida,
		"audio_colombiano_path": audio_colombiano_path,
	}
