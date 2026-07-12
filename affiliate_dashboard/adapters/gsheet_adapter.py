"""Google-Sheet-Adapter (Bruecke bis zur S3-Anbindung).

Laedt die *veroeffentlichte* CSV-Export-URL des Sheets:
    https://docs.google.com/spreadsheets/d/<id>/export?format=csv&gid=<gid>

Voraussetzung: Das Sheet ist auf "Jeder mit dem Link kann ansehen" gestellt
(bzw. im Web veroeffentlicht). Google antwortet mit einem 307-Redirect auf einen
googleusercontent-Host; ``urllib`` folgt dem automatisch. Es werden nur Module
der Standardbibliothek verwendet (kein ``requests`` noetig).
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

from .base import IngestionAdapter, IngestResult
from .. import columns

_EXPORT_URL = "https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
_USER_AGENT = "Mozilla/5.0 (affiliate-dashboard; +https://localhost)"


class GSheetAdapter(IngestionAdapter):
    source = "gsheet"

    def load(self) -> IngestResult:
        gs = self.config.get("gsheet", {})
        sheet_id = (gs.get("sheet_id") or "").strip()
        gid = str(gs.get("gid") or "0").strip()
        if not sheet_id:
            raise ValueError(
                "config.json: gsheet.sheet_id fehlt. Sheet-ID aus der URL eintragen "
                "(docs.google.com/spreadsheets/d/<HIER>/edit) und das Sheet auf "
                "'Jeder mit dem Link kann ansehen' stellen."
            )

        url = _EXPORT_URL.format(sheet_id=sheet_id, gid=gid)
        text = self._fetch(url)
        self._save_snapshot(text, gid)

        reader = csv.reader(io.StringIO(text))
        try:
            headers = next(reader)
        except StopIteration:
            raise ValueError("Google Sheet lieferte keine Daten (leere CSV).")

        items, stats = columns.normalize_rows(headers, reader)
        return IngestResult(
            items=items,
            source=self.source,
            source_file=f"gsheet:{sheet_id}#{gid}",
            full_snapshot=True,
            stats=stats,
        )

    # --- intern -----------------------------------------------------------
    def _fetch(self, url: str) -> str:
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

    def _save_snapshot(self, text: str, gid: str) -> None:
        try:
            archive = self.config.path("archive_dir") / datetime.now().strftime("%Y-%m-%d")
            archive.mkdir(parents=True, exist_ok=True)
            path: Path = archive / f"gsheet-{gid}.csv"
            path.write_text(text, encoding="utf-8")
        except Exception:  # Snapshot ist optional, niemals den Lauf abbrechen
            pass
