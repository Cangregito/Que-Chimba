import json
import importlib
import logging
import os
import secrets
from datetime import datetime, timedelta
from functools import wraps
from xml.sax.saxutils import escape as xml_escape

from flask import Flask, abort, redirect, render_template, request, session, url_for, make_response
from jinja2 import BaseLoader, ChoiceLoader, FileSystemLoader

try:
    from config_runtime import (
        DEFAULT_BAILEYS_BRIDGE_URL,
        DEFAULT_PUBLIC_BASE_URL,
        DEFAULT_WHATSAPP_PUBLIC_MESSAGE,
        DEFAULT_WHATSAPP_PUBLIC_NUMBER,
        env_bool,
        env_int,
        env_str,
        is_production,
    )
except Exception:
    from bot_empanadas.config_runtime import (
        DEFAULT_BAILEYS_BRIDGE_URL,
        DEFAULT_PUBLIC_BASE_URL,
        DEFAULT_WHATSAPP_PUBLIC_MESSAGE,
        DEFAULT_WHATSAPP_PUBLIC_NUMBER,
        env_bool,
        env_int,
        env_str,
        is_production,
    )

try:
    from services.api_response import error_response, expects_json, generate_error_id, ok_response, serialize
    from services.request_security import client_ip as _service_client_ip, is_valid_origin as _service_is_valid_origin
    from routes.common_routes import register_common_routes
    from routes.order_routes import register_order_routes
    from routes.report_routes import register_report_routes
    from routes.admin_routes import register_admin_routes
    from routes.marketing_support_routes import register_marketing_support_routes
    from routes.webhook_routes import register_webhook_routes
    from routes.audit_parser_routes import register_audit_parser_routes
    from services.whatsapp_service import (
        normalize_ticket_destination,
        normalize_whatsapp_id,
        send_audio_whatsapp,
        send_text_whatsapp,
    )
except Exception:
    from bot_empanadas.services.api_response import error_response, expects_json, generate_error_id, ok_response, serialize
    from bot_empanadas.services.request_security import client_ip as _service_client_ip, is_valid_origin as _service_is_valid_origin
    from bot_empanadas.routes.common_routes import register_common_routes
    from bot_empanadas.routes.order_routes import register_order_routes
    from bot_empanadas.routes.report_routes import register_report_routes
    from bot_empanadas.routes.admin_routes import register_admin_routes
    from bot_empanadas.routes.marketing_support_routes import register_marketing_support_routes
    from bot_empanadas.routes.webhook_routes import register_webhook_routes
    from bot_empanadas.routes.audit_parser_routes import register_audit_parser_routes
    from bot_empanadas.services.whatsapp_service import (
        normalize_ticket_destination,
        normalize_whatsapp_id,
        send_audio_whatsapp,
        send_text_whatsapp,
    )

class _FallbackMessage:
    def __init__(self):
        self._body = ""
        self._media = []

    def body(self, text):
        self._body = str(text)

    def media(self, url):
        self._media.append(str(url))

    def _to_xml(self):
        media_xml = "".join(f"<Media>{xml_escape(m)}</Media>" for m in self._media)
        body_xml = f"<Body>{xml_escape(self._body)}</Body>" if self._body else ""
        return f"<Message>{body_xml}{media_xml}</Message>"


class MessagingResponse:
    def __init__(self):
        self._messages = []

    def message(self):
        msg = _FallbackMessage()
        self._messages.append(msg)
        return msg

    def __str__(self):
        return "<Response>" + "".join(m._to_xml() for m in self._messages) + "</Response>"

try:
    import db
except Exception:
    from bot_empanadas import db

try:
    _bot_module = importlib.import_module("bot")
except Exception:
    try:
        _bot_module = importlib.import_module("bot_empanadas.bot")
    except Exception:
        _bot_module = None

if _bot_module is not None:
    procesar_mensaje_whatsapp = _bot_module.procesar_mensaje_whatsapp
