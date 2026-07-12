"""Roh-Items zu Monats-/Tracking-ID-Summen aggregieren."""

from __future__ import annotations

_SUM_FIELDS = ("earnings", "revenue", "items_shipped", "returns", "clicks", "ordered_items")


def aggregate_monthly(items: list[dict]) -> list[dict]:
    """Items nach ``(month, tracking_id)`` gruppieren und Kennzahlen summieren.

    Items ohne Monat werden uebersprungen (sie koennen keiner Monatszelle
    zugeordnet werden). Negative Werte (Retouren) mindern die Summen korrekt.
    """
    buckets: dict[tuple[str, str], dict] = {}
    for it in items:
        month = it.get("month")
        if not month:
            continue
        key = (month, it["tracking_id"])
        agg = buckets.get(key)
        if agg is None:
            agg = {"month": month, "tracking_id": it["tracking_id"], "rows": 0}
            for field in _SUM_FIELDS:
                agg[field] = 0.0
            buckets[key] = agg
        agg["rows"] += 1
        for field in _SUM_FIELDS:
            agg[field] += float(it.get(field) or 0.0)

    rows = list(buckets.values())
    # Geldbetraege auf Cent runden (Float-Summen-Drift vermeiden)
    for r in rows:
        r["earnings"] = round(r["earnings"], 2)
        r["revenue"] = round(r["revenue"], 2)
        r["items_shipped"] = round(r["items_shipped"], 3)
        r["returns"] = round(r["returns"], 3)
    rows.sort(key=lambda r: (r["month"], r["tracking_id"]))
    return rows
