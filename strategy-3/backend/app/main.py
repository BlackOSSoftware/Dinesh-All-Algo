from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import settings, log_startup_config
from app.database import SessionLocal, engine
from app.models import Base, User
from app.routers import auth as auth_router
from app.routers import users as users_router
from app.routers import trading as trading_router
from app.routers import angel as angel_router
from app.auth_utils import hash_password

LOG = logging.getLogger(__name__)


def ensure_schema():
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


def _start_angel_scheduler():
    try:
        from app.services.angel_auto_login_scheduler import start_angel_auto_login_scheduler

        start_angel_auto_login_scheduler()
    except Exception as exc:  # noqa: BLE001
        LOG.warning("Angel scheduler not started: %s", exc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_schema()
    seed_admin_if_missing()
    log_startup_config()
    _start_angel_scheduler()
    from app.services.strategy3_trading_engine import (
        start_strategy3_engine_task,
        stop_strategy3_engine_task,
    )

    start_strategy3_engine_task()
    LOG.info("Strategy 3 backend startup complete")
    yield
    await stop_strategy3_engine_task()


app = FastAPI(title="Strategy 3 API", lifespan=lifespan)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["http://localhost:3002"],
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
