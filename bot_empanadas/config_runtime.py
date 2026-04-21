import os

TRUE_VALUES = {"1", "true", "yes", "on"}

DEFAULT_BAILEYS_BRIDGE_URL = "http://localhost:3001"
DEFAULT_PUBLIC_BASE_URL = "http://localhost:5000"
DEFAULT_N8N_WEBHOOK_URL = ""
DEFAULT_WHATSAPP_PUBLIC_NUMBER = "526567751166"
DEFAULT_WHATSAPP_PUBLIC_MESSAGE = "Hola La Malparida Empanada, quiero pedir unas empanadas"


def env_str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in TRUE_VALUES


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def is_production() -> bool:
    app_env = (env_str("APP_ENV", "") or env_str("ENV", "development")).strip().lower()
    return app_env in {"prod", "production"}
