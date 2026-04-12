from typing import Any

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

        return ok(created, 201)

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
        return ok(updated)

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

        destino_data = db.obtener_destino_whatsapp_por_pedido(pedido_id=pedido_id)
        if isinstance(destino_data, dict) and not destino_data.get("error"):
            destino = normalize_whatsapp_id(destino_data.get("whatsapp_id"))
            confirmacion_pago = (response_data.get("confirmacion_pago") or "").strip()
            mensaje = (
                f"Muchisimas gracias por tu compra, parce. Confirmamos que tu pedido #{pedido_id} "
                "ya fue entregado. Que lo disfrutes."
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
        destino = normalize_whatsapp_id(destino_data.get("whatsapp_id"))
        mensaje = (
            f"Buena nota, tu codigo de entrega para el pedido #{pedido_id} es: {codigo}. "
            "Compartelo al repartidor para liberar el pedido."
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
