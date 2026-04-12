import logging
import os
from datetime import datetime
from functools import wraps

try:
    from logging_handlers import PostgreSQLHandler, RateLimitFilter
except Exception:
    from bot_empanadas.logging_handlers import PostgreSQLHandler, RateLimitFilter


LOG_DIR = os.getenv("LOG_DIR", os.path.join(os.path.dirname(__file__), "..", "logs", "app"))
LOG_LEVEL = (os.getenv("LOG_LEVEL", "INFO") or "INFO").upper()


os.makedirs(LOG_DIR, exist_ok=True)


def configurar_logger(nombre_componente: str) -> logging.Logger:
    logger = logging.getLogger(str(nombre_componente or "app"))
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_name = f"{nombre_componente}_{datetime.now().strftime('%Y-%m')}.log"
    file_path = os.path.join(LOG_DIR, file_name)
    file_handler = logging.FileHandler(file_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    pg_handler = PostgreSQLHandler(nombre_componente)
    pg_handler.setLevel(logging.WARNING)
    pg_handler.setFormatter(formatter)

    limiter = RateLimitFilter(min_interval_seconds=0.1)
    file_handler.addFilter(limiter)
    stream_handler.addFilter(limiter)
    pg_handler.addFilter(limiter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    logger.addHandler(pg_handler)
    logger.propagate = False
    return logger


def medir_tiempo(logger: logging.Logger, nombre_operacion: str):
    def decorator(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            start = datetime.now()
            try:
                result = func(*args, **kwargs)
                duration_ms = int((datetime.now() - start).total_seconds() * 1000)
                if duration_ms >= 3000:
                    logger.warning(
                        "%s tardó %sms",
                        nombre_operacion,
                        duration_ms,
                        extra={"duracion_ms": duration_ms},
                    )
                return result
            except Exception:
                duration_ms = int((datetime.now() - start).total_seconds() * 1000)
                logger.exception(
                    "Error en %s",
                    nombre_operacion,
                    extra={"duracion_ms": duration_ms},
                )
                raise

        return wrapped

    return decorator
