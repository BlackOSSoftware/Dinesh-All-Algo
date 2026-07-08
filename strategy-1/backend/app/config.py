import logging
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ directory (parent of app/)
BACKEND_ROOT = Path(__file__).resolve().parent.parent

LOG = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv

    load_dotenv(BACKEND_ROOT / ".env", override=True)
except ImportError:
    pass


def default_database_url() -> str:
    """SQLite file under backend/instance/ — works without Docker/MySQL."""
    inst = BACKEND_ROOT / "instance"
    inst.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(inst / 'app.db').as_posix()}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Omit DATABASE_URL in .env to use SQLite default. Set mysql+pymysql://... for MySQL.
    database_url: str = Field(default_factory=default_database_url)
    jwt_secret: str = "dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Angel One SmartAPI — Live Market Quote (POST .../market/v1/quote/)
    angel_api_key: str = ""  # X-PrivateKey (publisher API key)
    angel_jwt_token: str = ""  # Authorization: Bearer <jwt> from Angel login / token
    # From login response; renews JWT via generateTokens without TOTP (see angel_jwt_refresh).
    angel_refresh_token: str = ""
    angel_quote_mode: str = "LTP"  # LTP | OHLC | FULL
    # JSON object: exchange -> list of symbol tokens, e.g. {"NSE":["3045"]} for SBIN-EQ
    angel_exchange_tokens: str = ""
    angel_source_id: str = "WEB"
    angel_client_local_ip: str = "127.0.0.1"
    angel_client_public_ip: str = "127.0.0.1"
    angel_mac_address: str = "00:00:00:00:00:00"
    angel_user_type: str = "USER"
    angel_request_timeout_sec: float = 15.0
    angel_debug: bool = False  # if true, /angel/live-quote includes raw Angel JSON

    # BFO Sensex options for LIVE orders — JSON list:
    # [{"strike":75800,"side":"PE","token":"...","tradingsymbol":"...","lotsize":20}, ...]
    angel_bfo_instruments_json: str = ""
    angel_option_exchange: str = "BFO"
    angel_option_product_type: str = "CARRYFORWARD"
    default_sensex_option_lot_size: int = 20


settings = Settings()


def log_startup_config():
    """Log configuration status on startup (never print secrets)."""
    env_file = BACKEND_ROOT / ".env"
    env_exists = env_file.is_file()

    LOG.info("=" * 60)
    LOG.info("Backend Startup Configuration")
    LOG.info("=" * 60)
    LOG.info("Environment file path: %s", env_file)
    LOG.info("Environment file exists: %s", env_exists)
    LOG.info(
        "Database URL: %s",
        settings.database_url[:50] + "..."
        if len(settings.database_url) > 50
        else settings.database_url,
    )
    LOG.info("JWT algorithm: %s", settings.jwt_algorithm)
    LOG.info("Access token expiry: %d minutes", settings.access_token_expire_minutes)
    LOG.info("CORS origins: %s", settings.cors_origins)
    LOG.info(
        "Angel One: API key set=%s, JWT set=%s, refresh set=%s, exchange_tokens set=%s",
        bool(settings.angel_api_key),
        bool(settings.angel_jwt_token),
        bool((settings.angel_refresh_token or "").strip()),
        bool((settings.angel_exchange_tokens or "").strip()),
    )
    LOG.info("=" * 60)
