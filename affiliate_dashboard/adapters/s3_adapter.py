"""S3-Data-Feed-Adapter (vorbereiteter Stub).

Amazons offizieller Activity-Report-Feed muss beim Amazon-Partner-Support
beantragt werden; du erhaeltst eigene Feed-Credentials (NICHT aus der AWS-Konsole).
Der Feed besteht aus vier Dateitypen je Zeitraum:
    * Orders   - bei Bestellung
    * Earnings - bei Versand (enthaelt die Provision -> Haupteinnahmen)
    * Tracking - Klicks
    * Bounty   - Praemien (Prime/Audible/Abos)

Sobald die Credentials vorliegen: ``config.json`` -> ``s3`` ausfuellen und
``source: "s3"`` setzen. Die Normalisierung laeuft anschliessend ueber denselben
``columns.resolve_columns()``-Weg wie die anderen Quellen.
"""

from __future__ import annotations

from .base import IngestionAdapter, IngestResult


class S3Adapter(IngestionAdapter):
    source = "s3"

    def load(self) -> IngestResult:
        s3 = self.config.get("s3", {})
        if not s3.get("bucket"):
            raise ValueError(
                "S3 ist noch nicht konfiguriert. Trage in config.json unter 's3' "
                "Bucket/Prefix/Region und die vom Amazon-Partner-Support erhaltenen "
                "Credentials ein. Bis dahin nutze source='gsheet' oder source='csv'."
            )
        raise NotImplementedError(
            "Der S3-Adapter ist vorbereitet, aber noch nicht scharf geschaltet. "
            "Aktivierung nach Zuteilung des Activity-Report-Feeds: boto3-Client aus "
            "config['s3'] erstellen, per list_objects_v2 die Earnings-/Bounty-/"
            "Tracking-Dateien laden, mit columns.normalize_rows() normalisieren und "
            "als IngestResult(full_snapshot=...) zurueckgeben."
        )
