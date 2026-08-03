"""SE-Ranking Data API (Keyword-Research): verwandte/aehnliche/Longtail-Keywords +
Suchvolumen-Metriken. Anderes API-Produkt als die Project-API in ``seranking_client.py``
(andere Endpunkte, aber dieselbe Auth: ``Authorization: Token <api_key>``), kostet
Credits pro Aufruf -- deshalb cache-durchlaufend ueber ``SeoStore``.

Verifiziert gegen die echte API (Stand 2026-08):
    GET  /v1/keywords/similar?source=<region>&keyword=...   -- {"total", "keywords": [
         {"keyword","volume","cpc","difficulty","competition","intents",
          "serp_features","history_trend"}, ...]}
    GET  /v1/keywords/related?source=...&keyword=...        -- gleiche Form wie similar
    GET  /v1/keywords/questions?source=...&keyword=...      -- gleiche Form wie similar
    GET  /v1/keywords/longtail?source=...&keyword=...       -- {"total", "keywords": [str, ...]}
         (nur Keyword-Text, keine Metriken -- guenstigster Endpunkt)
    POST /v1/keywords/export?source=...  Body {"keywords": [...]} -- flache Liste
         [{"keyword","is_data_found","volume","cpc","difficulty","competition",
           "intents","history_trend"}, ...]

Wichtig: Keywords muessen mit echten Umlauten (nicht transliteriert) gesendet werden,
sonst liefert ``export`` ``is_data_found: false``.
"""

from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_BASE = "https://api.seranking.com/v1/keywords"


def _get(api_key: str, path: str, params: dict):
    url = f"{_BASE}/{path}?{urlencode(params)}"
    req = Request(url, headers={"Authorization": f"Token {api_key}"})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(api_key: str, path: str, params: dict, body: dict):
    url = f"{_BASE}/{path}?{urlencode(params)}"
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=payload, method="POST", headers={
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json; charset=utf-8",
    })
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _cached(store, api_key, kind: str, keyword: str, region: str, max_age_days: int, fetcher):
    cached = store.get_research_cache(keyword, kind, region, max_age_days=max_age_days)
    if cached is not None:
        return cached
    response = fetcher(api_key, kind, {"source": region, "keyword": keyword})
    store.set_research_cache(keyword, kind, region, response)
    return response


def fetch_similar(store, api_key: str, keyword: str, region: str = "de", *, max_age_days: int = 30) -> dict:
    return _cached(store, api_key, "similar", keyword, region, max_age_days, _get)


def fetch_related(store, api_key: str, keyword: str, region: str = "de", *, max_age_days: int = 30) -> dict:
    return _cached(store, api_key, "related", keyword, region, max_age_days, _get)


def fetch_questions(store, api_key: str, keyword: str, region: str = "de", *, max_age_days: int = 30) -> dict:
    return _cached(store, api_key, "questions", keyword, region, max_age_days, _get)


def fetch_longtail(store, api_key: str, keyword: str, region: str = "de", *, max_age_days: int = 30) -> dict:
    return _cached(store, api_key, "longtail", keyword, region, max_age_days, _get)


def export_metrics(store, api_key: str, keywords: list[str], region: str = "de",
                    *, max_age_days: int = 30) -> list[dict]:
    """Suchvolumen/CPC/Wettbewerb/Schwierigkeit fuer eine Liste von Keywords.

    Gecacht je EINZELNEM Keyword (nicht als Batch-Blob), damit ein spaeterer Aufruf mit
    teilweise ueberlappender Keyword-Liste die bereits bekannten Keywords aus dem Cache
    bedient und nur die tatsaechlich neuen per API abruft.

    Wichtig (durch echten Testlauf verifiziert): die API gibt das Keyword in ``item
    ["keyword"]`` KLEINGESCHRIEBEN zurueck (unabhaengig von der Schreibweise der
    Anfrage) und NICHT zwingend in der Reihenfolge der Anfrage. Der zurueckgegebene
    Eintrag traegt deshalb bewusst wieder die urspruenglich angefragte Schreibweise
    im ``keyword``-Feld (nicht die von der API kleingeschriebene) -- sonst muesste
    jeder Aufrufer denselben Kleinschreibungs-Abgleich erneut selbst nachbauen, um
    ein Ergebnis seinem eigenen (ggf. grossgeschriebenen) Keyword zuzuordnen.
    """
    results: dict[str, dict] = {}
    missing = []
    for kw in keywords:
        cached = store.get_research_cache(kw, "export", region, max_age_days=max_age_days)
        if cached is not None:
            results[kw] = cached
        else:
            missing.append(kw)

    if missing:
        response = _post(api_key, "export", {"source": region}, {"keywords": missing})
        by_lower = {item.get("keyword", "").strip().lower(): item for item in response}
        for kw in missing:
            item = by_lower.get(kw.strip().lower())
            if item is not None:
                item = {**item, "keyword": kw}
                store.set_research_cache(kw, "export", region, item)
                results[kw] = item

    return [results[kw] for kw in keywords if kw in results]
