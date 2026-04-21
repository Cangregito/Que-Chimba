import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, urlopen

from werkzeug.serving import make_server

from bot_empanadas.app import app


HOST = "127.0.0.1"
PORT = 5077
CONCURRENCY = 16
ROUNDS = 12
ENDPOINTS = [
    "/health",
    "/api/productos",
    "/api/stats/publicas",
]


class ServerThread(threading.Thread):
    def __init__(self, flask_app):
        super().__init__(daemon=True)
        self.srv = make_server(HOST, PORT, flask_app)

    def run(self):
        self.srv.serve_forever()

    def shutdown(self):
        self.srv.shutdown()


def percentile(values, p):
    arr = sorted(values)
    if not arr:
        return 0.0
    k = (len(arr) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(arr) - 1)
    if f == c:
        return float(arr[f])
    return float(arr[f] + (arr[c] - arr[f]) * (k - f))


def call(path):
    url = f"http://{HOST}:{PORT}{path}"
    req = Request(url, method="GET")
    t0 = time.perf_counter()
    with urlopen(req, timeout=10) as resp:
        status = resp.status
        _ = resp.read(256)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return path, status, elapsed_ms


def main() -> int:
    app.testing = False
    server = ServerThread(app)
    server.start()
    time.sleep(0.35)

    tasks = []
    for _ in range(ROUNDS):
        tasks.extend(ENDPOINTS)

    lat = []
    errs = []
    start = time.perf_counter()

    try:
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
            futures = [ex.submit(call, p) for p in tasks]
            for fut in as_completed(futures):
                try:
                    path, status, elapsed = fut.result()
                    lat.append(elapsed)
                    if status != 200:
                        errs.append((path, status))
                except Exception as exc:
                    errs.append(("EXC", str(exc)))
    finally:
        server.shutdown()

    total_ms = (time.perf_counter() - start) * 1000.0

    if lat:
        avg = sum(lat) / len(lat)
        print(f"PUBLIC_LOAD total_requests={len(tasks)} concurrency={CONCURRENCY} rounds={ROUNDS}")
        print(
            "PUBLIC_LATENCY_MS "
            f"avg={avg:.2f} p50={percentile(lat,50):.2f} p95={percentile(lat,95):.2f} p99={percentile(lat,99):.2f} total_elapsed={total_ms:.2f}"
        )

    if errs:
        print("PUBLIC_LOAD_ERRORS", json.dumps(errs[:20]))
        return 1

    print("PUBLIC_LOAD_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
