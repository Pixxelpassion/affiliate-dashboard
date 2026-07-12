"""Konfiguration laden und Pfade aufloesen.

Liest ``config.json`` aus dem Projektordner (eine Ebene ueber diesem Paket) und
mischt sie ueber die Standardwerte. Relative Pfade (db_path, inbox_dir, ...) werden
gegen den Projektordner aufgeloest, damit das Tool unabhaengig vom aktuellen
Arbeitsverzeichnis funktioniert.
"""

from __future__ import annotations

import json
from pathlib import Path

# Projektordner = .../affiliate-dashboard  (Elternverzeichnis dieses Pakets)
BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "source": "gsheet",
    "marketplace": "amazon.de",
    "currency": "EUR",
    "gsheet": {"sheet_id": "", "gid": "0"},
    "inbox_dir": "data/inbox",
    "archive_dir": "data/archive",
    "db_path": "data/affiliate.db",
    "out_file": "dashboard.html",
    "open_browser": True,
    "detail_top_n": 500,
    "s3": {
        "bucket": "",
        "prefix": "",
        "region": "eu-west-1",
        "aws_access_key_id": "",
        "aws_secret_access_key": "",
    },
    "seo": {
        "enabled": False,
        "db_path": "data/seo.db",
        "google": {
            "client_secret_path": "seo_client_secret.json",
            "token_path": "data/google_token.json",
        },
        "gsc": {"property": ""},
        "ga4": {"property_id": ""},
        "seranking": {"api_key": "", "project_id": ""},
        "pages": [],
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


class Config:
    """Geladene Konfiguration mit aufgeloesten Pfaden."""

    def __init__(self, data: dict):
        self._data = data

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        cfg_path = Path(path) if path else (BASE_DIR / "config.json")
        data = dict(DEFAULTS)
        if cfg_path.exists():
            with open(cfg_path, "r", encoding="utf-8") as fh:
                data = _deep_merge(DEFAULTS, json.load(fh))
        return cls(data)

    @classmethod
    def from_settings_store(cls, store) -> "Config":
        """Config aus der DB-gestuetzten ``SettingsStore`` bauen (Server-Betrieb),
        statt aus ``config.json`` zu lesen (lokaler Betrieb ohne Server)."""
        return cls(store.to_config_dict(DEFAULTS))

    # --- bequemer Zugriff -------------------------------------------------
    def __getitem__(self, key):
        return self._data[key]

    def get(self, key, default=None):
        return self._data.get(key, default)

    def path(self, key: str) -> Path:
        """Loest einen Pfad-Wert relativ zum Projektordner auf."""
        value = Path(self._data[key])
        return value if value.is_absolute() else (BASE_DIR / value)
