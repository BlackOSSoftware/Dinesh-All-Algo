#!/usr/bin/env python3
"""Quick test to verify configuration loading."""

import logging
import sys
from pathlib import Path

backend_root = Path(__file__).parent
sys.path.insert(0, str(backend_root))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

from app.config import BACKEND_ROOT, log_startup_config, settings

print("=" * 80)
print("CONFIGURATION AUDIT")
print("=" * 80)
print(f"Backend root: {BACKEND_ROOT}")
print(f".env file exists: {(BACKEND_ROOT / '.env').is_file()}")
print(f".env path: {BACKEND_ROOT / '.env'}")
print()

log_startup_config()

print()
print("=" * 80)
print("CONFIGURATION AUDIT COMPLETE")
print("=" * 80)
