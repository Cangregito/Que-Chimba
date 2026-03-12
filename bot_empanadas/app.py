import json
import importlib
import os
from datetime import date, datetime
from decimal import Decimal
from functools import wraps

from flask import Flask, abort, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from twilio.twiml.messaging_response import MessagingResponse

import db

try:
    _bot_module = importlib.import_module("bot")
    procesar_mensaje_whatsapp = _bot_module.procesar_mensaje_whatsapp
except Exception:
    def procesar_mensaje_whatsapp(
        whatsapp_id,
        mensaje,
        media_url=None,
        media_type=None,
        latitude=None,
        longitude=None,
    ):
        texto = (
            f"Ay que chimba, {whatsapp_id}. Recibi: '{mensaje or 'audio'}'. "
            "Listo parce, tu pedido va en camino en el flujo demo."
        )
        return {"tipo": "texto", "contenido": texto}


app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET", "cambia-esta-clave-en-produccion")
app.config["JSON_SORT_KEYS"] = False
app.config["AUDIO_DIR"] = os.path.join(os.path.dirname(__file__), "audios_temp")
app.config["PUBLIC_BASE_URL"] = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

os.makedirs(app.config["AUDIO_DIR"], exist_ok=True)


ESTADOS_VALIDOS_PEDIDO = {
    "recibido",
    "en_preparacion",
    "listo",
    "en_camino",
    "entregado",
    "cancelado",
}


USUARIOS_DEMO = {
    "admin": {"password": "admin123", "rol": "admin"},
    "cocina": {"password": "cocina123", "rol": "cocina"},
    "repartidor": {"password": "repartidor123", "rol": "repartidor"},
}


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _serialize(value):
    return json.loads(json.dumps(value, default=_json_default))


def _ok(data, status=200):
    return jsonify({"ok": True, "data": _serialize(data)}), status


def _error(message, status=400):
    return jsonify({"ok": False, "error": message}), status


def login_required(roles=None):
    roles = roles or []

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            usuario = session.get("user")
            if not usuario:
                return redirect(url_for("login_page", next=request.path))

            if roles and usuario.get("rol") not in roles:
                abort(403)
            return view_func(*args, **kwargs)

        return wrapper

    return decorator


@app.get("/health")
def health():
    return _ok({"status": "up"})


@app.get("/")
def landing():
    return render_template("index.html")


@app.get("/login")
def login_page():
    return render_template("login.html")


@app.post("/login")
def login_post():
    payload = request.get_json(silent=True) or request.form
    username = payload.get("username")
    password = payload.get("password")

    user = USUARIOS_DEMO.get(username)
    if not user or user["password"] != password:
        return _error("Credenciales invalidas", 401)

    session["user"] = {"username": username, "rol": user["rol"]}
    return _ok({"username": username, "rol": user["rol"]})


@app.post("/logout")
def logout():
    session.clear()
    return _ok({"message": "Sesion cerrada"})


@app.get("/admin")
@login_required(roles=["admin"])
def admin_page():
    return render_template("admin.html", user=session.get("user"))


@app.get("/cocina")
@login_required(roles=["admin", "cocina"])
def cocina_page():
    return render_template("cocina.html", user=session.get("user"))


@app.get("/repartidor")
@login_required(roles=["admin", "repartidor"])
def repartidor_page():
    return render_template("repartidor.html", user=session.get("user"))


@app.get("/audio/<path:filename>")
def servir_audio(filename):
    return send_from_directory(app.config["AUDIO_DIR"], filename, mimetype="audio/ogg")


@app.get("/api/productos")
def api_productos():
    data = db.obtener_productos()
    if isinstance(data, dict) and data.get("error"):
        return _error(data["error"], 500)
    return _ok(data)


@app.get("/api/pedidos")
def api_pedidos():
    estado = request.args.get("estado")
    fecha = request.args.get("fecha")

    data = db.obtener_pedidos(estado=estado, fecha=fecha)
    if isinstance(data, dict) and data.get("error"):
        return _error(data["error"], 500)
    return _ok(data)


@app.post("/api/pedidos")
def api_crear_pedido():
    payload = request.get_json(silent=True) or {}

    cliente_id = payload.get("cliente_id")
    whatsapp_id = payload.get("whatsapp_id")
    direccion_id = payload.get("direccion_id")
    metodo_pago = payload.get("metodo_pago", "efectivo")
    items = payload.get("items", [])

    if not cliente_id:
        if not whatsapp_id:
            return _error("Debes enviar cliente_id o whatsapp_id")
        cliente = db.obtener_o_crear_cliente(whatsapp_id)
        if isinstance(cliente, dict) and cliente.get("error"):
            return _error(cliente["error"], 500)
        cliente_id = cliente["cliente_id"]

    created = db.crear_pedido(cliente_id, items, direccion_id, metodo_pago)
    if isinstance(created, dict) and created.get("error"):
        return _error(created["error"], 500)
    return _ok(created, 201)


