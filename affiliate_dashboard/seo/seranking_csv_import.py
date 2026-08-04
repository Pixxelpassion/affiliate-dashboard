"""Parser fuer manuell aus der SE-Ranking-Weboberflaeche exportierte CSV-Dateien --
Alternative zu den Live-API-Aufrufen in ``seranking_client.py``/
``seranking_keyword_research.py``, wenn keine API-Credits verfuegbar sind (Web-Exporte
kosten keine Credits). Reine Funktionen, kein I/O ausser dem Datei-Inhalt selbst.

Verifiziert gegen echte Exporte (Stand 2026-08):

1. **Keyword-Liste** (Rank-Tracker-Export, ``parse_keyword_list_csv``): Zeile 1 ist
   oft eine Geraete-/Sprach-Meta-Zeile (z. B. ``"Google Mobile Germany, ..."``), die
   uebersprungen wird -- der echte Header beginnt mit ``Keyword,Url,...``. Ab
   Spaltenindex 7 folgt ein sich wiederholender 3er-Block je Tag
   (``<Datum>,Dynamics,URL``): Zellwert unter dem Datum = Position an dem Tag
   (``"-"`` = keine Daten), ``URL`` = an dem Tag tatsaechlich rankende Seite. Die
   statische ``Url``-Spalte (Index 1) ist die Ziel-URL-Zuordnung (leer = unzugeordnet).

2. **Similar/Related/Questions-Exporte** (Keyword-Research,
   ``parse_keyword_suggestions_csv``): ``Keyword,Difficulty,Search vol.,Search
   intent,SERP features,[Relevance,]CPC,Competition`` -- nur "Related" hat die
   zusaetzliche ``Relevance``-Spalte, sonst identisch. Diese Exporte sind je EINEM
   Seed-Begriff erzeugt (nicht je unzugeordnetem Keyword wie im Live-API-Pfad).

3. **Organic-Export** (Wettbewerber-Uebersicht, ``parse_organic_csv``): keine
   Keyword-Spalte -- der Seed-Begriff wird beim Aufruf mitgegeben (kommt aus dem
   Dateinamen bzw. wird beim Upload vom Nutzer eingetragen).
"""

from __future__ import annotations

import csv
import io

_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")


def _decode(file_bytes: bytes) -> str:
    for enc in _ENCODINGS:
        try:
            return file_bytes.decode(enc)
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("utf-8", errors="replace")


def _to_int(value) -> int | None:
    value = (value or "").strip()
    if not value or value == "-":
        return None
    try:
        return int(float(value.replace(",", ".")))
    except ValueError:
        return None


def _to_float(value) -> float | None:
    value = (value or "").strip()
    if not value or value == "-":
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def parse_keyword_list_csv(file_bytes: bytes) -> dict:
    """Gibt ``{"keywords": [{"keyword","url","search_volume"}, ...],
    "rank_rows": [{"date","keyword","position"}, ...]}`` zurueck.

    Bewusst OHNE Seiten-Gruppierung -- das uebernimmt
    ``seranking_pages_sync.discover_from_csv()`` (Wiederverwendung derselben
    Gruppierungslogik wie beim Live-API-Pfad). ``rank_rows`` traegt noch kein
    ``page``-Feld, das ordnet der Aufrufer anhand der konfigurierten Keywords je
    Seite zu (siehe ``research_agent.build_project_digest``).
    """
    rows = list(csv.reader(io.StringIO(_decode(file_bytes))))
    header_idx = next((i for i, r in enumerate(rows) if r and r[0].strip() == "Keyword"), None)
    if header_idx is None:
        raise ValueError("Kein 'Keyword'-Header in der Keyword-Listen-CSV gefunden.")
    header = rows[header_idx]

    date_cols = []
    i = 7
    while i < len(header):
        date_label = header[i].strip()
        if date_label:
            date_cols.append((date_label, i))
        i += 3

    keywords = []
    rank_rows = []
    for row in rows[header_idx + 1:]:
        if not row or not row[0].strip():
            continue
        keyword = row[0].strip()
        url = row[1].strip() if len(row) > 1 else ""
        search_volume = _to_int(row[3]) if len(row) > 3 else None
        keywords.append({"keyword": keyword, "url": url, "search_volume": search_volume})
        for date_label, idx in date_cols:
            if idx >= len(row):
                continue
            position = _to_int(row[idx])
            if position is None:
                continue
            rank_rows.append({"date": date_label, "keyword": keyword, "position": float(position)})

    return {"keywords": keywords, "rank_rows": rank_rows}


def parse_keyword_suggestions_csv(file_bytes: bytes) -> list[dict]:
    """Fuer similar/related/questions-Exporte. Gibt eine Liste von
    ``{"keyword","volume","difficulty","cpc","competition","intents","relevance"}``
    zurueck (``relevance`` ``None``, falls die Spalte fehlt -- nur bei "related" dabei).
    """
    reader = csv.DictReader(io.StringIO(_decode(file_bytes)))
    results = []
    for row in reader:
        keyword = (row.get("Keyword") or "").strip()
        if not keyword:
            continue
        results.append({
            "keyword": keyword,
            "difficulty": _to_int(row.get("Difficulty")),
            "volume": _to_int(row.get("Search vol.")),
            "intents": (row.get("Search intent") or "").strip(),
            "cpc": _to_float(row.get("CPC")),
            "competition": _to_float(row.get("Competition")),
            "relevance": _to_int(row.get("Relevance")) if "Relevance" in reader.fieldnames else None,
        })
    return results


def parse_organic_csv(file_bytes: bytes, seed_keyword: str) -> list[dict]:
    """Wettbewerber-Uebersicht. Gibt eine Liste von ``{"position","url","title",
    "total_traffic","dt","pt","backlinks","referring_domains","seed_keyword"}`` zurueck.
    """
    reader = csv.DictReader(io.StringIO(_decode(file_bytes)))
    results = []
    for row in reader:
        url = (row.get("URL") or "").strip()
        if not url:
            continue
        results.append({
            "position": _to_int(row.get("Position")),
            "url": url,
            "title": (row.get("Title") or "").strip(),
            "total_traffic": _to_int(row.get("Total traffic")),
            "dt": _to_int(row.get("DT")),
            "pt": _to_int(row.get("PT")),
            "backlinks": _to_int(row.get("Backlinks")),
            "referring_domains": _to_int(row.get("Referring Domains")),
            "seed_keyword": seed_keyword,
        })
    return results
