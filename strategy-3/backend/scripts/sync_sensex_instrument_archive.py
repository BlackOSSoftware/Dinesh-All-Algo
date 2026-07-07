#!/usr/bin/env python3
"""Sync SENSEX historical option instrument archive for backtesting."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.sensex_instrument_archive import (  # noqa: E402
    archive_stats,
    sync_archive,
    upsert_instrument,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync SENSEX BFO historical instrument archive")
    parser.add_argument(
        "--no-master",
        action="store_true",
        help="Skip downloading live Angel scrip master (use only local JSON/import files)",
    )
    parser.add_argument(
        "--import-file",
        type=Path,
        help="Optional JSON file with manual tokens (symbols dict or master row list)",
    )
    args = parser.parse_args()

    if args.import_file and args.import_file.is_file():
        from app.services.sensex_instrument_archive import _load_json_archive

        count = _load_json_archive(args.import_file, source="cli_import")
        print(f"Imported {count} rows from {args.import_file}")

    stats = sync_archive(fetch_master=not args.no_master)
    info = archive_stats()
    print(json.dumps({"sync": stats, "archive": info}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
