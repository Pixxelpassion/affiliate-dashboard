"""Flask-Wrapper: liefert die generierte ``dashboard.html`` aus, bietet einen
Sync-Trigger, eine DB-gestuetzte Einstellungsseite und die SEO-Events-API.

Lokal:  python server.py                 (Flask-Dev-Server)
Server: gunicorn -w 4 affiliate_dashboard.server:app   (siehe README "Deployment auf Hostinger")

Env-Vars:
    DASHBOARD_USER            -- Basic-Auth-Benutzername
    DASHBOARD_PASSWORD_HASH   -- Basic-Auth-Passwort-Hash (werkzeug.security.generate_password_hash)
    PORT                      -- lokaler Dev-Server-Port (Standard 5050)

Ohne gesetzte ``DASHBOARD_USER``/``DASHBOARD_PASSWORD_HASH`` ist der Zugriff (nur fuer
lokale Entwicklung!) ungeschuetzt -- im Produktivbetrieb MUESSEN beide Env-Vars gesetzt sein.
"""

from __future__ import annotations

import os
import threading

from flask import Flask, Response, jsonify, redirect, render_template_string, request, send_from_directory
from werkzeug.security import check_password_hash

from .config import BASE_DIR, Config
from .run import run_once
from .settings_store import SettingsStore

app = Flask(__name__)

_SETTINGS_DB = BASE_DIR / "data" / "settings.db"
_sync_lock = threading.Lock()
_sync_running = False
_last_sync_result: dict = {}


def _store() -> SettingsStore:
    return SettingsStore(_SETTINGS_DB)


def _cfg() -> Config:
    with _store() as store:
        return Config.from_settings_store(store)


# --- Basic Auth ----------------------------------------------------------------

def _auth_configured() -> bool:
    return bool(os.environ.get("DASHBOARD_USER")) and bool(os.environ.get("DASHBOARD_PASSWORD_HASH"))


def _check_auth(username: str, password: str) -> bool:
    expected_user = os.environ.get("DASHBOARD_USER", "")
    expected_hash = os.environ.get("DASHBOARD_PASSWORD_HASH", "")
    return username == expected_user and check_password_hash(expected_hash, password)


@app.before_request
def _require_auth():
    if not _auth_configured():
        return None  # nur lokale Entwicklung ohne Env-Vars
    auth = request.authorization
    if not auth or not _check_auth(auth.username, auth.password):
        return Response(
            "Login erforderlich", 401,
            {"WWW-Authenticate": 'Basic realm="Affiliate Dashboard"'},
        )
    return None


# --- Dashboard -------------------------------------------------------------------

@app.route("/")
def index():
    cfg = _cfg()
    out_path = cfg.path("out_file")
    if not out_path.exists():
        return (
            "Noch kein Dashboard generiert. Unter /settings Zugangsdaten eintragen, "
            "dann POST /api/sync ausloesen (z. B. per Cron oder curl).", 404,
        )
    return send_from_directory(out_path.parent, out_path.name)


@app.route("/api/sync", methods=["POST"])
def api_sync():
    if not _sync_lock.acquire(blocking=False):
        return jsonify({"status": "already_running"}), 409

    def _worker():
        global _last_sync_result
        try:
            cfg = _cfg()
            _last_sync_result = {"status": "ok", **run_once(cfg)}
        except Exception as exc:  # noqa: BLE001
            _last_sync_result = {"status": "error", "message": str(exc)}
        finally:
            _sync_lock.release()

    threading.Thread(target=_worker, daemon=True).start()
    return jsonify({"status": "started"}), 202


@app.route("/api/status")
def api_status():
    cfg = _cfg()
    return jsonify({
        "dashboard_exists": cfg.path("out_file").exists(),
        "sync_running": _sync_lock.locked(),
        "last_sync": _last_sync_result,
        "seo_enabled": bool(cfg.get("seo", {}).get("enabled")),
    })


# --- SEO-Events-API (ersetzt die fruehere localStorage-Loesung) ------------------

@app.route("/api/seo/events", methods=["GET"])
def api_seo_events_list():
    page = request.args.get("page")
    with _store() as store:
        return jsonify(store.list_events(page))


@app.route("/api/seo/events", methods=["POST"])
def api_seo_events_add():
    data = request.get_json(force=True, silent=True) or {}
    page = str(data.get("page", "")).strip()
    date = str(data.get("date", "")).strip()
    text = str(data.get("text", "")).strip()
    if not page or not date or not text:
        return jsonify({"error": "page, date und text sind erforderlich"}), 400
    with _store() as store:
        event_id = store.add_event(page, date, text)
    return jsonify({"id": event_id, "page": page, "date": date, "text": text}), 201


@app.route("/api/seo/events/<int:event_id>", methods=["DELETE"])
def api_seo_events_delete(event_id: int):
    with _store() as store:
        store.delete_event(event_id)
    return jsonify({"status": "deleted"})


# --- Einstellungsseite (serverseitig gerendertes Formular, kein JS noetig) -------

