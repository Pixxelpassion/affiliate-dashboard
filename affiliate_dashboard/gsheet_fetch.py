"""Gemeinsame Fetch-Mechanik fuer veroeffentlichte Google-Sheet-Tabs (CSV + XLSX).

Laedt die *veroeffentlichte* Export-URL eines einzelnen Tabs (gid):
    https://docs.google.com/spreadsheets/d/<id>/export?format=csv&gid=<gid>
    https://docs.google.com/spreadsheets/d/<id>/export?format=xlsx&gid=<gid>

Voraussetzung: Das Sheet ist auf "Jeder mit dem Link kann ansehen" gestellt
(bzw. im Web veroeffentlicht). Google antwortet mit einem 307-Redirect auf einen
googleusercontent-Host; ``urllib`` folgt dem automatisch. Es werden nur Module
der Standardbibliothek verwendet (kein ``requests`` noetig).

Wird vom bestehenden Umsatz-Import (``adapters/gsheet_adapter.py``, CSV) sowie
vom Produkt-Katalog-Reader (``products/catalog_reader.py``, XLSX) genutzt. XLSX
statt CSV fuer den Produkt-Katalog, weil CSV keine Zell-Hyperlinks mitfuehrt --
manche Produkt-Tabs haben den Link zum Testartikel nicht in einer eigenen
Spalte, sondern direkt auf dem Produktnamen verlinkt.
"""

from __future__ import annotations

from urllib.request import Request, urlopen

_EXPORT_URL_CSV = "https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
_EXPORT_URL_XLSX = "https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx&gid={gid}"
_USER_AGENT = "Mozilla/5.0 (affiliate-dashboard; +https://localhost)"


def _fetch_bytes(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urlopen(req, timeout=120) as resp:  # folgt 30x-Redirects automatisch
            return resp.read()
    except Exception as exc:  # noqa: BLE001 - verstaendliche Meldung weiterreichen
        raise RuntimeError(
            f"Abruf des Google Sheets fehlgeschlagen ({exc}). Pruefe, ob das "
            f"Sheet veroeffentlicht/link-lesbar ist und sheet_id/gid stimmen."
        ) from exc


def fetch_csv(sheet_id: str, gid: str) -> str:
    """Laedt einen einzelnen Sheet-Tab (gid) als CSV-Text."""
    raw = _fetch_bytes(_EXPORT_URL_CSV.format(sheet_id=sheet_id, gid=gid))
    # Google liefert UTF-8 (teils mit BOM)
    return raw.decode("utf-8-sig", errors="replace")


def fetch_xlsx(sheet_id: str, gid: str) -> bytes:
    """Laedt einen einzelnen Sheet-Tab (gid) als XLSX-Bytes (behaelt Zell-Hyperlinks,
    anders als der CSV-Export)."""
    return _fetch_bytes(_EXPORT_URL_XLSX.format(sheet_id=sheet_id, gid=gid))
