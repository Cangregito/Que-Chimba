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

    repartidores = [
        {
            "username": "repartidor_centro",
            "password": "repartidor_centro",
            "nombre_mostrar": "Repartidor Zona Centro",
            "telefono": "6560002001",
            "area_entrega": "juarez-centro",
        },
        {
            "username": "repartidor_norte",
            "password": "repartidor_norte",
            "nombre_mostrar": "Repartidor Zona Norte",
            "telefono": "6560002002",
            "area_entrega": "juarez-norte",
        },
        {
            "username": "repartidor_sur",
            "password": "repartidor_sur",
            "nombre_mostrar": "Repartidor Zona Sur",
            "telefono": "6560002003",
            "area_entrega": "juarez-sur",
        },
        {
            "username": "repartidor_oriente",
            "password": "repartidor_oriente",
            "nombre_mostrar": "Repartidor Zona Oriente",
            "telefono": "6560002004",
            "area_entrega": "juarez-oriente",
        },
        {
            "username": "repartidor_poniente",
            "password": "repartidor_poniente",
            "nombre_mostrar": "Repartidor Zona Poniente",
            "telefono": "6560002005",
            "area_entrega": "juarez-poniente",
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
            for r in repartidores:
                password_hash = generate_password_hash(r["password"])
                cur.execute(
                    """
                    INSERT INTO usuarios_sistema
                        (username, password_hash, rol, nombre_mostrar, telefono, area_entrega, activo)
                    VALUES (%s, %s, 'repartidor', %s, %s, %s, TRUE)
                    ON CONFLICT (username)
                    DO UPDATE SET
                        password_hash = EXCLUDED.password_hash,
                        rol = EXCLUDED.rol,
                        nombre_mostrar = EXCLUDED.nombre_mostrar,
                        telefono = EXCLUDED.telefono,
                        area_entrega = EXCLUDED.area_entrega,
                        activo = TRUE,
                        actualizado_en = NOW()
                    RETURNING usuario_id, username, rol, area_entrega, activo
                    """,
                    (
                        r["username"],
                        password_hash,
                        r["nombre_mostrar"],
                        r["telefono"],
                        r["area_entrega"],
                    ),
                )
                row = cur.fetchone()
                print(
                    f"OK user={row.get('username')} rol={row.get('rol')} area={row.get('area_entrega')} activo={row.get('activo')}"
                )

    print("SEED_REPARTIDORES_ZONAS_OK")


if __name__ == "__main__":
    main()
