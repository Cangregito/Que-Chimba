import csv
import io
import json
from datetime import datetime

from flask import make_response, request


def register_audit_parser_routes(app, deps: dict):
    db = deps["db"]
    ok = deps["ok"]
    error = deps["error"]
    login_required = deps["login_required"]
    parse_json_field = deps["parse_json_field"]
    bot_module = deps["bot_module"]

    @login_required(roles=["admin"])
    def api_admin_auditoria_seguridad():
        limit = request.args.get("limit", "40")
        offset = request.args.get("offset", "0")
        tipo_evento = (request.args.get("tipo_evento") or "").strip() or None
        severidad = (request.args.get("severidad") or "").strip().lower() or None
        actor = (request.args.get("actor") or "").strip() or None
        fecha_desde = (request.args.get("fecha_desde") or "").strip() or None
        fecha_hasta = (request.args.get("fecha_hasta") or "").strip() or None
        rango_rapido = (request.args.get("rango") or request.args.get("rango_rapido") or "").strip().lower() or None

        severidades_validas = {"info", "warning", "critical"}
        if severidad and severidad not in severidades_validas:
            return error("Parametro severidad invalido", 400)

        try:
            limit_int = max(1, min(200, int(limit)))
        except ValueError:
            return error("Parametro limit invalido", 400)
        try:
            offset_int = max(0, int(offset))
        except ValueError:
            return error("Parametro offset invalido", 400)

        data = db.obtener_auditoria_seguridad(
            limit=limit_int,
            offset=offset_int,
            tipo_evento=tipo_evento,
            severidad=severidad,
            actor_username=actor,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            rango_rapido=rango_rapido,
        )
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)
        return ok(data)

    app.add_url_rule("/api/admin/auditoria-seguridad", endpoint="api_admin_auditoria_seguridad", view_func=api_admin_auditoria_seguridad, methods=["GET"])

    @login_required(roles=["admin"])
    def api_admin_auditoria_seguridad_csv():
        tipo_evento = (request.args.get("tipo_evento") or "").strip() or None
        severidad = (request.args.get("severidad") or "").strip().lower() or None
        actor = (request.args.get("actor") or "").strip() or None
        fecha_desde = (request.args.get("fecha_desde") or "").strip() or None
        fecha_hasta = (request.args.get("fecha_hasta") or "").strip() or None
        limit = request.args.get("limit", "1000")

        severidades_validas = {"info", "warning", "critical"}
        if severidad and severidad not in severidades_validas:
            return error("Parametro severidad invalido", 400)

        try:
            limit_int = max(1, min(5000, int(limit)))
        except ValueError:
            return error("Parametro limit invalido", 400)

        data = db.obtener_auditoria_seguridad(
            limit=limit_int,
            tipo_evento=tipo_evento,
            severidad=severidad,
            actor_username=actor,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            "auditoria_id",
            "fecha",
            "tipo_evento",
            "severidad",
            "actor_usuario_id",
            "actor_username",
            "actor_rol",
            "objetivo_usuario_id",
            "objetivo_username",
            "direccion_ip",
            "detalle",
        ])

        for row in data:
            if not isinstance(row, dict):
                continue
            writer.writerow([
                row.get("auditoria_id"),
                row.get("creado_en"),
                row.get("tipo_evento"),
                row.get("severidad"),
                row.get("actor_usuario_id"),
                row.get("actor_username"),
                row.get("actor_rol"),
                row.get("objetivo_usuario_id"),
                row.get("objetivo_username"),
                row.get("direccion_ip"),
                json.dumps(row.get("detalle") or {}, ensure_ascii=False),
            ])

        filename = f"auditoria_seguridad_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        response = make_response(buffer.getvalue())
        response.headers["Content-Type"] = "text/csv; charset=utf-8"
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    app.add_url_rule(
        "/api/admin/auditoria-seguridad.csv",
        endpoint="api_admin_auditoria_seguridad_csv",
        view_func=api_admin_auditoria_seguridad_csv,
        methods=["GET"],
    )

    @login_required(roles=["admin"])
    def api_admin_auditoria_negocio():
        limit = request.args.get("limit", "40")
        offset = request.args.get("offset", "0")
        tabla = (request.args.get("tabla") or "").strip().lower() or None
        actor = (request.args.get("actor") or "").strip() or None
        fecha_desde = (request.args.get("fecha_desde") or "").strip() or None
        fecha_hasta = (request.args.get("fecha_hasta") or "").strip() or None
        rango_rapido = (request.args.get("rango") or request.args.get("rango_rapido") or "").strip().lower() or None

        tablas_validas = {"pedidos", "pagos", "insumos", "compras_insumos"}
        if tabla and tabla not in tablas_validas:
            return error("Parametro tabla invalido", 400)

        try:
            limit_int = max(1, min(200, int(limit)))
        except ValueError:
            return error("Parametro limit invalido", 400)
        try:
            offset_int = max(0, int(offset))
        except ValueError:
            return error("Parametro offset invalido", 400)

        data = db.obtener_auditoria_negocio(
            limit=limit_int,
            offset=offset_int,
            tabla_objetivo=tabla,
            actor_username=actor,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            rango_rapido=rango_rapido,
        )
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)
        return ok(data)

    app.add_url_rule("/api/admin/auditoria-negocio", endpoint="api_admin_auditoria_negocio", view_func=api_admin_auditoria_negocio, methods=["GET"])

    @login_required(roles=["admin"])
    def api_admin_auditoria_negocio_csv():
        tabla = (request.args.get("tabla") or "").strip().lower() or None
        actor = (request.args.get("actor") or "").strip() or None
        fecha_desde = (request.args.get("fecha_desde") or "").strip() or None
        fecha_hasta = (request.args.get("fecha_hasta") or "").strip() or None
        limit = request.args.get("limit", "1000")

        tablas_validas = {"pedidos", "pagos", "insumos", "compras_insumos"}
        if tabla and tabla not in tablas_validas:
            return error("Parametro tabla invalido", 400)

        try:
            limit_int = max(1, min(5000, int(limit)))
        except ValueError:
            return error("Parametro limit invalido", 400)

        data = db.obtener_auditoria_negocio(
            limit=limit_int,
            tabla_objetivo=tabla,
            actor_username=actor,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            "auditoria_negocio_id",
            "fecha",
            "tabla_objetivo",
            "operacion",
            "registro_id",
            "actor_username",
            "actor_rol",
            "detalle",
        ])

        for row in data:
            if not isinstance(row, dict):
                continue
            writer.writerow([
                row.get("auditoria_negocio_id"),
                row.get("creado_en"),
                row.get("tabla_objetivo"),
                row.get("operacion"),
                row.get("registro_id"),
                row.get("actor_username"),
                row.get("actor_rol"),
                json.dumps(row.get("detalle") or {}, ensure_ascii=False),
            ])

        filename = f"auditoria_negocio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        response = make_response(buffer.getvalue())
        response.headers["Content-Type"] = "text/csv; charset=utf-8"
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    app.add_url_rule(
        "/api/admin/auditoria-negocio.csv",
        endpoint="api_admin_auditoria_negocio_csv",
        view_func=api_admin_auditoria_negocio_csv,
        methods=["GET"],
    )

    @login_required(roles=["admin"])
    def api_admin_parser_observaciones():
        limit = request.args.get("limit", "80")
        tipo_evento = (request.args.get("tipo_evento") or "").strip() or None
        estado_revision = (request.args.get("estado_revision") or "").strip().lower() or None
        try:
            limit_int = max(1, min(300, int(limit)))
        except ValueError:
            return error("Parametro limit invalido", 400)
        data = db.obtener_observaciones_parser(limit=limit_int, tipo_evento=tipo_evento, estado_revision=estado_revision)
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)
        return ok(data)

    app.add_url_rule(
        "/api/admin/parser/observaciones",
        endpoint="api_admin_parser_observaciones",
        view_func=api_admin_parser_observaciones,
        methods=["GET"],
    )

    @login_required(roles=["admin"])
    def api_admin_parser_observacion_actualizar(observacion_id):
        payload = request.get_json(silent=True) or {}
        try:
            expected_items = parse_json_field(payload.get("expected_items_json"), None)
        except Exception:
            return error("expected_items_json debe ser JSON valido", 400)
        updated = db.actualizar_observacion_parser(
            observacion_id=observacion_id,
            estado_revision=payload.get("estado_revision") if "estado_revision" in payload else None,
            admin_notes=payload.get("admin_notes") if "admin_notes" in payload else None,
            expected_items_json=expected_items,
            regla_id=payload.get("regla_id") if "regla_id" in payload else None,
        )
        if isinstance(updated, dict) and updated.get("error"):
            msg = updated["error"].lower()
            status = 404 if "no encontrada" in msg or "no encontrado" in msg else 400
            return error(updated["error"], status)
        return ok(updated)

    app.add_url_rule(
        "/api/admin/parser/observaciones/<int:observacion_id>",
        endpoint="api_admin_parser_observacion_actualizar",
        view_func=api_admin_parser_observacion_actualizar,
        methods=["PATCH"],
    )

    @login_required(roles=["admin"])
    def api_admin_parser_frases():
        limit = request.args.get("limit", "200")
        activa_raw = (request.args.get("activa") or "").strip().lower()
        activa = None
        if activa_raw in {"1", "true", "yes", "on"}:
            activa = True
        elif activa_raw in {"0", "false", "no", "off"}:
            activa = False
        try:
            limit_int = max(1, min(500, int(limit)))
        except ValueError:
            return error("Parametro limit invalido", 400)
        data = db.obtener_frases_parser_curadas(limit=limit_int, activa=activa)
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)
        return ok(data)

    app.add_url_rule("/api/admin/parser/frases", endpoint="api_admin_parser_frases", view_func=api_admin_parser_frases, methods=["GET"])

    @login_required(roles=["admin"])
    def api_admin_parser_frases_crear():
        payload = request.get_json(silent=True) or {}
        try:
            items_json = parse_json_field(payload.get("items_json"), [])
        except Exception:
            return error("items_json debe ser JSON valido", 400)
        created = db.crear_frase_parser_curada(
            frase_original=payload.get("frase_original"),
            tipo_match=payload.get("tipo_match", "exact"),
            items_json=items_json,
            needs_confirmation=payload.get("needs_confirmation", False),
            needs_clarification=payload.get("needs_clarification", False),
            clarification_message=payload.get("clarification_message"),
            notas=payload.get("notas"),
            prioridad=payload.get("prioridad", 100),
            activa=payload.get("activa", True),
        )
        if isinstance(created, dict) and created.get("error"):
            return error(created["error"], 400)
        return ok(created, 201)

    app.add_url_rule("/api/admin/parser/frases", endpoint="api_admin_parser_frases_crear", view_func=api_admin_parser_frases_crear, methods=["POST"])

    @login_required(roles=["admin"])
    def api_admin_parser_frases_actualizar(regla_id):
        payload = request.get_json(silent=True) or {}
        try:
            items_json = parse_json_field(payload.get("items_json"), None) if "items_json" in payload else None
        except Exception:
            return error("items_json debe ser JSON valido", 400)
        updated = db.actualizar_frase_parser_curada(
            regla_id=regla_id,
            frase_original=payload.get("frase_original") if "frase_original" in payload else None,
            tipo_match=payload.get("tipo_match") if "tipo_match" in payload else None,
            items_json=items_json,
            needs_confirmation=payload.get("needs_confirmation") if "needs_confirmation" in payload else None,
            needs_clarification=payload.get("needs_clarification") if "needs_clarification" in payload else None,
            clarification_message=payload.get("clarification_message") if "clarification_message" in payload else None,
            notas=payload.get("notas") if "notas" in payload else None,
            prioridad=payload.get("prioridad") if "prioridad" in payload else None,
            activa=payload.get("activa") if "activa" in payload else None,
        )
        if isinstance(updated, dict) and updated.get("error"):
            msg = updated["error"].lower()
            status = 404 if "no encontrada" in msg or "no encontrado" in msg else 400
            return error(updated["error"], status)
        return ok(updated)

    app.add_url_rule(
        "/api/admin/parser/frases/<int:regla_id>",
        endpoint="api_admin_parser_frases_actualizar",
        view_func=api_admin_parser_frases_actualizar,
        methods=["PATCH"],
    )

    @login_required(roles=["admin"])
    def api_admin_parser_simular():
        payload = request.get_json(silent=True) or {}
        texto = (payload.get("texto") or "").strip()
        if not texto:
            return error("texto es obligatorio", 400)
        extractor = getattr(bot_module, "_extraer_items_menu_oficial", None) if bot_module is not None else None
        formatter = getattr(bot_module, "_formatear_carrito", None) if bot_module is not None else None
        if not callable(extractor):
            return error("Extractor del bot no disponible", 500)
        try:
            extraccion = extractor(texto)
            resumen = ""
            if callable(formatter):
                items = extraccion.get("items") or []
                total = int(extraccion.get("total") or 0)
                resumen = formatter(items, total) if items else ""
            return ok({"extraccion": extraccion, "resumen": resumen})
        except Exception as exc:
            return error(f"No se pudo simular el parser: {exc}", 500)

    app.add_url_rule("/api/admin/parser/simular", endpoint="api_admin_parser_simular", view_func=api_admin_parser_simular, methods=["POST"])
