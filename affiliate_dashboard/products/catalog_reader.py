"""Liest einen Produkt-Katalog-Tab (z. B. "tauchpumpe05-21", "tischkreissaege0a-21")
aus dem Google Sheet -- eine Zeile pro getestetem Produkt.

Andere Semantik als der Umsatz-Import (``adapters/gsheet_adapter.py``): hier ist
jede Zeile ein Produkt mit Name/ASIN/Test-URL/Amazon-URL/Kategorie plus frei
variierenden technischen Spezifikationen (je Nische unterschiedliche Spalten)
-- die Spezifikationen werden generisch als ``{header: wert}``-Dict
mitgenommen, nicht in ein festes Schema gezwungen. Die erste Spalte jedes Tabs
traegt als Kopfzeile den Namen der Nische selbst und wird deshalb positionell
(Index 0) als Produktname behandelt, nicht ueber Alias-Matching.

Die Tracking-ID wird NICHT aus einer Spalte gelesen (nicht jeder Tab hat eine
"Tracking ID"-Spalte -- z. B. der Tischkreissaegen-Tab), sondern kommt 1:1 vom
konfigurierten Tab-Label (``/settings`` -> Produkt-Tabs). Wer diese Zuordnung
nutzt, muss das Tab-Label exakt auf die echte Tracking-ID setzen (z. B.
"tauchpumpe05-21").
"""

from __future__ import annotations

import csv
import io

from .. import columns
from ..gsheet_fetch import fetch_csv


def _cell(row: list, idx: int | None) -> str:
    if idx is None or idx >= len(row):
        return ""
    return (row[idx] or "").strip()


def read_tab(sheet_id: str, gid: str, tab_label: str) -> tuple[list[dict], dict]:
    """Einen Produkt-Tab lesen. Gibt ``(items, stats)`` zurueck.

    ``items``: Liste von ``{tab_label, name, tracking_id, asin, category,
    test_url, amazon_url, specs}`` -- ``tracking_id`` ist immer gleich
    ``tab_label``. Zeilen ohne ASIN werden uebersprungen -- ohne ASIN ist
    weder eine Amazon-Verfuegbarkeitspruefung noch eine
    Besucherzahlen-Zuordnung moeglich.
    """
    text = fetch_csv(sheet_id, gid)
    reader = csv.reader(io.StringIO(text))
    try:
        headers = next(reader)
    except StopIteration:
        return [], {"rows": 0, "no_asin": 0}

    cols = columns.resolve_columns(headers, aliases=columns.PRODUCT_ALIASES)
    category_idx = cols.get("category")
    specs_start = (category_idx + 1) if category_idx is not None else len(headers)

    items: list[dict] = []
    stats = {"rows": 0, "no_asin": 0}

    for row in reader:
        if not row or not any((cell or "").strip() for cell in row):
            continue  # komplett leere Zeile

        name = _cell(row, 0)
        asin = _cell(row, cols.get("asin"))
        if not name and not asin:
            continue  # keine sinnvolle Produktzeile

        stats["rows"] += 1
        if not asin:
            stats["no_asin"] += 1
            continue

        specs: dict[str, str] = {}
        for idx in range(specs_start, len(headers)):
            header = (headers[idx] or "").strip()
            if not header:
                continue
            value = _cell(row, idx)
            if value:
                specs[header] = value

        items.append({
            "tab_label": tab_label,
            "name": name,
            "tracking_id": tab_label,
            "asin": asin,
            "category": _cell(row, cols.get("category")),
            "test_url": _cell(row, cols.get("test_url")),
            "amazon_url": _cell(row, cols.get("amazon_url")),
            "specs": specs,
        })

    return items, stats
