def client_ip(request):
    forwarded = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    return (request.remote_addr or "").strip() or None


def is_valid_origin(request):
    expected = request.host_url.rstrip("/").lower()
    origin = (request.headers.get("Origin") or "").strip().lower()
    referer = (request.headers.get("Referer") or "").strip().lower()

    if origin:
        return origin.startswith(expected)
    if referer:
        return referer.startswith(expected)
    return True
