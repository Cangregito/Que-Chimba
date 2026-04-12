from flask import request, session


def register_marketing_support_routes(app, deps: dict):
    db = deps["db"]
    ok = deps["ok"]
    error = deps["error"]
    login_required = deps["login_required"]
    normalize_whatsapp_id = deps["normalize_whatsapp_id"]
    normalize_ticket_destination = deps["normalize_ticket_destination"]
    send_text_whatsapp = deps["send_text_whatsapp"]

    @login_required(roles=["admin"])
    def api_campanias():
        payload = request.get_json(silent=True) or {}
        nombre = payload.get("nombre")
        mensaje = payload.get("mensaje")
        segmento = payload.get("segmento", "general")

        if not nombre or not mensaje:
            return error("Los campos nombre y mensaje son obligatorios")

        creada = db.crear_campania(
            nombre=nombre,
            mensaje=mensaje,
            segmento=segmento,
            creada_por=session.get("user", {}).get("username"),
        )
        if isinstance(creada, dict) and creada.get("error"):
            return error(creada["error"], 500)

        clientes = db.obtener_clientes_para_campania(filtro=segmento)
        if isinstance(clientes, dict) and clientes.get("error"):
            return error(clientes["error"], 500)

        lista_clientes = clientes if isinstance(clientes, list) else []
        enviados = 0
        fallidos = 0

        for cliente in lista_clientes:
            if not isinstance(cliente, dict):
                continue

            destino = normalize_whatsapp_id(cliente.get("whatsapp_id"))
            if not destino:
                fallidos += 1
                db.registrar_envio_campana(
                    campana_id=creada.get("campana_id"),
                    cliente_id=cliente.get("cliente_id"),
                    whatsapp_id="",
                    enviado=False,
                    error="Cliente sin whatsapp_id valido",
                )
                continue

            envio = send_text_whatsapp(destino=destino, texto=mensaje)
            if isinstance(envio, dict) and envio.get("error"):
                fallidos += 1
                db.registrar_envio_campana(
                    campana_id=creada.get("campana_id"),
                    cliente_id=cliente.get("cliente_id"),
                    whatsapp_id=destino,
                    enviado=False,
                    error=envio.get("error"),
                )
                continue

            enviados += 1
            db.registrar_envio_campana(
                campana_id=creada.get("campana_id"),
                cliente_id=cliente.get("cliente_id"),
                whatsapp_id=destino,
                enviado=True,
                error=None,
            )

        respuesta = dict(creada)
        respuesta["total_destinatarios"] = len(lista_clientes)
        respuesta["mensajes_enviados"] = enviados
        respuesta["mensajes_fallidos"] = fallidos
        return ok(respuesta, 201)

    app.add_url_rule("/api/campanias", endpoint="api_campanias", view_func=api_campanias, methods=["POST"])

    @login_required(roles=["admin"])
    def api_campanias_historial():
        limit_raw = request.args.get("limit", "80")
        try:
            limit = max(1, min(500, int(limit_raw)))
        except ValueError:
            return error("Parametro limit invalido", 400)

        data = db.obtener_campanias(limit=limit)
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)
        return ok(data)

    app.add_url_rule("/api/campanias", endpoint="api_campanias_historial", view_func=api_campanias_historial, methods=["GET"])

    @login_required(roles=["admin"])
    def api_campanias_historial_alias():
        return api_campanias_historial()

    app.add_url_rule(
        "/api/campanias/historial",
        endpoint="api_campanias_historial_alias",
        view_func=api_campanias_historial_alias,
        methods=["GET"],
    )

    @login_required(roles=["admin"])
    def api_clientes_count():
        filtro = (request.args.get("filtro") or "todos").strip().lower()
        data = db.contar_clientes_para_campania(filtro=filtro)
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)
        return ok(data)

    app.add_url_rule("/api/clientes/count", endpoint="api_clientes_count", view_func=api_clientes_count, methods=["GET"])

    @login_required(roles=["admin"])
    def api_empleados():
        data = db.obtener_empleados()
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)
        return ok(data)

    app.add_url_rule("/api/empleados", endpoint="api_empleados", view_func=api_empleados, methods=["GET"])

    def api_crear_ticket():
        payload = request.get_json(silent=True) or {}
        nombre = (payload.get("nombre_contacto") or "").strip()
        descripcion = (payload.get("descripcion") or "").strip()
        if not nombre:
            return error("nombre_contacto es obligatorio", 400, code="validation_error")
        if not descripcion:
            return error("descripcion es obligatoria", 400, code="validation_error")
        result = db.crear_ticket_soporte(
            categoria=(payload.get("categoria") or "otro").strip().lower(),
            prioridad=(payload.get("prioridad") or "media").strip().lower(),
            nombre_contacto=nombre,
            whatsapp_contacto=(payload.get("whatsapp_contacto") or "").strip() or None,
            descripcion=descripcion,
        )
        if isinstance(result, dict) and result.get("error"):
            return error(result["error"], 500)
        return ok(result, status=201)

    app.add_url_rule("/api/soporte/tickets", endpoint="api_crear_ticket", view_func=api_crear_ticket, methods=["POST"])

    @login_required(roles=["admin"])
    def api_listar_tickets():
        estado = request.args.get("estado") or None
        numero = (request.args.get("numero") or "").strip().upper()
        result = db.obtener_tickets_soporte(estado=estado)
        if isinstance(result, dict) and result.get("error"):
            return error(result["error"], 500)
        if numero:
            data = [t for t in result if isinstance(t, dict) and (t.get("numero_ticket") or "").strip().upper() == numero]
            return ok(data)
        return ok(result)

    app.add_url_rule("/api/soporte/tickets", endpoint="api_listar_tickets", view_func=api_listar_tickets, methods=["GET"])

    def api_consultar_ticket_publico(numero):
        numero_norm = (numero or "").strip().upper()
        if not numero_norm:
            return error("numero de ticket invalido", 400, code="validation_error")

        result = db.obtener_tickets_soporte(estado=None)
        if isinstance(result, dict) and result.get("error"):
            return error(result["error"], 500)

        ticket = None
        for item in result:
            if isinstance(item, dict) and (item.get("numero_ticket") or "").strip().upper() == numero_norm:
                ticket = item
                break

        if not ticket:
            return error(f"Ticket {numero_norm} no encontrado", 404, code="ticket_not_found")

        publico = {
            "numero_ticket": ticket.get("numero_ticket"),
            "categoria": ticket.get("categoria"),
            "prioridad": ticket.get("prioridad"),
            "estado": ticket.get("estado"),
            "descripcion": ticket.get("descripcion"),
            "creado_en": ticket.get("creado_en"),
            "actualizado_en": ticket.get("actualizado_en"),
            "notas_resolucion": ticket.get("notas_resolucion"),
        }
        return ok(publico)

    app.add_url_rule(
        "/api/soporte/tickets/public/<numero>",
        endpoint="api_consultar_ticket_publico",
        view_func=api_consultar_ticket_publico,
        methods=["GET"],
    )

    @login_required(roles=["admin"])
    def api_actualizar_ticket(numero):
        payload = request.get_json(silent=True) or {}
        nuevo_estado = (payload.get("estado") or "").strip()
        if not nuevo_estado:
            return error("estado es obligatorio", 400, code="validation_error")
        actor = session.get("user", {}).get("username")
        result = db.actualizar_estado_ticket(
            numero_ticket=numero,
            nuevo_estado=nuevo_estado,
            notas_resolucion=(payload.get("notas_resolucion") or "").strip() or None,
            resuelto_por=actor,
        )
        if isinstance(result, dict) and result.get("error"):
            return error(result["error"], 400)

        notificacion = {
            "intentada": False,
            "enviada": False,
            "destino": None,
            "motivo": "No aplica para este estado.",
        }
        estado_final = (result.get("estado") or "").strip().lower()
        if estado_final in {"resuelto", "cerrado"}:
            notificacion["intentada"] = True
            destino = normalize_ticket_destination(result.get("whatsapp_contacto"))
            notificacion["destino"] = destino or None
            if destino:
                notas = (result.get("notas_resolucion") or "").strip()
                texto = (
                    f"Listo parce, tu ticket {result.get('numero_ticket')} ya quedo {estado_final}. "
                    "Gracias por reportarlo."
                )
                if notas:
                    texto = f"{texto} Nota de soporte: {notas}"
                enviado = send_text_whatsapp(destino=destino, texto=texto)
                if isinstance(enviado, dict) and enviado.get("error"):
                    notificacion["motivo"] = enviado["error"]
                else:
                    notificacion["enviada"] = True
                    notificacion["motivo"] = "ok"
            else:
                notificacion["motivo"] = "Ticket sin whatsapp_contacto valido."

        response_data = dict(result)
        response_data["notificacion_whatsapp"] = notificacion
        return ok(response_data)

    app.add_url_rule(
        "/api/soporte/tickets/<numero>",
        endpoint="api_actualizar_ticket",
        view_func=api_actualizar_ticket,
        methods=["PATCH"],
    )
