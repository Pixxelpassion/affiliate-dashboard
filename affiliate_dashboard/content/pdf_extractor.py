"""PDF-Textextraktion fuer den Content-Erstellungs-Bereich.

Liest den Volltext einer hochgeladenen Bedienungsanleitung (PDF) aus, damit
``article_generator.py`` daraus technische Daten extrahieren kann.
"""

from __future__ import annotations

import io

from pypdf import PdfReader


def extract_text(pdf_bytes: bytes) -> str:
    """Gibt den zusammengefuegten Text aller Seiten zurueck (Seiten durch Leerzeile
    getrennt). Seiten, aus denen sich kein Text extrahieren laesst (z. B. reine
    Bild-Scans ohne OCR-Schicht), tragen einfach nichts bei -- kein Fehler."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(p.strip() for p in pages if p.strip())
