"""Ingestion-Adapter: gemeinsames Interface, austauschbare Quellen."""

from .base import IngestionAdapter, IngestResult
from .gsheet_adapter import GSheetAdapter
from .csv_adapter import CsvAdapter
from .s3_adapter import S3Adapter


def get_adapter(source: str, config):
    """Adapter-Instanz fuer den Quellnamen aus der Konfiguration liefern."""
    source = (source or "").lower()
    if source == "gsheet":
        return GSheetAdapter(config)
    if source == "csv":
        return CsvAdapter(config)
    if source == "s3":
        return S3Adapter(config)
    raise ValueError(f"Unbekannte Quelle: {source!r} (erlaubt: gsheet, csv, s3)")


__all__ = [
    "IngestionAdapter", "IngestResult", "get_adapter",
    "GSheetAdapter", "CsvAdapter", "S3Adapter",
]
