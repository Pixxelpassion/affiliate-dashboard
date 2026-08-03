"""Keyword-Kannibalisierungs-Erkennung: rankt mehr als eine eigene Seite fuer dieselbe
Suchanfrage? Reines Python, kein I/O -- arbeitet auf den Zeilen aus
``gsc_client.fetch_all_queries()`` (bzw. ``SeoStore.all_query_discovery()``).
"""

from __future__ import annotations


def detect_cannibalization(
    rows: list[dict],
    *,
    min_impressions: int = 50,
    min_page_impressions: int = 3,
    min_pages: int = 2,
    close_position_gap: float = 30.0,
) -> list[dict]:
    """Gruppiert ``rows`` nach ``query`` und meldet nur Faelle mit echtem Beitrag
    mehrerer eigener Seiten.

    Schwellenwerte gegen Rauschen (z. B. eine zufaellige Impression irgendwann):
    - ``min_page_impressions``: jede beteiligte Seite muss selbst mindestens so viele
      Impressionen beisteuern, um mitgezaehlt zu werden.
    - ``min_pages``: danach muessen mindestens so viele Seiten uebrig bleiben.
    - ``min_impressions``: die Summe der beitragenden Seiten muss mindestens so hoch sein.

    ``severity`` ist ``"high"``, wenn die beiden bestplatzierten Seiten innerhalb von
    ``close_position_gap`` Positionen liegen (echte Konkurrenz um dieselbe Anfrage),
    sonst ``"low"`` (eine Seite dominiert bereits klar).

    Gibt eine nach Gesamt-Impressionen absteigend sortierte Liste zurueck:
    ``{"query", "pages": [{"page","position","impressions","clicks"}, ...],
    "total_impressions", "severity"}``, ``pages`` selbst nach Position aufsteigend
    sortiert (bestplatzierte Seite zuerst).
    """
    by_query: dict[str, list[dict]] = {}
    for r in rows:
        by_query.setdefault(r["query"], []).append(r)

    findings = []
    for query, entries in by_query.items():
        contributing = {
            e["page"]: e for e in entries
            if (e.get("impressions") or 0) >= min_page_impressions
        }
        if len(contributing) < min_pages:
            continue

        total_impressions = sum((e.get("impressions") or 0) for e in contributing.values())
        if total_impressions < min_impressions:
            continue

        sorted_pages = sorted(contributing.values(), key=lambda e: e.get("position") or 999.0)
        gap = abs((sorted_pages[1].get("position") or 999.0) - (sorted_pages[0].get("position") or 999.0))
        severity = "high" if gap <= close_position_gap else "low"

        findings.append({
            "query": query,
            "pages": [
                {"page": e["page"], "position": e.get("position"),
                 "impressions": e.get("impressions"), "clicks": e.get("clicks")}
                for e in sorted_pages
            ],
            "total_impressions": total_impressions,
            "severity": severity,
        })

    findings.sort(key=lambda f: -f["total_impressions"])
    return findings
