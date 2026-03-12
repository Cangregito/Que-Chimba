import os
import random
import re
import string
import importlib
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, Iterable, Optional, Tuple

import db

try:
	voice = importlib.import_module("voice")
except Exception:
	voice = None


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


def _now_iso():
	return datetime.utcnow().isoformat()


def _normalizar_numero(numero):
	return (numero or "").strip().lower()


def _normalizar_texto(texto):
	return (texto or "").strip().lower()


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
	productos = db.obtener_productos()
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
		return ""

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
					return text.strip()
				return ""
			except Exception:
				continue
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
	match = re.search(r"\b(\d{1,3})\b", texto or "")
	if not match:
		return None
	return int(match.group(1))


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
	texto = "bienvenido a Que Chimba. Te voy guiando paso a paso para tu pedido."
	opciones = "Escribe cualquier mensaje para continuar"
	return "bienvenida", datos_temp, _armar_respuesta(texto, opciones)


def _manejar_bienvenida(_text, datos_temp):
	texto = "cuentame si hoy quieres orden individual o cotizacion para evento."
	opciones = "1) individual\n2) evento"
	return "tipo_servicio", datos_temp, _armar_respuesta(texto, opciones)


def _manejar_tipo_servicio(text, datos_temp):
	t = _normalizar_texto(text)
	if "1" in t or "individual" in t:
		datos_temp["tipo_servicio"] = "individual"
		catalogo = _obtener_catalogo_productos()
		texto = "de una, elige sabor de empanada."
		opciones = "carne\npollo\nmenu"
		if catalogo:
			opciones = f"carne\npollo\nmenu\n\n{_menu_texto(catalogo)}"
		return "seleccion_producto", datos_temp, _armar_respuesta(texto, opciones)

	if "2" in t or "evento" in t or "cotizacion" in t:
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

	if "domicilio" in t or "enviar" in t:
		datos_temp["metodo_entrega"] = "domicilio"
		texto = "comparteme tu ubicacion GPS para el envio."
		opciones = "Manda ubicacion en WhatsApp o escribe: lat, lng"
		return "solicitar_ubicacion", datos_temp, _armar_respuesta(texto, opciones)

	if "recoger" in t or "tienda" in t or "local" in t:
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
	elif "tarjeta" in t or "mercadopago" in t:
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
	if t in {"si", "sí", "s", "1"}:
		datos_temp["requiere_factura"] = True
		texto = "dale, pasame datos fiscales en este formato:\nRFC|RAZON SOCIAL|REGIMEN|USO_CFDI|EMAIL(opcional)"
		opciones = "Ejemplo: ABC123456T12|QUE CHIMBA SA DE CV|601|G03|correo@mail.com"
		return "datos_fiscales", datos_temp, _armar_respuesta(texto, opciones)

	if t in {"no", "n", "0"}:
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
	if "cancel" in t:
		return "inicio", {}, _armar_respuesta("pedido cancelado. Cuando quieras arrancamos de nuevo.", "Escribe hola para iniciar")

	if "confirm" not in t and t not in {"si", "sí", "ok", "dale"}:
		texto = "te leo, pero para cerrar necesito confirmacion explicita."
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
		if media_url and (media_type or "").startswith("audio"):
			transcrito = _voice_transcribir_audio(media_url)
			if transcrito:
				texto_entrada = transcrito
				datos_temp["ultimo_audio_transcrito"] = transcrito
		elif media_url and not body:
			# Si no llega media_type, intentamos de todos modos transcribir.
			transcrito = _voice_transcribir_audio(media_url)
			if transcrito:
				texto_entrada = transcrito
				datos_temp["ultimo_audio_transcrito"] = transcrito

		entrada = _normalizar_texto(texto_entrada)

		# Palabras clave globales.
		if "cancelar" in entrada:
			estado = "inicio"
			datos_temp = {}
			_guardar_sesion(whatsapp_id, estado, datos_temp)
			return _armar_respuesta("pedido cancelado y sesion reiniciada.", "Escribe hola para empezar")

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
