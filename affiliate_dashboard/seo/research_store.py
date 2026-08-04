"""SQLite-Persistenz fuer den Recherche-Bereich (Mehr-Nischen-Audits + Dialog).

Eigene Datenbank (``data/research.db``), getrennt von ``settings.db`` (Zugangsdaten/
Konfiguration -- Projekt-Stammdaten leben in ``settings_store.py``) und von ``seo.db``
(Rohdaten des globalen SEO-Monitorings). Enthaelt nur erfolgreich abgeschlossene Audits;
ein fehlgeschlagener Lauf landet als projekt-gescopter Meta-Key in ``settings_store``.

Tabellen:
    research_audits   -- (id, research_project_id, created_at, digest_json)
    research_messages -- (id, audit_id, role, content, sources_json, created_at)

Erste Zeile in ``research_messages`` je Audit (``role='assistant'``) ist der generierte
Bericht selbst -- der Dialog-Thread ist damit von Anfang an einheitlich modelliert.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_audits (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    research_project_id  INTEGER NOT NULL,
    created_at           TEXT NOT NULL,
    digest_json          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id     INTEGER NOT NULL,
    role         TEXT NOT NULL,
    content      TEXT NOT NULL,
    sources_json TEXT,
    created_at   TEXT NOT NULL
);

-- Manuell hochgeladene SE-Ranking-CSV-Exporte je Projekt+Kategorie (Alternative zu
-- den Live-API-Aufrufen, falls keine Credits verfuegbar sind). Ein Re-Upload ersetzt
-- den vorherigen Import komplett (kein Verlauf noetig, immer der neueste Stand zaehlt).
CREATE TABLE IF NOT EXISTS research_csv_imports (
    research_project_id INTEGER NOT NULL,
    kind                 TEXT NOT NULL,
    uploaded_at          TEXT NOT NULL,
    data_json            TEXT NOT NULL,
    PRIMARY KEY (research_project_id, kind)
);
"""


class ResearchStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "ResearchStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- Audits -----------------------------------------------------------------
    def create_audit(self, project_id: int, digest: dict, report_text: str,
                      sources: list[dict] | None = None) -> int:
        """Legt Audit + erste ``assistant``-Nachricht (der Bericht) an. Gibt audit_id zurueck."""
        now = datetime.utcnow().isoformat()
        cur = self.conn.execute(
            "INSERT INTO research_audits (research_project_id, created_at, digest_json) VALUES (?, ?, ?)",
            (project_id, now, json.dumps(digest, ensure_ascii=False)),
        )
        audit_id = cur.lastrowid
        self.conn.execute(
            """INSERT INTO research_messages (audit_id, role, content, sources_json, created_at)
               VALUES (?, 'assistant', ?, ?, ?)""",
            (audit_id, report_text, json.dumps(sources or [], ensure_ascii=False), now),
        )
        self.conn.commit()
        return audit_id

    def get_audit(self, audit_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT id, research_project_id, created_at, digest_json FROM research_audits WHERE id = ?",
            (audit_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "research_project_id": row["research_project_id"],
            "created_at": row["created_at"],
            "digest": json.loads(row["digest_json"]),
        }

    def list_audits(self, project_id: int) -> list[dict]:
        rows = self.conn.execute(
            """SELECT id, research_project_id, created_at FROM research_audits
               WHERE research_project_id = ? ORDER BY created_at DESC""",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Nachrichten (Dialog-Thread) ---------------------------------------------
    def add_message(self, audit_id: int, role: str, content: str,
                     sources: list[dict] | None = None) -> int:
        cur = self.conn.execute(
            """INSERT INTO research_messages (audit_id, role, content, sources_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (audit_id, role, content, json.dumps(sources or [], ensure_ascii=False),
             datetime.utcnow().isoformat()),
        )
        self.conn.commit()
        return cur.lastrowid

    def list_messages(self, audit_id: int) -> list[dict]:
        rows = self.conn.execute(
            """SELECT id, audit_id, role, content, sources_json, created_at
               FROM research_messages WHERE audit_id = ? ORDER BY id""",
            (audit_id,),
        ).fetchall()
        return [
            {"id": r["id"], "audit_id": r["audit_id"], "role": r["role"], "content": r["content"],
             "sources": json.loads(r["sources_json"]) if r["sources_json"] else [],
             "created_at": r["created_at"]}
            for r in rows
        ]

    # --- CSV-Importe (Alternative zur Live-API) --------------------------------
    def set_csv_import(self, project_id: int, kind: str, data) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO research_csv_imports
               (research_project_id, kind, uploaded_at, data_json) VALUES (?, ?, ?, ?)""",
            (project_id, kind, datetime.utcnow().isoformat(), json.dumps(data, ensure_ascii=False)),
        )
        self.conn.commit()

    def get_csv_import(self, project_id: int, kind: str) -> dict | None:
        row = self.conn.execute(
            """SELECT uploaded_at, data_json FROM research_csv_imports
               WHERE research_project_id = ? AND kind = ?""",
            (project_id, kind),
        ).fetchone()
        if row is None:
            return None
        return {"uploaded_at": row["uploaded_at"], "data": json.loads(row["data_json"])}

    def list_csv_imports(self, project_id: int) -> list[dict]:
        rows = self.conn.execute(
            """SELECT kind, uploaded_at FROM research_csv_imports
               WHERE research_project_id = ? ORDER BY kind""",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]
