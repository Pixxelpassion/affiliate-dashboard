"""Google Search Console API: Impressionen/Klicks/CTR/Position je Tag+Seite+Keyword.

Nutzt die Search Analytics API (``searchanalytics.query`` -- Ressourcenname im Google-API-
Discovery-Dokument ist kleingeschrieben, nicht ``searchAnalytics``), gefiltert auf eine einzelne
Seite (volle URL) und eine Liste von Keywords.

Wichtig (durch echten Testlauf verifiziert, offizielle Doku bestaetigt es explizit):
mehrere Eintraege in ``dimensionFilterGroups`` werden von der API mit UND verknuepft, NICHT
mit ODER ("All filter groups must match in order for a row to be returned"). Eine Anfrage
mit einer Filtergruppe je Keyword liefert deshalb bei 2+ Keywords fuer dieselbe Seite immer
0 Zeilen (Seite=X UND Query=A UND Query=B kann nie zutreffen). Deshalb: ein separater
API-Call je Keyword, Ergebnisse werden zusammengefuehrt.
"""

from __future__ import annotations

from googleapiclient.discovery import build

_ROW_LIMIT = 25000


def build_service(credentials):
    return build("searchconsole", "v1", credentials=credentials, cache_discovery=False)


def _full_url(property_url: str, page_path: str) -> str:
    return property_url.rstrip("/") + "/" + page_path.lstrip("/")


def _fetch_daily_single_keyword(service, property_url: str, page_path: str, page_url: str,
                                 keyword: str, start_date: str, end_date: str) -> list[dict]:
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": ["date", "page", "query"],
        "dimensionFilterGroups": [{"filters": [
            {"dimension": "page", "operator": "equals", "expression": page_url},
            {"dimension": "query", "operator": "equals", "expression": keyword},
        ]}],
        "rowLimit": _ROW_LIMIT,
    }
    response = service.searchanalytics().query(siteUrl=property_url, body=body).execute()

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


def fetch_daily(service, property_url: str, page_path: str, keywords: list[str],
                 start_date: str, end_date: str) -> list[dict]:
    """Taegliche Zeitreihe je Keyword fuer eine Seite (ein API-Call je Keyword, s.o.).

    Gibt eine flache Liste zurueck: {date, page, query, impressions, clicks, ctr, position}.
    """
    page_url = _full_url(property_url, page_path)
    rows = []
    for kw in keywords:
        rows.extend(_fetch_daily_single_keyword(
            service, property_url, page_path, page_url, kw, start_date, end_date
        ))
    return rows


def fetch_all_queries(service, property_url: str, page_path: str,
                       start_date: str, end_date: str) -> list[dict]:
    """Alle fuer eine Seite gefundenen Queries, OHNE Keyword-Filter -- Grundlage fuer
    Kannibalisierungs-Erkennung (rankt eine andere eigene Seite ebenfalls fuer dieselbe
    Anfrage?). Im Unterschied zu ``fetch_daily`` wird ueber den gesamten Zeitraum
    aggregiert (keine ``date``-Dimension), da hier der aktuelle Zustand interessiert,
    nicht der Tagesverlauf.

    Gibt eine flache Liste zurueck: {page, query, impressions, clicks, ctr, position}.
    """
    page_url = _full_url(property_url, page_path)
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": ["page", "query"],
        "dimensionFilterGroups": [
            {"filters": [{"dimension": "page", "operator": "equals", "expression": page_url}]}
        ],
        "rowLimit": _ROW_LIMIT,
    }
    response = service.searchanalytics().query(siteUrl=property_url, body=body).execute()

    rows = []
    for r in response.get("rows", []):
        _page, query = r["keys"]
        rows.append({
            "page": page_path,
            "query": query,
            "impressions": r.get("impressions", 0),
            "clicks": r.get("clicks", 0),
            "ctr": r.get("ctr", 0.0),
            "position": r.get("position", 0.0),
        })
    return rows
