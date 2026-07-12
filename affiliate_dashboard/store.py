"""SQLite-Persistenz fuer aggregierte Monatswerte und Detail-Items.

Tabellen:
    fact_monthly  -- eine Zeile je (month, tracking_id, source); Primaerschluessel
    fact_items    -- Rohzeilen der Quelle (aktuell nicht im Dashboard genutzt, da die
                     Google-Sheet-Quelle nur noch Monats-/Tracking-ID-Aggregate liefert)
    meta          -- Schluessel/Wert (z. B. letzter Lauf je Quelle)

Dedupe-Strategie:
    * ``replace_source`` (Voll-Snapshot, z. B. Google Sheet): loescht alle Zeilen
      der Quelle und schreibt neu -> "latest wins", inkl. nachtraeglicher
      Korrekturen/Loeschungen.
    * ``upsert_monthly`` (inkrementell, z. B. einzelne CSV-Dateien): ersetzt je
      Schluessel (month, tracking_id, source).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS fact_monthly (
    month         TEXT NOT NULL,
    tracking_id   TEXT NOT NULL,
    marketplace   TEXT,
    currency      TEXT,
    clicks        REAL,
    ordered_items REAL,
    items_shipped REAL,
    returns       REAL,
    revenue       REAL,
    earnings      REAL,
    source        TEXT NOT NULL,
    source_file   TEXT,
    ingested_at   TEXT,
    PRIMARY KEY (month, tracking_id, source)
);

CREATE TABLE IF NOT EXISTS fact_items (
    month        TEXT,
    tracking_id  TEXT,
    asin         TEXT,
    product_name TEXT,
    category     TEXT,
    seller       TEXT,
    device_group TEXT,
    price        REAL,
    revenue      REAL,
    earnings     REAL,
    source       TEXT NOT NULL,
    ingested_at  TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class Store:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- Schreiben --------------------------------------------------------
    def _monthly_tuple(self, r: dict, marketplace: str, currency: str,
                       source: str, source_file: str, ts: str) -> tuple:
        return (
            r["month"], r["tracking_id"], marketplace, currency,
            r.get("clicks"), r.get("ordered_items"), r.get("items_shipped"),
            r.get("returns"), r.get("revenue"), r.get("earnings"),
            source, source_file, ts,
        )

    def replace_source(self, source: str, monthly: list[dict], items: list[dict],
                       *, marketplace: str, currency: str, source_file: str = "") -> None:
        """Alle Zeilen einer Quelle ersetzen (Voll-Snapshot)."""
        ts = datetime.now().isoformat(timespec="seconds")
        cur = self.conn.cursor()
        cur.execute("DELETE FROM fact_monthly WHERE source = ?", (source,))
        cur.execute("DELETE FROM fact_items WHERE source = ?", (source,))
        cur.executemany(
            """INSERT INTO fact_monthly
               (month, tracking_id, marketplace, currency, clicks, ordered_items,
                items_shipped, returns, revenue, earnings, source, source_file, ingested_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [self._monthly_tuple(r, marketplace, currency, source, source_file, ts)
             for r in monthly],
        )
        self._insert_items(cur, items, source, ts)
        self.set_meta(f"last_run:{source}", ts)
        self.conn.commit()

    def upsert_monthly(self, source: str, monthly: list[dict], items: list[dict],
                      *, marketplace: str, currency: str, source_file: str = "") -> None:
        """Je Schluessel (month, tracking_id, source) einfuegen/ersetzen."""
        ts = datetime.now().isoformat(timespec="seconds")
        cur = self.conn.cursor()
        cur.executemany(
            """INSERT OR REPLACE INTO fact_monthly
               (month, tracking_id, marketplace, currency, clicks, ordered_items,
                items_shipped, returns, revenue, earnings, source, source_file, ingested_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [self._monthly_tuple(r, marketplace, currency, source, source_file, ts)
             for r in monthly],
        )
        self._insert_items(cur, items, source, ts)
        self.set_meta(f"last_run:{source}", ts)
        self.conn.commit()

    def _insert_items(self, cur, items: list[dict], source: str, ts: str) -> None:
        if not items:
            return
        cur.executemany(
            """INSERT INTO fact_items
               (month, tracking_id, asin, product_name, category, seller,
                device_group, price, revenue, earnings, source, ingested_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(it.get("month"), it["tracking_id"], it.get("asin"),
              it.get("product_name"), it.get("category"), it.get("seller"),
              it.get("device_group"), it.get("price"), it.get("revenue"),
              it.get("earnings"), source, ts) for it in items],
        )

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value)
        )

    def get_meta(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    # --- Lesen ------------------------------------------------------------
    def all_monthly(self) -> list[dict]:
        rows = self.conn.execute(
            """SELECT month, tracking_id, clicks, ordered_items, items_shipped,
                      returns, revenue, earnings, source
               FROM fact_monthly ORDER BY month, tracking_id"""
        ).fetchall()
        return [dict(r) for r in rows]

