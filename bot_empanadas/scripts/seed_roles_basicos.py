import os

import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.security import generate_password_hash


def _env(name: str, default: str) -> str:
    return (os.getenv(name, default) or default).strip()


def main() -> None:
    db_host = _env("DB_HOST", "localhost")
    db_port = int(_env("DB_PORT", "5432"))
    db_name = _env("DB_NAME", "que_chimba")
    db_user = _env("DB_USER", "postgres")
    db_password = os.getenv("DB_PASSWORD", "")

    users = [
        {
            "username": _env("ADMIN_DEFAULT_USERNAME", "admin"),
            "password": _env("ADMIN_DEFAULT_PASSWORD", "AdminQC2026!"),
            "rol": "admin",
            "nombre_mostrar": _env("ADMIN_DEFAULT_NOMBRE", "Administrador General"),
            "telefono": _env("ADMIN_DEFAULT_TELEFONO", "6560001001"),
            "area_entrega": None,
        },
        {
            "username": _env("COCINA_DEFAULT_USERNAME", "cocina"),
            "password": _env("COCINA_DEFAULT_PASSWORD", "CocinaQC2026!"),
            "rol": "cocina",
            "nombre_mostrar": _env("COCINA_DEFAULT_NOMBRE", "Jefe de Cocina"),
            "telefono": _env("COCINA_DEFAULT_TELEFONO", "6560001002"),
            "area_entrega": None,
        },
        {
            "username": _env("REPARTIDOR_DEFAULT_USERNAME", "repartidor"),
            "password": _env("REPARTIDOR_DEFAULT_PASSWORD", "RepartoQC2026!"),
            "rol": "repartidor",
            "nombre_mostrar": _env("REPARTIDOR_DEFAULT_NOMBRE", "Repartidor Zona Centro"),
            "telefono": _env("REPARTIDOR_DEFAULT_TELEFONO", "6560001003"),
            "area_entrega": _env("REPARTIDOR_DEFAULT_AREA", "juarez-centro"),
        },
    ]

    conn_kwargs = {
        "host": db_host,
        "port": db_port,
        "dbname": db_name,
        "user": db_user,
    }
    if db_password:
        conn_kwargs["password"] = db_password

    with psycopg2.connect(**conn_kwargs) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            for u in users:
                password_hash = generate_password_hash(u["password"])
                cur.execute(
                    """
                    INSERT INTO usuarios_sistema
                        (username, password_hash, rol, nombre_mostrar, telefono, area_entrega, activo)
                    VALUES (%s, %s, %s, %s, %s, %s, TRUE)
                    ON CONFLICT (username)
                    DO UPDATE SET
                        password_hash = EXCLUDED.password_hash,
                        rol = EXCLUDED.rol,
                        nombre_mostrar = EXCLUDED.nombre_mostrar,
                        telefono = EXCLUDED.telefono,
                        area_entrega = EXCLUDED.area_entrega,
                        activo = TRUE,
                        actualizado_en = NOW()
                    RETURNING usuario_id, username, rol, nombre_mostrar, telefono, area_entrega, activo
                    """,
                    (
                        u["username"],
                        password_hash,
                        u["rol"],
                        u["nombre_mostrar"],
                        u["telefono"],
                        u["area_entrega"],
                    ),
                )
                row = cur.fetchone()
                area = row.get("area_entrega") or "N/A"
                print(
                    f"OK user={row.get('username')} rol={row.get('rol')} area={area} activo={row.get('activo')}"
                )

    print("SEED_ROLES_OK")


if __name__ == "__main__":
    main()
