"""SQLite-Persistenz fuer den Content-Erstellungs-Bereich (Testartikel-Generator).

Eigene Datenbank (``data/content.db``), analog ``seo_store.py``/``research_store.py``.
Rohdateien (Bilder, PDF) und zurechtgeschnittene Bilder liegen als echte Dateien unter
``data/content_uploads/<content_item_id>/`` (gitignored wie der Rest von ``data/``) --
``content_item_files`` haelt nur die Pfade fest, nicht die Bytes selbst.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS content_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tracking_id   TEXT NOT NULL,
    product_name  TEXT NOT NULL,
    status        TEXT NOT NULL,
    error_message TEXT,
    article_json  TEXT,
    wp_post_id    INTEGER,
    wp_edit_link  TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS content_item_files (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    content_item_id INTEGER NOT NULL,
    kind            TEXT NOT NULL,
    path            TEXT NOT NULL
);
"""


class ContentStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "ContentStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- Items --------------------------------------------------------------
    def create_item(self, tracking_id: str, product_name: str) -> int:
        cur = self.conn.execute(
            """INSERT INTO content_items (tracking_id, product_name, status, created_at)
               VALUES (?, ?, 'pending', ?)""",
            (tracking_id, product_name, datetime.utcnow().isoformat()),
        )
        self.conn.commit()
        return cur.lastrowid

    def set_status(self, item_id: int, status: str, error: str | None = None) -> None:
        self.conn.execute(
            "UPDATE content_items SET status = ?, error_message = ? WHERE id = ?",
            (status, error, item_id),
        )
        self.conn.commit()

    def set_article_draft(self, item_id: int, article: dict) -> None:
        """Speichert den generierten Artikel, OHNE status/wp-Felder anzufassen --
        damit ein spaeter fehlschlagender WordPress-Upload den teuren Gemini-Call
        nicht verwirft (der Artikel bleibt in der Review-Ansicht sichtbar)."""
        self.conn.execute(
            "UPDATE content_items SET article_json = ? WHERE id = ?",
            (json.dumps(article, ensure_ascii=False), item_id),
        )
        self.conn.commit()

    def set_result(self, item_id: int, article: dict, wp_post_id: int | None,
                    wp_edit_link: str | None) -> None:
        self.conn.execute(
            """UPDATE content_items
               SET status = 'done', article_json = ?, wp_post_id = ?, wp_edit_link = ?
               WHERE id = ?""",
            (json.dumps(article, ensure_ascii=False), wp_post_id, wp_edit_link, item_id),
        )
        self.conn.commit()

    def get_item(self, item_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM content_items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["article"] = json.loads(item["article_json"]) if item["article_json"] else None
        return item

    def list_items(self, tracking_id: str) -> list[dict]:
        rows = self.conn.execute(
            """SELECT id, tracking_id, product_name, status, error_message, wp_edit_link, created_at
               FROM content_items WHERE tracking_id = ? ORDER BY created_at DESC""",
            (tracking_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Dateien --------------------------------------------------------------
    def add_file(self, item_id: int, kind: str, path: str) -> None:
        self.conn.execute(
            "INSERT INTO content_item_files (content_item_id, kind, path) VALUES (?, ?, ?)",
            (item_id, kind, path),
        )
        self.conn.commit()

    def list_files(self, item_id: int, kind: str | None = None) -> list[dict]:
        if kind:
            rows = self.conn.execute(
                "SELECT id, content_item_id, kind, path FROM content_item_files "
                "WHERE content_item_id = ? AND kind = ? ORDER BY id",
                (item_id, kind),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT id, content_item_id, kind, path FROM content_item_files "
                "WHERE content_item_id = ? ORDER BY id",
                (item_id,),
            ).fetchall()
        return [dict(r) for r in rows]
