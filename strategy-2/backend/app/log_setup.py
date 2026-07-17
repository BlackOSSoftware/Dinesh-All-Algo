"""Quiet-console logging: WARNINGs+ on screen, full INFO in a small rotating file.

Keeps the strategy CMD windows light on a VPS: the console only shows startup
and problems, while detailed logs go to instance/logs/backend.log which rotates
automatically (max ~5 MB x 3 files) so nothing has to be cleared by hand.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import BACKEND_ROOT

_CONFIGURED = False


def setup_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    log_dir = Path(BACKEND_ROOT) / "instance" / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            log_dir / "backend.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        fh.setLevel(logging.INFO)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        # File logging is best-effort; console handler below still works.
        pass

    # Console stays almost silent (only real errors) so the CMD window never
    # accumulates output and stays light on the VPS. Details are in the file.
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.ERROR)
    console.setFormatter(fmt)
    root.addHandler(console)

    # Per-request HTTP access lines flood the console; keep them out entirely
    # (uvicorn is also started with --no-access-log, this is belt-and-braces).
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    # Watchfiles (--reload) chatters on INFO.
    logging.getLogger("watchfiles").setLevel(logging.WARNING)
    logging.getLogger("watchfiles.main").setLevel(logging.WARNING)
