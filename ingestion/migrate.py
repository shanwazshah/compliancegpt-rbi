"""Apply append-only SQL migrations transactionally with a checksum ledger.

Run from the project root: python -m ingestion.migrate
Existing idempotent initial migrations can be adopted into the ledger on first run.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from app.db.queries import get_connection


def migrate(directory: Path) -> list[str]:
    applied = []
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(490429)")
        cur.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            name TEXT PRIMARY KEY, checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        for path in sorted(directory.glob("[0-9]*.sql")):
            text = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(text.encode()).hexdigest()
            cur.execute("SELECT checksum FROM schema_migrations WHERE name=%s", (path.name,))
            previous = cur.fetchone()
            if previous:
                if previous[0] != checksum:
                    raise ValueError(f"Applied migration was modified: {path.name}")
                continue
            cur.execute(text)
            cur.execute(
                "INSERT INTO schema_migrations(name,checksum) VALUES (%s,%s)", (path.name, checksum)
            )
            applied.append(path.name)
    return applied


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("migrations"))
    args = parser.parse_args()
    if not args.directory.is_dir():
        parser.error("Migration directory does not exist")
    for name in migrate(args.directory):
        print("Applied", name)


if __name__ == "__main__":
    main()
