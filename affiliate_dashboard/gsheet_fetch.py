"""Gemeinsame CSV-Fetch-Mechanik fuer veroeffentlichte Google-Sheet-Tabs.

Laedt die *veroeffentlichte* CSV-Export-URL eines einzelnen Tabs (gid):
    https://docs.google.com/spreadsheets/d/<id>/export?format=csv&gid=<gid>

Voraussetzung: Das Sheet ist auf "Jeder mit dem Link kann ansehen" gestellt
(bzw. im Web veroeffentlicht). Google antwortet mit einem 307-Redirect auf einen
googleusercontent-Host; ``urllib`` folgt dem automatisch. Es werden nur Module
der Standardbibliothek verwendet (kein ``requests`` noetig).

Wird sowohl vom bestehenden Umsatz-Import (``adapters/gsheet_adapter.py``) als
auch vom Produkt-Katalog-Reader (``products/catalog_reader.py``) genutzt.
"""

from __future__ import annotations

from urllib.request import Request, urlopen

_EXPORT_URL = "https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
_USER_AGENT = "Mozilla/5.0 (affiliate-dashboard; +https://localhost)"


def fetch_csv(sheet_id: str, gid: str) -> str:
    """Laedt einen einzelnen Sheet-Tab (gid) als CSV-Text."""
    url = _EXPORT_URL.format(sheet_id=sheet_id, gid=gid)
    req = Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urlopen(req, timeout=120) as resp:  # folgt 30x-Redirects automatisch
            raw = resp.read()
    except Exception as exc:  # noqa: BLE001 - verstaendliche Meldung weiterreichen
        raise RuntimeError(
            f"Abruf des Google Sheets fehlgeschlagen ({exc}). Pruefe, ob das "
            f"Sheet veroeffentlicht/link-lesbar ist und sheet_id/gid stimmen."
        ) from exc
    # Google liefert UTF-8 (teils mit BOM)
    return raw.decode("utf-8-sig", errors="replace")
