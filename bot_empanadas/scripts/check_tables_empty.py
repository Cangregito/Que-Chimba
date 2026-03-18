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
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
            )
            tables = [r[0] for r in cur.fetchall()]
            non_empty = []

            for table_name in tables:
                query = sql.SQL("SELECT COUNT(*) FROM {}")
                query = query.format(sql.Identifier("public", table_name))
                cur.execute(query)
                count = int(cur.fetchone()[0])
                if count != 0:
                    non_empty.append((table_name, count))

    print(f"TABLAS_TOTAL={len(tables)}")
    if non_empty:
        print("TABLAS_CON_DATOS=SI")
        for name, count in non_empty:
            print(f"{name}:{count}")
    else:
        print("TABLAS_CON_DATOS=NO")


if __name__ == "__main__":
    main()
