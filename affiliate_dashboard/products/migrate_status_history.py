"""Einmalige Migration: alte ``status``-Tabelle (vor dem Umbau auf einen
Verlauf) -> ``status_history``.

Beim Wechsel von einem Einzel-Status je (tracking_id, asin) auf einen
Append-Only-Verlauf (siehe ``products/store.py``) wurde die alte ``status``-
Tabelle nicht geloescht, nur nicht mehr benutzt -- ihre Zeilen sind also noch
in ``products.db`` vorhanden und lassen sich verlustfrei uebernehmen.

Nutzung (im Docker-Container bzw. lokal im Projektordner):
    python -m affiliate_dashboard.products.migrate_status_history [--db data/products.db]
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from ..config import BASE_DIR

_ENSURE_HISTORY_TABLE = """
CREATE TABLE IF NOT EXISTS status_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tracking_id TEXT NOT NULL,
    asin        TEXT NOT NULL,
    status      TEXT,
    note        TEXT,
    checked_at  TEXT
);
"""


def migrate(db_path=None) -> int:
    path = Path(db_path) if db_path else (BASE_DIR / "data" / "products.db")
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_ENSURE_HISTORY_TABLE)

        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='status'"
        ).fetchone()
        if not exists:
            print(f"Keine alte 'status'-Tabelle in {path} gefunden -- nichts zu migrieren.")
            return 0

        rows = conn.execute(
            "SELECT tracking_id, asin, status, note, checked_at FROM status"
        ).fetchall()
        if not rows:
            print("Alte 'status'-Tabelle ist leer -- nichts zu migrieren.")
            return 0

        conn.executemany(
            "INSERT INTO status_history (tracking_id, asin, status, note, checked_at) VALUES (?,?,?,?,?)",
            [(r["tracking_id"], r["asin"], r["status"], r["note"], r["checked_at"]) for r in rows],
        )
        conn.commit()
        print(f"{len(rows)} Status-Eintraege aus der alten 'status'-Tabelle nach 'status_history' uebernommen:")
        for r in rows:
            print(f"  {r['tracking_id']} / {r['asin']}: {r['status']} ({r['checked_at']})")
        return len(rows)
    finally:
        conn.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="affiliate_dashboard.products.migrate_status_history",
        description="Alte 'status'-Tabelle (vor dem Verlaufs-Umbau) nach 'status_history' uebernehmen.",
    )
    parser.add_argument("--db", help="Pfad zu products.db (Standard: data/products.db)")
    args = parser.parse_args(argv)
    migrate(args.db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
