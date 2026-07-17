from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import settings, log_startup_config
from app.log_setup import setup_logging

setup_logging()
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
from app.services.trading_engine import start_trading_engine_task, stop_trading_engine_task

LOG = logging.getLogger(__name__)


def ensure_schema():
    """Create tables if missing (useful when init SQL was skipped)."""
    Base.metadata.create_all(bind=engine)
    _ensure_trade_positions_columns()


def _ensure_trade_positions_columns():
    """Lightweight migration: add columns introduced after the table was created."""
    with engine.connect() as conn:
        if engine.dialect.name == "sqlite":
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(trade_positions)"))}
            if cols and "underlying_at_exit" not in cols:
                conn.execute(text("ALTER TABLE trade_positions ADD COLUMN underlying_at_exit FLOAT"))
                conn.commit()
            return
        try:
            conn.execute(text("ALTER TABLE trade_positions ADD COLUMN underlying_at_exit FLOAT NULL"))
            conn.commit()
        except Exception:  # noqa: BLE001 — column already exists
            pass


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
    start_trading_engine_task()
    LOG.info("Backend startup complete")
    yield
    await stop_trading_engine_task()
    stop_angel_auto_login_scheduler()


app = FastAPI(title="Indian Algo API", lifespan=lifespan)

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
