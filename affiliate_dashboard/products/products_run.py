"""Orchestrierung: Produkt-Katalog-Tabs einlesen + eigene Website(s) crawlen -> products.db.

Anders als beim SEO-Monitoring wird hier KEIN GA4 abgerufen -- das passiert erst
on-demand beim manuellen Speichern eines Verfuegbarkeits-Status (siehe
``products/ga4_traffic.py``, aufgerufen aus ``server.py``). ``sync()`` macht nur
zwei Dinge: (1) Produkt-Kataloge neu vom Sheet lesen, (2) Website(s) crawlen.
Ein Fehlschlag bei einem Tab (Sheet nicht lesbar, Website nicht erreichbar)
blockiert die anderen konfigurierten Tabs nicht.
"""

from __future__ import annotations

from pathlib import Path

from ..config import BASE_DIR, Config
from . import catalog_reader, site_crawler
from .store import ProductStore


def _db_path(cfg: Config) -> Path:
    p = Path(cfg.get("products", {}).get("db_path", "data/products.db"))
    return p if p.is_absolute() else (BASE_DIR / p)


def sync(cfg: Config) -> dict:
    """Alle konfigurierten Produkt-Tabs neu lesen + ihre Websites crawlen.

    Gibt ein Stats-Dict zurueck: ``{tab_label: {"catalog": ..., "crawl": ...}}``.
    """
    tabs = cfg.get("products", {}).get("tabs", [])
    if not tabs:
        print("Produkte: keine Tabs in config.json -> products.tabs konfiguriert, uebersprungen.")
        return {}

    sheet_id = cfg.get("gsheet", {}).get("sheet_id", "")
    stats: dict[str, dict] = {}

    with ProductStore(_db_path(cfg)) as store:
        for tab in tabs:
            label = tab.get("label", "")
            gid = str(tab.get("gid", ""))
            tab_stats: dict[str, str] = {}

            try:
                items, cat_stats = catalog_reader.read_tab(sheet_id, gid, label)
                store.replace_catalog(label, items)
                tab_stats["catalog"] = f"{len(items)} Produkte ({cat_stats})"
            except Exception as exc:  # noqa: BLE001
                tab_stats["catalog"] = f"FEHLER: {exc}"

            site_base_url = tab.get("site_base_url", "")
            if site_base_url:
                try:
                    links = site_crawler.crawl(site_base_url)
                    store.replace_page_links_for_site(site_base_url, links)
                    tab_stats["crawl"] = f"{len(links)} ASINs verlinkt"
                except Exception as exc:  # noqa: BLE001
                    tab_stats["crawl"] = f"FEHLER: {exc}"
            else:
                tab_stats["crawl"] = "uebersprungen (keine site_base_url konfiguriert)"

            stats[label] = tab_stats
            print(f"Produkte {label}: " + ", ".join(f"{k}={v}" for k, v in tab_stats.items()))

    return stats


def read_payload(cfg: Config) -> dict:
    """Alle Produkt-Daten aus products.db lesen, fuer render.py aufbereitet."""
    with ProductStore(_db_path(cfg)) as store:
        return {
            "catalog": store.all_catalog(),
            "status": store.all_status(),
            "visitors": store.all_visitors(),
            "page_links": store.all_page_links(),
            "tabs": cfg.get("products", {}).get("tabs", []),
        }


def merge_items(catalog: list[dict], status: list[dict], visitors: list[dict],
                page_links: dict[str, list[str]]) -> list[dict]:
    """Katalog + manueller Status + GA4-Besucherzahlen + Seiten-Links (Site-Crawler)
    zu einer flachen Item-Liste je (tracking_id, asin) zusammenfuehren.

    Gemeinsam genutzt von ``render.py`` (statischer Payload beim Sync) und
    ``server.py``s ``GET /api/products`` (Live-Abfrage, damit manuell gespeicherte
    Status-Aenderungen nicht erst nach dem naechsten Sync sichtbar werden). Der
    Amazon-Link wird bewusst immer kanonisch aus der ASIN gebaut, nicht aus der
    Sheet-Spalte, die teils ``amzn.to``-Kurzlinks oder veraltete Links enthaelt.
    """
    status_by_key = {(s["tracking_id"], s["asin"]): s for s in status}
    visitors_by_key = {(v["tracking_id"], v["asin"]): v for v in visitors}

    items = []
    for c in catalog:
        key = (c["tracking_id"], c["asin"])
        st = status_by_key.get(key)
        vi = visitors_by_key.get(key)
        items.append({
            "tracking_id": c["tracking_id"],
            "asin": c["asin"],
            "name": c.get("name") or "",
            "category": c.get("category") or "",
            "amazon_url": f"https://www.amazon.de/dp/{c['asin']}",
            "test_url": c.get("test_url") or "",
            "status": st["status"] if st else None,
            "note": (st or {}).get("note") or "",
            "checked_at": st["checked_at"] if st else None,
            "repeated_unavailable": bool((st or {}).get("repeated_unavailable")),
            "pageviews": vi["pageviews"] if vi else None,
            "visitors_fetched_at": vi["fetched_at"] if vi else None,
            "pages": page_links.get(c["asin"], []),
        })
    return items
