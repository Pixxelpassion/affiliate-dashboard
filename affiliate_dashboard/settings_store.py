"""SQLite-gestuetzte Einstellungen (Ersatz fuer die lokale config.json im Server-Betrieb).

Speichert Sheet-ID/gid, SEO-API-Zugangsdaten und die SEO-Watchlist in einer eigenen
SQLite-Datenbank (``data/settings.db``), editierbar ueber die ``/settings``-Weboberflaeche
in ``server.py``. ``affiliate.db``/``seo.db`` bleiben rein fachliche Datentoepfe, keine
Zugangsdaten.
"""

from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS seo_pages (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    url      TEXT NOT NULL,
    keywords TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seo_events (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    page TEXT NOT NULL,
    date TEXT NOT NULL,
    text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS product_tabs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    label           TEXT NOT NULL,
    gid             TEXT NOT NULL,
    ga4_property_id TEXT,
    site_base_url   TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# Bekannte Skalar-Settings: Schluessel in der `settings`-Tabelle -> Pfad im
# verschachtelten Config-Dict (dieselbe Form wie config.py::DEFAULTS).
_SETTING_PATHS = {
    "marketplace": ("marketplace",),
    "currency": ("currency",),
    "gsheet_sheet_id": ("gsheet", "sheet_id"),
    "gsheet_gid": ("gsheet", "gid"),
    "seo_enabled": ("seo", "enabled"),
    "gsc_property": ("seo", "gsc", "property"),
    "ga4_property_id": ("seo", "ga4", "property_id"),
    "seranking_api_key": ("seo", "seranking", "api_key"),
    "seranking_project_id": ("seo", "seranking", "project_id"),
    "seranking_auto_discover_pages": ("seo", "seranking", "auto_discover_pages"),
    "gemini_api_key": ("seo", "gemini", "api_key"),
    "products_enabled": ("products", "enabled"),
}
_BOOL_KEYS = {"seo_enabled", "products_enabled", "seranking_auto_discover_pages"}


class SettingsStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "SettingsStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- Skalar-Settings ----------------------------------------------------
    def get_setting(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value))
        )
        self.conn.commit()

    def all_settings(self) -> dict[str, str]:
        rows = self.conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}

    # --- SEO-Watchlist --------------------------------------------------------
    def list_pages(self) -> list[dict]:
        rows = self.conn.execute("SELECT id, url, keywords FROM seo_pages ORDER BY id").fetchall()
        return [{"id": r["id"], "url": r["url"], "keywords": json.loads(r["keywords"])} for r in rows]

    def add_page(self, url: str, keywords: list[str]) -> None:
        self.conn.execute(
            "INSERT INTO seo_pages (url, keywords) VALUES (?, ?)",
            (url.strip(), json.dumps(list(keywords))),
        )
        self.conn.commit()

    def delete_page(self, page_id: int) -> None:
        self.conn.execute("DELETE FROM seo_pages WHERE id = ?", (page_id,))
        self.conn.commit()

    def update_page_keywords(self, page_id: int, keywords: list[str]) -> None:
        self.conn.execute(
            "UPDATE seo_pages SET keywords = ? WHERE id = ?",
            (json.dumps(list(keywords)), page_id),
        )
        self.conn.commit()

    # --- Produkt-Tabs (Produkt-Lebenszyklus-Tab) -------------------------------
    def list_product_tabs(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, label, gid, ga4_property_id, site_base_url FROM product_tabs ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]

    def add_product_tab(self, label: str, gid: str, ga4_property_id: str = "",
                        site_base_url: str = "") -> None:
        self.conn.execute(
            """INSERT INTO product_tabs (label, gid, ga4_property_id, site_base_url)
               VALUES (?, ?, ?, ?)""",
            (label.strip(), gid.strip(), ga4_property_id.strip(), site_base_url.strip()),
        )
        self.conn.commit()

    def delete_product_tab(self, tab_id: int) -> None:
        self.conn.execute("DELETE FROM product_tabs WHERE id = ?", (tab_id,))
        self.conn.commit()

    # --- SEO-Events (Livegang-Marker) -----------------------------------------
    def list_events(self, page: str | None = None) -> list[dict]:
        if page:
            rows = self.conn.execute(
                "SELECT id, page, date, text FROM seo_events WHERE page = ? ORDER BY date",
                (page,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT id, page, date, text FROM seo_events ORDER BY date"
            ).fetchall()
        return [dict(r) for r in rows]

    def add_event(self, page: str, date: str, text: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO seo_events (page, date, text) VALUES (?, ?, ?)", (page, date, text)
        )
        self.conn.commit()
        return cur.lastrowid

    def delete_event(self, event_id: int) -> None:
        self.conn.execute("DELETE FROM seo_events WHERE id = ?", (event_id,))
        self.conn.commit()

    # --- Prozessuebergreifender Laufzeitzustand -------------------------------
    # (z. B. letztes Sync-Ergebnis; gunicorn laeuft mit mehreren Worker-Prozessen,
    # normale Python-Variablen sind NICHT zwischen ihnen geteilt -- die DB schon.)
    def get_meta(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value)
        )
        self.conn.commit()

    # --- Config-kompatibles Dict ----------------------------------------------
    def to_config_dict(self, defaults: dict) -> dict:
        """Verschachteltes Dict im DEFAULTS-Format bauen (fuer Config.from_settings_store)."""
        data = copy.deepcopy(defaults)
        for key, path in _SETTING_PATHS.items():
            value = self.get_setting(key, None)
            if value is None:
                continue
            if key in _BOOL_KEYS:
                value = str(value).lower() in ("1", "true", "yes")
            node = data
            for part in path[:-1]:
                node = node[part]
            node[path[-1]] = value
        data["seo"]["pages"] = [
            {"url": p["url"], "keywords": p["keywords"]} for p in self.list_pages()
        ]
        data["products"]["tabs"] = [
            {"label": t["label"], "gid": t["gid"],
             "ga4_property_id": t["ga4_property_id"] or "",
             "site_base_url": t["site_base_url"] or ""}
            for t in self.list_product_tabs()
        ]
        return data
