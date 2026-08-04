"""SE-Ranking-Projekt als Quelle fuer eine Seiten-Watchlist nutzen.

Bildet die in SE Ranking hinterlegten Keyword-Ziel-URLs auf Pfade relativ zur
konfigurierten GSC-Property ab und merged sie additiv (nie loeschend) in eine
Watchlist -- entweder die globale ``seo_pages``-Tabelle (bestehendes SEO-Monitoring)
oder die Seiten eines einzelnen Recherche-Projekts (``research_project_pages``).
Ohne diesen Schritt braucht jede neu in SE Ranking zugeordnete Seite Wochen, bis der
normale ``seo_run.sync()`` (rollierendes 450-Tage-Fenster) ueberhaupt Historie fuer sie
sammelt -- Trendaussagen waeren sonst fuer neu entdeckte Seiten unmoeglich.

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


def discover(api_key: str, project_id: str, property_url: str) -> dict:
    """SE-Ranking-Projekt-Keywords lesen, auf Property-relative Pfade abbilden.

    Gibt ``{"pages": [{"url": page_path, "keywords": [...]}], "unassigned": [...]}``
    zurueck. Bei fehlendem API-Key/Projekt/Property leere Listen (kein Fehler).
    """
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


def _merge_additively(pages: list[dict], existing: list[dict], add_fn, update_fn) -> dict:
    """Gemeinsame additive Merge-Logik: neue Seiten anlegen, bei bestehenden Seiten
    neu entdeckte Keywords zu den vorhandenen hinzufuegen (Vereinigung, niemals
    Ersetzen/Loeschen). ``add_fn(url, keywords)`` / ``update_fn(page_id, keywords)``
    kapseln die konkrete Zieltabelle (globale Watchlist vs. Recherche-Projekt)."""
    by_url = {p["url"]: p for p in existing}
    added_pages = 0
    updated_pages = 0
    for entry in pages:
        url = entry["url"]
        new_keywords = set(entry["keywords"])
        current = by_url.get(url)
        if current is None:
            add_fn(url, sorted(new_keywords))
            added_pages += 1
        else:
            merged = set(current["keywords"]) | new_keywords
            if merged != set(current["keywords"]):
                update_fn(current["id"], sorted(merged))
                updated_pages += 1
    return {"added_pages": added_pages, "updated_pages": updated_pages}


def sync_into_settings(cfg, store) -> dict:
    """``discover(...)["pages"]`` additiv in die globale ``seo_pages``-Watchlist einpflegen.

    Gibt ``{"added_pages": int, "updated_pages": int, "unassigned": [...]}`` zurueck.
    """
    seo_cfg = cfg.get("seo", {})
    se_cfg = seo_cfg.get("seranking", {})
    result = discover(se_cfg.get("api_key"), se_cfg.get("project_id"),
                       seo_cfg.get("gsc", {}).get("property", ""))
    stats = _merge_additively(result["pages"], store.list_pages(), store.add_page,
                               store.update_page_keywords)
    return {**stats, "unassigned": result["unassigned"]}


def sync_into_research_project(api_key: str, project_id: str, property_url: str,
                                research_project_id: int, store) -> dict:
    """``discover(...)["pages"]`` additiv in die Seiten EINES Recherche-Projekts
    (``research_project_pages``) einpflegen -- identische Merge-Logik wie
    ``sync_into_settings``, aber gegen die Seiten eines einzelnen Projekts.

    Gibt ``{"added_pages": int, "updated_pages": int, "unassigned": [...]}`` zurueck.
    """
    result = discover(api_key, project_id, property_url)
    existing = store.list_research_project_pages(research_project_id)
    stats = _merge_additively(
        result["pages"], existing,
        lambda url, kws: store.add_research_project_page(research_project_id, url, kws),
        store.update_research_project_page_keywords,
    )
    return {**stats, "unassigned": result["unassigned"]}
