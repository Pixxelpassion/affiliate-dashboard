"""Bild-Zuschnitt fuer den Content-Erstellungs-Bereich.

Liest die Crop-Vorgaben aus ``knowledge/image_spec.md`` (YAML-Frontmatter), schneidet
Rohbilder auf die Zielmasse zu -- zentriert auf einen vorgegebenen Motiv-Mittelpunkt
(normierte Koordinaten, z. B. von Gemini geschaetzt -- siehe article_generator.py),
NICHT stur auf die Bildmitte, da Produktfotos oft nicht zentriert aufgenommen sind
("aus der Hüfte geschossen").
"""

from __future__ import annotations

import io
from pathlib import Path

import yaml
from PIL import Image

_IMAGE_SPEC_PATH = Path(__file__).resolve().parent / "knowledge" / "image_spec.md"


def load_image_spec() -> dict:
    """Liest die YAML-Frontmatter aus ``knowledge/image_spec.md``."""
    text = _IMAGE_SPEC_PATH.read_text(encoding="utf-8")
    _, frontmatter, _ = text.split("---", 2)
    return yaml.safe_load(frontmatter)


def crop_and_resize(image_bytes: bytes, target_width: int, target_height: int,
                     fmt: str = "webp", quality: int = 85,
                     focus_x: float = 0.5, focus_y: float = 0.5) -> bytes:
    """Schneidet auf das Ziel-Seitenverhaeltnis zu (zentriert auf ``focus_x``/
    ``focus_y``, normierte Koordinaten 0-1 -- Default 0.5/0.5 = Bildmitte), skaliert
    auf die Zielmasse, speichert im Zielformat. Gibt die encodierten Bild-Bytes zurueck.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    src_w, src_h = img.size
    target_ratio = target_width / target_height
    src_ratio = src_w / src_h

    if src_ratio > target_ratio:
        crop_h = src_h
        crop_w = int(round(crop_h * target_ratio))
    else:
        crop_w = src_w
        crop_h = int(round(crop_w / target_ratio))

    center_x = focus_x * src_w
    center_y = focus_y * src_h
    left = max(0, min(src_w - crop_w, center_x - crop_w / 2))
    top = max(0, min(src_h - crop_h, center_y - crop_h / 2))

    cropped = img.crop((int(left), int(top), int(left) + crop_w, int(top) + crop_h))
    resized = cropped.resize((target_width, target_height), Image.LANCZOS)

    out = io.BytesIO()
    resized.save(out, format=fmt.upper(), quality=quality)
    return out.getvalue()
