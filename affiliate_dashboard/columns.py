"""Schema-tolerante Spaltenerkennung und Wert-Parser.

PartnerNet-/Google-Sheet-Spaltennamen variieren (Deutsch/Englisch, Umlaute,
Einheiten wie ``(EUR)``/``($)``, Tab- statt Komma-Trennung). Dieses Modul bildet
beliebige Header ueber ein Alias-Mapping auf ein kanonisches Schema ab und parst
deutsche Zahlen-/Datumsformate robust.

Kanonische Felder:
    tracking_id, month, earnings, revenue, items_shipped, returns, clicks,
    ordered_items, asin, product_name, category, seller, price, device_group,
    commission_rate
"""

from __future__ import annotations

import re
import unicodedata

# --- Header-Normalisierung --------------------------------------------------


def normalize_header(header: str | None) -> str:
    """Header auf kleingeschriebene, akzent-/zeichenfreie Form reduzieren.

    Beispiele: ``"Ad Gebuehren (EUR)"`` -> ``"adgebuhren"``,
    ``"Tracking-ID"`` -> ``"trackingid"``, ``"Datum geliefert"`` -> ``"datumgeliefert"``.
    """
    if header is None:
        return ""
    text = unicodedata.normalize("NFKD", str(header))
    # kombinierende Akzente entfernen (ae<-a+umlaut etc.)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    # Nur Buchstaben/Ziffern behalten (entfernt auch Klammern/Waehrungszeichen);
    # Buchstaben INNERHALB von Klammern bleiben erhalten, z. B. um
    # "Umsatz (best.)" von "Umsatz (vers.)" unterscheiden zu koennen.
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


# Kanonisches Feld -> Menge normalisierter Header-Varianten.
ALIASES: dict[str, set[str]] = {
    "tracking_id": {"trackingid", "trackingids"},
    "month": {"datumgeliefert", "datum", "monat", "monatjahr", "month", "date", "zeitraum"},
    "earnings": {
        "adgebuhren", "werbekostenerstattung", "einnahmen", "adfees",
        "earnings", "provision", "gebuhren", "ertrag",
    },
    # "umsatzvers" = "Umsatz (vers.)" (versendet/abgerechnet) -- kanonisches "revenue".
    # "Umsatz (best.)" (nur bestellt, vor Retouren) wird bewusst NICHT gemappt.
    "revenue": {"umsatz", "revenue", "umsatzeur", "umsatzvers"},
    "items_shipped": {
        "artikelgeliefert", "gelieferteartikel", "ausgelieferteartikel",
        "versendeteartikel", "shippeditems", "itemsshipped",
    },
    "ordered_items": {"bestellteartikel", "ordereditems"},
    "clicks": {"klicks", "clicks"},
    "returns": {"returns", "retouren", "ruckgaben", "ruckgabe"},
    "asin": {"asin", "itemasin"},
    "product_name": {"name", "artikelbezeichnung", "productname", "produktname"},
    "category": {"kategorie", "category"},
    "seller": {"verkaufer", "handler", "merchant", "seller"},
    "price": {"preis", "price"},
    "device_group": {"geratetypgruppe", "devicetypegroup", "geratetyp"},
    "commission_rate": {"empfehlungsvergutungssatz", "referralrate", "commissionrate"},
}

REQUIRED_FIELDS = ("tracking_id", "earnings")

# Felder, die als Zahl interpretiert werden.
NUMERIC_FIELDS = (
    "earnings", "revenue", "items_shipped", "returns",
    "clicks", "ordered_items", "price", "commission_rate",
)


def resolve_columns(headers: list[str]) -> dict[str, int]:
    """Header-Liste auf ``{kanonisches_feld: spaltenindex}`` abbilden.

    Das erste passende Header-Vorkommen je Feld gewinnt; unbekannte Spalten
    werden ignoriert.
    """
    norm = [normalize_header(h) for h in headers]
    mapping: dict[str, int] = {}
    for field, variants in ALIASES.items():
        for idx, nh in enumerate(norm):
            if nh and nh in variants:
                mapping[field] = idx
                break
    return mapping


# --- Wert-Parser ------------------------------------------------------------

_NUM_CLEAN = re.compile(r"[^0-9.\-]")


def parse_number(value) -> float:
    """Deutsche/englische Zahl robust nach float wandeln.

    Behandelt Waehrungszeichen, Tausenderpunkte, Dezimalkomma und negative
    Werte (Retouren). Leere/ungueltige Werte ergeben ``0.0``.
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return 0.0
    s = s.replace(" ", "").replace(" ", "")
    s = s.replace("EUR", "").replace("€", "").replace("$", "").replace("%", "")
    if "," in s and "." in s:
        # deutsches Format: Punkt = Tausender, Komma = Dezimal
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    s = _NUM_CLEAN.sub("", s)
    if s in ("", "-", ".", "-."):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


_MONTH_PATTERNS = (
    re.compile(r"^(\d{4})[-/.](\d{1,2})"),          # 2017-01, 2017/01, 2017-01-15
    re.compile(r"^(\d{1,2})[.](\d{1,2})[.](\d{4})"),  # 15.01.2017
    re.compile(r"^(\d{4})(\d{2})$"),                 # 201701
    re.compile(r"^(\d{1,2})-(\d{4})\b"),             # 01-2017 (Amazon "Monat/Jahr"-Export)
)


def parse_month(value) -> str | None:
    """Datums-/Monatswert auf ``YYYY-MM`` normalisieren (oder ``None``)."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    m = _MONTH_PATTERNS[0].match(s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = _MONTH_PATTERNS[1].match(s)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}"
    m = _MONTH_PATTERNS[2].match(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = _MONTH_PATTERNS[3].match(s)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    return None


def _cell(row: list, idx: int | None) -> str | None:
    if idx is None or idx >= len(row):
        return None
    return row[idx]


def normalize_rows(
    headers: list[str],
    rows,
    default_month: str | None = None,
) -> tuple[list[dict], dict]:
    """Rohzeilen in kanonische Item-Dicts wandeln.

    Gibt ``(items, stats)`` zurueck. ``stats`` enthaelt Zaehler (verarbeitet,
    ohne Monat, ohne Tracking-ID) fuer transparente Protokollierung.
    """
    cols = resolve_columns(headers)
    missing = [f for f in REQUIRED_FIELDS if f not in cols]
    if missing:
        raise ValueError(
            f"Pflichtspalten fehlen: {missing}. "
            f"Erkannte Spalten: {sorted(cols)}. Header waren: {headers}"
        )

    items: list[dict] = []
    stats = {"rows": 0, "no_tracking_id": 0, "no_month": 0}

    for row in rows:
        stats["rows"] += 1
        tid = (_cell(row, cols.get("tracking_id")) or "").strip()
        if not tid:
            stats["no_tracking_id"] += 1
            continue
        month = parse_month(_cell(row, cols.get("month"))) or default_month
        if not month:
            stats["no_month"] += 1

        item = {
            "tracking_id": tid,
            "month": month,
            "asin": (_cell(row, cols.get("asin")) or "").strip(),
            "product_name": (_cell(row, cols.get("product_name")) or "").strip(),
            "category": (_cell(row, cols.get("category")) or "").strip(),
            "seller": (_cell(row, cols.get("seller")) or "").strip(),
            "device_group": (_cell(row, cols.get("device_group")) or "").strip(),
        }
        for field in NUMERIC_FIELDS:
            item[field] = parse_number(_cell(row, cols.get(field)))
        items.append(item)

    return items, stats
