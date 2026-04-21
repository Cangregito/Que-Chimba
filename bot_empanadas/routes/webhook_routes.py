from flask import request
import re


def register_webhook_routes(app, deps: dict):
    ok = deps["ok"]
    error = deps["error"]
    normalize_whatsapp_id = deps["normalize_whatsapp_id"]
    procesar_mensaje_whatsapp = deps["procesar_mensaje_whatsapp"]
    messaging_response_cls = deps["messaging_response_cls"]
    send_audio_whatsapp = deps["send_audio_whatsapp"]
    verify_payment_status = deps.get("verify_payment_status")

    def _mask_identifier(value):
        raw = str(value or "").strip()
        if not raw:
            return ""
        digits = "".join(ch for ch in raw if ch.isdigit())
        if len(digits) >= 4:
            return f"***{digits[-4:]}"
        if len(raw) >= 4:
            return f"***{raw[-4:]}"
        return "***"

    def webhook_whatsapp():
        expected_token = app.config.get("WHATSAPP_LEGACY_WEBHOOK_TOKEN", "")
        if expected_token:
            incoming_token = (
                request.headers.get("x-webhook-token")
                or request.args.get("token")
                or ""
            ).strip()
            if incoming_token != expected_token:
                return error("Token de webhook legacy invalido", 401)

        whatsapp_id = normalize_whatsapp_id(request.values.get("From", ""))
        result = procesar_mensaje_whatsapp(
            whatsapp_id=whatsapp_id,
            mensaje=request.values.get("Body", ""),
            media_url=request.values.get("MediaUrl0"),
            media_type=request.values.get("MediaContentType0"),
            latitude=request.values.get("Latitude"),
            longitude=request.values.get("Longitude"),
        )
        if not isinstance(result, dict):
            result = {"tipo": "texto", "contenido": str(result)}

        twiml = messaging_response_cls()
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

        return str(twiml), 200, {"Content-Type": "text/xml; charset=utf-8"}

    app.add_url_rule("/webhook", endpoint="webhook_whatsapp", view_func=webhook_whatsapp, methods=["POST"])

    def webhook_baileys():
        expected_token = app.config.get("BAILEYS_WEBHOOK_TOKEN", "")
        if expected_token:
            incoming_token = (request.headers.get("x-bridge-token") or "").strip()
            if incoming_token != expected_token:
                return error("Token de bridge invalido", 401)

        payload = request.get_json(silent=True) or {}

        whatsapp_id = normalize_whatsapp_id(payload.get("whatsapp_id") or payload.get("from") or payload.get("jid"))
        whatsapp_jid = (payload.get("whatsapp_jid") or payload.get("jid") or "").strip()
        mensaje = payload.get("mensaje") or payload.get("text") or ""
        media_url = payload.get("media_url") or payload.get("mediaUrl")
        media_type = payload.get("media_type") or payload.get("mediaType")
        media_kind = payload.get("media_kind") or payload.get("mediaKind")
        latitude = payload.get("latitude")
        longitude = payload.get("longitude")

        app.logger.info(
            "Webhook Baileys recibido: whatsapp_id=%s has_text=%s media_type=%s has_media_url=%s",
            _mask_identifier(whatsapp_id),
            bool(str(mensaje or "").strip()),
            media_type or "",
            bool(media_url),
        )

        if not whatsapp_id:
            return error("whatsapp_id es obligatorio", 400)

        output = procesar_mensaje_whatsapp(
            whatsapp_id=whatsapp_id,
            mensaje=mensaje,
            media_url=media_url,
            media_type=media_type,
            media_kind=media_kind,
            latitude=latitude,
            longitude=longitude,
        )
        if not isinstance(output, dict):
            output = {"tipo": "texto", "contenido": str(output)}

        if output.get("tipo") == "audio" and output.get("audio_filename") and not output.get("audio_url"):
            base_url = app.config["PUBLIC_BASE_URL"] or request.url_root.rstrip("/")
            output["audio_url"] = f"{base_url}/audio/{output['audio_filename']}"

        audio_colombiano = output.get("audio_colombiano_path")
        should_send_transition_audio = bool(audio_colombiano) and bool(whatsapp_id) and output.get("tipo") != "audio"
        if should_send_transition_audio:
            import threading

            destino_audio = whatsapp_jid or whatsapp_id

            def _enviar_colombiano_bg():
                try:
                    send_audio_whatsapp(destino_audio, audio_colombiano)
                except Exception as _exc:
                    app.logger.debug("audio_colombiano bg error: %s", _exc)

            threading.Thread(target=_enviar_colombiano_bg, daemon=True).start()

        app.logger.info(
            "Webhook Baileys respuesta: whatsapp_id=%s tipo=%s has_audio_url=%s has_audio_colombiano=%s",
            _mask_identifier(whatsapp_id),
            output.get("tipo", "texto"),
            bool(output.get("audio_url")),
            bool(audio_colombiano),
        )

        return ok(output)

    app.add_url_rule("/webhook/baileys", endpoint="webhook_baileys", view_func=webhook_baileys, methods=["POST"])

    def webhook_pago():
        expected_token = app.config.get("MP_WEBHOOK_TOKEN", "")
        if expected_token:
            incoming_token = (
                request.headers.get("x-webhook-token")
                or request.headers.get("x-mp-webhook-token")
                or request.args.get("token")
                or ""
            ).strip()
            if incoming_token != expected_token:
                return error("Token de webhook de pagos invalido", 401)

        payload = request.get_json(silent=True) or {}

        data_obj = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        payment_id = (
            request.args.get("data.id")
            or request.args.get("id")
            or request.args.get("payment_id")
            or payload.get("id")
            or payload.get("payment_id")
            or data_obj.get("id")
        )
        payment_id = str(payment_id or "").strip()

        if not payment_id or not re.fullmatch(r"\d{1,20}", payment_id):
            return ok({
                "ack": True,
                "processed": False,
                "reason": "payment_id_missing_or_invalid",
            })

        verification = verify_payment_status(payment_id) if callable(verify_payment_status) else {"error": "payment_verifier_not_configured"}
        if isinstance(verification, dict) and verification.get("error"):
            app.logger.warning("Webhook pago no procesado: payment_id=%s error=%s", payment_id, verification.get("error"))
            return ok({
                "ack": True,
                "processed": False,
                "payment_id": payment_id,
                "reason": "verification_failed",
            })

        return ok({
            "ack": True,
            "processed": True,
            "payment_id": payment_id,
            "status": verification.get("status") if isinstance(verification, dict) else None,
            "external_reference": verification.get("external_reference") if isinstance(verification, dict) else None,
        })

    app.add_url_rule("/webhook/pago", endpoint="webhook_pago", view_func=webhook_pago, methods=["POST"])
