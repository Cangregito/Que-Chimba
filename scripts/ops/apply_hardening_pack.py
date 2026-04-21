import os
from pathlib import Path

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
    root = Path(__file__).resolve().parents[2]
    pack = root / "bot_empanadas" / "sql" / "migrations_hardening_2026_04"

    scripts = [
        "01_roles_app_minimo_privilegio.sql",
        "02_indices_online_concurrently.sql",
        "03_constraints_not_valid_y_validate.sql",
        "04_auditoria_triggers_catalogo.sql",
        "05_rls_fase1_policies.sql",
    ]

    cfg = db_config()
    print(f"Conectando a DB {cfg['dbname']} en {cfg['host']}:{cfg['port']} con usuario {cfg['user']}...")

    conn = psycopg2.connect(**cfg)
    conn.autocommit = True

    try:
        with conn.cursor() as cur:
            for name in scripts:
                path = pack / name
                if not path.exists():
                    raise FileNotFoundError(f"No existe el script: {path}")

                sql = path.read_text(encoding="utf-8")
                print(f"[APLICANDO] {name}")
                if name == "02_indices_online_concurrently.sql":
                    # CREATE INDEX CONCURRENTLY must run as standalone statements.
                    statements = [chunk.strip() for chunk in sql.split(";") if chunk.strip()]
                    for stmt in statements:
                        cur.execute(stmt + ";")
                else:
                    cur.execute(sql)
                print(f"[OK] {name}")

            print("Pack de hardening aplicado correctamente.")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
