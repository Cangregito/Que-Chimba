"""
payments.py – Integración con MercadoPago México (Sandbox / Producción).

Comisión MercadoPago México (costo operativo para presentación):
  • 3.49 % del total de la transacción
  • + $4.00 MXN fija por transacción
  Ejemplo: pedido $200 MXN → comisión $10.98 → neto negocio $189.02

Variables de entorno requeridas:
  MP_ACCESS_TOKEN       Token de acceso (sandbox o producción)
  MP_SANDBOX            'true' para sandbox/demo  (default: 'true')
  PUBLIC_BASE_URL       URL pública ngrok, p.ej. https://abc123.ngrok.io

Variables de entorno opcionales (notificaciones WhatsApp post-pago):
    BAILEYS_BRIDGE_URL  p.ej. http://localhost:3001
"""

import logging
import os
import re

import requests as http

import db

try:
    from config_runtime import DEFAULT_BAILEYS_BRIDGE_URL, env_bool, env_str
except Exception:
    from bot_empanadas.config_runtime import DEFAULT_BAILEYS_BRIDGE_URL, env_bool, env_str

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────
_MP_API_BASE = "https://api.mercadopago.com"

COMISION_PCT  = 3.49 / 100   # 3.49 %
COMISION_FIJA = 4.00          # $4.00 MXN fija por transacción


# ─────────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────────

def _mp_token() -> str:
    token = env_str("MP_ACCESS_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "MP_ACCESS_TOKEN no configurado. "
            "Agrégalo como variable de entorno antes de iniciar el servidor."
        )
    return token


def _base_url() -> str:
    return env_str("PUBLIC_BASE_URL", "https://tu-ngrok-url.ngrok.io").rstrip("/")


def _use_sandbox() -> bool:
    return env_bool("MP_SANDBOX", True)


# ─────────────────────────────────────────────────────────────────
# API pública
# ─────────────────────────────────────────────────────────────────

def calcular_comision(total: float) -> dict:
    """
    Retorna el desglose de comisiones MercadoPago México.
    Útil para mostrar en el dashboard o en la presentación al jurado.
    """
    porcentaje_mxn = round(float(total) * COMISION_PCT, 2)
    comision_total = round(porcentaje_mxn + COMISION_FIJA, 2)
    return {
        "total":           round(float(total), 2),
        "comision_mp":     comision_total,
        "neto_negocio":    round(float(total) - comision_total, 2),
        "detalle":         f"3.49 % (${porcentaje_mxn} MXN) + $4.00 MXN fija",
    }


