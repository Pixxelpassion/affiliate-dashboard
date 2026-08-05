"""Kernstueck der Content-Erstellung: Kontext-Bau + EIN Gemini-Call, der aus
Produktfotos + Anleitungs-Text + Knowledge-Base einen vollstaendigen Testartikel
als strukturiertes JSON erzeugt (inkl. Bild-Fokuspunkte fuer den Zuschnitt und
Bewertungsbox-Vorschlaegen fuer das manuelle Uebertragen ins Review-Plugin).

Verifiziert (siehe Session-Historie): Gemini unterstuetzt Google-Search-Grounding,
Bild-Input (multimodal) UND verschachtelten strukturierten JSON-Output
(``response_schema`` mit Arrays/Objekten) gleichzeitig in einem einzigen Call.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import yaml
from PIL import Image
from google.genai import types as genai_types

from .. import gemini_client

_KNOWLEDGE_ROOT = Path(__file__).resolve().parent / "knowledge"

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "meta_title": {"type": "string"},
        "meta_description": {"type": "string"},
        "focus_keyword": {"type": "string"},
        "body_html": {"type": "string"},
        "review_box": {
            "type": "object",
            "properties": {
                "overall_score": {"type": "number"},
                "sub_scores": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "category": {"type": "string"},
                            "score": {"type": "number"},
                        },
                        "required": ["category", "score"],
                    },
                },
                "pro": {"type": "array", "items": {"type": "string"}},
                "kontra": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["overall_score", "sub_scores", "pro", "kontra"],
        },
        "image_crops": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "focus_x": {"type": "number"},
                    "focus_y": {"type": "number"},
                },
                "required": ["index", "focus_x", "focus_y"],
            },
        },
    },
    "required": ["title", "meta_title", "meta_description", "focus_keyword",
                 "body_html", "review_box", "image_crops"],
}


def _read_md(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        _, fm_text, body = text.split("---", 2)
        frontmatter = yaml.safe_load(fm_text) or {}
        return frontmatter, body.strip()
    return {}, text.strip()


_UMLAUT_MAP = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})


def slugify_tracking_id(label: str) -> str:
    """Wandelt ein Produkt-Tab-Label (z. B. ``Tischkreissägen``) in den ASCII-Slug um,
    der als Ordnername unter ``knowledge/<slug>/`` erwartet wird (z. B. ``tischkreissaegen``)."""
    s = label.translate(_UMLAUT_MAP).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def load_knowledge(tracking_id: str) -> dict:
    """Liest Struktur-Regeln/Ton-of-Voice/Beispielartikel aus
    ``knowledge/<tracking_id>/`` (siehe CLAUDE.md-Analogie: eine Nische = ein Ordner)."""
    niche_dir = _KNOWLEDGE_ROOT / tracking_id
    _, structure_rules = _read_md(niche_dir / "structure_rules.md")
    _, tone_of_voice = _read_md(niche_dir / "tone_of_voice.md")
    examples = []
    examples_dir = niche_dir / "example_articles"
    if examples_dir.exists():
        for p in sorted(examples_dir.glob("*.md")):
            fm, body = _read_md(p)
            examples.append({
                "title": fm.get("title", p.stem),
                "note": fm.get("note", ""),
                "body": body,
            })
    return {
        "structure_rules": structure_rules,
        "tone_of_voice": tone_of_voice,
        "example_articles": examples,
    }


def build_context(product_name: str, tracking_id: str, site_base_url: str,
                   manual_text: str, num_images: int) -> dict:
    knowledge = load_knowledge(tracking_id)
    return {
        "product_name": product_name,
        "tracking_id": tracking_id,
        "site_base_url": site_base_url,
        "manual_text": manual_text,
        "num_images": num_images,
        **knowledge,
    }


def _build_system_instruction(context: dict) -> str:
    examples_text = "\n\n".join(
        f"### Beispielartikel: {ex['title']}" + (f" ({ex['note']})" if ex["note"] else "")
        + f"\n\n{ex['body']}"
        for ex in context["example_articles"]
    )
    return f"""Du bist Redakteur/in fuer Testartikel auf einer Amazon-Partnerprogramm-Ratgeberseite
