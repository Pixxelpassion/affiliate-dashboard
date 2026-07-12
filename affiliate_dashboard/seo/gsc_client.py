"""Google Search Console API: Impressionen/Klicks/CTR/Position je Tag+Seite+Keyword.

Nutzt die Search Analytics API (``searchAnalytics.query``), gefiltert auf eine einzelne
Seite (volle URL) und eine Liste von Keywords. Die API verknuepft Filter innerhalb einer
Filtergruppe per UND, mehrere Filtergruppen per ODER -- daher eine Filtergruppe
(Seite + Keyword) je gewuenschtem Keyword.
"""

from __future__ import annotations

from googleapiclient.discovery import build

_ROW_LIMIT = 25000


def build_service(credentials):
    return build("searchconsole", "v1", credentials=credentials, cache_discovery=False)


def _full_url(property_url: str, page_path: str) -> str:
    return property_url.rstrip("/") + "/" + page_path.lstrip("/")


def fetch_daily(service, property_url: str, page_path: str, keywords: list[str],
                 start_date: str, end_date: str) -> list[dict]:
    """Taegliche Zeitreihe je Keyword fuer eine Seite.

    Gibt eine flache Liste zurueck: {date, page, query, impressions, clicks, ctr, position}.
    """
    page_url = _full_url(property_url, page_path)
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": ["date", "page", "query"],
        "dimensionFilterGroups": [
            {
                "filters": [
                    {"dimension": "page", "operator": "equals", "expression": page_url},
                    {"dimension": "query", "operator": "equals", "expression": kw},
                ]
            }
            for kw in keywords
        ],
        "rowLimit": _ROW_LIMIT,
    }
    response = service.searchAnalytics().query(siteUrl=property_url, body=body).execute()

    rows = []
    for r in response.get("rows", []):
        _date, _page, query = r["keys"]
        rows.append({
            "date": _date,
            "page": page_path,
            "query": query,
            "impressions": r.get("impressions", 0),
            "clicks": r.get("clicks", 0),
            "ctr": r.get("ctr", 0.0),
            "position": r.get("position", 0.0),
        })
    return rows
