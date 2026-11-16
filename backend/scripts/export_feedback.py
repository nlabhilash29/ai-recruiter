"""Dump recruiter feedback and trace metadata to CSV.

From backend/:

    python scripts/export_feedback.py
    python scripts/export_feedback.py --output feedback.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import build_session_factory
from feedback_export import feedback_csv


def main() -> int:
    parser = argparse.ArgumentParser(description="Export recruiter score feedback and trace metadata.")
    parser.add_argument("--output", "-o", help="CSV path. Omit to write to stdout.")
    parser.add_argument("--database-url", help="Overrides DATABASE_URL for this run.")
    args = parser.parse_args()
    _engine, factory, _normalized = build_session_factory(args.database_url)
    db = factory()
    try:
        payload = feedback_csv(db)
    finally:
        db.close()
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
