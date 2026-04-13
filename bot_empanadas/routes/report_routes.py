import io
from datetime import datetime

from flask import make_response, request, session


def register_report_routes(app, deps: dict):
    db = deps["db"]
    ok = deps["ok"]
    error = deps["error"]
    login_required = deps["login_required"]
    serialize = deps["serialize"]

    @login_required(roles=["admin"])
    def api_top_clientes():
        top = db.obtener_top_clientes(limit=20)
        if isinstance(top, dict) and top.get("error"):
            return error(top["error"], 500)
        return ok(top)

    app.add_url_rule("/api/clientes/top20", endpoint="api_top_clientes", view_func=api_top_clientes, methods=["GET"])

    @login_required(roles=["admin"])
    def api_ventas_diarias():
        data = db.obtener_ventas_diarias()
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)
        return ok(data)

    app.add_url_rule("/api/ventas/diarias", endpoint="api_ventas_diarias", view_func=api_ventas_diarias, methods=["GET"])

    @login_required(roles=["admin"])
    def api_ventas_mensuales():
        data = db.obtener_ventas_mensuales()
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)
        return ok(data)

    app.add_url_rule("/api/ventas/mensuales", endpoint="api_ventas_mensuales", view_func=api_ventas_mensuales, methods=["GET"])

    @login_required(roles=["admin"])
    def api_ventas_anuales():
        data = db.obtener_ventas_anuales()
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)
        return ok(data)

    app.add_url_rule("/api/ventas/anuales", endpoint="api_ventas_anuales", view_func=api_ventas_anuales, methods=["GET"])

    @login_required(roles=["admin"])
    def api_kpis_ventas_periodo():
        data = db.obtener_kpis_ventas_periodo()
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)
        return ok(data)

    app.add_url_rule("/api/ventas/kpis-periodo", endpoint="api_kpis_ventas_periodo", view_func=api_kpis_ventas_periodo, methods=["GET"])

    @login_required(roles=["admin"])
    def api_reporte_ventas_profesional():
        periodo = (request.args.get("periodo") or "dia").strip().lower()
        fecha_base = (request.args.get("fecha") or "").strip() or None
        busqueda = (request.args.get("q") or request.args.get("buscar") or "").strip() or None

        limit_raw = request.args.get("limit", "300")
        try:
            limit_int = max(1, min(1000, int(limit_raw)))
        except ValueError:
            return error("Parametro limit invalido", 400)

        data = db.obtener_reporte_ventas_profesional(
            periodo=periodo,
            fecha_base=fecha_base,
            busqueda=busqueda,
            limit=limit_int,
        )
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)
        return ok(data)

    app.add_url_rule(
        "/api/admin/reporte-ventas-profesional",
        endpoint="api_reporte_ventas_profesional",
        view_func=api_reporte_ventas_profesional,
        methods=["GET"],
    )

    @login_required(roles=["admin"])
    def api_reporte_ventas_profesional_xlsx():
        periodo = (request.args.get("periodo") or "dia").strip().lower()
        fecha_base = (request.args.get("fecha") or "").strip() or None
        busqueda = (request.args.get("q") or request.args.get("buscar") or "").strip() or None

        limit_raw = request.args.get("limit", "1000")
        try:
            limit_int = max(1, min(5000, int(limit_raw)))
        except ValueError:
            return error("Parametro limit invalido", 400)

        data = db.obtener_reporte_ventas_profesional(
            periodo=periodo,
            fecha_base=fecha_base,
            busqueda=busqueda,
            limit=limit_int,
        )
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)

        try:
            from openpyxl import Workbook
        except Exception:
            return error("Falta dependencia openpyxl. Ejecuta: pip install openpyxl", 500)

        payload = serialize(data if isinstance(data, dict) else {})
        resumen = payload.get("resumen") or {}
        rows = payload.get("rows") or []

        wb = Workbook()
        ws_res = wb.active
        if ws_res is None:
            ws_res = wb.create_sheet(title="Resumen")
        else:
            ws_res.title = "Resumen"
        ws_res.append(["Metrica", "Valor"])
        periodo_label = {"dia": "Dia", "semana": "Semana", "mes": "Mes", "ano": "Ano"}.get(
            str(payload.get("periodo") or "dia").strip().lower(),
            str(payload.get("periodo") or "dia"),
        )
        ws_res.append(["Periodo", periodo_label])
        ws_res.append(["Fecha base", payload.get("fecha_base") or ""])
        ws_res.append(["Ventas", resumen.get("ventas") or 0])
        ws_res.append(["Pedidos", resumen.get("pedidos") or 0])
        ws_res.append(["Ticket promedio", resumen.get("ticket_promedio") or 0])
        ws_res.append(["Clientes unicos", resumen.get("clientes_unicos") or 0])
        ws_res.append(["Costo estimado total", resumen.get("costo_estimado_total") or 0])
        ws_res.append(["Utilidad estimada total", resumen.get("utilidad_estimada_total") or 0])
        ws_res.append(["Reserva impuestos pct", resumen.get("reserva_impuestos_pct") or 0])
        ws_res.append(["Reserva impuestos monto", resumen.get("reserva_impuestos_monto") or 0])
        ws_res.append(["Utilidad neta estimada", resumen.get("utilidad_neta_estimada") or 0])
        ws_res.append(["Margen estimado pct", resumen.get("margen_estimado_pct") or 0])
        ws_res.append(["Rapidez preparacion promedio min", resumen.get("rapidez_preparacion_promedio_min") or 0])
        ws_res.append(["Rapidez entrega promedio min", resumen.get("rapidez_entrega_promedio_min") or 0])

        ws_det = wb.create_sheet(title="Detalle")
        ws_det.append([
            "pedido_id",
            "creado_en",
            "cliente",
            "whatsapp_id",
            "metodo_pago",
            "metodo_entrega",
            "estado",
            "productos",
            "piezas",
            "total",
            "costo_estimado",
            "utilidad_estimada",
            "margen_estimado_pct",
            "rapidez_preparacion_min",
            "rapidez_entrega_min",
        ])

        for row in rows:
            if not isinstance(row, dict):
                continue
            ws_det.append([
                row.get("pedido_id"),
                row.get("creado_en"),
                row.get("cliente"),
                row.get("whatsapp_id"),
                row.get("metodo_pago"),
                row.get("metodo_entrega"),
                row.get("estado"),
                row.get("productos"),
                row.get("piezas"),
                row.get("total"),
                row.get("costo_estimado"),
                row.get("utilidad_estimada"),
                row.get("margen_estimado_pct"),
                row.get("rapidez_preparacion_min"),
                row.get("rapidez_entrega_min"),
            ])

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        filename = f"reporte_ventas_profesional_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        response = make_response(output.getvalue())
        response.headers["Content-Type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    app.add_url_rule(
        "/api/admin/reporte-ventas-profesional.xlsx",
        endpoint="api_reporte_ventas_profesional_xlsx",
        view_func=api_reporte_ventas_profesional_xlsx,
        methods=["GET"],
    )

    @login_required(roles=["admin"])
    def api_alertas_inventario():
        data = db.obtener_alertas_inventario()
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)
        return ok(data)

    app.add_url_rule("/api/inventario/alertas", endpoint="api_alertas_inventario", view_func=api_alertas_inventario, methods=["GET"])

    @login_required(roles=["admin"])
    def api_inventario():
        texto = (request.args.get("q") or request.args.get("texto") or "").strip() or None
        estado_stock = (request.args.get("estado_stock") or "").strip().lower() or None
        proveedor = (request.args.get("proveedor") or "").strip() or None

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

        data = db.obtener_inventario(
            texto=texto,
            estado_stock=estado_stock,
            proveedor=proveedor,
            limit=limit_int,
            offset=offset_int,
        )
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)
        return ok(data)

    app.add_url_rule("/api/inventario", endpoint="api_inventario", view_func=api_inventario, methods=["GET"])

    @login_required(roles=["admin"])
    def api_inventario_compras():
        payload = request.get_json(silent=True) or {}

        insumo = payload.get("insumo")
        cantidad = payload.get("cantidad")
        proveedor = payload.get("proveedor")
        costo_total = payload.get("costo_total")
        confirmar_unidad_base = bool(payload.get("confirmar_unidad_base"))

        created = db.registrar_compra_insumo(
            insumo=insumo,
            cantidad=cantidad,
            proveedor=proveedor,
            costo_total=costo_total,
            creado_por=session.get("user", {}).get("username"),
            actor_rol=session.get("user", {}).get("rol", "admin"),
            confirmar_unidad_base=confirmar_unidad_base,
        )
        if isinstance(created, dict) and created.get("error"):
            return error(created["error"], 400)
        return ok(created, 201)

    app.add_url_rule("/api/inventario/compras", endpoint="api_inventario_compras", view_func=api_inventario_compras, methods=["POST"])

    @login_required(roles=["admin"])
    def api_historial_compras_inventario():
        limit = request.args.get("limit", "30")
        try:
            limit_int = max(1, min(200, int(limit)))
        except ValueError:
            return error("Parametro limit invalido", 400)

        data = db.obtener_compras_insumos(limit=limit_int)
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)
        return ok(data)

    app.add_url_rule(
        "/api/inventario/compras",
        endpoint="api_historial_compras_inventario",
        view_func=api_historial_compras_inventario,
        methods=["GET"],
    )

    @login_required(roles=["admin"])
    def api_admin_resumen_db():
        data = db.obtener_resumen_db()
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)
        return ok(data)

    app.add_url_rule("/api/admin/resumen-db", endpoint="api_admin_resumen_db", view_func=api_admin_resumen_db, methods=["GET"])

    @login_required(roles=["admin"])
    def api_admin_rentabilidad_productos():
        limit = request.args.get("limit", "20")
        try:
            limit_int = max(1, min(200, int(limit)))
        except ValueError:
            return error("Parametro limit invalido", 400)

        data = db.obtener_rentabilidad_productos(limit=limit_int)
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)
        return ok(data)

    app.add_url_rule(
        "/api/admin/rentabilidad-productos",
        endpoint="api_admin_rentabilidad_productos",
        view_func=api_admin_rentabilidad_productos,
        methods=["GET"],
    )

    @login_required(roles=["admin"])
    def api_admin_rentabilidad_diagnostico():
        limit = request.args.get("limit", "200")
        try:
            limit_int = max(1, min(500, int(limit)))
        except ValueError:
            return error("Parametro limit invalido", 400)

        data = db.obtener_diagnostico_costos_receta(limit=limit_int)
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)

        if isinstance(data, list):
            normalized = []
            for row in data:
                if not isinstance(row, dict):
                    normalized.append(row)
                    continue

                detalle = row.get("insumos_sin_costo_detalle")
                if isinstance(detalle, list):
                    normalized.append(row)
                    continue

                fallback_names = row.get("insumos_sin_costo")
                if isinstance(fallback_names, list):
                    row["insumos_sin_costo_detalle"] = [
                        {"insumo_id": None, "nombre": str(name)} for name in fallback_names
                    ]
                else:
                    row["insumos_sin_costo_detalle"] = []
                normalized.append(row)
            data = normalized

        return ok(data)

    app.add_url_rule(
        "/api/admin/rentabilidad-diagnostico",
        endpoint="api_admin_rentabilidad_diagnostico",
        view_func=api_admin_rentabilidad_diagnostico,
        methods=["GET"],
    )