else:
    def procesar_mensaje_whatsapp(
        whatsapp_id,
        mensaje,
        media_url=None,
        media_type=None,
        latitude=None,
        longitude=None,
    ):
        texto = (
            f"Ay, {whatsapp_id}. Recibi: '{mensaje or 'audio'}'. "
            "Listo parce, tu pedido va en camino en el flujo demo."
        )
        return {"tipo": "texto", "contenido": texto}


app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), "templates"))
_flask_secret = (os.getenv("FLASK_SECRET", "") or "").strip()
if not _flask_secret:
    _flask_secret = secrets.token_hex(32)
app.config["SECRET_KEY"] = _flask_secret
app.config["JSON_SORT_KEYS"] = False
app.config["AUDIO_DIR"] = os.path.join(os.path.dirname(__file__), "audios_temp")
app.config["IMG_DIR"] = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Img"))
app.config["PUBLIC_BASE_URL"] = env_str("PUBLIC_BASE_URL", "").rstrip("/")
app.config["BAILEYS_BRIDGE_URL"] = (env_str("BAILEYS_BRIDGE_URL", DEFAULT_BAILEYS_BRIDGE_URL) or DEFAULT_BAILEYS_BRIDGE_URL).rstrip("/")
app.config["BAILEYS_BRIDGE_API_TOKEN"] = env_str("BAILEYS_BRIDGE_API_TOKEN", "").strip()
app.config["BAILEYS_WEBHOOK_TOKEN"] = env_str("BAILEYS_WEBHOOK_TOKEN", "").strip()
app.config["WHATSAPP_LEGACY_WEBHOOK_TOKEN"] = env_str("WHATSAPP_LEGACY_WEBHOOK_TOKEN", "").strip()
app.config["MP_WEBHOOK_TOKEN"] = env_str("MP_WEBHOOK_TOKEN", "").strip()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = env_str("SESSION_COOKIE_SAMESITE", "Lax").strip() or "Lax"
app.config["SESSION_COOKIE_SECURE"] = env_bool("SESSION_COOKIE_SECURE", is_production())
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=max(15, env_int("SESSION_TTL_MINUTES", 720)))

root_templates_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "templates"))
if os.path.isdir(root_templates_dir):
    jinja_loaders: list[BaseLoader] = [FileSystemLoader(root_templates_dir)]
    if app.jinja_loader is not None:
        jinja_loaders.insert(0, app.jinja_loader)
    app.jinja_loader = ChoiceLoader(jinja_loaders)  # type: ignore[assignment]

os.makedirs(app.config["AUDIO_DIR"], exist_ok=True)

_log_level_name = (os.getenv("LOG_LEVEL", "INFO") or "INFO").upper()
_log_level = getattr(logging, _log_level_name, logging.INFO)
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=_log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
app.logger.setLevel(_log_level)

if not (os.getenv("FLASK_SECRET", "") or "").strip():
    app.logger.warning("FLASK_SECRET no esta configurado. Se usa una clave aleatoria temporal para esta ejecucion.")

if is_production() and not (os.getenv("FLASK_SECRET", "") or "").strip():
    raise RuntimeError(
        "FLASK_SECRET no esta configurado en produccion; se requiere un secreto persistente para sesiones seguras."
    )

if is_production() and not app.config.get("BAILEYS_WEBHOOK_TOKEN"):
    raise RuntimeError(
        "BAILEYS_WEBHOOK_TOKEN no esta configurado en produccion; el webhook del bridge queda sin autenticacion de token."
    )

if is_production() and not app.config.get("WHATSAPP_LEGACY_WEBHOOK_TOKEN"):
    raise RuntimeError(
        "WHATSAPP_LEGACY_WEBHOOK_TOKEN no esta configurado en produccion; el webhook legacy queda sin autenticacion compartida."
    )

if is_production() and not (os.getenv("SENSITIVE_DATA_KEY", "") or "").strip():
    raise RuntimeError(
        "SENSITIVE_DATA_KEY no esta configurada en produccion; se requiere para proteger datos sensibles."
    )


ESTADOS_VALIDOS_PEDIDO = {
    "recibido",
    "en_preparacion",
    "listo",
    "en_camino",
    "entregado",
    "cancelado",
}


def _ok(data, status=200):
    return ok_response(data, status)


