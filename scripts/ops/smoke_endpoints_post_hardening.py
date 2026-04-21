import json

from bot_empanadas.app import app


def hit(client, method, path, expected=(200,)):
    resp = client.open(path, method=method)
    ok = resp.status_code in expected
    print(f"{method} {path} -> {resp.status_code} {'OK' if ok else 'FAIL'}")
    return ok


def main() -> int:
    app.testing = True
    failures = 0

    with app.test_client() as client:
        # Public smoke
        if not hit(client, "GET", "/health", expected=(200,)):
            failures += 1
        if not hit(client, "GET", "/api/productos", expected=(200,)):
            failures += 1

        # Admin smoke
        with client.session_transaction() as sess:
            sess["user"] = {
                "usuario_id": 1,
                "username": "admin_smoke",
                "rol": "admin",
                "nombre_mostrar": "Admin Smoke",
                "area_entrega": None,
            }

        admin_paths = [
            "/api/pedidos?limit=5",
            "/api/clientes/top20",
            "/api/ventas/mensuales",
            "/api/inventario?limit=5",
            "/api/admin/reporte-ventas-profesional?periodo=dia&limit=10",
        ]
        for path in admin_paths:
            if not hit(client, "GET", path, expected=(200,)):
                failures += 1

        # Repartidor smoke
        with client.session_transaction() as sess:
            sess["user"] = {
                "usuario_id": 2,
                "username": "repartidor_smoke",
                "rol": "repartidor",
                "nombre_mostrar": "Repartidor Smoke",
                "area_entrega": "juarez-centro",
            }

        if not hit(client, "GET", "/api/repartidor/pedidos", expected=(200,)):
            failures += 1

    print("SMOKE_RESULT", json.dumps({"failures": failures}))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
