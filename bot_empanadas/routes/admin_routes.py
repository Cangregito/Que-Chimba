from flask import request, session


def register_admin_routes(app, deps: dict):
    db = deps["db"]
    ok = deps["ok"]
    error = deps["error"]
    login_required = deps["login_required"]
    client_ip = deps["client_ip"]

    @login_required(roles=["admin"])
    def api_admin_productos_listar():
        limit = request.args.get("limit", "200")
        try:
            limit_int = max(1, min(500, int(limit)))
        except ValueError:
            return error("Parametro limit invalido", 400)

        data = db.obtener_productos_admin(limit=limit_int)
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)
        return ok(data)

    app.add_url_rule("/api/admin/productos", endpoint="api_admin_productos_listar", view_func=api_admin_productos_listar, methods=["GET"])

    @login_required(roles=["admin"])
    def api_admin_productos_crear_actualizar():
        payload = request.get_json(silent=True) or {}
        created = db.crear_producto_manual(
            nombre=payload.get("nombre"),
            variante=payload.get("variante"),
            precio=payload.get("precio"),
            activo=payload.get("activo", True),
        )
        if isinstance(created, dict) and created.get("error"):
            return error(created["error"], 400)
        return ok(created, 201)

    app.add_url_rule("/api/admin/productos", endpoint="api_admin_productos_crear_actualizar", view_func=api_admin_productos_crear_actualizar, methods=["POST"])

    @login_required(roles=["admin"])
    def api_admin_productos_actualizar(producto_id):
        payload = request.get_json(silent=True) or {}
        updated = db.actualizar_producto_admin(
            producto_id=producto_id,
            nombre=payload.get("nombre") if "nombre" in payload else None,
            variante=payload.get("variante") if "variante" in payload else None,
            precio=payload.get("precio") if "precio" in payload else None,
            activo=payload.get("activo") if "activo" in payload else None,
        )
        if isinstance(updated, dict) and updated.get("error"):
            msg = updated["error"].lower()
            status = 404 if "no encontrado" in msg else 400
            return error(updated["error"], status)
        return ok(updated)

    app.add_url_rule(
        "/api/admin/productos/<int:producto_id>",
        endpoint="api_admin_productos_actualizar",
        view_func=api_admin_productos_actualizar,
        methods=["PATCH"],
    )

    @login_required(roles=["admin"])
    def api_admin_insumos_crear_actualizar():
        payload = request.get_json(silent=True) or {}
        actor = session.get("user", {})
        created = db.crear_insumo_manual(
            nombre=payload.get("nombre"),
            unidad_medida=payload.get("unidad_medida"),
            stock_minimo=payload.get("stock_minimo", 0),
            stock_inicial=payload.get("stock_inicial", 0),
            proveedor=payload.get("proveedor"),
            actor_username=actor.get("username"),
            actor_rol=actor.get("rol", "admin"),
        )
        if isinstance(created, dict) and created.get("error"):
            return error(created["error"], 400)
        return ok(created, 201)

    app.add_url_rule("/api/admin/insumos", endpoint="api_admin_insumos_crear_actualizar", view_func=api_admin_insumos_crear_actualizar, methods=["POST"])

    @login_required(roles=["admin"])
    def api_admin_insumos_actualizar(insumo_id):
        payload = request.get_json(silent=True) or {}
        updated = db.actualizar_insumo_admin(
            insumo_id=insumo_id,
            unidad_medida=payload.get("unidad_medida") if "unidad_medida" in payload else None,
            stock_minimo=payload.get("stock_minimo") if "stock_minimo" in payload else None,
            proveedor=payload.get("proveedor") if "proveedor" in payload else None,
        )
        if isinstance(updated, dict) and updated.get("error"):
            msg = updated["error"].lower()
            status = 404 if "no encontrado" in msg else 400
            return error(updated["error"], status)
        return ok(updated)

    app.add_url_rule(
        "/api/admin/insumos/<int:insumo_id>",
        endpoint="api_admin_insumos_actualizar",
        view_func=api_admin_insumos_actualizar,
        methods=["PATCH"],
    )

    @login_required(roles=["admin"])
    def api_admin_insumos_ajustar_stock(insumo_id):
        payload = request.get_json(silent=True) or {}
        actor = session.get("user", {})
        updated = db.ajustar_stock_insumo(
            insumo_id=insumo_id,
            cantidad_ajuste=payload.get("cantidad_ajuste"),
            motivo=payload.get("motivo"),
            actor_username=actor.get("username"),
            actor_rol=actor.get("rol", "admin"),
        )
        if isinstance(updated, dict) and updated.get("error"):
            msg = updated["error"].lower()
            status = 404 if "no encontrado" in msg else 400
            return error(updated["error"], status)
        return ok(updated, 201)

    app.add_url_rule(
        "/api/admin/insumos/<int:insumo_id>/ajuste-stock",
        endpoint="api_admin_insumos_ajustar_stock",
        view_func=api_admin_insumos_ajustar_stock,
        methods=["POST"],
    )

    @login_required(roles=["admin"])
    def api_admin_recetas_producto_guardar_componente():
        payload = request.get_json(silent=True) or {}
        saved = db.guardar_componente_receta(
            producto_id=payload.get("producto_id"),
            insumo_id=payload.get("insumo_id"),
            cantidad_por_unidad=payload.get("cantidad_por_unidad"),
            activo=payload.get("activo", True),
        )
        if isinstance(saved, dict) and saved.get("error"):
            return error(saved["error"], 400)
        return ok(saved, 201)

    app.add_url_rule(
        "/api/admin/recetas-producto",
        endpoint="api_admin_recetas_producto_guardar_componente",
        view_func=api_admin_recetas_producto_guardar_componente,
        methods=["POST"],
    )

    @login_required(roles=["admin"])
    def api_admin_recetas_producto_listar():
        producto_id = request.args.get("producto_id")
        texto = (request.args.get("q") or request.args.get("texto") or "").strip() or None
        activa_raw = (request.args.get("activa") or "").strip().lower()
        activa = None
        if activa_raw in {"1", "true", "yes", "on"}:
            activa = True
        elif activa_raw in {"0", "false", "no", "off"}:
            activa = False

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

        pid = None
        if producto_id not in (None, ""):
            try:
                pid = int(producto_id)
            except ValueError:
                return error("Parametro producto_id invalido", 400)

        data = db.obtener_recetas_producto(
            producto_id=pid,
            texto=texto,
            activa=activa,
            limit=limit_int,
            offset=offset_int,
        )
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)
        return ok(data)

    app.add_url_rule(
        "/api/admin/recetas-producto",
        endpoint="api_admin_recetas_producto_listar",
        view_func=api_admin_recetas_producto_listar,
        methods=["GET"],
    )

    @login_required(roles=["admin"])
    def api_admin_recetas_producto_actualizar(receta_id):
        payload = request.get_json(silent=True) or {}
        updated = db.actualizar_componente_receta(
            receta_id=receta_id,
            activo=payload.get("activo") if "activo" in payload else None,
            cantidad_por_unidad=payload.get("cantidad_por_unidad") if "cantidad_por_unidad" in payload else None,
        )
        if isinstance(updated, dict) and updated.get("error"):
            msg = updated["error"].lower()
            status = 404 if "no encontrado" in msg else 400
            return error(updated["error"], status)
        return ok(updated)

    app.add_url_rule(
        "/api/admin/recetas-producto/<int:receta_id>",
        endpoint="api_admin_recetas_producto_actualizar",
        view_func=api_admin_recetas_producto_actualizar,
        methods=["PATCH"],
    )

    @login_required(roles=["admin"])
    def api_admin_inventario_movimientos():
        limit = request.args.get("limit", "50")
        insumo_id = request.args.get("insumo_id")
        tipo = (request.args.get("tipo") or "").strip() or None

        try:
            limit_int = max(1, min(500, int(limit)))
        except ValueError:
            return error("Parametro limit invalido", 400)

        iid = None
        if insumo_id not in (None, ""):
            try:
                iid = int(insumo_id)
            except ValueError:
                return error("Parametro insumo_id invalido", 400)

        data = db.obtener_movimientos_inventario(limit=limit_int, insumo_id=iid, tipo=tipo)
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)
        return ok(data)

    app.add_url_rule(
        "/api/admin/inventario/movimientos",
        endpoint="api_admin_inventario_movimientos",
        view_func=api_admin_inventario_movimientos,
        methods=["GET"],
    )

    @login_required(roles=["admin"])
    def api_admin_productos_sin_receta():
        data = db.obtener_productos_sin_receta()
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)
        return ok(data)

    app.add_url_rule(
        "/api/admin/productos-sin-receta",
        endpoint="api_admin_productos_sin_receta",
        view_func=api_admin_productos_sin_receta,
        methods=["GET"],
    )

    @login_required(roles=["admin"])
    def api_admin_usuarios_listar():
        rol = (request.args.get("rol") or "").strip() or None
        area_entrega = (request.args.get("area_entrega") or "").strip() or None

        data = db.obtener_usuarios_sistema(rol=rol, area_entrega=area_entrega)
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)
        return ok(data)

    app.add_url_rule("/api/admin/usuarios", endpoint="api_admin_usuarios_listar", view_func=api_admin_usuarios_listar, methods=["GET"])

    @login_required(roles=["admin"])
    def api_admin_usuarios_crear():
        payload = request.get_json(silent=True) or {}
        actor = session.get("user", {})
        username = payload.get("username")
        password = payload.get("password")
        rol = payload.get("rol")
        nombre_mostrar = payload.get("nombre_mostrar") or payload.get("nombre")
        telefono = payload.get("telefono")
        area_entrega = payload.get("area_entrega")

        created = db.crear_usuario_sistema(
            username=username,
            password=password,
            rol=rol,
            nombre_mostrar=nombre_mostrar,
            telefono=telefono,
            area_entrega=area_entrega,
            actor_usuario_id=actor.get("usuario_id"),
            actor_username=actor.get("username"),
            actor_rol=actor.get("rol"),
            direccion_ip=client_ip(),
        )
        if isinstance(created, dict) and created.get("error"):
            return error(created["error"], 400)
        return ok(created, 201)

    app.add_url_rule("/api/admin/usuarios", endpoint="api_admin_usuarios_crear", view_func=api_admin_usuarios_crear, methods=["POST"])

    @login_required(roles=["admin"])
    def api_admin_usuarios_actualizar(usuario_id):
        payload = request.get_json(silent=True) or {}
        actor = session.get("user", {})
        updated = db.actualizar_usuario_sistema(
            usuario_id=usuario_id,
            rol=payload.get("rol"),
            nombre_mostrar=payload.get("nombre_mostrar"),
            telefono=payload.get("telefono"),
            area_entrega=payload.get("area_entrega") if "area_entrega" in payload else None,
            activo=payload.get("activo") if "activo" in payload else None,
            nueva_password=payload.get("nueva_password"),
            actor_usuario_id=actor.get("usuario_id"),
            actor_username=actor.get("username"),
            actor_rol=actor.get("rol"),
            direccion_ip=client_ip(),
        )
        if isinstance(updated, dict) and updated.get("error"):
            msg = updated["error"].lower()
            status = 404 if "no encontrado" in msg else 400
            return error(updated["error"], status)
        return ok(updated)

    app.add_url_rule(
        "/api/admin/usuarios/<int:usuario_id>",
        endpoint="api_admin_usuarios_actualizar",
        view_func=api_admin_usuarios_actualizar,
        methods=["PATCH"],
    )

    @login_required(roles=["admin"])
    def api_admin_logs_backups():
        import os
        import pathlib
        
        limit = request.args.get("limit", "50")
        try:
            limit_int = max(1, min(500, int(limit)))
        except ValueError:
            return error("Parametro limit invalido", 400)
        
        # Definir rutas de logs
        base_path = pathlib.Path(__file__).parent.parent.parent / "logs" / "ops"
        
        if not base_path.exists():
            return ok({"logs": [], "total": 0})
        
        # Leer archivos de logs de backups
        logs = []
        try:
            # Backup logs
            backup_log = base_path / "backup-postgres-2026-04.log"
            if backup_log.exists():
                with open(backup_log, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    for line in reversed(lines[-limit_int:]):
                        if line.strip():
                            logs.append({
                                "type": "backup",
                                "timestamp": line[:19] if len(line) > 19 else line[:10],
                                "message": line.strip(),
                                "level": "ERROR" if "[ERROR]" in line else "INFO"
                            })
            
            # Verify logs
            verify_log = base_path / "verify-restore-postgres-2026-04.log"
            if verify_log.exists():
                with open(verify_log, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    for line in reversed(lines[-limit_int:]):
                        if line.strip():
                            logs.append({
                                "type": "verify",
                                "timestamp": line[:19] if len(line) > 19 else line[:10],
                                "message": line.strip(),
                                "level": "ERROR" if "[ERROR]" in line else "INFO"
                            })
        except Exception as e:
            return error(f"Error leyendo logs: {str(e)}", 500)
        
        # Ordenar por timestamp descendente
        logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        
        return ok({"logs": logs[:limit_int], "total": len(logs)})

    app.add_url_rule("/api/admin/logs/backups", endpoint="api_admin_logs_backups", view_func=api_admin_logs_backups, methods=["GET"])

    @login_required(roles=["admin"])
    def api_admin_backup_estadisticas():
        import os
        import pathlib
        
        base_path = pathlib.Path(__file__).parent.parent.parent / "backups" / "postgres"
        
        if not base_path.exists():
            return ok({"total_backups": 0, "total_size_mb": 0, "ultimo_backup": None, "proxima_ejecucion": "02:00 (diario)"})
        
        try:
            # Contar backups y tamaño
            backup_files = list(base_path.glob("*.zip"))
            total_size = sum(f.stat().st_size for f in backup_files) / (1024 * 1024)  # MB
            
            # Último backup
            ultimo_backup = None
            if backup_files:
                archivo_mas_reciente = max(backup_files, key=lambda f: f.stat().st_mtime)
                import datetime
                timestamp = datetime.datetime.fromtimestamp(archivo_mas_reciente.stat().st_mtime)
                ultimo_backup = timestamp.strftime("%Y-%m-%d %H:%M:%S")
            
            return ok({
                "total_backups": len(backup_files),
                "total_size_mb": round(total_size, 2),
                "ultimo_backup": ultimo_backup,
                "proxima_ejecucion": "02:00 (diario)",
                "proxima_verificacion": "03:00 domingo (semanal)"
            })
        except Exception as e:
            return error(f"Error obteniendo estadísticas: {str(e)}", 500)

    app.add_url_rule("/api/admin/backup/estadisticas", endpoint="api_admin_backup_estadisticas", view_func=api_admin_backup_estadisticas, methods=["GET"])

    @login_required(roles=["admin"])
    def api_logs_sistema_listar():
        nivel = (request.args.get("nivel") or "").strip().upper() or None
        componente = (request.args.get("componente") or "").strip().lower() or None
        q = (request.args.get("q") or "").strip() or None
        pendientes_raw = (request.args.get("pendientes") or "").strip().lower()
        solo_pendientes = pendientes_raw in {"1", "true", "yes", "on"}

        try:
            limit_int = max(1, min(500, int(request.args.get("limit", "50"))))
        except ValueError:
            return error("Parametro limit invalido", 400)

        try:
            offset_int = max(0, int(request.args.get("offset", "0")))
        except ValueError:
            return error("Parametro offset invalido", 400)

        rows = db.obtener_logs_sistema(
            nivel=nivel,
            componente=componente,
            limit=limit_int,
            offset=offset_int,
            solo_pendientes=solo_pendientes,
            q=q,
        )
        if isinstance(rows, dict) and rows.get("error"):
            return error(rows["error"], 500)

        total = db.contar_logs_sistema(
            nivel=nivel,
            componente=componente,
            solo_pendientes=solo_pendientes,
            q=q,
        )

        return ok(
            {
                "items": rows if isinstance(rows, list) else [],
                "total": int(total or 0),
                "limit": limit_int,
                "offset": offset_int,
            }
        )

    app.add_url_rule("/api/logs", endpoint="api_logs_sistema_listar", view_func=api_logs_sistema_listar, methods=["GET"])

    @login_required(roles=["admin"])
    def api_logs_sistema_resumen():
        summary = db.resumen_logs_sistema()
        if isinstance(summary, dict) and summary.get("error"):
            return error(summary["error"], 500)
        return ok(summary)

    app.add_url_rule("/api/logs/resumen", endpoint="api_logs_sistema_resumen", view_func=api_logs_sistema_resumen, methods=["GET"])

    @login_required(roles=["admin"])
    def api_logs_sistema_resolver(log_id):
        updated = db.marcar_log_sistema_resuelto(log_id)
        if isinstance(updated, dict) and updated.get("error"):
            status = 404 if "no encontrado" in str(updated.get("error", "")).lower() else 400
            return error(updated["error"], status)
        return ok(updated)

    app.add_url_rule(
        "/api/logs/<int:log_id>/resolver",
        endpoint="api_logs_sistema_resolver",
        view_func=api_logs_sistema_resolver,
        methods=["PATCH"],
    )
