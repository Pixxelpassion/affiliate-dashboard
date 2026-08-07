"""WordPress-REST-Client (Basic Auth mit Application Password).

Nutzt nur die Python-Standardbibliothek (``urllib``), wie der Rest des Projekts.
Medien-Upload nutzt den von der WP-REST-API dokumentierten Weg fuer rohe Bytes
(``Content-Disposition``-Header statt multipart/form-data) -- einfacher als ein
manuell gebautes multipart-Encoding.

Kein RankMath-Meta-Write in dieser Iteration (siehe Plan): RankMath gibt seine
SEO-Felder standardmaessig nicht fuer die REST-API frei.
"""

from __future__ import annotations

import base64
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def _auth_header(username: str, app_password: str) -> str:
    token = base64.b64encode(f"{username}:{app_password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _request(url: str, username: str, app_password: str, *, method: str = "GET",
             data: bytes | None = None, headers: dict | None = None, timeout: int = 60) -> dict:
    all_headers = {"Authorization": _auth_header(username, app_password)}
    all_headers.update(headers or {})
    req = Request(url, data=data, headers=all_headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"WordPress-API-Fehler {exc.code} bei {url}: {body}") from exc


def test_connection(wp_url: str, username: str, app_password: str) -> dict:
    """Fragt ``/wp/v2/users/me`` ab (erfordert gueltige Auth) -- zur Diagnose von
    401-Fehlern: unterscheidet zwischen "Zugangsdaten greifen gar nicht" (Anfrage
    wird als ANONYM behandelt, daher fehlende Rechte unabhaengig von der eigentlich
    gemeinten Nutzerrolle) und "Zugangsdaten greifen, aber Rolle reicht nicht".
    ``context=edit`` liefert die vollen Capabilities mit, nicht nur oeffentliche Felder.
    Gibt ``{"id", "name", "slug", "roles", "can_upload_files", "can_publish_posts"}``
    zurueck."""
    url = f"{wp_url.rstrip('/')}/wp-json/wp/v2/users/me?context=edit"
    result = _request(url, username, app_password, method="GET")
    capabilities = result.get("capabilities", {})
    return {
        "id": result.get("id"),
        "name": result.get("name"),
        "slug": result.get("slug"),
        "roles": result.get("roles", []),
        "can_upload_files": bool(capabilities.get("upload_files")),
        "can_publish_posts": bool(capabilities.get("publish_posts") or capabilities.get("edit_posts")),
    }


def upload_media(wp_url: str, username: str, app_password: str, image_bytes: bytes,
                  filename: str, mime_type: str = "image/webp") -> int:
    """Laedt ein Bild in die WordPress-Mediathek hoch, gibt die Medien-ID zurueck."""
    url = f"{wp_url.rstrip('/')}/wp-json/wp/v2/media"
    headers = {
        "Content-Type": mime_type,
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    result = _request(url, username, app_password, method="POST", data=image_bytes, headers=headers)
    return result["id"]


def update_media_metadata(wp_url: str, username: str, app_password: str, media_id: int, *,
                           title: str | None = None, alt_text: str | None = None,
                           caption: str | None = None, description: str | None = None) -> None:
    """Setzt Titel/Alt-Text/Beschriftung/Beschreibung eines bereits hochgeladenen
    Mediums nachtraeglich (zweiter Aufruf, da der Roh-Byte-Upload in ``upload_media()``
    keine zusaetzlichen Felder in derselben Anfrage transportieren kann -- der
    REST-Standard-Weg dafuer ist ein Update per ID, derselbe Mechanismus wie beim
    Aktualisieren eines Beitrags)."""
    payload = {}
    if title is not None:
        payload["title"] = title
    if alt_text is not None:
        payload["alt_text"] = alt_text
    if caption is not None:
        payload["caption"] = caption
    if description is not None:
        payload["description"] = description
    if not payload:
        return
    url = f"{wp_url.rstrip('/')}/wp-json/wp/v2/media/{media_id}"
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    _request(url, username, app_password, method="POST", data=data, headers=headers)


def create_draft_post(wp_url: str, username: str, app_password: str, title: str,
                       body_html: str, featured_media_id: int | None = None) -> dict:
    """Legt einen Entwurf an. Gibt ``{"id": ..., "edit_link": ...}`` zurueck."""
    url = f"{wp_url.rstrip('/')}/wp-json/wp/v2/posts"
    payload = {"title": title, "content": body_html, "status": "draft"}
    if featured_media_id is not None:
        payload["featured_media"] = featured_media_id
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    result = _request(url, username, app_password, method="POST", data=data, headers=headers)
    post_id = result["id"]
    edit_link = f"{wp_url.rstrip('/')}/wp-admin/post.php?post={post_id}&action=edit"
    return {"id": post_id, "edit_link": edit_link}
