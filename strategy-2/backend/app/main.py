from contextlib import asynccontextmanager
import logging
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import settings, log_startup_config
from app.database import SessionLocal, engine
from app.models import Base, StrategySettings, TradePosition, TradingLog, User
from app.routers import angel as angel_router
from app.routers import auth as auth_router
from app.routers import trading as trading_router
from app.routers import users as users_router
from app.auth_utils import hash_password
from app.services.angel_auto_login_scheduler import (
    start_angel_auto_login_scheduler,
    stop_angel_auto_login_scheduler,
    verify_angel_login_paths,
)
from app.services.grid_trading_engine import start_grid_engine_task, stop_grid_engine_task

LOG = logging.getLogger(__name__)


def ensure_schema():
    """Create tables if missing (useful when init SQL was skipped)."""
    Base.metadata.create_all(bind=engine)


def seed_admin_if_missing():
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        password_hash = hash_password("admin")
        if admin:
            admin.password_hash = password_hash
            admin.role = "admin"
        else:
            db.add(
                User(
                    username="admin",
                    password_hash=password_hash,
                    role="admin",
                )
            )
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_schema()
    seed_admin_if_missing()
    log_startup_config()

    ok_paths, path_errs = verify_angel_login_paths()
    if ok_paths:
        LOG.info("[Scheduler] Angel login script and venv Python verified.")
    else:
        for msg in path_errs:
            LOG.error("[Scheduler] Startup verification failed: %s", msg)

    start_angel_auto_login_scheduler()

    def _startup_mcx_quote_check() -> None:
        try:
            from app.services.mcx_quotes import ensure_angel_session_for_quotes, fetch_all_mcx_quotes

            quotes = fetch_all_mcx_quotes()
            live_count = sum(1 for q in quotes if q.source == "live" and q.price > 0)
            if quotes and live_count == 0 and any(q.error and "token" in (q.error or "").lower() for q in quotes):
                if ensure_angel_session_for_quotes(reason="startup_token_check"):
                    quotes = fetch_all_mcx_quotes()
                    live_count = sum(1 for q in quotes if q.source == "live" and q.price > 0)
            LOG.info("MCX startup quotes: %d instruments, %d live", len(quotes), live_count)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("MCX startup quote check failed: %s", exc)

        try:
            from app.services.mcx_instruments import load_mcx_instruments

            for key, inst in load_mcx_instruments().items():
                LOG.info(
                    "MCX %s token=%s symbol=%s configured=%s",
                    key,
                    inst.token or "-",
                    inst.tradingsymbol or "-",
                    inst.configured,
                )
        except Exception as exc:  # noqa: BLE001
            LOG.warning("MCX instrument resolve failed at startup: %s", exc)

    threading.Thread(target=_startup_mcx_quote_check, name="mcx-startup-check", daemon=True).start()

    start_grid_engine_task()
    LOG.info("Strategy 2 backend startup complete")
    yield
    await stop_grid_engine_task()
    stop_angel_auto_login_scheduler()


app = FastAPI(title="Strategy 2 API", lifespan=lifespan)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(users_router.router)
app.include_router(trading_router.router)
app.include_router(angel_router.router)


@app.get("/health")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "degraded", "database": "error", "detail": str(exc)}
