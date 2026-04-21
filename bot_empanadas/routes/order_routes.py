from typing import Any
from pathlib import Path

from flask import request, session


def register_order_routes(app, deps: dict):
    db = deps["db"]
    ok = deps["ok"]
    error = deps["error"]
    login_required = deps["login_required"]
    validar_requeridos = deps["validar_requeridos"]
    estados_validos_pedido = deps["estados_validos_pedido"]
    send_text_whatsapp = deps["send_text_whatsapp"]
    normalize_whatsapp_id = deps["normalize_whatsapp_id"]
    normalize_ticket_destination = deps["normalize_ticket_destination"]

    def _auto_enviar_factura_entregada(pedido_id: int, actor_username: str | None) -> dict[str, Any]:
        resultado = {
            "intentado": False,
            "enviado": False,
            "motivo": "No aplica envio automatico de factura.",
        }

        if not hasattr(db, "obtener_preview_factura"):
            resultado["motivo"] = "Modulo de facturacion no disponible en DB."
            return resultado

        preview = db.obtener_preview_factura(pedido_id)
        if isinstance(preview, dict) and preview.get("error"):
            if hasattr(db, "reparar_factura_pedido"):
                reparacion = db.reparar_factura_pedido(pedido_id=pedido_id, actor_usuario=actor_username or "sistema")
                if not (isinstance(reparacion, dict) and reparacion.get("error")):
                    preview = db.obtener_preview_factura(pedido_id)
        if isinstance(preview, dict) and preview.get("error"):
            resultado["motivo"] = preview.get("error") or "Factura no encontrada."
            return resultado
        if not isinstance(preview, dict):
            resultado["motivo"] = "Respuesta de facturacion invalida."
            return resultado

        resultado["intentado"] = True
        estado_envio = str(preview.get("ultimo_envio_estado") or "").strip().lower()
        if estado_envio == "enviado":
            resultado["motivo"] = "La factura ya estaba enviada previamente."
            resultado["enviado"] = True
            return resultado

        docs = preview.get("documentos") or {}
        pdf_info = docs.get("pdf") or {}
        xml_info = docs.get("xml") or {}
        if not pdf_info.get("ready") or not xml_info.get("ready"):
            resultado["motivo"] = "Factura sin PDF/XML listos para envio."
            if hasattr(db, "registrar_resultado_envio_factura"):
                db.registrar_resultado_envio_factura(
                    pedido_id,
                    "error",
                    destino=preview.get("whatsapp_id"),
                    error_detalle=resultado["motivo"],
                    marcar_entregada=False,
                )
            return resultado

        destino = normalize_ticket_destination(preview.get("whatsapp_id"))
        if not destino:
            resultado["motivo"] = "Factura sin destino WhatsApp valido."
            if hasattr(db, "registrar_resultado_envio_factura"):
                db.registrar_resultado_envio_factura(
                    pedido_id,
                    "error",
                    destino=None,
                    error_detalle=resultado["motivo"],
                    marcar_entregada=False,
                )
            return resultado

        try:
            from services.whatsapp_service import send_document_whatsapp
        except ImportError:
            from bot_empanadas.services.whatsapp_service import send_document_whatsapp

        pdf_path = str(pdf_info.get("path") or "").strip()
        xml_path = str(xml_info.get("path") or "").strip()
        if not pdf_path or not xml_path:
            resultado["motivo"] = "Rutas de documentos faltantes para envio."
            return resultado

        caption_pdf = f"Factura {preview.get('folio_factura')} · Pedido #{pedido_id}"
        caption_xml = f"XML CFDI {preview.get('folio_factura')} · Pedido #{pedido_id}"
        pdf_result = send_document_whatsapp(app, destino, pdf_path, caption=caption_pdf)
        if isinstance(pdf_result, dict) and pdf_result.get("error"):
            motivo = pdf_result.get("error") or "Error enviando PDF."
            resultado["motivo"] = motivo
            if hasattr(db, "registrar_resultado_envio_factura"):
                db.registrar_resultado_envio_factura(
                    pedido_id,
                    "error",
                    destino=destino,
                    error_detalle=motivo,
                    marcar_entregada=False,
                )
            return resultado

        xml_result = send_document_whatsapp(app, destino, xml_path, caption=caption_xml)
        if isinstance(xml_result, dict) and xml_result.get("error"):
            motivo = xml_result.get("error") or "Error enviando XML."
            resultado["motivo"] = motivo
            if hasattr(db, "registrar_resultado_envio_factura"):
                db.registrar_resultado_envio_factura(
                    pedido_id,
                    "error",
                    destino=destino,
                    error_detalle=motivo,
                    marcar_entregada=False,
                )
            return resultado

        warning_texto = None
        if callable(send_text_whatsapp):
            confirmacion = (
                f"✅ Tu factura #{preview.get('folio_factura')} fue enviada automaticamente al marcar tu pedido como entregado.\n"
                f"Pedido: #{pedido_id}\n"
                "Incluye PDF y XML."
            )
            text_result = send_text_whatsapp(destino=destino, texto=confirmacion)
            if isinstance(text_result, dict) and text_result.get("error"):
                warning_texto = text_result.get("error")

        if hasattr(db, "registrar_resultado_envio_factura"):
            db.registrar_resultado_envio_factura(
                pedido_id,
                "enviado",
                destino=destino,
                error_detalle=warning_texto,
                marcar_entregada=True,
            )
        if hasattr(db, "registrar_auditoria_factura"):
            try:
                db.registrar_auditoria_factura(
                    pedido_id=pedido_id,
                    evento_tipo="notificacion_whatsapp_enviada",
                    detalles={
                        "origen": "auto_estado_entregado",
                        "destino": destino,
                        "documentos": [Path(pdf_path).name, Path(xml_path).name],
                        "warning": warning_texto,
                    },
                    actor_username=actor_username,
                    actor_rol="admin",
                )
            except Exception:
                pass
        if hasattr(db, "crear_log_notificacion"):
            db.crear_log_notificacion(
                {
                    "pedido_id": pedido_id,
                    "canal": "whatsapp",
                    "destino": destino,
                    "tipo": "factura_entregada_auto",
                    "mensaje": f"Factura {preview.get('folio_factura')} enviada automaticamente (PDF y XML).",
                    "total": preview.get("total"),
                    "direccion": None,
                }
            )

        return {
            "intentado": True,
            "enviado": True,
            "motivo": warning_texto or None,
            "destino": destino,
            "folio_factura": preview.get("folio_factura"),
        }

    def _notificar_cliente_pedido(pedido_id: int, mensaje: str, tipo_log: str) -> dict[str, Any]:
        resultado = {
            "enviado": False,
            "motivo": "No se intento enviar notificacion.",
        }

        if not callable(send_text_whatsapp):
            resultado["motivo"] = "Servicio de WhatsApp no disponible."
            return resultado

        destino_data = db.obtener_destino_whatsapp_por_pedido(pedido_id=pedido_id)
        if isinstance(destino_data, dict) and destino_data.get("error"):
            resultado["motivo"] = destino_data.get("error") or "No se encontro WhatsApp del cliente."
            return resultado

        destino = normalize_ticket_destination((destino_data or {}).get("whatsapp_id"))
        if not destino:
            resultado["motivo"] = "Cliente sin whatsapp_id valido."
            resultado["destino"] = None
            return resultado

        enviado = send_text_whatsapp(destino=destino, texto=mensaje)
        if isinstance(enviado, dict) and enviado.get("error"):
            resultado["motivo"] = enviado["error"]
            resultado["destino"] = destino
            return resultado

        if hasattr(db, "crear_log_notificacion"):
            db.crear_log_notificacion(
                {
                    "pedido_id": pedido_id,
                    "canal": "whatsapp",
                    "destino": destino,
                    "tipo": tipo_log,
                    "mensaje": mensaje,
                    "total": None,
                    "direccion": None,
                }
            )

        return {
            "enviado": True,
            "motivo": None,
            "destino": destino,
        }

    @login_required(roles=["admin", "cocina", "repartidor"])
    def api_pedidos():
        estado_raw = request.args.get("estado")
        estado = None
        if estado_raw:
            estados = [part.strip() for part in estado_raw.split(",") if part.strip()]
            estado = estados if len(estados) > 1 else estados[0]
        fecha = request.args.get("fecha")
        fecha_desde = (request.args.get("fecha_desde") or "").strip() or None
        fecha_hasta = (request.args.get("fecha_hasta") or "").strip() or None
        busqueda = (request.args.get("q") or request.args.get("buscar") or "").strip() or None

        limit_raw = request.args.get("limit")
        offset_raw = request.args.get("offset", "0")
        limit_int = None
        offset_int = 0
        if limit_raw not in (None, ""):
            try:
                limit_int = max(1, min(500, int(limit_raw)))
            except ValueError:
                return error("Parametro limit invalido", 400)
        try:
            offset_int = max(0, int(offset_raw))
        except ValueError:
            return error("Parametro offset invalido", 400)

        data = db.obtener_pedidos(
            estado=estado,
            fecha=fecha,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            busqueda=busqueda,
            limit=limit_int,
            offset=offset_int,
        )
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)
        return ok(data)

    app.add_url_rule("/api/pedidos", endpoint="api_pedidos", view_func=api_pedidos, methods=["GET"])

    def api_crear_pedido():
        payload = request.get_json(silent=True) or {}
        actor = session.get("user", {})

        cliente_id = payload.get("cliente_id")
        whatsapp_id = payload.get("whatsapp_id")
        direccion_id = payload.get("direccion_id")
        metodo_pago = payload.get("metodo_pago", "efectivo")
        items = payload.get("items", [])

        if not cliente_id:
            if not whatsapp_id:
                return error(
                    "Debes enviar cliente_id o whatsapp_id",
                    400,
                    code="validation_error",
                    details={"fields": ["cliente_id", "whatsapp_id"]},
                )
            cliente = db.obtener_o_crear_cliente(whatsapp_id)
            if isinstance(cliente, dict) and cliente.get("error"):
                return error(cliente["error"], 500)
            cliente_id = cliente["cliente_id"]

        if not isinstance(items, list) or not items:
            return error(
                "Debes enviar al menos un item en el pedido",
                400,
                code="validation_error",
                details={"fields": ["items"]},
            )

        created = db.crear_pedido(
            cliente_id,
            items,
            direccion_id,
            metodo_pago,
            actor_usuario=actor.get("username") or whatsapp_id or "bot_whatsapp",
            actor_rol=actor.get("rol") or "cliente",
        )
        if isinstance(created, dict) and created.get("error"):
            return error(created["error"], 500)

        response_data: dict[str, Any] = dict(created or {})
        pedido_id_creado = int(response_data.get("pedido_id") or 0)
        codigo = (response_data.get("codigo_entrega") or "").strip()
        mensaje_confirmacion = (
            f"Confirmamos que ya recibimos tu pedido #{pedido_id_creado} y lo estamos preparando."
        )
        if codigo:
            mensaje_confirmacion = (
                f"{mensaje_confirmacion} Tu codigo de entrega es: {codigo}."
            )
        response_data["notificacion_cliente"] = _notificar_cliente_pedido(
            pedido_id_creado,
            mensaje_confirmacion,
            "confirmacion_recepcion",
        ) if pedido_id_creado > 0 else {
            "enviado": False,
            "motivo": "Pedido sin identificador valido para notificar.",
        }

        return ok(response_data, 201)

    app.add_url_rule("/api/pedidos", endpoint="api_crear_pedido", view_func=api_crear_pedido, methods=["POST"])

    def api_crear_log_notificacion():
        payload = request.get_json(silent=True) or {}

        required = ["pedido_id", "canal", "destino", "tipo", "mensaje"]
        faltantes = validar_requeridos(payload, required)
        if faltantes:
            return error(
                f"Campos obligatorios faltantes: {', '.join(faltantes)}",
                400,
                code="validation_error",
                details={"fields": faltantes},
            )

        created = db.crear_log_notificacion(payload)
        if isinstance(created, dict) and created.get("error"):
            return error(created["error"], 500)

        return ok(created, 201)

    app.add_url_rule("/api/logs", endpoint="api_crear_log_notificacion", view_func=api_crear_log_notificacion, methods=["POST"])

    @login_required(roles=["admin", "cocina", "repartidor"])
    def api_actualizar_estado_pedido(pedido_id):
        payload = request.get_json(silent=True) or {}
        nuevo_estado = payload.get("estado")
        motivo = payload.get("motivo")

        if nuevo_estado not in estados_validos_pedido:
            return error(
                "Estado no valido",
                400,
                code="validation_error",
                details={"fields": ["estado"], "allowed": sorted(list(estados_validos_pedido))},
            )

        actor = session.get("user", {})
        updated = db.actualizar_estado_pedido(
            pedido_id,
            nuevo_estado,
            actor_usuario=actor.get("username", "sistema"),
            rol_actor=actor.get("rol", "sistema"),
            motivo=motivo,
        )
        if isinstance(updated, dict) and updated.get("error"):
            msg = updated["error"].lower()
            if "no encontrado" in msg:
                status = 404
            elif "transicion no permitida" in msg or "estado no valido" in msg:
                status = 400
            else:
                status = 500
            return error(updated["error"], status)

        response_data: dict[str, Any] = dict(updated or {})
        response_data["notificacion_cliente"] = {
            "enviado": False,
            "motivo": "No se intento enviar notificacion.",
        }
        response_data["factura_envio"] = {
            "intentado": False,
            "enviado": False,
            "motivo": "No aplica envio automatico.",
        }

        estado_confirmado = (response_data.get("estado") or "").strip().lower()
        if estado_confirmado in {"recibido", "en_preparacion"}:
            mensaje = (
                f"Confirmamos que ya recibimos tu pedido #{pedido_id} y lo estamos preparando. "
                "Te avisaremos cuando vaya en camino."
            )
            response_data["notificacion_cliente"] = _notificar_cliente_pedido(
                pedido_id,
                mensaje,
                "confirmacion_recepcion",
            )
        elif estado_confirmado == "entregado":
            response_data["factura_envio"] = _auto_enviar_factura_entregada(
                pedido_id=pedido_id,
                actor_username=actor.get("username"),
            )

        return ok(response_data)

    app.add_url_rule(
        "/api/pedidos/<int:pedido_id>/estado",
        endpoint="api_actualizar_estado_pedido",
        view_func=api_actualizar_estado_pedido,
        methods=["PATCH"],
    )

    @login_required(roles=["admin", "repartidor"])
    def api_repartidor_pedidos():
        user = session.get("user", {})
        repartidor_usuario = None if user.get("rol") == "admin" else user.get("username")
        area_entrega = None if user.get("rol") == "admin" else user.get("area_entrega")

        data = db.obtener_pedidos_repartidor(
            repartidor_usuario=repartidor_usuario,
            area_entrega=area_entrega,
        )
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)

        pedidos = []
        rows = data if isinstance(data, list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            productos = []
            for item in row.get("items") or []:
                if not isinstance(item, dict):
                    continue
                nombre = item.get("producto") or item.get("nombre") or "Producto"
                variante = item.get("variante") or ""
                cantidad = item.get("cantidad") or 1
                label = f"{cantidad} x {nombre} {variante}".strip()
                productos.append(label)

            pedidos.append(
                {
                    "pedido_id": row.get("pedido_id"),
                    "estado": row.get("estado"),
                    "metodo_pago": row.get("metodo_pago") or "efectivo",
                    "cliente_nombre": " ".join(
                        [part for part in [row.get("nombre"), row.get("apellidos")] if part]
                    ).strip()
                    or "Cliente",
                    "direccion_entrega": row.get("direccion_entrega") or "Sin direccion",
                    "codigo_postal": row.get("codigo_postal") or "00000",
                    "area_entrega": row.get("area_entrega") or row.get("codigo_postal") or "N/A",
                    "productos": productos,
                }
            )

        return ok(pedidos)

    app.add_url_rule("/api/repartidor/pedidos", endpoint="api_repartidor_pedidos", view_func=api_repartidor_pedidos, methods=["GET"])

    @login_required(roles=["admin", "repartidor"])
    def api_confirmar_entrega_pedido(pedido_id):
        payload = request.get_json(silent=True) or {}
        codigo_entrega = payload.get("codigo_entrega")
        numero_confirmacion_pago = payload.get("numero_confirmacion_pago")
        actor = session.get("user", {})

        updated = db.confirmar_entrega_pedido(
            pedido_id=pedido_id,
            codigo_entrega=codigo_entrega,
            numero_confirmacion_pago=numero_confirmacion_pago,
            actor_usuario=actor.get("username"),
            rol_actor=actor.get("rol"),
        )
        if isinstance(updated, dict) and updated.get("error"):
            msg = updated["error"].lower()
            status = 404 if "no encontrado" in msg else 400
            return error(updated["error"], status)

        response_data: dict[str, Any] = dict(updated or {})
        response_data["notificacion_cliente"] = {
            "enviado": False,
            "motivo": "No se intento enviar notificacion.",
        }
        response_data["factura_envio"] = {
            "intentado": False,
            "enviado": False,
            "motivo": "No aplica envio automatico.",
        }

        destino_data = db.obtener_destino_whatsapp_por_pedido(pedido_id=pedido_id)
        if isinstance(destino_data, dict) and not destino_data.get("error"):
            destino = normalize_ticket_destination(destino_data.get("whatsapp_id"))
            if not destino:
                response_data["notificacion_cliente"] = {
                    "enviado": False,
                    "motivo": "Cliente sin whatsapp_id valido.",
                    "destino": None,
                }
                return ok(response_data)

            confirmacion_pago = (response_data.get("confirmacion_pago") or "").strip()
            mensaje = (
                f"Gracias por tu compra. Confirmamos que tu pedido #{pedido_id} "
                "ha sido entregado correctamente. Esperamos que lo disfrutes."
            )
            if confirmacion_pago:
                mensaje = (
                    f"{mensaje} Confirmacion de pago: {confirmacion_pago}."
                )
            enviado = send_text_whatsapp(destino=destino, texto=mensaje)

            if isinstance(enviado, dict) and enviado.get("error"):
                app.logger.warning(
                    "Pedido %s liberado, pero no se pudo enviar agradecimiento al cliente (%s): %s",
                    pedido_id,
                    destino,
                    enviado["error"],
                )
                response_data["notificacion_cliente"] = {
                    "enviado": False,
                    "motivo": enviado["error"],
                    "destino": destino,
                }
            else:
                db.crear_log_notificacion(
                    {
                        "pedido_id": pedido_id,
                        "canal": "whatsapp",
                        "destino": destino,
                        "tipo": "agradecimiento_entrega",
                        "mensaje": mensaje,
                        "total": None,
                        "direccion": None,
                    }
                )
                response_data["notificacion_cliente"] = {
                    "enviado": True,
                    "destino": destino,
                }
        else:
            motivo = destino_data.get("error") if isinstance(destino_data, dict) else "Sin detalle."
            app.logger.warning(
                "Pedido %s liberado, pero no se encontro WhatsApp destino para agradecimiento: %s",
                pedido_id,
                motivo,
            )
            response_data["notificacion_cliente"] = {
                "enviado": False,
                "motivo": motivo,
            }

        response_data["factura_envio"] = _auto_enviar_factura_entregada(
            pedido_id=pedido_id,
            actor_username=actor.get("username"),
        )

        return ok(response_data)

    app.add_url_rule(
        "/api/pedidos/<int:pedido_id>/confirmar",
        endpoint="api_confirmar_entrega_pedido",
        view_func=api_confirmar_entrega_pedido,
        methods=["POST"],
    )

    @login_required(roles=["admin"])
    def api_asignar_pedido_repartidor():
        payload = request.get_json(silent=True) or {}
        pedido_id = payload.get("pedido_id")
        repartidor_usuario = payload.get("repartidor_usuario")

        if not pedido_id:
            return error("pedido_id es obligatorio", 400)

        if not repartidor_usuario:
            return error(
                "repartidor_usuario es obligatorio. Usa un usuario de rol repartidor con area_entrega configurada.",
                400,
            )

        created = db.asignar_pedido_repartidor(
            pedido_id=pedido_id,
            repartidor_usuario=repartidor_usuario,
            asignado_por=session.get("user", {}).get("username", "admin"),
        )
        if isinstance(created, dict) and created.get("error"):
            msg = created["error"].lower()
            status = 404 if "no encontrado" in msg else 400
            return error(created["error"], status)
        return ok(created, 201)

    app.add_url_rule("/api/repartidor/asignaciones", endpoint="api_asignar_pedido_repartidor", view_func=api_asignar_pedido_repartidor, methods=["POST"])

    @login_required(roles=["admin", "cocina", "repartidor"])
    def api_bitacora_pedido(pedido_id):
        limit = request.args.get("limit", "50")
        try:
            limit_int = max(1, min(200, int(limit)))
        except ValueError:
            return error("Parametro limit invalido", 400)

        data = db.obtener_bitacora_pedido(pedido_id=pedido_id, limit=limit_int)
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)
        return ok(data)

    app.add_url_rule(
        "/api/pedidos/<int:pedido_id>/bitacora",
        endpoint="api_bitacora_pedido",
        view_func=api_bitacora_pedido,
        methods=["GET"],
    )

    @login_required(roles=["admin", "cocina", "repartidor"])
    def api_obtener_codigo_entrega_pedido(pedido_id):
        data = db.obtener_o_generar_codigo_entrega_pedido(pedido_id=pedido_id)
        if isinstance(data, dict) and data.get("error"):
            msg = data["error"].lower()
            status = 404 if "no encontrado" in msg else 400
            return error(data["error"], status)
        return ok(
            {
                "pedido_id": pedido_id,
                "codigo_entrega": data.get("codigo_entrega"),
                "message": "Codigo de entrega disponible.",
            }
        )

    app.add_url_rule(
        "/api/pedidos/<int:pedido_id>/codigo-entrega",
        endpoint="api_obtener_codigo_entrega_pedido",
        view_func=api_obtener_codigo_entrega_pedido,
        methods=["GET"],
    )

    @login_required(roles=["admin", "repartidor"])
    def api_reenviar_codigo_pedido(pedido_id):
        data = db.obtener_o_generar_codigo_entrega_pedido(pedido_id=pedido_id)
        if isinstance(data, dict) and data.get("error"):
            msg = data["error"].lower()
            status = 404 if "no encontrado" in msg else 400
            return error(data["error"], status)

        destino_data = db.obtener_destino_whatsapp_por_pedido(pedido_id=pedido_id)
        if isinstance(destino_data, dict) and destino_data.get("error"):
            msg = destino_data["error"].lower()
            status = 404 if "no encontrado" in msg else 400
            return error(destino_data["error"], status)

        codigo = data.get("codigo_entrega")
        destino = normalize_ticket_destination(destino_data.get("whatsapp_id"))
        if not destino:
            return error("No se encontro un WhatsApp valido para reenviar el codigo.", 400)

        mensaje = (
            f"Buena nota, tu codigo de entrega para el pedido #{pedido_id} es: {codigo}. "
            "Si no te aparece el QR, comparte este codigo al repartidor para liberar el pedido."
        )

        enviado = send_text_whatsapp(destino=destino, texto=mensaje)
        if isinstance(enviado, dict) and enviado.get("error"):
            return error(f"No se pudo reenviar el codigo por WhatsApp: {enviado['error']}", 502)

        db.crear_log_notificacion(
            {
                "pedido_id": pedido_id,
                "canal": "whatsapp",
                "destino": destino,
                "tipo": "codigo_entrega",
                "mensaje": mensaje,
                "total": None,
                "direccion": None,
            }
        )

        return ok(
            {
                "pedido_id": pedido_id,
                "codigo_entrega": codigo,
                "destino": destino,
                "message": "Codigo reenviado por WhatsApp al cliente.",
            }
        )

    app.add_url_rule(
        "/api/pedidos/<int:pedido_id>/reenviar-codigo",
        endpoint="api_reenviar_codigo_pedido",
        view_func=api_reenviar_codigo_pedido,
        methods=["POST"],
    )

    @login_required(roles=["admin", "repartidor"])
    def api_programar_evaluacion_entrega():
        payload = request.get_json(silent=True) or {}
        pedido_id = payload.get("pedido_id")
        retraso_minutos = payload.get("retraso_minutos", 15)
        if not pedido_id:
            return error("pedido_id es obligatorio", 400)
        return ok(
            {
                "pedido_id": pedido_id,
                "retraso_minutos": retraso_minutos,
                "message": "Evaluacion programada (demo).",
            }
        )

    app.add_url_rule(
        "/api/evaluaciones/programar",
        endpoint="api_programar_evaluacion_entrega",
        view_func=api_programar_evaluacion_entrega,
        methods=["POST"],
    )
