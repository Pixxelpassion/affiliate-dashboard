"""SE-Ranking-Projekt als Quelle fuer die ``seo_pages``-Watchlist nutzen.

Bildet die in SE Ranking hinterlegten Keyword-Ziel-URLs auf Pfade relativ zur
konfigurierten GSC-Property ab und merged sie additiv (nie loeschend) in die
bestehende ``seo_pages``-Tabelle. Ohne diesen Schritt braucht jede neu in SE Ranking
zugeordnete Seite Wochen, bis der normale ``seo_run.sync()`` (rollierendes
450-Tage-Fenster) ueberhaupt Historie fuer sie sammelt -- Trendaussagen waeren sonst
fuer neu entdeckte Seiten unmoeglich.

Keywords ohne Ziel-URL (oder mit Ziel-URL auf einer anderen Domain als der
konfigurierten Property) werden als ``unassigned`` durchgereicht statt verworfen --
das ist ein Befund fuer die Keyword-Research-/Clustering-Stufe (Content-Luecke),
kein Fehler.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from . import seranking_client


def _relative_path(property_url: str, link: str) -> str | None:
    """Pfad von ``link`` relativ zu ``property_url``, oder ``None`` bei anderer Domain."""
    prop = urlsplit(property_url)
    tgt = urlsplit(link)
    if (tgt.scheme, tgt.netloc) != (prop.scheme, prop.netloc):
        return None
    prop_path = prop.path.rstrip("/")
    if prop_path and not tgt.path.startswith(prop_path):
        return None
    return tgt.path[len(prop_path):].lstrip("/")


def discover(cfg) -> dict:
    """SE-Ranking-Projekt-Keywords lesen, auf Property-relative Pfade abbilden.

    Gibt ``{"pages": [{"url": page_path, "keywords": [...]}], "unassigned": [...]}``
    zurueck. Bei fehlendem API-Key/Projekt/Property leere Listen (kein Fehler).
    """
    seo_cfg = cfg.get("seo", {})
    se_cfg = seo_cfg.get("seranking", {})
    api_key = se_cfg.get("api_key")
    project_id = se_cfg.get("project_id")
    property_url = seo_cfg.get("gsc", {}).get("property", "")
    if not api_key or not project_id or not property_url:
        return {"pages": [], "unassigned": []}

    raw = seranking_client.discover_pages(api_key, project_id)
    unassigned = set(raw["unassigned"])
    pages = []
    for entry in raw["pages"]:
        rel = _relative_path(property_url, entry["url"])
        if rel is None:
            unassigned.update(entry["keywords"])
        else:
            pages.append({"url": rel, "keywords": entry["keywords"]})
    return {"pages": pages, "unassigned": sorted(unassigned)}


def sync_into_settings(cfg, store) -> dict:
    """``discover(cfg)["pages"]`` additiv in ``seo_pages`` einpflegen.

    Matched per Pfad (``url``). Neue Seiten werden angelegt, bei bestehenden Seiten
    werden neu entdeckte Keywords zu den vorhandenen hinzugefuegt (Vereinigung,
    niemals Ersetzen/Loeschen) -- manuell in ``/settings`` gepflegte Eintraege oder
    Keywords bleiben unangetastet.

    Gibt ``{"added_pages": int, "updated_pages": int, "unassigned": [...]}`` zurueck.
    """
    result = discover(cfg)
    by_url = {p["url"]: p for p in store.list_pages()}

    added_pages = 0
    updated_pages = 0
    for entry in result["pages"]:
        url = entry["url"]
        new_keywords = set(entry["keywords"])
        current = by_url.get(url)
        if current is None:
            store.add_page(url, sorted(new_keywords))
            added_pages += 1
        else:
            merged = set(current["keywords"]) | new_keywords
            if merged != set(current["keywords"]):
                store.update_page_keywords(current["id"], sorted(merged))
                updated_pages += 1

    return {
        "added_pages": added_pages,
        "updated_pages": updated_pages,
        "unassigned": result["unassigned"],
    }
