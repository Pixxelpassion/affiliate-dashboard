"""SQLite-Persistenz fuer SEO-Monitoring (Search Console + GA4 + SE Ranking).

Eigene Datenbank (``data/seo.db``), getrennt von der Affiliate-Datenbank -- andere
Granularitaet (Datum x Seite x Keyword statt Monat x Tracking-ID).

Tabellen:
    gsc_daily  -- (date, page, query)  -> impressions, clicks, ctr, position
    ga4_daily  -- (date, page)         -> pageviews, avg_engagement_seconds
    rank_daily -- (date, page, keyword) -> position (SE Ranking)

Alle drei werden per ``INSERT OR REPLACE`` aktualisiert -- die APIs liefern pro Tag
bereits eindeutige/korrigierte Werte, keine Retouren-Logik wie bei Amazon noetig.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS gsc_daily (
    date        TEXT NOT NULL,
    page        TEXT NOT NULL,
    query       TEXT NOT NULL,
    impressions REAL,
    clicks      REAL,
    ctr         REAL,
    position    REAL,
    PRIMARY KEY (date, page, query)
);

CREATE TABLE IF NOT EXISTS ga4_daily (
    date                   TEXT NOT NULL,
    page                   TEXT NOT NULL,
    pageviews              REAL,
    avg_engagement_seconds REAL,
    PRIMARY KEY (date, page)
);

CREATE TABLE IF NOT EXISTS rank_daily (
    date     TEXT NOT NULL,
    page     TEXT NOT NULL,
    keyword  TEXT NOT NULL,
    position REAL,
    PRIMARY KEY (date, page, keyword)
);
"""


class SeoStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "SeoStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- Schreiben --------------------------------------------------------
    def upsert_gsc(self, rows: list[dict]) -> None:
        if not rows:
            return
        self.conn.executemany(
            """INSERT OR REPLACE INTO gsc_daily
               (date, page, query, impressions, clicks, ctr, position)
               VALUES (?,?,?,?,?,?,?)""",
            [(r["date"], r["page"], r["query"], r.get("impressions"),
              r.get("clicks"), r.get("ctr"), r.get("position")) for r in rows],
        )
        self.conn.commit()

    def upsert_ga4(self, rows: list[dict]) -> None:
        if not rows:
            return
        self.conn.executemany(
            """INSERT OR REPLACE INTO ga4_daily
               (date, page, pageviews, avg_engagement_seconds)
               VALUES (?,?,?,?)""",
            [(r["date"], r["page"], r.get("pageviews"), r.get("avg_engagement_seconds"))
             for r in rows],
        )
        self.conn.commit()

    def upsert_rank(self, rows: list[dict]) -> None:
        if not rows:
            return
        self.conn.executemany(
            """INSERT OR REPLACE INTO rank_daily (date, page, keyword, position)
               VALUES (?,?,?,?)""",
            [(r["date"], r["page"], r["keyword"], r.get("position")) for r in rows],
        )
        self.conn.commit()

    # --- Lesen --------------------------------------------------------------
    def all_gsc(self) -> list[dict]:
        rows = self.conn.execute(
            """SELECT date, page, query, impressions, clicks, ctr, position
               FROM gsc_daily ORDER BY date"""
        ).fetchall()
        return [dict(r) for r in rows]

    def all_ga4(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT date, page, pageviews, avg_engagement_seconds FROM ga4_daily ORDER BY date"
        ).fetchall()
        return [dict(r) for r in rows]

    def all_rank(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT date, page, keyword, position FROM rank_daily ORDER BY date"
        ).fetchall()
        return [dict(r) for r in rows]
