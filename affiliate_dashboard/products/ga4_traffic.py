"""GA4-Besucherzahlen on-demand fuer den Produkt-Lebenszyklus-Tab.

Anders als beim SEO-Monitoring (taeglich, rollierendes 450-Tage-Fenster als Teil
des automatischen Sync, siehe ``seo/seo_run.py``) wird hier NICHT automatisch
synchronisiert -- der Abruf passiert erst beim manuellen Speichern eines
Verfuegbarkeits-Status (``server.py``: ``POST /api/products/status``), synchron,
fuer genau ein Produkt, Zeitraum fest auf die letzten 365 Tage verdrahtet.
"""

from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import urlsplit

from ..seo import ga4_client, google_auth

_LOOKBACK_DAYS = 365


def fetch_pageviews(cfg, property_id: str, test_url: str) -> int:
    """Pageviews der letzten 365 Tage fuer eine Test-URL (aufsummiert)."""
    if not property_id:
        raise ValueError(
            "Keine GA4-Property-ID konfiguriert (weder je Produkt-Tab noch global "
            "unter seo.ga4.property_id)."
        )
    if not test_url:
        raise ValueError("Keine Test-URL fuer dieses Produkt hinterlegt -- GA4-Abgleich nicht moeglich.")

    path = urlsplit(test_url).path or "/"
    end = date.today()
    start = end - timedelta(days=_LOOKBACK_DAYS)

    credentials = google_auth.get_credentials(cfg)
    client = ga4_client.build_client(credentials)
    rows = ga4_client.fetch_daily(client, property_id, path, start.isoformat(), end.isoformat())
    return sum(r["pageviews"] for r in rows)
