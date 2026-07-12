"""Gemeinsames Adapter-Interface.

Jeder Adapter liefert ueber ``load()`` ein ``IngestResult`` mit normalisierten
Items (kanonisches Schema aus ``columns.py``) plus Metadaten. Ob die Quelle ein
Voll-Snapshot ist (``full_snapshot=True`` -> Store.replace_source) oder
inkrementell (``False`` -> Store.upsert_monthly), entscheidet der Adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from abc import ABC, abstractmethod


@dataclass
class IngestResult:
    items: list[dict]
    source: str
    source_file: str = ""
    full_snapshot: bool = True
    stats: dict = field(default_factory=dict)


class IngestionAdapter(ABC):
    #: Name der Quelle (gsheet/csv/s3)
    source: str = ""

    def __init__(self, config):
        self.config = config

    @abstractmethod
    def load(self) -> IngestResult:
        """Quelle einlesen und normalisierte Items zurueckgeben."""
        raise NotImplementedError