@app.patch("/api/pedidos/<int:pedido_id>/estado")
def api_actualizar_estado_pedido(pedido_id):
    payload = request.get_json(silent=True) or {}
    nuevo_estado = payload.get("estado")

    if nuevo_estado not in ESTADOS_VALIDOS_PEDIDO:
        return _error("Estado no valido", 400)

    updated = db.actualizar_estado_pedido(pedido_id, nuevo_estado)
    if isinstance(updated, dict) and updated.get("error"):
        status = 404 if "no encontrado" in updated["error"].lower() else 500
        return _error(updated["error"], status)
    return _ok(updated)


@app.get("/api/clientes/top20")
def api_top_clientes():
    top = db.obtener_top_clientes(limit=20)
    if isinstance(top, dict) and top.get("error"):
        return _error(top["error"], 500)
    return _ok(top)


@app.get("/api/ventas/diarias")
def api_ventas_diarias():
    data = db.obtener_ventas_diarias()
    if isinstance(data, dict) and data.get("error"):
        return _error(data["error"], 500)
    return _ok(data)


@app.get("/api/ventas/mensuales")
def api_ventas_mensuales():
    data = db.obtener_ventas_mensuales()
    if isinstance(data, dict) and data.get("error"):
        return _error(data["error"], 500)
    return _ok(data)


@app.get("/api/ventas/anuales")
def api_ventas_anuales():
    data = db.obtener_ventas_anuales()
    if isinstance(data, dict) and data.get("error"):
        return _error(data["error"], 500)
    return _ok(data)


@app.get("/api/inventario/alertas")
def api_alertas_inventario():
    data = db.obtener_alertas_inventario()
    if isinstance(data, dict) and data.get("error"):
        return _error(data["error"], 500)
    return _ok(data)


@app.post("/api/campanias")
@login_required(roles=["admin"])
def api_campanias():
    payload = request.get_json(silent=True) or {}
    nombre = payload.get("nombre")
    mensaje = payload.get("mensaje")
    segmento = payload.get("segmento", "general")

    if not nombre or not mensaje:
        return _error("Los campos nombre y mensaje son obligatorios")

    creada = db.crear_campania(
        nombre=nombre,
        mensaje=mensaje,
        segmento=segmento,
        creada_por=session.get("user", {}).get("username"),
    )
    if isinstance(creada, dict) and creada.get("error"):
        return _error(creada["error"], 500)
    return _ok(creada, 201)


@app.get("/api/empleados")
@login_required(roles=["admin"])
def api_empleados():
    data = db.obtener_empleados()
    if isinstance(data, dict) and data.get("error"):
        return _error(data["error"], 500)
    return _ok(data)


@app.post("/webhook")
def webhook_whatsapp():
    whatsapp_id = request.values.get("From", "")
    mensaje = request.values.get("Body", "")
    media_url = request.values.get("MediaUrl0")
    media_type = request.values.get("MediaContentType0")
    latitude = request.values.get("Latitude")
    longitude = request.values.get("Longitude")

    result = procesar_mensaje_whatsapp(
        whatsapp_id=whatsapp_id,
        mensaje=mensaje,
        media_url=media_url,
        media_type=media_type,
        latitude=latitude,
        longitude=longitude,
    )
    if not isinstance(result, dict):
        result = {"tipo": "texto", "contenido": str(result)}

    twiml = MessagingResponse()
    msg = twiml.message()

    tipo = result.get("tipo", "texto")
    if tipo == "audio" and result.get("audio_filename"):
        base_url = app.config["PUBLIC_BASE_URL"] or request.url_root.rstrip("/")
        audio_url = f"{base_url}/audio/{result['audio_filename']}"
        msg.media(audio_url)
        if result.get("contenido"):
            msg.body(result["contenido"])
    else:
        msg.body(result.get("contenido", "Listo parce, mensaje recibido."))

    return str(twiml), 200, {"Content-Type": "application/xml"}


@app.errorhandler(403)
def forbidden(_err):
    return _error("No autorizado para acceder a este recurso", 403)


@app.errorhandler(404)
def not_found(_err):
    return _error("Recurso no encontrado", 404)


@app.errorhandler(500)
def server_error(_err):
    return _error("Error interno del servidor", 500)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
