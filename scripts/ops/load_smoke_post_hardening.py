import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from bot_empanadas.app import app


ENDPOINTS = [
    ("GET", "/api/pedidos?limit=20"),
    ("GET", "/api/clientes/top20"),
    ("GET", "/api/ventas/mensuales"),
    ("GET", "/api/admin/reporte-ventas-profesional?periodo=mes&limit=100"),
    ("GET", "/api/repartidor/pedidos"),
]

CONCURRENCY = 12
ROUNDS = 10


def percentile(values, p):
    if not values:
        return 0.0
    arr = sorted(values)
    k = (len(arr) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(arr) - 1)
    if f == c:
        return float(arr[f])
    return float(arr[f] + (arr[c] - arr[f]) * (k - f))


def call_endpoint(method, path):
    with app.test_client() as client:
        # Admin session for admin routes.
        with client.session_transaction() as sess:
            sess["user"] = {
                "usuario_id": 1,
                "username": "admin_load",
                "rol": "admin",
                "nombre_mostrar": "Admin Load",
                "area_entrega": None,
            }

        if path == "/api/repartidor/pedidos":
            with client.session_transaction() as sess:
                sess["user"] = {
                    "usuario_id": 2,
                    "username": "repartidor_load",
                    "rol": "repartidor",
                    "nombre_mostrar": "Repartidor Load",
                    "area_entrega": "juarez-centro",
                }

        t0 = time.perf_counter()
        resp = client.open(path, method=method)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return method, path, resp.status_code, elapsed_ms


def main() -> int:
    app.testing = True

    tasks = []
    for _ in range(ROUNDS):
        for method, path in ENDPOINTS:
            tasks.append((method, path))

    latencies = []
    errors = []

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        future_map = {ex.submit(call_endpoint, method, path): (method, path) for method, path in tasks}
        for fut in as_completed(future_map):
            method, path = future_map[fut]
            try:
                _m, _p, status, elapsed_ms = fut.result()
                latencies.append(elapsed_ms)
                if status != 200:
                    errors.append((method, path, status))
            except Exception as exc:
                errors.append((method, path, f"EXC:{exc}"))

    total_ms = (time.perf_counter() - started) * 1000.0

    if latencies:
        p50 = percentile(latencies, 50)
        p95 = percentile(latencies, 95)
        p99 = percentile(latencies, 99)
        avg = statistics.mean(latencies)
        print(f"LOAD_SUMMARY total_requests={len(tasks)} concurrency={CONCURRENCY} rounds={ROUNDS}")
        print(f"LATENCY_MS avg={avg:.2f} p50={p50:.2f} p95={p95:.2f} p99={p99:.2f} total_elapsed={total_ms:.2f}")
    else:
        print("LOAD_SUMMARY no_latencies")

    if errors:
        print(f"LOAD_ERRORS count={len(errors)}")
        for item in errors[:20]:
            print("ERROR", item)
        return 1

    print("LOAD_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
