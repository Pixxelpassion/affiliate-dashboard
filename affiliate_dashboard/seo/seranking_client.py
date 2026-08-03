"""SE Ranking REST-API (Project API): Keyword-Rankingposition je Tag+Seite.

Verifiziert gegen die offizielle Doku (https://seranking.com/api/project/):
    GET /v1/project-management/keywords?site_id=...        -- Keyword-Text + Ziel-URL je ID
    GET /v1/project-management/sites/positions?site_id=... -- Rankingverlauf je Keyword-ID
      (gruppiert nach site_engine_id; jedes Keyword traegt ein "positions"-Array mit
      {date, pos, change}). Der Positions-Endpunkt liefert selbst keinen Klartext --
      beide Endpunkte werden ueber die Keyword-ID verknuepft.

Auth: Header ``Authorization: Token <api_key>``. Nutzt nur die Python-Standardbibliothek
(``urllib``), wie der Rest des Projekts.
"""

from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_BASE = "https://api.seranking.com/v1/project-management"


def _get(api_key: str, path: str, params: dict):
    url = f"{_BASE}{path}?{urlencode(params)}"
    req = Request(url, headers={"Authorization": f"Token {api_key}"})
    with urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _keyword_lookup(api_key: str, site_id: str) -> dict[str, dict]:
    """``{keyword_id: {"name": ..., "link": ...}}`` fuer alle Keywords des Projekts."""
    data = _get(api_key, "/keywords", {"site_id": site_id})
    return {kw["id"]: {"name": kw.get("name", ""), "link": kw.get("link", "")} for kw in data}


def discover_pages(api_key: str, site_id: str) -> dict:
    """Gruppiert alle Projekt-Keywords nach der in SE Ranking hinterlegten Ziel-URL.

    Nicht jedes Keyword hat eine Ziel-URL (``link``) -- diese landen unter
    ``unassigned`` statt verworfen zu werden, sie sind fuer die Keyword-Research-/
    Clustering-Stufe ein Befund (Content-Luecke), kein Fehler.

    Gibt ``{"pages": [{"url": link, "keywords": [name, ...]}], "unassigned": [name, ...]}``
    zurueck.
    """
    lookup = _keyword_lookup(api_key, site_id)
    by_link: dict[str, set[str]] = {}
    unassigned: set[str] = set()
    for meta in lookup.values():
        name = meta.get("name", "").strip()
        if not name:
            continue
        link = (meta.get("link") or "").strip()
        if link:
            by_link.setdefault(link, set()).add(name)
        else:
            unassigned.add(name)
    return {
        "pages": [{"url": url, "keywords": sorted(kws)} for url, kws in sorted(by_link.items())],
        "unassigned": sorted(unassigned),
    }


def fetch_daily(api_key: str, site_id: str, page_path: str, keywords: list[str],
                 start_date: str, end_date: str) -> list[dict]:
    """Taegliche Rankingposition je konfiguriertem Keyword fuer eine Seite.

    Gibt eine flache Liste zurueck: {date, page, keyword, position}.
    """
    lookup = _keyword_lookup(api_key, site_id)
    wanted = {name.strip().lower() for name in keywords}

    positions_resp = _get(api_key, "/sites/positions", {
        "site_id": site_id, "date_from": start_date, "date_to": end_date,
    })

    rows = []
    for engine_group in positions_resp:
        for kw in engine_group.get("keywords", []):
            meta = lookup.get(kw.get("id"))
            if not meta or meta["name"].strip().lower() not in wanted:
                continue
            for p in kw.get("positions", []):
                rows.append({
                    "date": p["date"],
                    "page": page_path,
                    "keyword": meta["name"],
                    "position": p.get("pos"),
                })
    return rows
