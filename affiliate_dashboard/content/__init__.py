"""Content-Erstellung (Testartikel-Generator).

Eigenstaendiges Unterpaket: aus hochgeladenen Produktfotos + Bedienungsanleitung (PDF)
wird ein vollstaendiger Testartikel als WordPress-Entwurf erzeugt (Bild-Zuschnitt,
PDF-Extraktion, Web-Recherche via Gemini-Search-Grounding, WordPress-REST-Upload).
Knowledge Base (Ton-of-Voice/Struktur-Regeln/Beispielartikel) liegt pro Tracking-ID
unter ``content/knowledge/<tracking_id>/``, Bild-Zuschnitt-Vorgaben global unter
``content/knowledge/image_spec.md``.
"""
