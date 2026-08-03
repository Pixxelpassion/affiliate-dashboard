"""SQLite-Persistenz fuer den Produkt-Lebenszyklus-Tab (eigene Datei ``products.db``,
andere Granularitaet als ``affiliate.db``/``seo.db``).

Tabellen:
    catalog         -- ein Produkt je (tracking_id, asin), aus dem Google-Sheet-Katalog-Tab
                       gelesen. Refresh-Strategie "replace-by-tab" (Voll-Snapshot je Tab).
    status_history  -- APPEND-ONLY Verlauf der manuellen Verfuegbarkeits-Checks je
                       (tracking_id, asin) -- bewusst kein Upsert/Overwrite: bei
                       jaehrlicher statt woechentlicher Kontrolle braucht es den
                       Vergleich zum vorherigen Check, um einen kurzfristigen
                       Lagerengpass von dauerhaftem Delisting zu unterscheiden
                       (zwei aufeinanderfolgende "nicht verfuegbar"-Checks). Wird
                       NUR von der manuellen Check-API beschrieben, nie vom Sync.
    visitors        -- GA4-Besucherzahl je (tracking_id, asin). Wird NUR beim Speichern
                       eines Status-Eintrags aktualisiert (on-demand), nicht vom Sync.
    page_links      -- Ergebnis des Site-Crawlers: welche eigenen Website-Seiten verlinken
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

CREATE TABLE IF NOT EXISTS status_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tracking_id TEXT NOT NULL,
    asin        TEXT NOT NULL,
    status      TEXT,
    note        TEXT,
    checked_at  TEXT
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

    # --- status_history (nur manuelle Check-API, append-only) --------------
    def add_status_check(self, tracking_id: str, asin: str, status: str, note: str = "") -> str:
        """Fuegt einen neuen Check hinzu, statt den vorherigen zu ueberschreiben --
        siehe Modul-Docstring: der Vergleich zum vorherigen Check ist der Punkt."""
        ts = datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            """INSERT INTO status_history (tracking_id, asin, status, note, checked_at)
               VALUES (?,?,?,?,?)""",
            (tracking_id, asin, status, note, ts),
        )
        self.conn.commit()
        return ts

    def all_status(self) -> list[dict]:
        """Neuester Check je (tracking_id, asin), plus ``repeated_unavailable``:
        True, wenn sowohl der neueste als auch der davor liegende Check
        "unavailable" waren -- das Signal fuer dauerhaftes Delisting statt
        eines kurzfristigen Lagerengpasses bei jaehrlicher Kontrolle."""
        rows = self.conn.execute(
            """SELECT tracking_id, asin, status, note, checked_at FROM status_history
               ORDER BY checked_at ASC, id ASC"""
        ).fetchall()
        history: dict[tuple[str, str], list[dict]] = {}
        for r in rows:
            history.setdefault((r["tracking_id"], r["asin"]), []).append(dict(r))

        result = []
        for (tracking_id, asin), checks in history.items():
            latest = checks[-1]
            previous = checks[-2] if len(checks) >= 2 else None
            result.append({
                "tracking_id": tracking_id,
                "asin": asin,
                "status": latest["status"],
                "note": latest["note"],
                "checked_at": latest["checked_at"],
                "repeated_unavailable": bool(
                    previous and previous["status"] == "unavailable" and latest["status"] == "unavailable"
                ),
            })
        return result

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
