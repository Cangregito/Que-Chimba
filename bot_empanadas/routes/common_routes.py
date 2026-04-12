import os
from typing import Any
from urllib.parse import quote

from flask import abort, jsonify, render_template, request, send_from_directory, session


def register_common_routes(app, deps: dict):
    db = deps["db"]
    login_required = deps["login_required"]
    ok = deps["ok"]
    error = deps["error"]
    client_ip = deps["client_ip"]
    is_valid_origin = deps["is_valid_origin"]
    env_str = deps["env_str"]
    default_public_number = deps["default_public_number"]
    default_public_message = deps["default_public_message"]

    def health():
        return ok({"status": "up"})

    app.add_url_rule("/health", endpoint="health", view_func=health, methods=["GET"])

    def serve_img(filename):
        img_dir = app.config.get("IMG_DIR", "")
        if not img_dir or not os.path.isdir(img_dir):
            abort(404)
        return send_from_directory(img_dir, filename)

    app.add_url_rule("/img/<path:filename>", endpoint="serve_img", view_func=serve_img, methods=["GET"])

    def serve_img_upper(filename):
        return serve_img(filename)

    app.add_url_rule("/Img/<path:filename>", endpoint="serve_img_upper", view_func=serve_img_upper, methods=["GET"])

    def favicon():
        return serve_img("simbolo-cuadrado-amarillo.png")

    app.add_url_rule("/favicon.ico", endpoint="favicon", view_func=favicon, methods=["GET"])

    def landing():
        raw_number = env_str("WHATSAPP_PUBLIC_NUMBER", default_public_number)
        message = env_str("WHATSAPP_PUBLIC_MESSAGE", default_public_message)

        wa_number = "".join(ch for ch in str(raw_number) if ch.isdigit())
        whatsapp_url = f"https://wa.me/{wa_number}?text={quote(message)}"
        whatsapp_display = f"+{wa_number}" if wa_number else "WhatsApp"

        return render_template(
            "index.html",
            whatsapp_url=whatsapp_url,
            whatsapp_display=whatsapp_display,
        )

    app.add_url_rule("/", endpoint="landing", view_func=landing, methods=["GET"])

    def login_page():
        return render_template("login.html")

    app.add_url_rule("/login", endpoint="login_page", view_func=login_page, methods=["GET"])

    def soporte_page():
        return render_template("soporte.html")

    app.add_url_rule("/soporte", endpoint="soporte_page", view_func=soporte_page, methods=["GET"])

    @login_required(roles=["admin"])
    def admin_tickets_page():
        return render_template("tickets_admin.html", user=session.get("user"))

    app.add_url_rule("/admin/tickets", endpoint="admin_tickets_page", view_func=admin_tickets_page, methods=["GET"])

    def login_post():
        payload = request.get_json(silent=True) or request.form
        username = payload.get("username")
        password = payload.get("password")

        if not isinstance(username, str) or not isinstance(password, str):
            return error("Credenciales invalidas", 401, code="invalid_credentials")

        username = username.strip()
        if not username or not password:
            return error(
                "Completa usuario y contrasena",
                400,
                code="validation_error",
                details={"fields": ["username", "password"]},
            )

        user = db.autenticar_usuario(username=username, password=password, direccion_ip=client_ip())
        if isinstance(user, dict) and user.get("error"):
            return error(user["error"], int(user.get("status", 401)), code="auth_failed")

        user_session = {
            "usuario_id": user.get("usuario_id"),
            "username": user.get("username"),
            "rol": user.get("rol"),
            "nombre_mostrar": user.get("nombre_mostrar"),
            "area_entrega": user.get("area_entrega"),
        }
        session["user"] = user_session
        return ok(user_session)

    app.add_url_rule("/login", endpoint="login_post", view_func=login_post, methods=["POST"])

    def logout():
        if session.get("user") and not is_valid_origin():
            return error("Origen no autorizado", 403, code="forbidden_origin")

        actor = session.get("user", {})
        if actor:
            db.registrar_evento_seguridad(
                tipo_evento="logout_success",
                severidad="info",
                actor_usuario_id=actor.get("usuario_id"),
                actor_username=actor.get("username"),
                actor_rol=actor.get("rol"),
                direccion_ip=client_ip(),
            )
        session.clear()
        return ok({"message": "Sesion cerrada"})

    app.add_url_rule("/logout", endpoint="logout", view_func=logout, methods=["POST"])

    @login_required(roles=["admin"])
    def admin_page():
        return render_template("admin.html", user=session.get("user"))

    app.add_url_rule("/admin", endpoint="admin_page", view_func=admin_page, methods=["GET"])

    @login_required(roles=["admin", "cocina"])
    def cocina_page():
        return render_template("cocina.html", user=session.get("user"))

    app.add_url_rule("/cocina", endpoint="cocina_page", view_func=cocina_page, methods=["GET"])

    @login_required(roles=["admin", "repartidor"])
    def repartidor_page():
        return render_template("repartidor.html", user=session.get("user"))

    app.add_url_rule("/repartidor", endpoint="repartidor_page", view_func=repartidor_page, methods=["GET"])

    def servir_audio(filename):
        return send_from_directory(app.config["AUDIO_DIR"], filename, mimetype="audio/ogg")

    app.add_url_rule("/audio/<path:filename>", endpoint="servir_audio", view_func=servir_audio, methods=["GET"])

    def api_productos():
        solo_pedibles_raw = (request.args.get("solo_pedibles") or "1").strip().lower()
        solo_pedibles = solo_pedibles_raw not in {"0", "false", "no", "off"}
        data = db.obtener_productos(solo_pedibles=solo_pedibles)
        if isinstance(data, dict) and data.get("error"):
            return error(data["error"], 500)
        return ok(data)

    app.add_url_rule("/api/productos", endpoint="api_productos", view_func=api_productos, methods=["GET"])

    def api_stats_publicas():
        resumen = db.obtener_resumen_db()
        if isinstance(resumen, dict) and resumen.get("error"):
            return jsonify(
                {
                    "total_empanadas_vendidas": 0,
                    "total_clientes_felices": 0,
                    "total_eventos": 0,
                    "source": "fallback",
                }
            )

        total_empanadas = int(resumen.get("pedidos", 0) or 0)
        total_clientes = int(resumen.get("clientes", 0) or 0)
        total_eventos = int(resumen.get("campanas", 0) or 0)

        return jsonify(
            {
                "total_empanadas_vendidas": total_empanadas,
                "total_clientes_felices": total_clientes,
                "total_eventos": total_eventos,
            }
        )

    app.add_url_rule("/api/stats/publicas", endpoint="api_stats_publicas", view_func=api_stats_publicas, methods=["GET"])

    def api_evaluaciones_publicas():
        conn = None
        try:
            conn = db.get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name = 'evaluaciones'
                    LIMIT 1
                    """
                )
                if not cur.fetchone():
                    return jsonify([])

                cur.execute(
                    """
                    SELECT
                        e.calificacion,
                        COALESCE(NULLIF(TRIM(e.comentario), ''), 'Excelente servicio y sabor.') AS comentario,
                        COALESCE(NULLIF(TRIM(c.nombre), ''), 'Cliente') AS nombre_cliente
                    FROM evaluaciones e
                    LEFT JOIN pedidos p ON p.pedido_id = e.pedido_id
                    LEFT JOIN clientes c ON c.cliente_id = p.cliente_id
                    WHERE e.calificacion IS NOT NULL
                    ORDER BY COALESCE(e.creado_en, NOW()) DESC
                    LIMIT 12
                    """
                )
                rows = cur.fetchall() or []

            payload = []
            for row in rows:
                if isinstance(row, dict):
                    payload.append(
                        {
                            "calificacion": int(row.get("calificacion") or 0),
                            "comentario": row.get("comentario") or "Excelente servicio y sabor.",
                            "nombre_cliente": row.get("nombre_cliente") or "Cliente",
                        }
                    )
                    continue

                payload.append(
                    {
                        "calificacion": int(row[0] or 0),
                        "comentario": row[1] or "Excelente servicio y sabor.",
                        "nombre_cliente": row[2] or "Cliente",
                    }
                )

            return jsonify(payload)
        except Exception:
            return jsonify([])
        finally:
            if conn:
                conn.close()

    app.add_url_rule(
        "/api/evaluaciones/publicas",
        endpoint="api_evaluaciones_publicas",
        view_func=api_evaluaciones_publicas,
        methods=["GET"],
    )
