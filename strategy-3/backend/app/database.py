from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import BACKEND_ROOT, settings


class Base(DeclarativeBase):
    pass


def _ensure_sqlite_parent_dir():
    url = settings.database_url
    if not url.startswith("sqlite"):
        return
    u = make_url(url)
    if not u.database:
        return
    p = Path(u.database)
    if not p.is_absolute():
        p = (BACKEND_ROOT / p).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_parent_dir()

_engine_kwargs: dict = {"pool_pre_ping": True}
if settings.database_url.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(settings.database_url, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
