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


def fetch_daily(client: BetaAnalyticsDataClient, property_id: str, page_path: str,
                 start_date: str, end_date: str) -> list[dict]:
    """Taegliche Zeitreihe (Seitenviews + Ø Engagement-Zeit) fuer eine Seite.

    Gibt eine flache Liste zurueck: {date, page, pageviews, avg_engagement_seconds}.
    """
    request = RunReportRequest(
        property=property_id,
        dimensions=[Dimension(name="date"), Dimension(name="pagePath")],
        metrics=[Metric(name="screenPageViews"), Metric(name="userEngagementDuration")],
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimension_filter=FilterExpression(
            filter=Filter(
                field_name="pagePath",
                string_filter=Filter.StringFilter(
                    value=page_path, match_type=Filter.StringFilter.MatchType.EXACT
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
