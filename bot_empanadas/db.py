import json
import os
from datetime import date, datetime
from decimal import Decimal

import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.security import check_password_hash, generate_password_hash


def _db_config():
    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "5432")),
        "dbname": os.getenv("DB_NAME", "que_chimba"),
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD", "postgres"),
    }


def get_connection():
    try:
        return psycopg2.connect(**_db_config())
    except Exception as exc:
        raise RuntimeError(f"No se pudo conectar a PostgreSQL: {exc}") from exc


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Tipo no serializable: {type(value)}")


def _to_json_text(payload):
    if payload is None:
        return "{}"
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, default=_json_default)


def _tabla_tiene_columna(conn, tabla, columna):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
              AND column_name = %s
            LIMIT 1
            """,
            (tabla, columna),
        )
        return cur.fetchone() is not None


ESTADOS_PEDIDO = {"recibido", "en_preparacion", "listo", "en_camino", "entregado", "cancelado"}
ROLES_USUARIO_SISTEMA = {"admin", "cocina", "repartidor"}
TRANSICIONES_PEDIDO_VALIDAS = {
    "recibido": {"en_preparacion", "cancelado"},
    "en_preparacion": {"listo", "cancelado"},
    "listo": {"en_camino", "entregado", "cancelado"},
    "en_camino": {"entregado", "cancelado"},
    "entregado": set(),
    "cancelado": set(),
}


def _asegurar_tabla_usuarios_sistema(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS usuarios_sistema (
                usuario_id BIGSERIAL PRIMARY KEY,
                username VARCHAR(80) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                rol VARCHAR(30) NOT NULL,
                nombre_mostrar VARCHAR(120) NOT NULL,
                telefono VARCHAR(30),
                activo BOOLEAN NOT NULL DEFAULT TRUE,
                intentos_fallidos SMALLINT NOT NULL DEFAULT 0,
                bloqueado_hasta TIMESTAMP,
                ultimo_login TIMESTAMP,
                creado_en TIMESTAMP NOT NULL DEFAULT NOW(),
                actualizado_en TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT chk_usuarios_sistema_rol CHECK (rol IN ('admin', 'cocina', 'repartidor')),
                CONSTRAINT chk_usuarios_sistema_hash_len CHECK (char_length(password_hash) >= 20)
            )
            """
        )
        cur.execute(
            """
            ALTER TABLE usuarios_sistema
            ADD COLUMN IF NOT EXISTS intentos_fallidos SMALLINT NOT NULL DEFAULT 0
            """
        )
        cur.execute(
            """
            ALTER TABLE usuarios_sistema
            ADD COLUMN IF NOT EXISTS bloqueado_hasta TIMESTAMP
            """
        )
        cur.execute(
            """
            ALTER TABLE usuarios_sistema
            ADD COLUMN IF NOT EXISTS ultimo_login TIMESTAMP
            """
        )
        cur.execute(
            """
            ALTER TABLE usuarios_sistema
            ADD COLUMN IF NOT EXISTS actualizado_en TIMESTAMP NOT NULL DEFAULT NOW()
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_usuarios_sistema_rol_activo
                ON usuarios_sistema (rol, activo)
            """
        )


def _bootstrap_usuarios_por_rol(conn):
    defaults = {
        "admin": {
            "username": os.getenv("ADMIN_DEFAULT_USERNAME", "admin").strip() or "admin",
            "password": os.getenv("ADMIN_DEFAULT_PASSWORD", "admin123"),
            "nombre": os.getenv("ADMIN_DEFAULT_NAME", "Administrador"),
        },
        "cocina": {
            "username": os.getenv("COCINA_DEFAULT_USERNAME", "cocina").strip() or "cocina",
            "password": os.getenv("COCINA_DEFAULT_PASSWORD", "cocina123"),
            "nombre": os.getenv("COCINA_DEFAULT_NAME", "Operador Cocina"),
        },
        "repartidor": {
            "username": os.getenv("REPARTIDOR_DEFAULT_USERNAME", "repartidor").strip() or "repartidor",
            "password": os.getenv("REPARTIDOR_DEFAULT_PASSWORD", "repartidor123"),
            "nombre": os.getenv("REPARTIDOR_DEFAULT_NAME", "Operador Reparto"),
        },
    }

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        for rol, data in defaults.items():
            cur.execute(
                """
                SELECT 1
                FROM usuarios_sistema
                WHERE rol = %s AND activo = TRUE
                LIMIT 1
                """,
                (rol,),
            )
            if cur.fetchone():
                continue

            cur.execute(
                """
                INSERT INTO usuarios_sistema (username, password_hash, rol, nombre_mostrar, activo)
                VALUES (%s, %s, %s, %s, TRUE)
                ON CONFLICT (username) DO NOTHING
                """,
                (
                    data["username"],
                    generate_password_hash(data["password"]),
                    rol,
                    data["nombre"],
                ),
            )


