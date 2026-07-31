"""SQLite-Persistenz fuer den Produkt-Lebenszyklus-Tab (eigene Datei ``products.db``,
andere Granularitaet als ``affiliate.db``/``seo.db``).

Tabellen:
    catalog     -- ein Produkt je (tracking_id, asin), aus dem Google-Sheet-Katalog-Tab
                   gelesen. Refresh-Strategie "replace-by-tab" (Voll-Snapshot je Tab).
    status      -- manueller Verfuegbarkeits-Status je (tracking_id, asin). Wird NUR
                   von der manuellen Check-API beschrieben, nie vom automatischen Sync.
    visitors    -- GA4-Besucherzahl je (tracking_id, asin). Wird NUR beim Speichern
                   eines Status-Eintrags aktualisiert (on-demand), nicht vom Sync.
    page_links  -- Ergebnis des Site-Crawlers: welche eigenen Website-Seiten verlinken
                   auf welche ASIN. Volles Replace je Crawl-Lauf.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog (
    tracking_id TEXT NOT NULL,
    asin        TEXT NOT NULL,
    name        TEXT,
    category    TEXT,
    test_url    TEXT,
    amazon_url  TEXT,
    specs       TEXT,
    tab_label   TEXT,
    PRIMARY KEY (tracking_id, asin)
);

CREATE TABLE IF NOT EXISTS status (
    tracking_id TEXT NOT NULL,
    asin        TEXT NOT NULL,
    status      TEXT,
    note        TEXT,
    checked_at  TEXT,
    PRIMARY KEY (tracking_id, asin)
);

CREATE TABLE IF NOT EXISTS visitors (
    tracking_id TEXT NOT NULL,
    asin        TEXT NOT NULL,
    pageviews   INTEGER,
    fetched_at  TEXT,
    PRIMARY KEY (tracking_id, asin)
);

CREATE TABLE IF NOT EXISTS page_links (
    asin     TEXT NOT NULL,
    page_url TEXT NOT NULL,
    PRIMARY KEY (asin, page_url)
);
"""


class ProductStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "ProductStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- catalog (Sync, replace-by-tab) ------------------------------------
    def replace_catalog(self, tab_label: str, items: list[dict]) -> None:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM catalog WHERE tab_label = ?", (tab_label,))
        cur.executemany(
            """INSERT OR REPLACE INTO catalog
               (tracking_id, asin, name, category, test_url, amazon_url, specs, tab_label)
               VALUES (?,?,?,?,?,?,?,?)""",
            [(it["tracking_id"], it["asin"], it.get("name"), it.get("category"),
              it.get("test_url"), it.get("amazon_url"),
              json.dumps(it.get("specs") or {}, ensure_ascii=False), tab_label)
             for it in items],
        )
        self.conn.commit()

    def all_catalog(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT tracking_id, asin, name, category, test_url, amazon_url, specs, tab_label FROM catalog"
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["specs"] = json.loads(d["specs"] or "{}")
            except ValueError:
                d["specs"] = {}
            out.append(d)
        return out

    # --- status (nur manuelle Check-API) -----------------------------------
    def upsert_status(self, tracking_id: str, asin: str, status: str, note: str = "") -> str:
        ts = datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            """INSERT OR REPLACE INTO status (tracking_id, asin, status, note, checked_at)
               VALUES (?,?,?,?,?)""",
            (tracking_id, asin, status, note, ts),
        )
        self.conn.commit()
        return ts

    def all_status(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT tracking_id, asin, status, note, checked_at FROM status"
        ).fetchall()
        return [dict(r) for r in rows]

    # --- visitors (nur on-demand beim Status-Speichern) --------------------
    def upsert_visitors(self, tracking_id: str, asin: str, pageviews: int) -> str:
        ts = datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            """INSERT OR REPLACE INTO visitors (tracking_id, asin, pageviews, fetched_at)
               VALUES (?,?,?,?)""",
            (tracking_id, asin, pageviews, ts),
        )
        self.conn.commit()
        return ts

    def all_visitors(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT tracking_id, asin, pageviews, fetched_at FROM visitors"
        ).fetchall()
        return [dict(r) for r in rows]

    # --- page_links (Site-Crawler, Replace je Website/Domain) ---------------
    def replace_page_links_for_site(self, site_base_url: str, links: dict[str, list[str]]) -> None:
        """Ersetzt alle ``page_links``-Zeilen, deren Seiten-URL zu dieser Website
        gehoert -- gescoped per Domain statt der ganzen Tabelle, damit ein
        fehlgeschlagener Crawl einer anderen Nische die hier frisch gefundenen
        Links nicht wegwirft (und umgekehrt: ein Fehlschlag hier die zuvor
        gecrawlten Links einer anderen Domain nicht loescht)."""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM page_links WHERE page_url LIKE ?", (site_base_url.rstrip("/") + "/%",))
        pairs = [(asin, url) for asin, urls in links.items() for url in urls]
        if pairs:
            cur.executemany(
                "INSERT OR REPLACE INTO page_links (asin, page_url) VALUES (?,?)", pairs
            )
        self.conn.commit()

    def all_page_links(self) -> dict[str, list[str]]:
        rows = self.conn.execute("SELECT asin, page_url FROM page_links").fetchall()
        out: dict[str, list[str]] = {}
        for r in rows:
            out.setdefault(r["asin"], []).append(r["page_url"])
        return out
