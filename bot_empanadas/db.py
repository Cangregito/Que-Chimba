import json
import os
from datetime import date, datetime
from decimal import Decimal

import psycopg2
from psycopg2.extras import RealDictCursor


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


def obtener_productos():
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
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


def crear_pedido(cliente_id, items, direccion_id, metodo_pago):
    conn = None
    try:
        if not items:
            return {"error": "El pedido debe incluir al menos un item."}

        total = sum(float(item.get("cantidad", 0)) * float(item.get("precio_unitario", 0)) for item in items)

        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO pedidos (cliente_id, direccion_id, metodo_pago, total, estado)
                VALUES (%s, %s, %s, %s, 'recibido')
                RETURNING pedido_id, cliente_id, direccion_id, metodo_pago, total, estado, creado_en
                """,
                (cliente_id, direccion_id, metodo_pago, total),
            )
            pedido = cur.fetchone()

            for item in items:
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

            conn.commit()
            pedido["items"] = items
            return pedido
    except Exception as exc:
        if conn:
            conn.rollback()
        return {"error": str(exc)}
    finally:
        if conn:
            conn.close()


def actualizar_estado_pedido(pedido_id, nuevo_estado):
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE pedidos
                SET estado = %s
                WHERE pedido_id = %s
                RETURNING pedido_id, estado, creado_en
                """,
                (nuevo_estado, pedido_id),
            )
            actualizado = cur.fetchone()
            conn.commit()
            if not actualizado:
                return {"error": "Pedido no encontrado."}
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
                c.apellidos
            FROM pedidos p
            JOIN clientes c ON c.cliente_id = p.cliente_id
            {where_sql}
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