def _asegurar_tabla_auditoria_seguridad(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS auditoria_seguridad (
                auditoria_id BIGSERIAL PRIMARY KEY,
                tipo_evento VARCHAR(50) NOT NULL,
                severidad VARCHAR(15) NOT NULL DEFAULT 'info',
                actor_usuario_id BIGINT,
                actor_username VARCHAR(80),
                actor_rol VARCHAR(30),
                objetivo_usuario_id BIGINT,
                objetivo_username VARCHAR(80),
                direccion_ip VARCHAR(64),
                detalle JSONB NOT NULL DEFAULT '{}'::jsonb,
                creado_en TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT chk_auditoria_seguridad_severidad CHECK (severidad IN ('info', 'warning', 'critical'))
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auditoria_seguridad_creado_en
                ON auditoria_seguridad (creado_en DESC)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auditoria_seguridad_tipo_evento
                ON auditoria_seguridad (tipo_evento, creado_en DESC)
            """
        )


def _registrar_auditoria_seguridad_cur(
    cur,
    tipo_evento,
    severidad="info",
    actor_usuario_id=None,
    actor_username=None,
    actor_rol=None,
    objetivo_usuario_id=None,
    objetivo_username=None,
    direccion_ip=None,
    detalle=None,
):
    cur.execute(
        """
        INSERT INTO auditoria_seguridad (
            tipo_evento,
            severidad,
            actor_usuario_id,
            actor_username,
            actor_rol,
            objetivo_usuario_id,
            objetivo_username,
            direccion_ip,
            detalle
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        """,
        (
            tipo_evento,
            severidad,
            actor_usuario_id,
            actor_username,
            actor_rol,
            objetivo_usuario_id,
            objetivo_username,
            direccion_ip,
            _to_json_text(detalle),
        ),
    )


def registrar_evento_seguridad(
    tipo_evento,
    severidad="info",
    actor_usuario_id=None,
    actor_username=None,
    actor_rol=None,
    objetivo_usuario_id=None,
    objetivo_username=None,
    direccion_ip=None,
    detalle=None,
):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_auditoria_seguridad(conn)
        with conn.cursor() as cur:
            _registrar_auditoria_seguridad_cur(
                cur,
                tipo_evento=tipo_evento,
                severidad=severidad,
                actor_usuario_id=actor_usuario_id,
                actor_username=actor_username,
                actor_rol=actor_rol,
                objetivo_usuario_id=objetivo_usuario_id,
                objetivo_username=objetivo_username,
                direccion_ip=direccion_ip,
                detalle=detalle,
            )
            conn.commit()
            return {"ok": True}
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_auditoria_seguridad(
    limit=50,
    tipo_evento=None,
    severidad=None,
    actor_username=None,
    fecha_desde=None,
    fecha_hasta=None,
):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_auditoria_seguridad(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            filtros = []
            params = []

            if tipo_evento:
                filtros.append("tipo_evento = %s")
                params.append(str(tipo_evento).strip())

            if severidad:
                filtros.append("severidad = %s")
                params.append(str(severidad).strip().lower())

            if actor_username:
                filtros.append("LOWER(actor_username) = LOWER(%s)")
                params.append(str(actor_username).strip())

            if fecha_desde:
                filtros.append("creado_en >= %s::date")
                params.append(str(fecha_desde).strip())

            if fecha_hasta:
                filtros.append("creado_en < (%s::date + INTERVAL '1 day')")
                params.append(str(fecha_hasta).strip())

            where_sql = ""
            if filtros:
                where_sql = "WHERE " + " AND ".join(filtros)

            params.append(int(limit))
            cur.execute(
                f"""
                SELECT
                    auditoria_id,
                    tipo_evento,
                    severidad,
                    actor_usuario_id,
                    actor_username,
                    actor_rol,
                    objetivo_usuario_id,
                    objetivo_username,
                    direccion_ip,
                    detalle,
                    creado_en
                FROM auditoria_seguridad
                {where_sql}
                ORDER BY creado_en DESC
                LIMIT %s
                """,
                tuple(params),
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def _asegurar_auditoria_negocio(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS auditoria_negocio (
                auditoria_negocio_id BIGSERIAL PRIMARY KEY,
                tabla_objetivo VARCHAR(60) NOT NULL,
                operacion VARCHAR(10) NOT NULL,
                registro_id VARCHAR(120),
                actor_username VARCHAR(80),
                actor_rol VARCHAR(30),
                detalle JSONB NOT NULL DEFAULT '{}'::jsonb,
                creado_en TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT chk_auditoria_negocio_operacion CHECK (operacion IN ('INSERT', 'UPDATE', 'DELETE'))
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auditoria_negocio_fecha
                ON auditoria_negocio (creado_en DESC)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auditoria_negocio_tabla
                ON auditoria_negocio (tabla_objetivo, creado_en DESC)
            """
        )
        cur.execute(
            """
            CREATE OR REPLACE FUNCTION fn_auditoria_negocio_generic()
            RETURNS TRIGGER AS $$
            DECLARE
                actor_name TEXT := NULLIF(current_setting('app.current_user', true), '');
                actor_role TEXT := NULLIF(current_setting('app.current_role', true), '');
                source_row JSONB;
                row_id TEXT;
                payload JSONB;
            BEGIN
                source_row := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
                row_id := COALESCE(
                    source_row->>'pedido_id',
                    source_row->>'pago_id',
                    source_row->>'compra_id',
                    source_row->>'insumo_id',
                    source_row->>'detalle_id',
                    'N/A'
                );

                IF TG_OP = 'INSERT' THEN
                    payload := jsonb_build_object('new', to_jsonb(NEW));
                ELSIF TG_OP = 'UPDATE' THEN
                    payload := jsonb_build_object('old', to_jsonb(OLD), 'new', to_jsonb(NEW));
                ELSE
                    payload := jsonb_build_object('old', to_jsonb(OLD));
                END IF;

                INSERT INTO auditoria_negocio (tabla_objetivo, operacion, registro_id, actor_username, actor_rol, detalle)
                VALUES (TG_TABLE_NAME, TG_OP, row_id, actor_name, actor_role, payload);

                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        for table_name in ("pedidos", "pagos", "insumos", "compras_insumos"):
            cur.execute(
                f"""
                DROP TRIGGER IF EXISTS trg_auditoria_negocio_{table_name} ON {table_name};
                CREATE TRIGGER trg_auditoria_negocio_{table_name}
                AFTER INSERT OR UPDATE OR DELETE ON {table_name}
                FOR EACH ROW
                EXECUTE FUNCTION fn_auditoria_negocio_generic();
                """
            )


def _set_audit_actor(cur, actor_username=None, actor_rol=None):
    cur.execute("SELECT set_config('app.current_user', %s, true)", (str(actor_username or "sistema"),))
    cur.execute("SELECT set_config('app.current_role', %s, true)", (str(actor_rol or "sistema"),))


def obtener_auditoria_negocio(limit=50, tabla_objetivo=None, actor_username=None, fecha_desde=None, fecha_hasta=None):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_compras_insumos(conn)
        _asegurar_auditoria_negocio(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            filtros = []
            params = []

            if tabla_objetivo:
                filtros.append("tabla_objetivo = %s")
                params.append(str(tabla_objetivo).strip().lower())

            if actor_username:
                filtros.append("LOWER(actor_username) = LOWER(%s)")
                params.append(str(actor_username).strip())

            if fecha_desde:
                filtros.append("creado_en >= %s::date")
                params.append(str(fecha_desde).strip())

            if fecha_hasta:
                filtros.append("creado_en < (%s::date + INTERVAL '1 day')")
                params.append(str(fecha_hasta).strip())

            where_sql = ""
            if filtros:
                where_sql = "WHERE " + " AND ".join(filtros)

            params.append(int(limit))
            cur.execute(
                f"""
                SELECT
                    auditoria_negocio_id,
                    tabla_objetivo,
                    operacion,
                    registro_id,
                    actor_username,
                    actor_rol,
                    detalle,
                    creado_en
                FROM auditoria_negocio
                {where_sql}
                ORDER BY creado_en DESC
                LIMIT %s
                """,
                tuple(params),
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def autenticar_usuario(username, password, direccion_ip=None):
    conn = None
    try:
        usuario = (username or "").strip()
        secret = password or ""
        if not usuario or not secret:
            return {"error": "Credenciales invalidas", "status": 401}

        conn = get_connection()
        _asegurar_tabla_usuarios_sistema(conn)
        _asegurar_tabla_auditoria_seguridad(conn)
        _bootstrap_usuarios_por_rol(conn)

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    usuario_id,
                    username,
                    password_hash,
                    rol,
                    nombre_mostrar,
                    activo,
                    intentos_fallidos,
                    bloqueado_hasta
                FROM usuarios_sistema
                WHERE LOWER(username) = LOWER(%s)
                LIMIT 1
                """,
                (usuario,),
            )
            row = cur.fetchone()

            if not row:
                _registrar_auditoria_seguridad_cur(
                    cur,
                    tipo_evento="login_failed",
                    severidad="warning",
                    actor_username=usuario,
                    direccion_ip=direccion_ip,
                    detalle={"motivo": "usuario_no_encontrado"},
                )
                conn.commit()
                return {"error": "Credenciales invalidas", "status": 401}

            if not row.get("activo"):
                _registrar_auditoria_seguridad_cur(
                    cur,
                    tipo_evento="login_blocked",
                    severidad="warning",
                    actor_usuario_id=row.get("usuario_id"),
                    actor_username=row.get("username"),
                    actor_rol=row.get("rol"),
                    direccion_ip=direccion_ip,
                    detalle={"motivo": "usuario_inactivo"},
                )
                conn.commit()
                return {"error": "Usuario inactivo", "status": 403}

            bloqueado_hasta = row.get("bloqueado_hasta")
            if bloqueado_hasta and bloqueado_hasta > datetime.now():
                _registrar_auditoria_seguridad_cur(
                    cur,
                    tipo_evento="login_blocked",
                    severidad="warning",
                    actor_usuario_id=row.get("usuario_id"),
                    actor_username=row.get("username"),
                    actor_rol=row.get("rol"),
                    direccion_ip=direccion_ip,
                    detalle={"motivo": "bloqueo_temporal", "bloqueado_hasta": bloqueado_hasta.isoformat()},
                )
                conn.commit()
                return {"error": "Usuario bloqueado temporalmente", "status": 423}

            if not check_password_hash(row["password_hash"], secret):
                cur.execute(
                    """
                    UPDATE usuarios_sistema
                    SET
                        intentos_fallidos = CASE
                            WHEN intentos_fallidos + 1 >= 5 THEN 0
                            ELSE intentos_fallidos + 1
                        END,
                        bloqueado_hasta = CASE
                            WHEN intentos_fallidos + 1 >= 5 THEN NOW() + INTERVAL '15 minutes'
                            ELSE bloqueado_hasta
                        END,
                        actualizado_en = NOW()
                    WHERE usuario_id = %s
                    """,
                    (row["usuario_id"],),
                )
                _registrar_auditoria_seguridad_cur(
                    cur,
                    tipo_evento="login_failed",
                    severidad="warning",
                    actor_usuario_id=row.get("usuario_id"),
                    actor_username=row.get("username"),
                    actor_rol=row.get("rol"),
                    direccion_ip=direccion_ip,
                    detalle={"motivo": "password_incorrecto"},
                )
                conn.commit()
                return {"error": "Credenciales invalidas", "status": 401}

            cur.execute(
                """
                UPDATE usuarios_sistema
                SET
                    ultimo_login = NOW(),
                    intentos_fallidos = 0,
                    bloqueado_hasta = NULL,
                    actualizado_en = NOW()
                WHERE usuario_id = %s
                """,
                (row["usuario_id"],),
            )
            _registrar_auditoria_seguridad_cur(
                cur,
                tipo_evento="login_success",
                severidad="info",
                actor_usuario_id=row.get("usuario_id"),
                actor_username=row.get("username"),
                actor_rol=row.get("rol"),
                direccion_ip=direccion_ip,
            )
            conn.commit()
            return {
                "usuario_id": row["usuario_id"],
                "username": row["username"],
                "rol": row["rol"],
                "nombre_mostrar": row["nombre_mostrar"],
            }
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc), "status": 500}
    finally:
        if conn:
            conn.close()


