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

import json
import sqlite3
from datetime import datetime, timedelta
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

-- Snapshot fuer den Rechercheagenten (Kannibalisierungs-Erkennung): wird bei jedem
-- Analyse-Lauf KOMPLETT ersetzt (kein Upsert/kumulieren wie bei den drei Tabellen
-- oben) -- es ist der aktuelle Zustand, kein Langzeit-Verlauf. Eigene Tabelle statt
-- Wiederverwendung von gsc_daily, damit die bestehenden Keyword-Charts im SEO-Tab
-- nicht mit tausenden ungefilterten Long-Tail-Queries geflutet werden.
CREATE TABLE IF NOT EXISTS gsc_query_discovery (
    page         TEXT NOT NULL,
    query        TEXT NOT NULL,
    impressions  REAL,
    clicks       REAL,
    ctr          REAL,
    position     REAL,
    window_start TEXT NOT NULL,
    window_end   TEXT NOT NULL,
    PRIMARY KEY (page, query)
);

-- Cache fuer die SE-Ranking Data API (Keyword-Research kostet Credits pro Aufruf).
CREATE TABLE IF NOT EXISTS keyword_research_cache (
    seed_keyword  TEXT NOT NULL,
    kind          TEXT NOT NULL,
    region        TEXT NOT NULL,
    fetched_at    TEXT NOT NULL,
    response_json TEXT NOT NULL,
    PRIMARY KEY (seed_keyword, kind, region)
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

    # --- Query-Discovery (Kannibalisierungs-Snapshot) --------------------------
    def replace_query_discovery(self, rows: list[dict]) -> None:
        """Ersetzt den kompletten Inhalt -- Snapshot fuer den aktuellen Analyse-Lauf,
        kein kumulierender Verlauf wie bei den anderen drei Tabellen."""
        self.conn.execute("DELETE FROM gsc_query_discovery")
        if rows:
            self.conn.executemany(
                """INSERT INTO gsc_query_discovery
                   (page, query, impressions, clicks, ctr, position, window_start, window_end)
                   VALUES (?,?,?,?,?,?,?,?)""",
                [(r["page"], r["query"], r.get("impressions"), r.get("clicks"),
                  r.get("ctr"), r.get("position"), r["window_start"], r["window_end"])
                 for r in rows],
            )
        self.conn.commit()

    def all_query_discovery(self) -> list[dict]:
        rows = self.conn.execute(
            """SELECT page, query, impressions, clicks, ctr, position, window_start, window_end
               FROM gsc_query_discovery"""
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Keyword-Research-Cache (SE-Ranking Data API) --------------------------
    def get_research_cache(self, seed_keyword: str, kind: str, region: str,
                            max_age_days: int = 30) -> dict | None:
        row = self.conn.execute(
            """SELECT fetched_at, response_json FROM keyword_research_cache
               WHERE seed_keyword = ? AND kind = ? AND region = ?""",
            (seed_keyword, kind, region),
        ).fetchone()
        if row is None:
            return None
        fetched_at = datetime.fromisoformat(row["fetched_at"])
        if datetime.utcnow() - fetched_at > timedelta(days=max_age_days):
            return None
        return json.loads(row["response_json"])

    def set_research_cache(self, seed_keyword: str, kind: str, region: str, response) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO keyword_research_cache
               (seed_keyword, kind, region, fetched_at, response_json)
               VALUES (?,?,?,?,?)""",
            (seed_keyword, kind, region, datetime.utcnow().isoformat(),
             json.dumps(response, ensure_ascii=False)),
        )
        self.conn.commit()
