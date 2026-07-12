"""Einmalige Migration: bestehende lokale ``config.json`` -> ``settings.db``.

Nutzung:
    python -m affiliate_dashboard.migrate_config_to_db [--config config.json]

Danach ist die DB-gestuetzte ``SettingsStore`` die primaere Konfigurationsquelle im
Server-Betrieb (siehe ``server.py``); ``config.json`` bleibt nur fuer den rein lokalen
Betrieb ohne Server relevant (CLI ``python -m affiliate_dashboard.run``).
"""

from __future__ import annotations

import argparse

from .config import BASE_DIR, Config
from .settings_store import SettingsStore


def migrate(config_path: str | None = None, db_path=None) -> None:
    cfg = Config.load(config_path)
    store_path = db_path or (BASE_DIR / "data" / "settings.db")

    with SettingsStore(store_path) as store:
        store.set_setting("marketplace", cfg.get("marketplace", "amazon.de"))
        store.set_setting("currency", cfg.get("currency", "EUR"))

        gsheet = cfg.get("gsheet", {})
        store.set_setting("gsheet_sheet_id", gsheet.get("sheet_id", ""))
        store.set_setting("gsheet_gid", gsheet.get("gid", "0"))

        seo = cfg.get("seo", {})
        store.set_setting("seo_enabled", "true" if seo.get("enabled") else "false")
        store.set_setting("gsc_property", seo.get("gsc", {}).get("property", ""))
        store.set_setting("ga4_property_id", seo.get("ga4", {}).get("property_id", ""))
        seranking = seo.get("seranking", {})
        store.set_setting("seranking_api_key", seranking.get("api_key", ""))
        store.set_setting("seranking_project_id", seranking.get("project_id", ""))

        existing_urls = {p["url"] for p in store.list_pages()}
        added = 0
        for page in seo.get("pages", []):
            url = page.get("url", "")
            if not url or url in existing_urls:
                continue
            store.add_page(url, page.get("keywords", []))
            added += 1

    print(f"Migration abgeschlossen -> {store_path}")
    print(f"Watchlist-Seiten uebernommen: {added} neu (bereits vorhandene wurden nicht doppelt angelegt)")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="affiliate_dashboard.migrate_config_to_db",
        description="Bestehende config.json einmalig in die DB-gestuetzte SettingsStore uebernehmen.",
    )
    parser.add_argument("--config", help="Pfad zu config.json (Standard: ./config.json)")
    args = parser.parse_args(argv)
    migrate(args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
