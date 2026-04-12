import json
import secrets
from datetime import date, datetime
from decimal import Decimal

from flask import jsonify


def json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def serialize(value):
    return json.loads(json.dumps(value, default=json_default))


def ok_response(data, status=200):
    return jsonify({"ok": True, "data": serialize(data)}), status


def generate_error_id() -> str:
    return f"ERR-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3).upper()}"


def expects_json(request):
    path = request.path or ""
    if path.startswith("/api/"):
        return True
    accept = (request.headers.get("Accept") or "").lower()
    return "application/json" in accept


def error_response(message, status=400, code=None, details=None, error_id=None):
    resolved_error_id = error_id or generate_error_id()
    payload = {
        "ok": False,
        "error": str(message),
        "error_id": resolved_error_id,
    }
    if code:
        payload["code"] = str(code)
    if details is not None:
        payload["details"] = serialize(details)

    response = jsonify(payload)
    response.status_code = status
    response.headers["X-Error-ID"] = resolved_error_id
    return response
