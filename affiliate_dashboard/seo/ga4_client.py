"""GA4 Data API: Seitenviews + Engagement-Zeit je Tag+Seite.

Naeherung fuer "Verweildauer": GA4 kennt keine 1:1-Entsprechung zur alten
"Time on Page" mehr. ``userEngagementDuration`` (Sekunden, Summe ueber alle Sitzungen)
geteilt durch ``screenPageViews`` ergibt eine grobe **durchschnittliche Engagement-Zeit
pro Seitenaufruf** -- im Dashboard entsprechend beschriftet, keine exakte Kennzahl.
"""

from __future__ import annotations

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Filter,
    FilterExpression,
    Metric,
    RunReportRequest,
)


def build_client(credentials) -> BetaAnalyticsDataClient:
    return BetaAnalyticsDataClient(credentials=credentials)


def _normalize_property_id(property_id: str) -> str:
    """Erlaubt sowohl die blanke numerische ID (aus /settings, z.B. '386535911') als
    auch die volle Form ('properties/386535911') -- die GA4-API verlangt zwingend
    Letzteres."""
    property_id = property_id.strip()
    return property_id if property_id.startswith("properties/") else f"properties/{property_id}"


def _normalize_page_path(page_path: str) -> str:
    """GA4s ``pagePath``-Dimension traegt immer einen fuehrenden Slash (Startseite:
    '/', nicht ''). ``seo_pages.url`` ist dagegen Property-relativ OHNE fuehrenden
    Slash gespeichert (Konvention aus ``gsc_client.py``, das die volle URL selbst
    zusammenbaut) -- ohne diese Normalisierung liefert GA4 fuer jede so konfigurierte
    Seite still 0 Zeilen statt eines Fehlers."""
    return "/" + page_path.lstrip("/")


def fetch_daily(client: BetaAnalyticsDataClient, property_id: str, page_path: str,
                 start_date: str, end_date: str) -> list[dict]:
    """Taegliche Zeitreihe (Seitenviews + Ø Engagement-Zeit) fuer eine Seite.

    Gibt eine flache Liste zurueck: {date, page, pageviews, avg_engagement_seconds}.
    """
    request = RunReportRequest(
        property=_normalize_property_id(property_id),
        dimensions=[Dimension(name="date"), Dimension(name="pagePath")],
        metrics=[Metric(name="screenPageViews"), Metric(name="userEngagementDuration")],
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimension_filter=FilterExpression(
            filter=Filter(
                field_name="pagePath",
                string_filter=Filter.StringFilter(
                    value=_normalize_page_path(page_path),
                    match_type=Filter.StringFilter.MatchType.EXACT,
                ),
            )
        ),
    )
    response = client.run_report(request)

    rows = []
    for r in response.rows:
        date_raw = r.dimension_values[0].value  # YYYYMMDD
        date = f"{date_raw[0:4]}-{date_raw[4:6]}-{date_raw[6:8]}"
        pageviews = int(float(r.metric_values[0].value or 0))
        engagement_seconds = float(r.metric_values[1].value or 0)
        avg_engagement = (engagement_seconds / pageviews) if pageviews else 0.0
        rows.append({
            "date": date,
            "page": page_path,
            "pageviews": pageviews,
            "avg_engagement_seconds": round(avg_engagement, 1),
        })
    return rows