def crear_link_pago(pedido_id: int, total: float, descripcion: str) -> dict:
    """
    Crea una Preference en MercadoPago y registra el pago como 'pendiente' en DB.

    Parámetros:
        pedido_id   – ID del pedido en tabla pedidos
        total       – Monto en MXN (float / Decimal)
        descripcion – Texto visible al cliente en el checkout

    Retorna:
        {"url": "https://...", "preference_id": "..."}   → éxito
        {"error": "mensaje"}                              → fallo
    """
    base = _base_url()

    payload = {
        "items": [
            {
                "id":          str(pedido_id),
                "title":       descripcion or f"Pedido #{pedido_id} – Que Chimba Empanadas",
                "quantity":    1,
                "currency_id": "MXN",
                "unit_price":  round(float(total), 2),
            }
        ],
        "external_reference": str(pedido_id),
        "back_urls": {
            "success": f"{base}/pago/exitoso",
            "failure": f"{base}/pago/fallido",
            "pending": f"{base}/pago/pendiente",
        },
        "auto_return":          "approved",
        "notification_url":     f"{base}/webhook/pago",
        "statement_descriptor": "QUE CHIMBA EMPANADAS",
        "payment_methods": {
            "installments": 1,          # sin meses sin intereses (sandbox demo)
        },
    }

    try:
        token = _mp_token()
    except RuntimeError as exc:
        return {"error": str(exc)}

    try:
        resp = http.post(
            f"{_MP_API_BASE}/checkout/preferences",
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

    except http.HTTPError as exc:
        msg = (
            f"MercadoPago HTTP {exc.response.status_code}: "
            f"{exc.response.text[:400]}"
        )
        logger.error("crear_link_pago: %s", msg)
        return {"error": msg}

    except Exception as exc:
        logger.exception("crear_link_pago: error inesperado")
        return {"error": str(exc)}

    preference_id = data.get("id", "")

    # Sandbox → sandbox_init_point  |  Producción → init_point
    url = data.get("sandbox_init_point") if _use_sandbox() else data.get("init_point")

    # Registrar pago pendiente en la base de datos
    db.registrar_pago(
        pedido_id=pedido_id,
        monto=total,
        proveedor="mercadopago",
        mp_preference_id=preference_id,
    )

    logger.info(
        "Preferencia MP creada: pedido=%s preference=%s sandbox=%s",
        pedido_id, preference_id, _use_sandbox(),
    )
    return {"url": url, "preference_id": preference_id}


def verificar_pago_mp(payment_id: str) -> dict:
    """
    Consulta la API de MercadoPago para obtener el estado real de un pago.
    Se llama desde el webhook cuando MP notifica una actualización.

    Parámetros:
        payment_id – ID numérico del pago (string recibido del webhook)

    Retorna dict con claves:
        payment_id, status, status_detail, external_reference, transaction_amount
    o  {"error": "..."}
    """
    # Validar que el ID sea numérico para prevenir inyección / SSRF
    if not re.fullmatch(r"\d{1,20}", str(payment_id)):
        return {"error": f"payment_id inválido: {payment_id!r}"}

    try:
        token = _mp_token()
    except RuntimeError as exc:
        return {"error": str(exc)}

    try:
        resp = http.get(
            f"{_MP_API_BASE}/v1/payments/{payment_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

    except http.HTTPError as exc:
        msg = (
            f"MercadoPago HTTP {exc.response.status_code}: "
            f"{exc.response.text[:400]}"
        )
        logger.error("verificar_pago_mp(%s): %s", payment_id, msg)
        return {"error": msg}

    except Exception as exc:
        logger.exception("verificar_pago_mp(%s): error inesperado", payment_id)
        return {"error": str(exc)}

    return {
        "payment_id":          str(payment_id),
        "status":              data.get("status"),          # approved / rejected / pending / cancelled
        "status_detail":       data.get("status_detail"),
        "external_reference":  data.get("external_reference"),  # nuestro pedido_id
        "transaction_amount":  data.get("transaction_amount"),
    }


def enviar_whatsapp_pago(whatsapp_id: str, pedido_id: int, estado_mp: str) -> None:
    """
    Envia al cliente una notificacion de WhatsApp con el resultado del pago.
    Usa el puente Baileys por HTTP.

    estado_mp: 'approved' | 'rejected' | 'pending' | 'cancelled'
    """
    mensajes = {
        "approved": (
            f"Ay que chimba, parce. Tu pago del pedido #{pedido_id} fue aprobado. "
            "Ya estamos preparando tus empanadas con todo el amor colombiano. Buena nota."
        ),
        "rejected": (
            f"Uy parce, el pago del pedido #{pedido_id} no paso. "
            "Intenta con otra tarjeta o escribenos para ayudarte. Dale que si."
        ),
        "cancelled": (
            f"Parce, el pago del pedido #{pedido_id} fue cancelado. "
            "Si fue un error, vuelve a intentar. Aqui estamos, mi rey."
        ),
        "pending": (
            f"Listo parce, el pago del pedido #{pedido_id} esta en proceso. "
            "Te avisamos en cuanto se confirme. Tranquilo mi rey, vas a comer rico."
        ),
    }

    body = mensajes.get(
        estado_mp,
        f"Novedad en tu pedido #{pedido_id}: estado de pago actualizado a '{estado_mp}'.",
    )

    bridge_url = env_str("BAILEYS_BRIDGE_URL", DEFAULT_BAILEYS_BRIDGE_URL).strip().rstrip("/")
    if not bridge_url:
        logger.warning("BAILEYS_BRIDGE_URL no configurado. Se omite notificacion de pago para pedido %s.", pedido_id)
        return

    to = (whatsapp_id or "").replace("whatsapp:", "").strip()
    if not to:
        logger.warning("whatsapp_id vacio para pedido %s. No se envia notificacion de pago.", pedido_id)
        return

    try:
        http.post(
            f"{bridge_url}/api/send-text",
            json={"to": to, "text": body},
            timeout=10,
        ).raise_for_status()
        logger.info("Notificación WA enviada a %s (pedido %s, estado %s)", to, pedido_id, estado_mp)
    except Exception as exc:
        logger.error("enviar_whatsapp_pago(%s): %s", whatsapp_id, exc)
