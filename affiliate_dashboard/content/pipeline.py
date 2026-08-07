"""Hintergrund-Thread-Funktion der Content-Erstellung, analog
``seo.research_agent.start_project_audit()``: Bilder zuschneiden, PDF-Text
extrahieren, EIN Gemini-Call (Artikel + Bild-Fokuspunkte + Bewertungsbox),
WordPress-Upload. Jeder Schritt-Fehler fuehrt zu ``status='error'`` statt zu
einem haengenden Zustand (Lehre aus dem Gemini-Timeout-Vorfall, siehe
``gemini_client.py``)."""

from __future__ import annotations

import re
from pathlib import Path

from . import article_generator, image_processor, pdf_extractor, wordpress_client
from .content_store import ContentStore

_PLACEHOLDER_RE = re.compile(r"\[\[BILD:(\d+)\]\]")


def _place_gallery_images(body_html: str, media_by_index: dict, crops_by_index: dict) -> str:
    """Ersetzt von Gemini gesetzte ``[[BILD:<Index>]]``-Platzhalter durch echte
    Gutenberg-Bild-Bloecke (Keyvisual/Index 0 ausgenommen -- das wird separat als
    Beitragsbild gesetzt, nie inline eingebettet). Bilder, fuer die Gemini KEINEN
    Platzhalter gesetzt hat (oder ein falscher/doppelter Index vorkam), werden ans
    Ende angehaengt, statt sie stillschweigend verloren gehen zu lassen."""
    placed = set()

    def _replace(match: "re.Match") -> str:
        idx = int(match.group(1))
        media = media_by_index.get(idx)
        if idx == 0 or media is None or idx in placed:
            return ""
        placed.add(idx)
        crop = crops_by_index.get(idx, {})
        return wordpress_client.build_image_block_html(
            media["id"], media["source_url"], crop.get("alt_text", ""), crop.get("caption", ""),
        )

    body_html = _PLACEHOLDER_RE.sub(_replace, body_html)

    for idx, media in media_by_index.items():
        if idx == 0 or idx in placed:
            continue
        crop = crops_by_index.get(idx, {})
        body_html += wordpress_client.build_image_block_html(
            media["id"], media["source_url"], crop.get("alt_text", ""), crop.get("caption", ""),
        )
    return body_html


def run_content_item(item_id: int, content_db_path, tracking_id: str, site_base_url: str,
                      wp_username: str, wp_app_password: str, gemini_api_key: str) -> None:
    with ContentStore(content_db_path) as store:
        item = store.get_item(item_id)
        if item is None:
            return
        store.set_status(item_id, "processing")
        try:
            raw_images = [Path(f["path"]).read_bytes()
                          for f in store.list_files(item_id, "image_raw")]
            manual_files = store.list_files(item_id, "manual_pdf")
            manual_text = ""
            if manual_files:
                manual_text = pdf_extractor.extract_text(Path(manual_files[0]["path"]).read_bytes())

            context = article_generator.build_context(
                item["product_name"], tracking_id, site_base_url, manual_text, len(raw_images),
            )
            article = article_generator.generate_article(context, raw_images, gemini_api_key)
            store.set_article_draft(item_id, article)

            spec = image_processor.load_image_spec()
            crops_by_index = {c["index"]: c for c in article.get("image_crops", [])}
            img_format = spec.get("format", "webp")

            media_by_index = {}
            for idx, raw in enumerate(raw_images):
                crop = crops_by_index.get(idx, {})
                focus_x = crop.get("focus_x", 0.5)
                focus_y = crop.get("focus_y", 0.5)
                if idx == 0:
                    width, height = spec["keyvisual_width"], spec["keyvisual_height"]
                else:
                    width, height = spec["width"], spec["height"]
                cropped = image_processor.crop_and_resize(
                    raw, width, height, img_format, spec.get("quality", 85),
                    focus_x=focus_x, focus_y=focus_y,
                )
                filename = f"{tracking_id}-{item_id}-{idx}.{img_format}"
                cropped_path = Path(content_db_path).parent / "content_uploads" / str(item_id) / filename
                cropped_path.parent.mkdir(parents=True, exist_ok=True)
                cropped_path.write_bytes(cropped)
                store.add_file(item_id, "image_cropped", str(cropped_path))

                media = wordpress_client.upload_media(
                    site_base_url, wp_username, wp_app_password, cropped, filename,
                    mime_type=f"image/{img_format}",
                )
                media_by_index[idx] = media
                wordpress_client.update_media_metadata(
                    site_base_url, wp_username, wp_app_password, media["id"],
                    title=crop.get("title"), alt_text=crop.get("alt_text"),
                    caption=crop.get("caption"), description=crop.get("description"),
                )

            featured_media_id = media_by_index.get(0, {}).get("id")
            article["body_html"] = _place_gallery_images(article["body_html"], media_by_index, crops_by_index)
            post = wordpress_client.create_draft_post(
                site_base_url, wp_username, wp_app_password,
                article["title"], article["body_html"], featured_media_id,
                rank_math_title=article.get("meta_title"),
                rank_math_description=article.get("meta_description"),
                rank_math_focus_keyword=article.get("focus_keyword"),
            )
            store.set_result(item_id, article, post["id"], post["edit_link"])
        except Exception as exc:  # noqa: BLE001
            store.set_status(item_id, "error", str(exc))