def _serialize(value):
    return serialize(value)


def _generar_error_id() -> str:
    return generate_error_id()


def _espera_json() -> bool:
    return expects_json(request)


def _error(message, status=400, code=None, details=None, error_id=None):
    return error_response(message, status=status, code=code, details=details, error_id=error_id)


def _parse_json_field(value, fallback):
    if value is None:
        return fallback
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return fallback
        return json.loads(raw)
    return fallback


def _validar_requeridos(payload, required_fields):
    missing = []
    for field in required_fields:
        value = payload.get(field)
        if value is None:
            missing.append(field)
            continue
        if isinstance(value, str) and not value.strip():
            missing.append(field)
    return missing


def _normalizar_whatsapp_id(raw_value):
    return normalize_whatsapp_id(raw_value)


def _normalizar_destino_ticket_whatsapp(raw_value):
    return normalize_ticket_destination(raw_value)


def _client_ip():
    return _service_client_ip(request)


def _es_origen_valido() -> bool:
    return _service_is_valid_origin(request)


@app.before_request
def _hardening_before_request():
    if session.get("user"):
        session.permanent = True

    method = request.method.upper()
    if method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None

    path = request.path or ""
    if path.startswith("/webhook") or path in {"/login"}:
        return None

    if path.startswith("/api/") and session.get("user"):
        if not _es_origen_valido():
            return _error("Origen no autorizado", 403)

    return None


def _enviar_texto_whatsapp(destino, texto):
    return send_text_whatsapp(app, destino, texto)


def _enviar_audio_whatsapp(destino, audio_path, caption=""):
    return send_audio_whatsapp(app, destino, audio_path, caption=caption, default_public_base_url=DEFAULT_PUBLIC_BASE_URL)


def _verificar_pago_externo(payment_id):
    try:
        try:
            import payments as _payments
        except Exception:
            from bot_empanadas import payments as _payments
        return _payments.verificar_pago_mp(payment_id)
    except Exception as exc:
        return {"error": str(exc)}


def login_required(roles=None):
    roles = roles or []

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            usuario = session.get("user")
            if not usuario:
                if _espera_json():
                    return _error("Sesion requerida", 401, code="auth_required")
                return redirect(url_for("login_page", next=request.path))

            if roles and usuario.get("rol") not in roles:
                if _espera_json():
                    return _error("No autorizado para esta accion", 403, code="forbidden_role")
                abort(403)
            return view_func(*args, **kwargs)

        return wrapper

    return decorator


_common_route_deps = {
    "db": db,
    "login_required": login_required,
    "ok": _ok,
    "error": _error,
    "client_ip": _client_ip,
    "is_valid_origin": _es_origen_valido,
    "env_str": env_str,
    "default_public_number": DEFAULT_WHATSAPP_PUBLIC_NUMBER,
    "default_public_message": DEFAULT_WHATSAPP_PUBLIC_MESSAGE,
}

_order_route_deps = {
    "db": db,
    "ok": _ok,
    "error": _error,
    "login_required": login_required,
    "validar_requeridos": _validar_requeridos,
    "estados_validos_pedido": ESTADOS_VALIDOS_PEDIDO,
    "send_text_whatsapp": _enviar_texto_whatsapp,
    "normalize_whatsapp_id": _normalizar_whatsapp_id,
    "normalize_ticket_destination": _normalizar_destino_ticket_whatsapp,
}

_report_route_deps = {
    "db": db,
    "ok": _ok,
    "error": _error,
    "login_required": login_required,
    "serialize": _serialize,
    "send_text_whatsapp": _enviar_texto_whatsapp,
    "normalize_ticket_destination": _normalizar_destino_ticket_whatsapp,
}

_admin_route_deps = {
    "db": db,
    "ok": _ok,
    "error": _error,
    "login_required": login_required,
    "client_ip": _client_ip,
}

_marketing_support_route_deps = {
    "db": db,
    "ok": _ok,
    "error": _error,
    "login_required": login_required,
    "normalize_whatsapp_id": _normalizar_whatsapp_id,
    "normalize_ticket_destination": _normalizar_destino_ticket_whatsapp,
    "send_text_whatsapp": _enviar_texto_whatsapp,
}