({context['site_base_url']}). Du schreibst einen vollstaendigen Testartikel fuer ein neues Produkt,
exakt im Stil und in der Struktur der folgenden Vorgaben.

# Struktur-Regeln
{context['structure_rules']}

# Ton-of-Voice
{context['tone_of_voice']}

# Beispielartikel (Referenz fuer Struktur/Ton/Tiefe -- NICHT wortwoertlich uebernehmen,
es ist ein anderes Produkt)
{examples_text}

# Deine Aufgabe
1. Nutze die Google-Suche, um auf der Herstellerwebseite zusaetzliche technische
   Spezifikationen zu finden (falls sie aus der Anleitung unten fehlen), und um echte
   Nutzerbewertungen/Testberichte Dritter im Netz zu recherchieren (fuer den optionalen
   Kundenmeinungen-Abschnitt).
2. Erfinde NIEMALS technische Daten oder Bewertungen -- nur was aus der Anleitung, der
   Hersteller-Recherche oder gefundenen Bewertungen tatsaechlich hervorgeht. Fehlt eine
   Angabe, lass sie in der Tabelle weg, statt zu raten.
3. body_html: vollstaendiges HTML (h2/h3-Ueberschriften, Absaetze, die Technische-Daten-
   Tabelle als echte <table>, Listen wo passend) -- KEIN <h1> (der Titel wird separat als
   "title" ausgegeben), KEIN Markdown, reines HTML.
4. meta_title (<= 60 Zeichen) und meta_description (<= 155 Zeichen) fuer RankMath (werden
   manuell eingetragen, nicht automatisch per API), focus_keyword als wichtigstes Ziel-Keyword.
5. review_box: Gesamt-Score (0-10), Einzel-Scores passend zu den in der Artikelstruktur
   genannten Kategorien, sowie Pro-/Kontra-Stichpunkte -- wird manuell ins Bewertungs-Plugin
   uebertragen, nicht automatisch gesetzt.
6. image_crops: fuer JEDES der {context['num_images']} als Bild-Input uebergebenen Fotos
   (Reihenfolge = Index ab 0) den normierten Mittelpunkt (x,y, je 0-1) des interessanten
   Produkt-Motivs -- NICHT die Bildmitte, da die Fotos teils nicht zentriert aufgenommen sind.
"""


def _guess_mime_type(image_bytes: bytes) -> str:
    fmt = Image.open(io.BytesIO(image_bytes)).format or "JPEG"
    return f"image/{fmt.lower()}"


def _build_contents(context: dict, image_bytes_list: list[bytes]) -> list:
    contents: list = [
        genai_types.Part.from_bytes(data=img_bytes, mime_type=_guess_mime_type(img_bytes))
        for img_bytes in image_bytes_list
    ]
    manual_section = context["manual_text"] or "(keine Anleitung hochgeladen / kein Text extrahierbar)"
    contents.append(
        f"""Produktname: {context['product_name']}

Extrahierter Text der Bedienungsanleitung:
{manual_section}

Anzahl uebergebener Produktfotos: {context['num_images']} (siehe oben als Bild-Input,
Reihenfolge = image_crops-Index ab 0)."""
    )
    return contents


def generate_article(context: dict, image_bytes_list: list[bytes], api_key: str) -> dict:
    """EIN Gemini-Call: Search-Grounding + Bild-Input + strukturierter JSON-Output.
    Gibt das Schema-Dict zurueck, ergaenzt um ``sources`` (Grounding-Quellen)."""
    system_instruction = _build_system_instruction(context)
    contents = _build_contents(context, image_bytes_list)
    article, sources = gemini_client.generate(
        contents, system_instruction, api_key,
        search=True, response_schema=_RESPONSE_SCHEMA, max_output_tokens=16000,
    )
    article["sources"] = sources
    return article
