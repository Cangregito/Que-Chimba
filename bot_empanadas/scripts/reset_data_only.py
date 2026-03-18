import os

import psycopg2
from psycopg2 import sql


def main() -> None:
    host = os.getenv("DB_HOST", "localhost")
    port = int(os.getenv("DB_PORT", "5432"))
    dbname = os.getenv("DB_NAME", "que_chimba")
    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD")

    conn_kwargs = {"host": host, "port": port, "dbname": dbname, "user": user}
    if password:
        conn_kwargs["password"] = password

    with psycopg2.connect(**conn_kwargs) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
            )
            tables = [r[0] for r in cur.fetchall()]

            if not tables:
                print("No hay tablas en el esquema public.")
                return

            table_list = sql.SQL(", ").join(sql.Identifier("public", t) for t in tables)
            stmt = sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(table_list)
            cur.execute(stmt)

            print(f"LIMPIEZA_OK tablas={len(tables)}")
            for name in tables:
                print(name)


if __name__ == "__main__":
    main()
