import logging
import time


class PostgreSQLHandler(logging.Handler):
    """Persiste logs WARNING+ en logs_sistema sin romper el flujo principal."""

    def __init__(self, componente: str):
        super().__init__()
        self.componente = str(componente or "app")

    def emit(self, record: logging.LogRecord):
        try:
            try:
                import db  # type: ignore
            except Exception:
                from bot_empanadas import db  # type: ignore

            db.insertar_log_sistema(
                nivel=str(record.levelname or "INFO"),
                componente=self.componente,
                funcion=str(record.funcName or ""),
                mensaje=self.format(record)[:500],
                detalle=self.formatException(record.exc_info) if record.exc_info else None,
                whatsapp_id=getattr(record, "whatsapp_id", None),
                pedido_id=getattr(record, "pedido_id", None),
                ip_origen=getattr(record, "ip_origen", None),
                duracion_ms=getattr(record, "duracion_ms", None),
            )
        except Exception:
            # Un fallo de log no debe afectar el request principal.
            pass


class RateLimitFilter(logging.Filter):
    """Evita spam de logs repetidos en ventanas de tiempo cortas."""

    def __init__(self, min_interval_seconds: float = 0.1):
        super().__init__()
        self.min_interval_seconds = float(min_interval_seconds)
        self._last_seen = {}

    def filter(self, record: logging.LogRecord) -> bool:
        message = str(record.getMessage() or "")
        key = (record.name, record.levelname, message)
        now = time.time()
        last = self._last_seen.get(key)
        if last is not None and (now - last) < self.min_interval_seconds:
            return False
        self._last_seen[key] = now
        return True