def obtener_usuarios_sistema():
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_usuarios_sistema(conn)
        _bootstrap_usuarios_por_rol(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    usuario_id,
                    username,
                    rol,
                    nombre_mostrar,
                    telefono,
                    activo,
                    ultimo_login,
                    creado_en,
                    actualizado_en
                FROM usuarios_sistema
                ORDER BY rol, username
                """
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def crear_usuario_sistema(
    username,
    password,
    rol,
    nombre_mostrar,
    telefono=None,
    actor_usuario_id=None,
    actor_username=None,
    actor_rol=None,
    direccion_ip=None,
):
    conn = None
    try:
        usuario = (username or "").strip()
        secret = password or ""
        rol_val = (rol or "").strip().lower()
        nombre = (nombre_mostrar or "").strip()
        tel = (telefono or "").strip() or None

        if not usuario or not nombre:
            return {"error": "username y nombre_mostrar son obligatorios"}
        if len(secret) < 8:
            return {"error": "La contrasena debe tener al menos 8 caracteres"}
        if rol_val not in ROLES_USUARIO_SISTEMA:
            return {"error": "Rol invalido"}

        conn = get_connection()
        _asegurar_tabla_usuarios_sistema(conn)
        _asegurar_tabla_auditoria_seguridad(conn)

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO usuarios_sistema
                    (username, password_hash, rol, nombre_mostrar, telefono, activo)
                VALUES (%s, %s, %s, %s, %s, TRUE)
                RETURNING
                    usuario_id,
                    username,
                    rol,
                    nombre_mostrar,
                    telefono,
                    activo,
                    ultimo_login,
                    creado_en,
                    actualizado_en
                """,
                (usuario, generate_password_hash(secret), rol_val, nombre, tel),
            )
            row = cur.fetchone()
            _registrar_auditoria_seguridad_cur(
                cur,
                tipo_evento="user_created",
                severidad="info",
                actor_usuario_id=actor_usuario_id,
                actor_username=actor_username,
                actor_rol=actor_rol,
                objetivo_usuario_id=row.get("usuario_id"),
                objetivo_username=row.get("username"),
                direccion_ip=direccion_ip,
                detalle={"rol": row.get("rol"), "telefono": row.get("telefono")},
            )
            conn.commit()
            return row
    except psycopg2.IntegrityError:
        if conn:
            conn.rollback()
        return {"error": "El username ya existe"}
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def actualizar_usuario_sistema(
    usuario_id,
    rol=None,
    nombre_mostrar=None,
    telefono=None,
    activo=None,
    nueva_password=None,
    actor_usuario_id=None,
    actor_username=None,
    actor_rol=None,
    direccion_ip=None,
):
    conn = None
    try:
        user_id = int(usuario_id)
        cambios = []
        params = []
        detalle_auditoria = {}

        if rol is not None:
            rol_val = str(rol).strip().lower()
            if rol_val not in ROLES_USUARIO_SISTEMA:
                return {"error": "Rol invalido"}
            cambios.append("rol = %s")
            params.append(rol_val)
            detalle_auditoria["rol"] = rol_val

        if nombre_mostrar is not None:
            nombre = str(nombre_mostrar).strip()
            if not nombre:
                return {"error": "nombre_mostrar no puede ser vacio"}
            cambios.append("nombre_mostrar = %s")
            params.append(nombre)
            detalle_auditoria["nombre_mostrar"] = nombre

        if telefono is not None:
            tel = str(telefono).strip() or None
            cambios.append("telefono = %s")
            params.append(tel)
            detalle_auditoria["telefono"] = tel

        if activo is not None:
            cambios.append("activo = %s")
            params.append(bool(activo))
            detalle_auditoria["activo"] = bool(activo)

        if nueva_password is not None:
            secret = str(nueva_password)
            if len(secret) < 8:
                return {"error": "La contrasena debe tener al menos 8 caracteres"}
            cambios.append("password_hash = %s")
            params.append(generate_password_hash(secret))
            cambios.append("intentos_fallidos = 0")
            cambios.append("bloqueado_hasta = NULL")
            detalle_auditoria["password_reset"] = True

        if not cambios:
            return {"error": "No hay campos para actualizar"}

        conn = get_connection()
        _asegurar_tabla_usuarios_sistema(conn)
        _asegurar_tabla_auditoria_seguridad(conn)

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            query = f"""
                UPDATE usuarios_sistema
                SET
                    {", ".join(cambios)},
                    actualizado_en = NOW()
                WHERE usuario_id = %s
                RETURNING
                    usuario_id,
                    username,
                    rol,
                    nombre_mostrar,
                    telefono,
                    activo,
                    ultimo_login,
                    creado_en,
                    actualizado_en
            """
            params.append(user_id)
            cur.execute(query, tuple(params))
            row = cur.fetchone()
            if not row:
                return {"error": "Usuario no encontrado"}
            tipo_evento = "user_updated"
            severidad = "info"
            if detalle_auditoria.get("password_reset"):
                tipo_evento = "user_password_reset"
            elif "activo" in detalle_auditoria:
                tipo_evento = "user_activated" if detalle_auditoria["activo"] else "user_deactivated"
                severidad = "warning" if not detalle_auditoria["activo"] else "info"

            _registrar_auditoria_seguridad_cur(
                cur,
                tipo_evento=tipo_evento,
                severidad=severidad,
                actor_usuario_id=actor_usuario_id,
                actor_username=actor_username,
                actor_rol=actor_rol,
                objetivo_usuario_id=row.get("usuario_id"),
                objetivo_username=row.get("username"),
                direccion_ip=direccion_ip,
                detalle=detalle_auditoria,
            )
            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def _asegurar_tablas_operacion_pedidos(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS asignaciones_reparto (
                asignacion_id BIGSERIAL PRIMARY KEY,
                pedido_id BIGINT NOT NULL REFERENCES pedidos(pedido_id),
                repartidor_usuario VARCHAR(80) NOT NULL,
                asignado_por VARCHAR(80),
                asignado_en TIMESTAMP NOT NULL DEFAULT NOW(),
                activo BOOLEAN NOT NULL DEFAULT TRUE
            )
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_asignaciones_reparto_pedido_activo
                ON asignaciones_reparto(pedido_id)
                WHERE activo = TRUE
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bitacora_estado_pedidos (
                bitacora_id BIGSERIAL PRIMARY KEY,
                pedido_id BIGINT NOT NULL REFERENCES pedidos(pedido_id),
                estado_anterior VARCHAR(30),
                estado_nuevo VARCHAR(30) NOT NULL,
                actor_usuario VARCHAR(80),
                rol_actor VARCHAR(30),
                motivo TEXT,
                creado_en TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_bitacora_estado_pedidos_pedido
                ON bitacora_estado_pedidos (pedido_id, creado_en DESC)
            """
        )


def _registrar_bitacora_estado(cur, pedido_id, estado_anterior, estado_nuevo, actor_usuario=None, rol_actor=None, motivo=None):
    cur.execute(
        """
        INSERT INTO bitacora_estado_pedidos
            (pedido_id, estado_anterior, estado_nuevo, actor_usuario, rol_actor, motivo)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (pedido_id, estado_anterior, estado_nuevo, actor_usuario, rol_actor, motivo),
    )


def obtener_productos(solo_pedibles=False):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tablas_inventario_real(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if solo_pedibles:
                cur.execute(
                    """
                    SELECT p.producto_id, p.nombre, p.variante, p.precio, p.activo
                    FROM productos p
                    WHERE p.activo = TRUE
                      AND EXISTS (
                        SELECT 1
                        FROM recetas_producto_insumo r
                        WHERE r.producto_id = p.producto_id
                          AND r.activo = TRUE
                    )
                    ORDER BY p.nombre, p.variante
                    """
                )
            else:
                cur.execute(
                    """
                    SELECT producto_id, nombre, variante, precio, activo
                    FROM productos
                    WHERE activo = TRUE
                    ORDER BY nombre, variante
                    """
                )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_productos_sin_receta():
    conn = None
    try:
        conn = get_connection()
        _asegurar_tablas_inventario_real(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT p.producto_id, p.nombre, p.variante, p.precio, p.activo
                FROM productos p
                WHERE p.activo = TRUE
                  AND NOT EXISTS (
                    SELECT 1
                    FROM recetas_producto_insumo r
                    WHERE r.producto_id = p.producto_id
                      AND r.activo = TRUE
                  )
                ORDER BY p.nombre, p.variante
                """
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_o_crear_cliente(whatsapp_id):
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT cliente_id, whatsapp_id, nombre, apellidos
                FROM clientes
                WHERE whatsapp_id = %s
                LIMIT 1
                """,
                (whatsapp_id,),
            )
            cliente = cur.fetchone()
            if cliente:
                conn.commit()
                return cliente

            cur.execute(
                """
                INSERT INTO clientes (whatsapp_id, nombre, apellidos)
                VALUES (%s, %s, %s)
                RETURNING cliente_id, whatsapp_id, nombre, apellidos
                """,
                (whatsapp_id, "Cliente", "WhatsApp"),
            )
            nuevo = cur.fetchone()
            conn.commit()
            return nuevo
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def crear_pedido(cliente_id, items, direccion_id, metodo_pago, actor_usuario="sistema", actor_rol="bot"):
    conn = None
    try:
        if not items:
            return {"error": "El pedido debe incluir al menos un item."}

        items_normalizados = []

        conn = get_connection()
        _asegurar_tablas_operacion_pedidos(conn)
        _asegurar_tablas_inventario_real(conn)
        _asegurar_auditoria_negocio(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            for item in items:
                producto_id = int(item.get("producto_id") or 0)
                cantidad = int(item.get("cantidad") or 0)
                if producto_id <= 0:
                    return {"error": "Cada item requiere producto_id valido."}
                if cantidad <= 0:
                    return {"error": f"Cantidad invalida para producto_id={producto_id}."}

                cur.execute(
                    """
                    SELECT producto_id, nombre, variante, precio, activo
                    FROM productos
                    WHERE producto_id = %s
                    LIMIT 1
                    """,
                    (producto_id,),
                )
                producto = cur.fetchone()
                if not producto:
                    return {"error": f"Producto no encontrado: producto_id={producto_id}."}
                if not producto.get("activo"):
                    return {"error": f"Producto inactivo: {producto.get('nombre')} ({producto_id})."}

                precio_item = item.get("precio_unitario")
                precio_unitario = float(precio_item) if precio_item not in (None, "") else float(producto.get("precio") or 0)
                if precio_unitario <= 0:
                    return {"error": f"Precio invalido para producto_id={producto_id}."}

                items_normalizados.append(
                    {
                        "producto_id": producto_id,
                        "cantidad": cantidad,
                        "precio_unitario": precio_unitario,
                        "producto": producto.get("nombre"),
                        "variante": producto.get("variante"),
                    }
                )

            total = sum(float(item["cantidad"]) * float(item["precio_unitario"]) for item in items_normalizados)

            _set_audit_actor(cur, actor_username=actor_usuario, actor_rol=actor_rol)
            cur.execute(
                """
                INSERT INTO pedidos (cliente_id, direccion_id, metodo_pago, total, estado)
                VALUES (%s, %s, %s, %s, 'recibido')
                RETURNING pedido_id, cliente_id, direccion_id, metodo_pago, total, estado, creado_en
                """,
                (cliente_id, direccion_id, metodo_pago, total),
            )
            pedido = cur.fetchone()

            for item in items_normalizados:
                cur.execute(
                    """
                    INSERT INTO detalle_pedido (pedido_id, producto_id, cantidad, precio_unitario)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        pedido["pedido_id"],
                        item.get("producto_id"),
                        item.get("cantidad", 1),
                        item.get("precio_unitario", 0),
                    ),
                )

            consumo = _descontar_inventario_por_pedido(
                cur,
                pedido_id=pedido["pedido_id"],
                items=items_normalizados,
                actor_usuario=actor_usuario,
                actor_rol=actor_rol,
            )
            if isinstance(consumo, dict) and consumo.get("error"):
                return consumo

            _registrar_bitacora_estado(
                cur,
                pedido_id=pedido["pedido_id"],
                estado_anterior=None,
                estado_nuevo="recibido",
                actor_usuario=actor_usuario,
                rol_actor=actor_rol,
                motivo="Pedido creado",
            )

            conn.commit()
            pedido["items"] = items_normalizados
            pedido["movimientos_inventario"] = consumo.get("movimientos", [])
            return pedido
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def actualizar_estado_pedido(pedido_id, nuevo_estado, actor_usuario=None, rol_actor=None, motivo=None):
    conn = None
    try:
        nuevo = (nuevo_estado or "").strip().lower()
        if nuevo not in ESTADOS_PEDIDO:
            return {"error": "Estado no valido."}

        conn = get_connection()
        _asegurar_tablas_operacion_pedidos(conn)
        _asegurar_auditoria_negocio(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _set_audit_actor(cur, actor_username=actor_usuario, actor_rol=rol_actor)
            cur.execute(
                """
                SELECT pedido_id, estado, creado_en
                FROM pedidos
                WHERE pedido_id = %s
                LIMIT 1
                """,
                (pedido_id,),
            )
            actual = cur.fetchone()
            if not actual:
                return {"error": "Pedido no encontrado."}

            estado_actual = (actual.get("estado") or "").strip().lower()
            if estado_actual == nuevo:
                return {
                    "pedido_id": actual["pedido_id"],
                    "estado": actual["estado"],
                    "creado_en": actual["creado_en"],
                }

            permitidos = TRANSICIONES_PEDIDO_VALIDAS.get(estado_actual, set())
            if nuevo not in permitidos:
                return {
                    "error": f"Transicion no permitida: {estado_actual} -> {nuevo}."
                }

            cur.execute(
                """
                UPDATE pedidos
                SET estado = %s
                WHERE pedido_id = %s
                RETURNING pedido_id, estado, creado_en
                """,
                (nuevo, pedido_id),
            )
            actualizado = cur.fetchone()

            _registrar_bitacora_estado(
                cur,
                pedido_id=pedido_id,
                estado_anterior=estado_actual,
                estado_nuevo=nuevo,
                actor_usuario=actor_usuario,
                rol_actor=rol_actor,
                motivo=motivo,
            )

            if nuevo in {"entregado", "cancelado"}:
                cur.execute(
                    """
                    UPDATE asignaciones_reparto
                    SET activo = FALSE
                    WHERE pedido_id = %s AND activo = TRUE
                    """,
                    (pedido_id,),
                )

            conn.commit()
            return actualizado
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_pedidos_por_estado(estado):
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    p.pedido_id,
                    p.estado,
                    p.total,
                    p.creado_en,
                    c.cliente_id,
                    c.whatsapp_id,
                    c.nombre,
                    c.apellidos
                FROM pedidos p
                JOIN clientes c ON c.cliente_id = p.cliente_id
                WHERE p.estado = %s
                ORDER BY p.creado_en DESC
                """,
                (estado,),
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_pedidos(estado=None, fecha=None):
    conn = None
    try:
        conn = get_connection()
        clauses = []
        params = []

        if estado:
            if isinstance(estado, (list, tuple, set)):
                estados = [str(e).strip() for e in estado if str(e).strip()]
                if estados:
                    placeholders = ", ".join(["%s"] * len(estados))
                    clauses.append(f"p.estado IN ({placeholders})")
                    params.extend(estados)
            else:
                clauses.append("p.estado = %s")
                params.append(estado)

        if fecha == "hoy":
            clauses.append("p.creado_en::date = CURRENT_DATE")

        where_sql = ""
        if clauses:
            where_sql = "WHERE " + " AND ".join(clauses)

        query = f"""
            SELECT
                p.pedido_id,
                p.estado,
                p.total,
                p.creado_en,
                c.cliente_id,
                c.whatsapp_id,
                c.nombre,
                c.apellidos,
                COALESCE(dc.direccion_texto, 'Sin direccion') AS direccion_entrega,
                COALESCE(NULLIF(SUBSTRING(COALESCE(dc.direccion_texto, '') FROM '([0-9]{5})'), ''), '00000') AS codigo_postal,
                COALESCE(SUM(dp.cantidad), 0)::INT AS cantidad_total,
                COALESCE(
                    json_agg(
                        json_build_object(
                            'detalle_id', dp.detalle_id,
                            'producto_id', dp.producto_id,
                            'producto', COALESCE(pr.nombre, 'Producto'),
                            'variante', COALESCE(pr.variante, ''),
                            'cantidad', dp.cantidad,
                            'precio_unitario', dp.precio_unitario
                        )
                    ) FILTER (WHERE dp.detalle_id IS NOT NULL),
                    '[]'::json
                ) AS items
            FROM pedidos p
            JOIN clientes c ON c.cliente_id = p.cliente_id
            LEFT JOIN direcciones_cliente dc ON dc.direccion_id = p.direccion_id
            LEFT JOIN detalle_pedido dp ON dp.pedido_id = p.pedido_id
            LEFT JOIN productos pr ON pr.producto_id = dp.producto_id
            {where_sql}
            GROUP BY p.pedido_id, p.estado, p.total, p.creado_en, c.cliente_id, c.whatsapp_id, c.nombre, c.apellidos, dc.direccion_texto
            ORDER BY p.creado_en DESC
        """

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, tuple(params))
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def confirmar_entrega_pedido(pedido_id, codigo_entrega=None):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tablas_operacion_pedidos(conn)
        has_codigo = _tabla_tiene_columna(conn, "pedidos", "codigo_entrega")

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if has_codigo:
                cur.execute(
                    """
                    SELECT pedido_id, estado, codigo_entrega
                    FROM pedidos
                    WHERE pedido_id = %s
                    LIMIT 1
                    """,
                    (pedido_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT pedido_id, estado
                    FROM pedidos
                    WHERE pedido_id = %s
                    LIMIT 1
                    """,
                    (pedido_id,),
                )

            row = cur.fetchone()
            if not row:
                return {"error": "Pedido no encontrado."}

            estado_actual = (row.get("estado") or "").strip().lower()
            if estado_actual not in {"listo", "en_camino"}:
                return {"error": "Solo se puede confirmar entrega para pedidos en estado listo o en_camino."}

            if has_codigo:
                codigo_db = (row.get("codigo_entrega") or "").strip().upper()
                codigo_in = (codigo_entrega or "").strip().upper()
                if codigo_db and codigo_db != codigo_in:
                    return {"error": "Codigo de entrega incorrecto."}

            updated = actualizar_estado_pedido(
                pedido_id=pedido_id,
                nuevo_estado="entregado",
                actor_usuario="repartidor",
                rol_actor="repartidor",
                motivo="Confirmacion de entrega con codigo",
            )
            if isinstance(updated, dict) and updated.get("error"):
                return updated

            cur.execute(
                """
                UPDATE asignaciones_reparto
                SET activo = FALSE
                WHERE pedido_id = %s AND activo = TRUE
                """,
                (pedido_id,),
            )
            conn.commit()
            return updated
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def asignar_pedido_repartidor(pedido_id, repartidor_usuario, asignado_por=None):
    conn = None
    try:
        if not repartidor_usuario:
            return {"error": "repartidor_usuario es obligatorio."}

        conn = get_connection()
        _asegurar_tablas_operacion_pedidos(conn)

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT pedido_id, estado
                FROM pedidos
                WHERE pedido_id = %s
                LIMIT 1
                """,
                (pedido_id,),
            )
            pedido = cur.fetchone()
            if not pedido:
                return {"error": "Pedido no encontrado."}

            if (pedido.get("estado") or "").strip().lower() not in {"listo", "en_camino"}:
                return {"error": "Solo se pueden asignar pedidos en estado listo o en_camino."}

            cur.execute(
                """
                UPDATE asignaciones_reparto
                SET activo = FALSE
                WHERE pedido_id = %s AND activo = TRUE
                """,
                (pedido_id,),
            )

            cur.execute(
                """
                INSERT INTO asignaciones_reparto (pedido_id, repartidor_usuario, asignado_por, activo)
                VALUES (%s, %s, %s, TRUE)
                RETURNING asignacion_id, pedido_id, repartidor_usuario, asignado_por, asignado_en, activo
                """,
                (pedido_id, repartidor_usuario, asignado_por),
            )
            row = cur.fetchone()
            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_pedidos_repartidor(repartidor_usuario=None):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tablas_operacion_pedidos(conn)

        params = ["listo", "en_camino"]
        where_assignment = ""
        if repartidor_usuario:
            where_assignment = " AND (ar.repartidor_usuario = %s OR ar.repartidor_usuario IS NULL)"
            params.append(repartidor_usuario)

        query = f"""
            SELECT
                p.pedido_id,
                p.estado,
                p.total,
                p.creado_en,
                c.nombre,
                c.apellidos,
                c.whatsapp_id,
                COALESCE(dc.direccion_texto, 'Sin direccion') AS direccion_entrega,
                COALESCE(NULLIF(SUBSTRING(COALESCE(dc.direccion_texto, '') FROM '([0-9]{{5}})'), ''), '00000') AS codigo_postal,
                ar.repartidor_usuario,
                COALESCE(
                    json_agg(
                        json_build_object(
                            'producto', COALESCE(pr.nombre, 'Producto'),
                            'variante', COALESCE(pr.variante, ''),
                            'cantidad', dp.cantidad
                        )
                    ) FILTER (WHERE dp.detalle_id IS NOT NULL),
                    '[]'::json
                ) AS items
            FROM pedidos p
            JOIN clientes c ON c.cliente_id = p.cliente_id
            LEFT JOIN direcciones_cliente dc ON dc.direccion_id = p.direccion_id
            LEFT JOIN detalle_pedido dp ON dp.pedido_id = p.pedido_id
            LEFT JOIN productos pr ON pr.producto_id = dp.producto_id
            LEFT JOIN asignaciones_reparto ar ON ar.pedido_id = p.pedido_id AND ar.activo = TRUE
            WHERE p.estado IN (%s, %s)
            {where_assignment}
            GROUP BY p.pedido_id, p.estado, p.total, p.creado_en, c.nombre, c.apellidos, c.whatsapp_id, dc.direccion_texto, ar.repartidor_usuario
            ORDER BY p.creado_en ASC
        """

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, tuple(params))
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_bitacora_pedido(pedido_id, limit=50):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tablas_operacion_pedidos(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT bitacora_id, pedido_id, estado_anterior, estado_nuevo, actor_usuario, rol_actor, motivo, creado_en
                FROM bitacora_estado_pedidos
                WHERE pedido_id = %s
                ORDER BY creado_en DESC
                LIMIT %s
                """,
                (pedido_id, int(limit)),
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_ventas_diarias():
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    TO_CHAR(DATE_TRUNC('hour', p.creado_en), 'HH24:00') AS etiqueta,
                    COUNT(*)::INT AS pedidos,
                    COALESCE(SUM(p.total), 0)::NUMERIC(10,2) AS ventas
                FROM pedidos p
                WHERE p.estado <> 'cancelado'
                  AND p.creado_en::date = CURRENT_DATE
                GROUP BY DATE_TRUNC('hour', p.creado_en)
                ORDER BY DATE_TRUNC('hour', p.creado_en)
                """
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_ventas_mensuales():
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    TO_CHAR(DATE_TRUNC('day', p.creado_en), 'YYYY-MM-DD') AS etiqueta,
                    COUNT(*)::INT AS pedidos,
                    COALESCE(SUM(p.total), 0)::NUMERIC(10,2) AS ventas
                FROM pedidos p
                WHERE p.estado <> 'cancelado'
                  AND DATE_TRUNC('month', p.creado_en) = DATE_TRUNC('month', CURRENT_DATE)
                GROUP BY DATE_TRUNC('day', p.creado_en)
                ORDER BY DATE_TRUNC('day', p.creado_en)
                """
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_ventas_anuales():
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    TO_CHAR(DATE_TRUNC('month', p.creado_en), 'YYYY-MM') AS etiqueta,
                    COUNT(*)::INT AS pedidos,
                    COALESCE(SUM(p.total), 0)::NUMERIC(10,2) AS ventas
                FROM pedidos p
                WHERE p.estado <> 'cancelado'
                  AND DATE_TRUNC('year', p.creado_en) = DATE_TRUNC('year', CURRENT_DATE)
                GROUP BY DATE_TRUNC('month', p.creado_en)
                ORDER BY DATE_TRUNC('month', p.creado_en)
                """
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_rentabilidad_productos(limit=30):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tablas_inventario_real(conn)
        _asegurar_tabla_compras_insumos(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                WITH costo_insumo AS (
                    SELECT DISTINCT ON (c.insumo_id)
                        c.insumo_id,
                        COALESCE(c.costo_total / NULLIF(c.cantidad, 0), 0)::NUMERIC(12,4) AS costo_unitario
                    FROM compras_insumos c
                    WHERE c.costo_total IS NOT NULL
                      AND c.cantidad > 0
                    ORDER BY c.insumo_id, c.creado_en DESC
                )
                SELECT
                    p.producto_id,
                    p.nombre,
                    p.variante,
                    p.precio::NUMERIC(10,2) AS precio_venta,
                    COALESCE(SUM(r.cantidad_por_unidad * COALESCE(ci.costo_unitario, 0)), 0)::NUMERIC(12,4) AS costo_estimado_unitario,
                    (p.precio - COALESCE(SUM(r.cantidad_por_unidad * COALESCE(ci.costo_unitario, 0)), 0))::NUMERIC(12,4) AS margen_unitario,
                    CASE
                        WHEN p.precio > 0 THEN ((p.precio - COALESCE(SUM(r.cantidad_por_unidad * COALESCE(ci.costo_unitario, 0)), 0)) / p.precio) * 100
                        ELSE 0
                    END::NUMERIC(8,2) AS margen_pct,
                    COUNT(r.insumo_id)::INT AS componentes_activos,
                    COUNT(ci.insumo_id)::INT AS componentes_con_costo,
                    GREATEST(COUNT(r.insumo_id) - COUNT(ci.insumo_id), 0)::INT AS componentes_sin_costo,
                    CASE
                        WHEN COUNT(r.insumo_id) = 0 THEN 'sin_receta'
                        WHEN COUNT(ci.insumo_id) = COUNT(r.insumo_id) THEN 'completo'
                        ELSE 'incompleto'
                    END AS calidad_costo
                FROM productos p
                LEFT JOIN recetas_producto_insumo r
                    ON r.producto_id = p.producto_id
                   AND r.activo = TRUE
                LEFT JOIN costo_insumo ci
                    ON ci.insumo_id = r.insumo_id
                WHERE p.activo = TRUE
                GROUP BY p.producto_id, p.nombre, p.variante, p.precio
                ORDER BY margen_unitario DESC, p.nombre, p.variante
                LIMIT %s
                """,
                (int(limit),),
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_top_clientes(limit=20):
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    c.cliente_id,
                    c.whatsapp_id,
                    c.nombre,
                    c.apellidos,
                    COUNT(p.pedido_id)::INT AS total_pedidos,
                    COALESCE(SUM(p.total), 0)::NUMERIC(10,2) AS monto_total_comprado,
                    MAX(p.creado_en) AS ultima_compra
                FROM clientes c
                JOIN pedidos p ON p.cliente_id = c.cliente_id
                WHERE p.estado <> 'cancelado'
                GROUP BY c.cliente_id, c.whatsapp_id, c.nombre, c.apellidos
                ORDER BY monto_total_comprado DESC, total_pedidos DESC
                LIMIT %s
                """,
                (limit,),
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_alertas_inventario():
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    i.insumo_id,
                    i.nombre,
                    i.unidad_medida,
                    i.stock_actual,
                    i.stock_minimo,
                    (i.stock_minimo - i.stock_actual)::NUMERIC(10,3) AS faltante,
                    pv.nombre AS proveedor
                FROM insumos i
                LEFT JOIN proveedores pv ON pv.proveedor_id = i.proveedor_id
                WHERE i.stock_actual < i.stock_minimo
                ORDER BY faltante DESC, i.nombre
                """
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_inventario():
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    i.insumo_id,
                    i.nombre,
                    i.unidad_medida,
                    i.stock_actual,
                    i.stock_minimo,
                    (i.stock_actual - i.stock_minimo)::NUMERIC(12,3) AS margen_stock,
                    pv.nombre AS proveedor
                FROM insumos i
                LEFT JOIN proveedores pv ON pv.proveedor_id = i.proveedor_id
                ORDER BY i.nombre
                """
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def _asegurar_tabla_compras_insumos(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS compras_insumos (
                compra_id BIGSERIAL PRIMARY KEY,
                insumo_id BIGINT NOT NULL REFERENCES insumos(insumo_id),
                cantidad NUMERIC(12,3) NOT NULL,
                costo_total NUMERIC(10,2),
                proveedor VARCHAR(120),
                creado_por VARCHAR(80),
                creado_en TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_compras_insumos_insumo_id
                ON compras_insumos (insumo_id)
            """
        )


def _obtener_o_crear_proveedor(cur, nombre_proveedor):
    if not nombre_proveedor:
        return None

    cur.execute(
        """
        SELECT proveedor_id
        FROM proveedores
        WHERE LOWER(nombre) = LOWER(%s)
        LIMIT 1
        """,
        (nombre_proveedor,),
    )
    row = cur.fetchone()
    if row:
        return row["proveedor_id"] if isinstance(row, dict) else row[0]

    cur.execute(
        """
        INSERT INTO proveedores (nombre)
        VALUES (%s)
        RETURNING proveedor_id
        """,
        (nombre_proveedor,),
    )
    created = cur.fetchone()
    return created["proveedor_id"] if isinstance(created, dict) else created[0]


def _asegurar_tablas_inventario_real(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS recetas_producto_insumo (
                receta_id BIGSERIAL PRIMARY KEY,
                producto_id BIGINT NOT NULL REFERENCES productos(producto_id),
                insumo_id BIGINT NOT NULL REFERENCES insumos(insumo_id),
                cantidad_por_unidad NUMERIC(12,3) NOT NULL,
                activo BOOLEAN NOT NULL DEFAULT TRUE,
                creado_en TIMESTAMP NOT NULL DEFAULT NOW(),
                actualizado_en TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT chk_recetas_cantidad_pos CHECK (cantidad_por_unidad > 0)
            )
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_recetas_producto_insumo_activo
                ON recetas_producto_insumo (producto_id, insumo_id)
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS movimientos_inventario (
                movimiento_id BIGSERIAL PRIMARY KEY,
                insumo_id BIGINT NOT NULL REFERENCES insumos(insumo_id),
                tipo VARCHAR(30) NOT NULL,
                cantidad_movimiento NUMERIC(12,3) NOT NULL,
                stock_antes NUMERIC(12,3) NOT NULL,
                stock_despues NUMERIC(12,3) NOT NULL,
                referencia_tipo VARCHAR(30),
                referencia_id BIGINT,
                detalle JSONB NOT NULL DEFAULT '{}'::jsonb,
                actor_username VARCHAR(80),
                actor_rol VARCHAR(30),
                creado_en TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT chk_movimientos_tipo CHECK (tipo IN ('compra', 'consumo_pedido', 'ajuste_entrada', 'ajuste_salida'))
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_movimientos_inventario_insumo
                ON movimientos_inventario (insumo_id, creado_en DESC)
            """
        )


def _registrar_movimiento_inventario_cur(
    cur,
    insumo_id,
    tipo,
    cantidad_movimiento,
    stock_antes,
    stock_despues,
    referencia_tipo=None,
    referencia_id=None,
    detalle=None,
    actor_username=None,
    actor_rol=None,
):
    cur.execute(
        """
        INSERT INTO movimientos_inventario (
            insumo_id,
            tipo,
            cantidad_movimiento,
            stock_antes,
            stock_despues,
            referencia_tipo,
            referencia_id,
            detalle,
            actor_username,
            actor_rol
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
        """,
        (
            insumo_id,
            tipo,
            cantidad_movimiento,
            stock_antes,
            stock_despues,
            referencia_tipo,
            referencia_id,
            _to_json_text(detalle),
            actor_username,
            actor_rol,
        ),
    )


def _descontar_inventario_por_pedido(cur, pedido_id, items, actor_usuario=None, actor_rol=None):
    requeridos = {}
    faltan_recetas = []

    for item in items:
        producto_id = int(item["producto_id"])
        cantidad_pedido = float(item["cantidad"])
        cur.execute(
            """
            SELECT
                r.insumo_id,
                r.cantidad_por_unidad,
                i.nombre AS insumo_nombre,
                i.unidad_medida
            FROM recetas_producto_insumo r
            JOIN insumos i ON i.insumo_id = r.insumo_id
            WHERE r.producto_id = %s AND r.activo = TRUE
            """,
            (producto_id,),
        )
        componentes = cur.fetchall() or []
        if not componentes:
            faltan_recetas.append(str(producto_id))
            continue

        for comp in componentes:
            insumo_id = int(comp["insumo_id"])
            qty = float(comp["cantidad_por_unidad"]) * cantidad_pedido
            if insumo_id not in requeridos:
                requeridos[insumo_id] = {
                    "cantidad": 0.0,
                    "insumo_nombre": comp["insumo_nombre"],
                    "unidad_medida": comp["unidad_medida"],
                }
            requeridos[insumo_id]["cantidad"] += qty

    if faltan_recetas:
        return {"error": f"No hay receta configurada para producto_id: {', '.join(faltan_recetas)}"}

    if not requeridos:
        return {"ok": True, "movimientos": []}

    ids = list(requeridos.keys())
    placeholders = ", ".join(["%s"] * len(ids))
    cur.execute(
        f"""
        SELECT insumo_id, nombre, unidad_medida, stock_actual
        FROM insumos
        WHERE insumo_id IN ({placeholders})
        FOR UPDATE
        """,
        tuple(ids),
    )
    stocks = {int(row["insumo_id"]): row for row in (cur.fetchall() or [])}

    faltantes = []
    for insumo_id, req in requeridos.items():
        row = stocks.get(insumo_id)
        if not row:
            faltantes.append(f"insumo_id={insumo_id} no existe")
            continue
        disponible = float(row["stock_actual"])
        requerido = float(req["cantidad"])
        if disponible < requerido:
            faltantes.append(
                f"{row['nombre']}: disponible={disponible:.3f} {row['unidad_medida']} / requerido={requerido:.3f} {row['unidad_medida']}"
            )

    if faltantes:
        return {"error": "Stock insuficiente para surtir pedido. " + " | ".join(faltantes)}

    movimientos = []
    for insumo_id, req in requeridos.items():
        row = stocks[insumo_id]
        stock_antes = float(row["stock_actual"])
        qty = float(req["cantidad"])
        stock_despues = stock_antes - qty

        cur.execute(
            """
            UPDATE insumos
            SET stock_actual = %s
            WHERE insumo_id = %s
            """,
            (stock_despues, insumo_id),
        )

        _registrar_movimiento_inventario_cur(
            cur,
            insumo_id=insumo_id,
            tipo="consumo_pedido",
            cantidad_movimiento=-qty,
            stock_antes=stock_antes,
            stock_despues=stock_despues,
            referencia_tipo="pedido",
            referencia_id=pedido_id,
            detalle={"pedido_id": pedido_id},
            actor_username=actor_usuario,
            actor_rol=actor_rol,
        )
        movimientos.append(
            {
                "insumo_id": insumo_id,
                "insumo": row["nombre"],
                "consumo": qty,
                "stock_despues": stock_despues,
                "unidad_medida": row["unidad_medida"],
            }
        )

    return {"ok": True, "movimientos": movimientos}


def registrar_compra_insumo(insumo, cantidad, proveedor=None, costo_total=None, creado_por=None, actor_rol="admin"):
    conn = None
    try:
        nombre_insumo = (insumo or "").strip()
        if not nombre_insumo:
            return {"error": "El nombre del insumo es obligatorio."}

        qty = float(cantidad or 0)
        if qty <= 0:
            return {"error": "La cantidad debe ser mayor a 0."}

        proveedor_nombre = (proveedor or "").strip() or None

        conn = get_connection()
        _asegurar_tabla_compras_insumos(conn)
        _asegurar_tablas_inventario_real(conn)
        _asegurar_auditoria_negocio(conn)

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _set_audit_actor(cur, actor_username=creado_por, actor_rol=actor_rol)
            proveedor_id = _obtener_o_crear_proveedor(cur, proveedor_nombre)

            cur.execute(
                """
                SELECT insumo_id, nombre, unidad_medida, stock_actual, stock_minimo, proveedor_id
                FROM insumos
                WHERE LOWER(nombre) = LOWER(%s)
                LIMIT 1
                """,
                (nombre_insumo,),
            )
            insumo_row = cur.fetchone()

            if not insumo_row:
                stock_antes = 0.0
                cur.execute(
                    """
                    INSERT INTO insumos (nombre, unidad_medida, stock_actual, stock_minimo, proveedor_id)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING insumo_id, nombre, unidad_medida, stock_actual, stock_minimo, proveedor_id
                    """,
                    (nombre_insumo, "pieza", qty, 10, proveedor_id),
                )
                insumo_row = cur.fetchone()
            else:
                stock_antes = float(insumo_row["stock_actual"])
                cur.execute(
                    """
                    UPDATE insumos
                    SET
                        stock_actual = stock_actual + %s,
                        proveedor_id = COALESCE(%s, proveedor_id)
                    WHERE insumo_id = %s
                    RETURNING insumo_id, nombre, unidad_medida, stock_actual, stock_minimo, proveedor_id
                    """,
                    (qty, proveedor_id, insumo_row["insumo_id"]),
                )
                insumo_row = cur.fetchone()

            cur.execute(
                """
                INSERT INTO compras_insumos (insumo_id, cantidad, costo_total, proveedor, creado_por)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING compra_id, insumo_id, cantidad, costo_total, proveedor, creado_por, creado_en
                """,
                (
                    insumo_row["insumo_id"],
                    qty,
                    costo_total,
                    proveedor_nombre,
                    creado_por,
                ),
            )
            compra = cur.fetchone()

            _registrar_movimiento_inventario_cur(
                cur,
                insumo_id=insumo_row["insumo_id"],
                tipo="compra",
                cantidad_movimiento=qty,
                stock_antes=stock_antes,
                stock_despues=float(insumo_row["stock_actual"]),
                referencia_tipo="compra_insumo",
                referencia_id=compra["compra_id"],
                detalle={
                    "proveedor": proveedor_nombre,
                    "costo_total": costo_total,
                },
                actor_username=creado_por,
                actor_rol=actor_rol,
            )

            conn.commit()
            return {
                "compra": compra,
                "insumo": insumo_row,
            }
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_compras_insumos(limit=30):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_compras_insumos(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    c.compra_id,
                    c.insumo_id,
                    i.nombre AS insumo,
                    c.cantidad,
                    c.costo_total,
                    c.proveedor,
                    c.creado_por,
                    c.creado_en
                FROM compras_insumos c
                JOIN insumos i ON i.insumo_id = c.insumo_id
                ORDER BY c.creado_en DESC
                LIMIT %s
                """,
                (int(limit),),
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def crear_producto_manual(nombre, variante, precio, activo=True):
    conn = None
    try:
        nom = (nombre or "").strip()
        var = (variante or "").strip()
        pre = float(precio or 0)
        if not nom:
            return {"error": "nombre es obligatorio"}
        if pre <= 0:
            return {"error": "precio debe ser mayor a 0"}

        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT producto_id
                FROM productos
                WHERE LOWER(nombre) = LOWER(%s)
                  AND LOWER(COALESCE(variante, '')) = LOWER(%s)
                LIMIT 1
                """,
                (nom, var),
            )
            existe = cur.fetchone()

            if existe:
                cur.execute(
                    """
                    UPDATE productos
                    SET precio = %s, activo = %s
                    WHERE producto_id = %s
                    RETURNING producto_id, nombre, variante, precio, activo
                    """,
                    (pre, bool(activo), existe["producto_id"]),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO productos (nombre, variante, precio, activo)
                    VALUES (%s, %s, %s, %s)
                    RETURNING producto_id, nombre, variante, precio, activo
                    """,
                    (nom, var, pre, bool(activo)),
                )
            row = cur.fetchone()
            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def crear_insumo_manual(nombre, unidad_medida, stock_minimo=0, stock_inicial=0, proveedor=None, actor_username=None, actor_rol="admin"):
    conn = None
    try:
        nom = (nombre or "").strip()
        unidad = (unidad_medida or "").strip()
        minimo = float(stock_minimo or 0)
        inicial = float(stock_inicial or 0)
        proveedor_nombre = (proveedor or "").strip() or None

        if not nom:
            return {"error": "nombre es obligatorio"}
        if not unidad:
            return {"error": "unidad_medida es obligatoria"}
        if minimo < 0 or inicial < 0:
            return {"error": "stock_minimo y stock_inicial no pueden ser negativos"}

        conn = get_connection()
        _asegurar_tablas_inventario_real(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            proveedor_id = _obtener_o_crear_proveedor(cur, proveedor_nombre)

            cur.execute(
                """
                SELECT insumo_id, stock_actual
                FROM insumos
                WHERE LOWER(nombre) = LOWER(%s)
                LIMIT 1
                """,
                (nom,),
            )
            existe = cur.fetchone()

            if existe:
                cur.execute(
                    """
                    UPDATE insumos
                    SET unidad_medida = %s,
                        stock_minimo = %s,
                        proveedor_id = COALESCE(%s, proveedor_id)
                    WHERE insumo_id = %s
                    RETURNING insumo_id, nombre, unidad_medida, stock_actual, stock_minimo, proveedor_id
                    """,
                    (unidad, minimo, proveedor_id, existe["insumo_id"]),
                )
                row = cur.fetchone()
            else:
                cur.execute(
                    """
                    INSERT INTO insumos (nombre, unidad_medida, stock_actual, stock_minimo, proveedor_id)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING insumo_id, nombre, unidad_medida, stock_actual, stock_minimo, proveedor_id
                    """,
                    (nom, unidad, inicial, minimo, proveedor_id),
                )
                row = cur.fetchone()
                if inicial > 0:
                    _registrar_movimiento_inventario_cur(
                        cur,
                        insumo_id=row["insumo_id"],
                        tipo="ajuste_entrada",
                        cantidad_movimiento=inicial,
                        stock_antes=0,
                        stock_despues=float(row["stock_actual"]),
                        referencia_tipo="alta_insumo",
                        referencia_id=row["insumo_id"],
                        detalle={"motivo": "stock inicial"},
                        actor_username=actor_username,
                        actor_rol=actor_rol,
                    )

            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def guardar_componente_receta(producto_id, insumo_id, cantidad_por_unidad, activo=True):
    conn = None
    try:
        pid = int(producto_id)
        iid = int(insumo_id)
        qty = float(cantidad_por_unidad or 0)
        if qty <= 0:
            return {"error": "cantidad_por_unidad debe ser mayor a 0"}

        conn = get_connection()
        _asegurar_tablas_inventario_real(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT 1 FROM productos WHERE producto_id = %s LIMIT 1", (pid,))
            if not cur.fetchone():
                return {"error": "Producto no encontrado"}

            cur.execute("SELECT 1 FROM insumos WHERE insumo_id = %s LIMIT 1", (iid,))
            if not cur.fetchone():
                return {"error": "Insumo no encontrado"}

            cur.execute(
                """
                INSERT INTO recetas_producto_insumo (producto_id, insumo_id, cantidad_por_unidad, activo)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (producto_id, insumo_id)
                DO UPDATE SET
                    cantidad_por_unidad = EXCLUDED.cantidad_por_unidad,
                    activo = EXCLUDED.activo,
                    actualizado_en = NOW()
                RETURNING receta_id, producto_id, insumo_id, cantidad_por_unidad, activo, actualizado_en
                """,
                (pid, iid, qty, bool(activo)),
            )
            row = cur.fetchone()
            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_recetas_producto(producto_id=None):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tablas_inventario_real(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            params = []
            where_sql = ""
            if producto_id is not None:
                where_sql = "WHERE r.producto_id = %s"
                params.append(int(producto_id))

            cur.execute(
                f"""
                SELECT
                    r.receta_id,
                    r.producto_id,
                    p.nombre AS producto,
                    p.variante,
                    r.insumo_id,
                    i.nombre AS insumo,
                    i.unidad_medida,
                    r.cantidad_por_unidad,
                    r.activo,
                    r.actualizado_en
                FROM recetas_producto_insumo r
                JOIN productos p ON p.producto_id = r.producto_id
                JOIN insumos i ON i.insumo_id = r.insumo_id
                {where_sql}
                ORDER BY p.nombre, p.variante, i.nombre
                """,
                tuple(params),
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def actualizar_componente_receta(receta_id, activo=None, cantidad_por_unidad=None):
    conn = None
    try:
        rid = int(receta_id)
        cambios = []
        params = []

        if activo is not None:
            cambios.append("activo = %s")
            params.append(bool(activo))

        if cantidad_por_unidad is not None:
            qty = float(cantidad_por_unidad)
            if qty <= 0:
                return {"error": "cantidad_por_unidad debe ser mayor a 0"}
            cambios.append("cantidad_por_unidad = %s")
            params.append(qty)

        if not cambios:
            return {"error": "No hay campos para actualizar"}

        conn = get_connection()
        _asegurar_tablas_inventario_real(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            query = f"""
                UPDATE recetas_producto_insumo
                SET {", ".join(cambios)},
                    actualizado_en = NOW()
                WHERE receta_id = %s
                RETURNING receta_id, producto_id, insumo_id, cantidad_por_unidad, activo, actualizado_en
            """
            params.append(rid)
            cur.execute(query, tuple(params))
            row = cur.fetchone()
            if not row:
                return {"error": "Componente de receta no encontrado"}

            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_movimientos_inventario(limit=100, insumo_id=None, tipo=None):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tablas_inventario_real(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            filtros = []
            params = []
            if insumo_id is not None:
                filtros.append("m.insumo_id = %s")
                params.append(int(insumo_id))
            if tipo:
                filtros.append("m.tipo = %s")
                params.append(str(tipo).strip())

            where_sql = ""
            if filtros:
                where_sql = "WHERE " + " AND ".join(filtros)

            params.append(int(limit))
            cur.execute(
                f"""
                SELECT
                    m.movimiento_id,
                    m.insumo_id,
                    i.nombre AS insumo,
                    i.unidad_medida,
                    m.tipo,
                    m.cantidad_movimiento,
                    m.stock_antes,
                    m.stock_despues,
                    m.referencia_tipo,
                    m.referencia_id,
                    m.detalle,
                    m.actor_username,
                    m.actor_rol,
                    m.creado_en
                FROM movimientos_inventario m
                JOIN insumos i ON i.insumo_id = m.insumo_id
                {where_sql}
                ORDER BY m.creado_en DESC
                LIMIT %s
                """,
                tuple(params),
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_resumen_db():
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_auditoria_seguridad(conn)
        _asegurar_tabla_compras_insumos(conn)
        _asegurar_auditoria_negocio(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*)::INT FROM clientes) AS clientes,
                    (SELECT COUNT(*)::INT FROM pedidos) AS pedidos,
                    (SELECT COUNT(*)::INT FROM pedidos WHERE estado IN ('recibido', 'en_preparacion', 'listo', 'en_camino')) AS pedidos_activos,
                    (SELECT COUNT(*)::INT FROM productos WHERE activo = TRUE) AS productos_activos,
                    (SELECT COUNT(*)::INT FROM insumos) AS insumos,
                    (SELECT COUNT(*)::INT FROM campanas) AS campanas,
                    (SELECT COUNT(*)::INT FROM log_notificaciones) AS logs_notificaciones,
                    (SELECT COUNT(*)::INT FROM auditoria_seguridad) AS eventos_seguridad,
                    (SELECT COUNT(*)::INT FROM auditoria_seguridad WHERE creado_en::date = CURRENT_DATE) AS eventos_seguridad_hoy,
                    (SELECT COUNT(*)::INT FROM auditoria_negocio) AS eventos_negocio,
                    (SELECT COUNT(*)::INT FROM auditoria_negocio WHERE creado_en::date = CURRENT_DATE) AS eventos_negocio_hoy,
                    (SELECT COUNT(*)::INT FROM sesiones_bot WHERE expira_en > NOW()) AS sesiones_activas,
                    (SELECT COALESCE(SUM(total), 0)::NUMERIC(10,2) FROM pedidos WHERE creado_en::date = CURRENT_DATE AND estado <> 'cancelado') AS ventas_hoy,
                                        (SELECT COALESCE(SUM(total), 0)::NUMERIC(10,2) FROM pedidos WHERE DATE_TRUNC('month', creado_en) = DATE_TRUNC('month', CURRENT_DATE) AND estado <> 'cancelado') AS ventas_mes,
                                        (
                                                WITH costo_insumo AS (
                                                        SELECT DISTINCT ON (c.insumo_id)
                                                                c.insumo_id,
                                                                COALESCE(c.costo_total / NULLIF(c.cantidad, 0), 0)::NUMERIC(12,4) AS costo_unitario
                                                        FROM compras_insumos c
                                                        WHERE c.costo_total IS NOT NULL
                                                            AND c.cantidad > 0
                                                        ORDER BY c.insumo_id, c.creado_en DESC
                                                )
                                                SELECT COALESCE(SUM(dp.cantidad * dp.precio_unitario), 0)::NUMERIC(12,2)
                                                FROM pedidos p
                                                JOIN detalle_pedido dp ON dp.pedido_id = p.pedido_id
                                                WHERE p.creado_en::date = CURRENT_DATE
                                                    AND p.estado <> 'cancelado'
                                        ) AS ingresos_estimados_hoy,
                                        (
                                                WITH costo_insumo AS (
                                                        SELECT DISTINCT ON (c.insumo_id)
                                                                c.insumo_id,
                                                                COALESCE(c.costo_total / NULLIF(c.cantidad, 0), 0)::NUMERIC(12,4) AS costo_unitario
                                                        FROM compras_insumos c
                                                        WHERE c.costo_total IS NOT NULL
                                                            AND c.cantidad > 0
                                                        ORDER BY c.insumo_id, c.creado_en DESC
                                                )
                                                SELECT COALESCE(SUM(dp.cantidad * r.cantidad_por_unidad * COALESCE(ci.costo_unitario, 0)), 0)::NUMERIC(12,2)
                                                FROM pedidos p
                                                JOIN detalle_pedido dp ON dp.pedido_id = p.pedido_id
                                                LEFT JOIN recetas_producto_insumo r
                                                             ON r.producto_id = dp.producto_id
                                                            AND r.activo = TRUE
                                                LEFT JOIN costo_insumo ci
                                                             ON ci.insumo_id = r.insumo_id
                                                WHERE p.creado_en::date = CURRENT_DATE
                                                    AND p.estado <> 'cancelado'
                                        ) AS costo_estimado_hoy
                """
            )
            row = cur.fetchone() or {}
            ingresos = float(row.get("ingresos_estimados_hoy") or 0)
            costo = float(row.get("costo_estimado_hoy") or 0)
            utilidad = ingresos - costo
            margen_pct = (utilidad / ingresos * 100) if ingresos > 0 else 0
            row["utilidad_estimada_hoy"] = round(utilidad, 2)
            row["margen_estimado_pct_hoy"] = round(margen_pct, 2)
            return row
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def guardar_sesion_bot(whatsapp_id, estado, datos_temp):
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO sesiones_bot (whatsapp_id, estado, datos_temp, actualizado_en, expira_en)
                VALUES (%s, %s, %s::jsonb, NOW(), NOW() + INTERVAL '5 days')
                ON CONFLICT (whatsapp_id)
                DO UPDATE SET
                    estado = EXCLUDED.estado,
                    datos_temp = EXCLUDED.datos_temp,
                    actualizado_en = NOW(),
                    expira_en = NOW() + INTERVAL '5 days'
                RETURNING whatsapp_id, estado, datos_temp, actualizado_en, expira_en
                """,
                (whatsapp_id, estado, _to_json_text(datos_temp)),
            )
            row = cur.fetchone()
            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_sesion_bot(whatsapp_id):
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT whatsapp_id, estado, datos_temp, actualizado_en, expira_en
                FROM sesiones_bot
                WHERE whatsapp_id = %s
                  AND expira_en > NOW()
                LIMIT 1
                """,
                (whatsapp_id,),
            )
            return cur.fetchone()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def limpiar_sesiones_expiradas():
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                DELETE FROM sesiones_bot
                WHERE expira_en <= NOW()
                RETURNING whatsapp_id
                """
            )
            borradas = cur.fetchall()
            conn.commit()
            return {"eliminadas": len(borradas)}
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def crear_campania(nombre, mensaje, segmento="general", creada_por=None):
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO campanas (nombre, mensaje, segmento, creada_por)
                VALUES (%s, %s, %s, %s)
                RETURNING campana_id, nombre, mensaje, segmento, creada_por, creado_en
                """,
                (nombre, mensaje, segmento, creada_por),
            )
            row = cur.fetchone()
            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def obtener_empleados():
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT empleado_id, nombre, apellidos, rol, telefono, activo
                FROM empleados
                ORDER BY rol, nombre
                """
            )
            return cur.fetchall()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def _asegurar_tabla_log_notificaciones(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS log_notificaciones (
                log_id BIGSERIAL PRIMARY KEY,
                pedido_id BIGINT NOT NULL,
                canal VARCHAR(30) NOT NULL,
                destino VARCHAR(30) NOT NULL,
                tipo VARCHAR(30) NOT NULL,
                mensaje TEXT NOT NULL,
                total NUMERIC(10,2),
                direccion TEXT,
                creado_en TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_log_notificaciones_pedido_id
                ON log_notificaciones (pedido_id)
            """
        )


def crear_log_notificacion(payload):
    conn = None
    try:
        conn = get_connection()
        _asegurar_tabla_log_notificaciones(conn)

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO log_notificaciones
                    (pedido_id, canal, destino, tipo, mensaje, total, direccion)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING log_id, pedido_id, canal, destino, tipo, mensaje, total, direccion, creado_en
                """,
                (
                    int(payload.get("pedido_id")),
                    payload.get("canal"),
                    payload.get("destino"),
                    payload.get("tipo"),
                    payload.get("mensaje"),
                    payload.get("total"),
                    payload.get("direccion"),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return row
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()
