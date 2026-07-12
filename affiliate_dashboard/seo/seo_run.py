"""Orchestrierung: GSC + GA4 + SE Ranking einlesen -> seo.db.

Ein Fehlschlag einer Quelle (z. B. leere SE-Ranking-Credits, abgelaufener Google-Token)
blockiert die anderen beiden nicht -- jede Quelle laeuft in ihrem eigenen try/except,
Fehler werden protokolliert statt den gesamten Lauf abzubrechen.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

from ..config import BASE_DIR, Config
from . import ga4_client, google_auth, gsc_client, seranking_client
from .seo_store import SeoStore

_LOOKBACK_DAYS = 450  # > GSC-16-Monats-Fenster; die API liefert ausserhalb einfach nichts
_LAG_DAYS = 3         # GSC/GA4-Datenverzoegerung


def _date_range() -> tuple[str, str]:
    end = date.today() - timedelta(days=_LAG_DAYS)
    start = end - timedelta(days=_LOOKBACK_DAYS)
    return start.isoformat(), end.isoformat()


def _db_path(cfg: Config) -> Path:
    p = Path(cfg.get("seo", {}).get("db_path", "data/seo.db"))
    return p if p.is_absolute() else (BASE_DIR / p)


def sync(cfg: Config) -> dict:
    """Alle konfigurierten Seiten gegen GSC/GA4/SE-Ranking abgleichen, in seo.db speichern.

    Gibt ein Stats-Dict zurueck: {page_url: {"gsc": ..., "ga4": ..., "rank": ...}}.
    """
    seo_cfg = cfg.get("seo", {})
    pages = seo_cfg.get("pages", [])
    if not pages:
        print("SEO: keine Seiten in config.json -> seo.pages konfiguriert, uebersprungen.")
        return {}

    start_date, end_date = _date_range()

    credentials = None
    try:
        credentials = google_auth.get_credentials(cfg)
    except Exception as exc:  # noqa: BLE001
        print(f"SEO: Google-Login fehlgeschlagen ({exc}) -- GSC/GA4 werden uebersprungen.",
              file=sys.stderr)

    gsc_service = None
    ga4_service = None
    if credentials is not None:
        try:
            gsc_service = gsc_client.build_service(credentials)
        except Exception as exc:  # noqa: BLE001
            print(f"SEO: GSC-Service-Aufbau fehlgeschlagen ({exc})", file=sys.stderr)
        try:
            ga4_service = ga4_client.build_client(credentials)
        except Exception as exc:  # noqa: BLE001
            print(f"SEO: GA4-Client-Aufbau fehlgeschlagen ({exc})", file=sys.stderr)

    se_cfg = seo_cfg.get("seranking", {})

    stats: dict[str, dict] = {}
    with SeoStore(_db_path(cfg)) as store:
        for entry in pages:
            page_url = entry["url"]
            keywords = entry.get("keywords", [])
            page_stats: dict[str, str] = {}

            if gsc_service is not None:
                try:
                    rows = gsc_client.fetch_daily(
                        gsc_service, seo_cfg["gsc"]["property"], page_url, keywords,
                        start_date, end_date,
                    )
                    store.upsert_gsc(rows)
                    page_stats["gsc"] = f"{len(rows)} Zeilen"
                except Exception as exc:  # noqa: BLE001
                    page_stats["gsc"] = f"FEHLER: {exc}"
            else:
                page_stats["gsc"] = "uebersprungen (kein Login)"

            if ga4_service is not None:
                try:
                    rows = ga4_client.fetch_daily(
                        ga4_service, seo_cfg["ga4"]["property_id"], page_url,
                        start_date, end_date,
                    )
                    store.upsert_ga4(rows)
                    page_stats["ga4"] = f"{len(rows)} Zeilen"
                except Exception as exc:  # noqa: BLE001
                    page_stats["ga4"] = f"FEHLER: {exc}"
            else:
                page_stats["ga4"] = "uebersprungen (kein Login)"

            if se_cfg.get("api_key") and se_cfg.get("project_id") and keywords:
                try:
                    rows = seranking_client.fetch_daily(
                        se_cfg["api_key"], se_cfg["project_id"], page_url, keywords,
                        start_date, end_date,
                    )
                    store.upsert_rank(rows)
                    page_stats["rank"] = f"{len(rows)} Zeilen"
                except Exception as exc:  # noqa: BLE001
                    page_stats["rank"] = f"FEHLER: {exc}"
            else:
                page_stats["rank"] = "uebersprungen (kein API-Key/Projekt/Keyword)"

            stats[page_url] = page_stats
            print(f"SEO {page_url}: " + ", ".join(f"{k}={v}" for k, v in page_stats.items()))

    return stats


def read_payload(cfg: Config) -> dict:
    """Alle SEO-Daten aus seo.db lesen, fuer render.py aufbereitet."""
    with SeoStore(_db_path(cfg)) as store:
        return {
            "gsc": store.all_gsc(),
            "ga4": store.all_ga4(),
            "rank": store.all_rank(),
            "pages": cfg.get("seo", {}).get("pages", []),
        }
