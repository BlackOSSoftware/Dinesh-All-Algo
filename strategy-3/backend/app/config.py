import logging
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent

LOG = logging.getLogger(__name__)


def default_database_url() -> str:
    inst = BACKEND_ROOT / "instance"
    inst.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(inst / 'app.db').as_posix()}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(default_factory=default_database_url)
    jwt_secret: str = "dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7
    cors_origins: str = "http://localhost:3002,http://127.0.0.1:3002"

    angel_api_key: str = ""
    angel_jwt_token: str = ""
    angel_refresh_token: str = ""
    angel_quote_mode: str = "LTP"
    angel_exchange_tokens: str = ""
    angel_source_id: str = "WEB"
    angel_client_local_ip: str = "127.0.0.1"
    angel_client_public_ip: str = "127.0.0.1"
    angel_mac_address: str = "00:00:00:00:00:00"
    angel_user_type: str = "USER"
    angel_request_timeout_sec: float = 15.0
    angel_debug: bool = False

    angel_bfo_instruments_json: str = ""
    angel_option_exchange: str = "BFO"
    angel_option_product_type: str = "INTRADAY"
    default_sensex_option_lot_size: int = 20

    # StocksRin historical API (Strategy 3 backtest)
    stocksrin_base_url: str = "https://apih.stocksrin.com"
    stocksrin_auth_base_url: str = "https://api.stocksrin.com"
    stocksrin_session_file: str = ""
    stocksrin_app_authorization: str = ""
    stocksrin_email: str = ""
    stocksrin_password_b64: str = ""
    stocksrin_device_id: str = "device_strategy3"
    stocksrin_device_type: str = "laptop"
    stocksrin_hmac_key: str = "stocksrinkey"
    stocksrin_exchange: str = "NSE"
    stocksrin_index_exchange: str = "BSE"
    stocksrin_index_symbol: str = "SENSEX"
    stocksrin_resolution: int = 10
    stocksrin_request_timeout_sec: float = 30.0
    # Legacy migration only
    stocksrin_authorization: str = ""
    stocksrin_request_token: str = ""
    stocksrin_request_nonce: str = ""
    stocksrin_user: str = ""


settings = Settings()


def log_startup_config():
    env_file = BACKEND_ROOT / ".env"
    LOG.info(
        "Strategy 3 API — env=%s db=%s angel_key=%s jwt=%s",
        env_file.is_file(),
        settings.database_url[:40],
        bool(settings.angel_api_key.strip()),
        bool(settings.angel_jwt_token.strip()),
    )