_webhook_route_deps = {
    "ok": _ok,
    "error": _error,
    "normalize_whatsapp_id": _normalizar_whatsapp_id,
    "procesar_mensaje_whatsapp": procesar_mensaje_whatsapp,
    "messaging_response_cls": MessagingResponse,
    "send_audio_whatsapp": _enviar_audio_whatsapp,
    "verify_payment_status": _verificar_pago_externo,
}

_audit_parser_route_deps = {
    "db": db,
    "ok": _ok,
    "error": _error,
    "login_required": login_required,
    "parse_json_field": _parse_json_field,
    "bot_module": _bot_module,
}

register_common_routes(app, _common_route_deps)
register_order_routes(app, _order_route_deps)
register_report_routes(app, _report_route_deps)
register_admin_routes(app, _admin_route_deps)
register_marketing_support_routes(app, _marketing_support_route_deps)
register_webhook_routes(app, _webhook_route_deps)
register_audit_parser_routes(app, _audit_parser_route_deps)


@app.route("/interno/log", methods=["POST"])
def interno_log_evento():
    remote = (request.remote_addr or "").strip()
    if remote not in {"127.0.0.1", "::1", "localhost"}:
        return _error("Origen no permitido", 403)

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return _error("Payload invalido", 400)

    created = db.insertar_log_sistema(
        nivel=payload.get("nivel") or "INFO",
        componente=payload.get("componente") or "externo",
        funcion=payload.get("funcion") or "interno_log_evento",
        mensaje=payload.get("mensaje") or "(sin mensaje)",
        detalle=payload.get("detalle"),
        whatsapp_id=payload.get("whatsapp_id"),
        pedido_id=payload.get("pedido_id"),
        ip_origen=payload.get("ip_origen") or remote,
        duracion_ms=payload.get("duracion_ms"),
    )
    if isinstance(created, dict) and created.get("error"):
        return _error(created["error"], 500)

    return _ok({"ok": True}, 201)

def _render_error_page(status_code, title, message, error_id):
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    response = make_response(
        render_template(
            "error.html",
            status_code=status_code,
            title=title,
            message=message,
            error_id=error_id,
            timestamp=now_text,
        ),
        status_code,
    )
    response.headers["X-Error-ID"] = error_id
    return response


@app.errorhandler(400)
def handle_400(err):
    if _espera_json():
        return _error("Solicitud invalida", 400, code="bad_request")
    error_id = _generar_error_id()
    return _render_error_page(400, "Solicitud invalida", "La solicitud no pudo ser procesada. Verifica los datos enviados.", error_id)


@app.errorhandler(401)
def handle_401(err):
    if _espera_json():
        return _error("Sesion requerida", 401, code="auth_required")
    return redirect(url_for("login_page", next=request.path))


@app.errorhandler(403)
def handle_403(err):
    if _espera_json():
        return _error("No autorizado para esta accion", 403, code="forbidden")
    error_id = _generar_error_id()
    return _render_error_page(403, "Acceso denegado", "No tienes permisos para acceder a esta seccion.", error_id)


@app.errorhandler(404)
def handle_404(err):
    if _espera_json():
        return _error("Recurso no encontrado", 404, code="not_found")
    error_id = _generar_error_id()
    return _render_error_page(404, "Pagina no encontrada", "La pagina solicitada no existe o fue movida.", error_id)


@app.errorhandler(500)
def handle_500(err):
    error_id = _generar_error_id()
    app.logger.exception("Error interno no controlado [%s]: %s", error_id, err)
    if _espera_json():
        return _error("Error interno del servidor", 500, code="internal_error", error_id=error_id)
    return _render_error_page(500, "Error interno", "Ocurrio un problema inesperado. Intenta nuevamente en unos minutos.", error_id)


if __name__ == "__main__":
    port = env_int("PORT", 5000)
    debug_enabled = env_bool("FLASK_DEBUG", False)
    app.run(host="0.0.0.0", port=port, debug=debug_enabled)
