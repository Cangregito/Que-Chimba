import os

import psycopg2


def db_config() -> dict:
    cfg = {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "5432")),
        "dbname": os.getenv("DB_NAME", "que_chimba"),
        "user": os.getenv("DB_USER", "postgres"),
    }
    pwd = os.getenv("DB_PASSWORD")
    if pwd:
        cfg["password"] = pwd
    return cfg


def main() -> int:
    conn = psycopg2.connect(**db_config())
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT tablename, indexname
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND tablename IN ('pagos', 'asignaciones_reparto', 'detalle_pedido', 'pedidos', 'sesiones_bot')
                ORDER BY tablename, indexname
                """
            )
            indexes = cur.fetchall()

            cur.execute(
                """
                SELECT conname, convalidated
                FROM pg_constraint
                WHERE conname IN (
                    'chk_pedidos_total_nonneg',
                    'chk_detalle_pedido_cantidad_pos',
                    'chk_detalle_pedido_precio_nonneg',
                    'chk_pagos_monto_nonneg'
                )
                ORDER BY conname
                """
            )
            constraints = cur.fetchall()

            cur.execute(
                """
                SELECT relname, relrowsecurity, relforcerowsecurity
                FROM pg_class
                WHERE relname IN ('pedidos', 'pagos', 'direcciones_cliente')
                ORDER BY relname
                """
            )
            rls = cur.fetchall()

            cur.execute(
                """
                SELECT tablename, policyname
                FROM pg_policies
                WHERE schemaname = 'public'
                  AND tablename IN ('pedidos', 'pagos', 'direcciones_cliente')
                ORDER BY tablename, policyname
                """
            )
            policies = cur.fetchall()

        print("INDEXES:")
        for row in indexes:
            print(row)

        print("\nCONSTRAINTS:")
        for row in constraints:
            print(row)

        print("\nRLS:")
        for row in rls:
            print(row)

        print("\nPOLICIES:")
        for row in policies:
            print(row)
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