_SETTINGS_TEMPLATE = """
<!doctype html><html lang="de"><head><meta charset="utf-8">
<title>Einstellungen – Affiliate-Dashboard</title>
<style>
body{font-family:'Segoe UI',system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem;color:#1a202c}
h1{font-size:1.4rem} h2{font-size:1.1rem;margin-top:2rem;border-bottom:1px solid #e6e8e1;padding-bottom:.3rem}
label{display:block;margin-top:.9rem;font-size:.85rem;color:#4b5563}
input[type=text],input[type=password]{width:100%;padding:.5rem .65rem;border:1px solid #d1d5db;border-radius:6px;font-size:.95rem;margin-top:.25rem}
button{margin-top:1.2rem;padding:.55rem 1.1rem;border-radius:6px;border:1px solid #717e21;background:#b7cb3a;font-weight:600;cursor:pointer}
table{width:100%;border-collapse:collapse;margin-top:.6rem;font-size:.88rem}
td,th{text-align:left;padding:.4rem .5rem;border-bottom:1px solid #e6e8e1}
.small-btn{padding:.3rem .6rem;font-size:.8rem;background:#fff;border:1px solid #d1d5db}
.flash{background:#eef7e1;border:1px solid #b7cb3a;padding:.6rem 1rem;border-radius:6px;margin-bottom:1rem}
</style></head><body>
<h1>Einstellungen</h1>
{% if saved %}<div class="flash">Gespeichert.</div>{% endif %}

<form method="post" action="/settings">
  <h2>Amazon PartnerNet (Google Sheet)</h2>
  <label>Marketplace <input type="text" name="marketplace" value="{{ s.get('marketplace','') }}"></label>
  <label>Währung <input type="text" name="currency" value="{{ s.get('currency','') }}"></label>
  <label>Google-Sheet-ID <input type="text" name="gsheet_sheet_id" value="{{ s.get('gsheet_sheet_id','') }}"></label>
  <label>Sheet-Tab-ID (gid) <input type="text" name="gsheet_gid" value="{{ s.get('gsheet_gid','') }}"></label>

  <h2>SEO-Monitoring</h2>
  <label><input type="checkbox" name="seo_enabled" {{ 'checked' if s.get('seo_enabled')=='true' else '' }}> Aktiviert</label>
  <label>GSC-Property <input type="text" name="gsc_property" value="{{ s.get('gsc_property','') }}" placeholder="https://example.de/"></label>
  <label>GA4-Property-ID <input type="text" name="ga4_property_id" value="{{ s.get('ga4_property_id','') }}" placeholder="properties/123456789"></label>
  <label>SE-Ranking API-Key <input type="password" name="seranking_api_key" value="{{ s.get('seranking_api_key','') }}"></label>
  <label>SE-Ranking Projekt-ID <input type="text" name="seranking_project_id" value="{{ s.get('seranking_project_id','') }}"></label>

  <button type="submit">Speichern</button>
</form>

<h2>SEO-Watchlist (Seiten + Keywords)</h2>
<table>
  <tr><th>URL</th><th>Keywords</th><th></th></tr>
  {% for p in pages %}
  <tr>
    <td>{{ p.url }}</td>
    <td>{{ p.keywords|join(', ') }}</td>
    <td><form method="post" action="/settings/pages/{{ p.id }}/delete" style="margin:0">
      <button type="submit" class="small-btn">Löschen</button>
    </form></td>
  </tr>
  {% endfor %}
</table>

<form method="post" action="/settings/pages/add">
  <label>Neue Seite (Pfad relativ zur Property) <input type="text" name="url" placeholder="/ratgeber/beispiel-seite/"></label>
  <label>Keywords (Komma-getrennt) <input type="text" name="keywords" placeholder="keyword eins, keyword zwei"></label>
  <button type="submit">Seite hinzufügen</button>
</form>

<h2>Manueller Sync</h2>
<form method="post" action="/api/sync-form">
  <button type="submit">Jetzt aktualisieren</button>
</form>
</body></html>
"""


@app.route("/settings", methods=["GET"])
def settings_page():
    with _store() as store:
        s = store.all_settings()
        pages = store.list_pages()
    return render_template_string(_SETTINGS_TEMPLATE, s=s, pages=pages, saved=request.args.get("saved"))


@app.route("/settings", methods=["POST"])
def settings_save():
    form = request.form
    with _store() as store:
        store.set_setting("marketplace", form.get("marketplace", "").strip())
        store.set_setting("currency", form.get("currency", "").strip())
        store.set_setting("gsheet_sheet_id", form.get("gsheet_sheet_id", "").strip())
        store.set_setting("gsheet_gid", form.get("gsheet_gid", "").strip())
        store.set_setting("seo_enabled", "true" if form.get("seo_enabled") else "false")
        store.set_setting("gsc_property", form.get("gsc_property", "").strip())
        store.set_setting("ga4_property_id", form.get("ga4_property_id", "").strip())
        store.set_setting("seranking_api_key", form.get("seranking_api_key", "").strip())
        store.set_setting("seranking_project_id", form.get("seranking_project_id", "").strip())
    return redirect("/settings?saved=1")


@app.route("/settings/pages/add", methods=["POST"])
def settings_add_page():
    url = request.form.get("url", "").strip()
    keywords = [k.strip() for k in request.form.get("keywords", "").split(",") if k.strip()]
    if url and keywords:
        with _store() as store:
            store.add_page(url, keywords)
    return redirect("/settings?saved=1")


@app.route("/settings/pages/<int:page_id>/delete", methods=["POST"])
def settings_delete_page(page_id: int):
    with _store() as store:
        store.delete_page(page_id)
    return redirect("/settings?saved=1")


@app.route("/api/sync-form", methods=["POST"])
def api_sync_form():
    """Formular-freundlicher Sync-Trigger (redirectet zurueck statt JSON zu liefern)."""
    api_sync()
    return redirect("/settings?saved=1")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    if not _auth_configured():
        print("WARNUNG: DASHBOARD_USER/DASHBOARD_PASSWORD_HASH nicht gesetzt -- "
              "Zugriff ist unverschluesselt/ungeschuetzt. Nur fuer lokale Entwicklung!")
    app.run(host="127.0.0.1", port=port, debug=False)
