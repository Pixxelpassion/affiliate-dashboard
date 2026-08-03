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

import json
import os
import threading
from pathlib import Path

from flask import Flask, Response, jsonify, redirect, render_template_string, request, send_from_directory
from werkzeug.security import check_password_hash

from . import branding
from .config import BASE_DIR, Config
from .run import run_once
from .settings_store import SettingsStore
from .products import ga4_traffic
from .products.products_run import merge_items
from .products.store import ProductStore

try:
    import fcntl  # nur auf Linux/Unix verfuegbar (Produktivserver)
except ImportError:
    fcntl = None  # lokale Windows-Entwicklung: kein Cross-Prozess-Lock noetig

app = Flask(__name__)

_SETTINGS_DB = BASE_DIR / "data" / "settings.db"
_SYNC_LOCK_PATH = BASE_DIR / "data" / "sync.lock"

# gunicorn laeuft mit mehreren Worker-PROZESSEN (-w 4) -- ein einfaches
# threading.Lock() waere je Prozess getrennt und wuerde NICHT verhindern, dass
# mehrere Worker gleichzeitig synchronisieren. Auf Linux nutzen wir daher einen
# echten Datei-Lock (fcntl.flock) auf eine gemeinsame Datei im data/-Volume, das
# von allen Workern geteilt wird. Lokal (Windows, ein einzelner Flask-Prozess)
# reicht ein simples threading.Lock().
_local_sync_lock = threading.Lock()


def _try_acquire_sync_lock():
    """Liefert ein offenes File-Handle (muss bis Sync-Ende offen bleiben) oder
    ``None``, wenn bereits ein anderer Worker synchronisiert."""
    if fcntl is None:
        return object() if _local_sync_lock.acquire(blocking=False) else None
    _SYNC_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fh = open(_SYNC_LOCK_PATH, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except OSError:
        fh.close()
        return None


def _release_sync_lock(handle) -> None:
    if handle is None:
        return
    if fcntl is None:
        _local_sync_lock.release()
        return
    try:
        fcntl.flock(handle, fcntl.LOCK_UN)
    except OSError:
        pass
    handle.close()


def _is_sync_running() -> bool:
    if fcntl is None:
        return _local_sync_lock.locked()
    if not _SYNC_LOCK_PATH.exists():
        return False
    fh = open(_SYNC_LOCK_PATH, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fh, fcntl.LOCK_UN)
        return False  # Lock war frei -> niemand synchronisiert gerade
    except OSError:
        return True
    finally:
        fh.close()


def _store() -> SettingsStore:
    return SettingsStore(_SETTINGS_DB)


def _cfg() -> Config:
    with _store() as store:
        return Config.from_settings_store(store)


def _products_db_path(cfg: Config) -> Path:
    p = Path(cfg.get("products", {}).get("db_path", "data/products.db"))
    return p if p.is_absolute() else (BASE_DIR / p)


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
    lock_handle = _try_acquire_sync_lock()
    if lock_handle is None:
        return jsonify({"status": "already_running"}), 409

    def _worker():
        try:
            cfg = _cfg()
            result = {"status": "ok", **run_once(cfg)}
        except Exception as exc:  # noqa: BLE001
            result = {"status": "error", "message": str(exc)}
        finally:
            with _store() as store:
                store.set_meta("last_sync_result", json.dumps(result))
            _release_sync_lock(lock_handle)

    threading.Thread(target=_worker, daemon=True).start()
    return jsonify({"status": "started"}), 202


@app.route("/api/status")
def api_status():
    cfg = _cfg()
    with _store() as store:
        raw = store.get_meta("last_sync_result")
    last_sync = json.loads(raw) if raw else {}
    return jsonify({
        "dashboard_exists": cfg.path("out_file").exists(),
        "sync_running": _is_sync_running(),
        "last_sync": last_sync,
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


# --- Produkt-Lebenszyklus-API ----------------------------------------------------
# Katalog/Status/Besucher/Seiten-Links werden LIVE aus products.db gelesen (nicht aus
# dem in dashboard.html eingebetteten Sync-Snapshot), damit ein manuell gespeicherter
# Status sofort sichtbar ist, ohne auf den naechsten Sync warten zu muessen.

@app.route("/api/products")
def api_products():
    tracking_id = request.args.get("tracking_id", "")
    cfg = _cfg()
    with ProductStore(_products_db_path(cfg)) as store:
        catalog = store.all_catalog()
        status = store.all_status()
        visitors = store.all_visitors()
        page_links = store.all_page_links()

    items = merge_items(catalog, status, visitors, page_links)
    if tracking_id:
        items = [it for it in items if it["tracking_id"] == tracking_id]
    return jsonify({"items": items})


@app.route("/api/products/status", methods=["POST"])
def api_products_status():
    """Speichert den manuellen Verfuegbarkeits-Status UND ruft synchron die
    GA4-Besucherzahl der letzten 365 Tage fuer dieses Produkt ab -- genau im Moment
    des Speicherns, nicht als Teil des automatischen Syncs (siehe Plan-Entscheidung:
    kein Amazon-Scraping, GA4 nur on-demand beim manuellen Check)."""
    data = request.get_json(force=True, silent=True) or {}
    tracking_id = str(data.get("tracking_id", "")).strip()
    asin = str(data.get("asin", "")).strip()
    status = str(data.get("status", "")).strip()
    note = str(data.get("note", "")).strip()
    if not tracking_id or not asin:
        return jsonify({"error": "tracking_id und asin sind erforderlich"}), 400

    cfg = _cfg()
    with ProductStore(_products_db_path(cfg)) as store:
        checked_at = store.add_status_check(tracking_id, asin, status, note)

        catalog_row = next(
            (c for c in store.all_catalog() if c["tracking_id"] == tracking_id and c["asin"] == asin),
            None,
        )
        result = {"status": "ok", "checked_at": checked_at}

        tabs = cfg.get("products", {}).get("tabs", [])
        tab = next((t for t in tabs if t.get("label") == (catalog_row or {}).get("tab_label")), None)
        property_id = (tab or {}).get("ga4_property_id") or cfg.get("seo", {}).get("ga4", {}).get("property_id")
        test_url = (catalog_row or {}).get("test_url", "")

        try:
            pageviews = ga4_traffic.fetch_pageviews(cfg, property_id, test_url)
            store.upsert_visitors(tracking_id, asin, pageviews)
            result["pageviews"] = pageviews
        except Exception as exc:  # noqa: BLE001
            result["ga4_error"] = str(exc)

    return jsonify(result)


# --- Einstellungsseite (serverseitig gerendertes Formular, kein JS noetig) -------

_SETTINGS_TEMPLATE = """
<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Einstellungen – Affiliate-Dashboard</title>
{{ favicon|safe }}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@500;600;700;800&family=Poppins:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
:root{--pp-green:#b7cb3a;--pp-green-dark:#717e21;--pp-ink:#1A202C;--pp-muted:#6b7280;--pp-bg:#fbfbfb;--pp-card:#ffffff;--pp-border:#e6e8e1;--body-font:'Poppins','Segoe UI',system-ui,sans-serif;--head-font:'Montserrat','Poppins','Segoe UI',sans-serif}
*{box-sizing:border-box}
body{font-family:var(--body-font);margin:0;background:var(--pp-bg);color:var(--pp-ink);-webkit-font-smoothing:antialiased}
.topbar{height:6px;background:linear-gradient(90deg,var(--pp-green) 0%,var(--pp-green-dark) 60%,#09adbe 100%)}
header{display:flex;align-items:center;gap:1.1rem;padding:1.1rem 2rem;background:var(--pp-card);border-bottom:1px solid var(--pp-border);flex-wrap:wrap}
header img.logo{height:46px;width:auto}
header .titles{line-height:1.15}
header h1{font-family:var(--head-font);font-weight:800;font-size:1.4rem;margin:0;letter-spacing:.2px}
header .sub{color:var(--pp-muted);font-size:.82rem;margin-top:.15rem}
header .spacer{flex:1}
header .nav-link{color:var(--pp-muted);font-size:.8rem;text-decoration:none;border:1px solid var(--pp-border);border-radius:5px;padding:.4rem .8rem;white-space:nowrap}
header .nav-link:hover{color:var(--pp-green-dark);border-color:var(--pp-green)}
main{padding:1.4rem 2rem 3rem;max-width:760px;margin:0 auto}
h2{font-family:var(--head-font);font-size:1.1rem;margin-top:2rem;border-bottom:1px solid var(--pp-border);padding-bottom:.3rem}
label{display:block;margin-top:.9rem;font-size:.85rem;color:var(--pp-muted)}
input[type=text],input[type=password]{width:100%;padding:.5rem .65rem;border:1px solid var(--pp-border);border-radius:5px;font-size:.95rem;margin-top:.25rem;font-family:var(--body-font);color:var(--pp-ink)}
input:focus{outline:2px solid color-mix(in srgb,var(--pp-green) 55%,transparent);border-color:var(--pp-green)}
button{font-family:var(--body-font);margin-top:1.2rem;padding:.5rem 1.1rem;border-radius:5px;border:none;background:var(--pp-green);color:#fff;font-weight:500;font-size:.9rem;cursor:pointer}
button:hover{background:var(--pp-green-dark)}
table{width:100%;border-collapse:collapse;margin-top:.6rem;font-size:.88rem}
td,th{text-align:left;padding:.4rem .5rem;border-bottom:1px solid var(--pp-border)}
th{font-family:var(--head-font);color:var(--pp-muted);font-weight:600}
.small-btn{margin-top:0;padding:.3rem .6rem;font-size:.8rem;background:var(--pp-card);color:var(--pp-ink);border:1px solid var(--pp-border)}
.small-btn:hover{background:var(--pp-card);border-color:var(--pp-neg,#b82105);color:#b82105}
.flash{background:color-mix(in srgb,var(--pp-green) 18%,var(--pp-card));border:1px solid var(--pp-green);padding:.6rem 1rem;border-radius:5px;margin-bottom:1rem}
</style></head><body>
<div class="topbar"></div>
<header>
  <img class="logo" src="{{ logo }}" alt="Pixxelpassion">
  <div class="titles">
    <h1>Einstellungen</h1>
    <div class="sub">Affiliate-Dashboard</div>
  </div>
  <div class="spacer"></div>
  <a class="nav-link" href="/">← Zum Dashboard</a>
</header>
<main>
{% if saved %}<div class="flash">Gespeichert.</div>{% endif %}

<form method="post" action="/settings">
  <h2>Amazon PartnerNet (Google Sheet)</h2>
  <label>Marketplace <input type="text" name="marketplace" value="{{ s.get('marketplace','') }}"></label>
  <label>Währung <input type="text" name="currency" value="{{ s.get('currency','') }}"></label>
  <label>Google-Sheet-ID <input type="text" name="gsheet_sheet_id" value="{{ s.get('gsheet_sheet_id','') }}"></label>
  <label>Sheet-Tab-ID (gid) <input type="text" name="gsheet_gid" value="{{ s.get('gsheet_gid','') }}"></label>
  <button type="submit">Speichern</button>
</form>

<form method="post" action="/settings">
  <h2>SEO-Monitoring</h2>
  <input type="hidden" name="seo_form" value="1">
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

<form method="post" action="/settings">
  <h2>Produkt-Lebenszyklus</h2>
  <input type="hidden" name="products_form" value="1">
  <label><input type="checkbox" name="products_enabled" {{ 'checked' if s.get('products_enabled')=='true' else '' }}> Aktiviert</label>
  <button type="submit">Speichern</button>
</form>

<h2>Produkt-Tabs (ein Google-Sheet-Tab je Nische)</h2>
<table>
  <tr><th>Label</th><th>gid</th><th>GA4-Property-ID</th><th>Website</th><th></th></tr>
  {% for t in product_tabs %}
  <tr>
    <td>{{ t.label }}</td>
    <td>{{ t.gid }}</td>
    <td>{{ t.ga4_property_id }}</td>
    <td>{{ t.site_base_url }}</td>
    <td><form method="post" action="/settings/product-tabs/{{ t.id }}/delete" style="margin:0">
      <button type="submit" class="small-btn">Löschen</button>
    </form></td>
  </tr>
  {% endfor %}
</table>

<form method="post" action="/settings/product-tabs/add">
  <label>Label (Nische) <input type="text" name="label" placeholder="Tauchpumpen"></label>
  <label>Sheet-Tab-ID (gid) <input type="text" name="gid" placeholder="342635093"></label>
  <label>GA4-Property-ID (optional, sonst SEO-Property) <input type="text" name="ga4_property_id" placeholder="properties/123456789"></label>
  <label>Website-Basis-URL (für den Crawler) <input type="text" name="site_base_url" placeholder="https://tauchpumpe-tests.de"></label>
  <button type="submit">Tab hinzufügen</button>
</form>

<h2>Manueller Sync</h2>
<form method="post" action="/api/sync-form">
  <button type="submit">Jetzt aktualisieren</button>
</form>
</main>
</body></html>
"""


@app.route("/settings", methods=["GET"])
def settings_page():
    with _store() as store:
        s = store.all_settings()
        pages = store.list_pages()
        product_tabs = store.list_product_tabs()
    return render_template_string(_SETTINGS_TEMPLATE, s=s, pages=pages, product_tabs=product_tabs,
                                   saved=request.args.get("saved"),
                                   favicon=branding.FAVICON_LINK, logo=branding.logo_data_uri())


@app.route("/settings", methods=["POST"])
def settings_save():
    """Speichert nur die Felder des tatsächlich abgeschickten Formulars (PartnerNet
    ODER SEO-Monitoring -- getrennte <form>-Bloecke im Template), damit ein Teil-Update
    nicht versehentlich die Werte des jeweils anderen Formulars mit Leerstrings
    ueberschreibt (siehe Bug: SE-Ranking-Update loeschte die Sheet-ID)."""
    form = request.form
    is_seo_form = "seo_form" in form
    is_products_form = "products_form" in form

    with _store() as store:
        if is_seo_form:
            store.set_setting("seo_enabled", "true" if form.get("seo_enabled") else "false")
            store.set_setting("gsc_property", form.get("gsc_property", "").strip())
            store.set_setting("ga4_property_id", form.get("ga4_property_id", "").strip())
            store.set_setting("seranking_api_key", form.get("seranking_api_key", "").strip())
            store.set_setting("seranking_project_id", form.get("seranking_project_id", "").strip())
        elif is_products_form:
            store.set_setting("products_enabled", "true" if form.get("products_enabled") else "false")
        else:
            store.set_setting("marketplace", form.get("marketplace", "").strip())
            store.set_setting("currency", form.get("currency", "").strip())
            store.set_setting("gsheet_sheet_id", form.get("gsheet_sheet_id", "").strip())
            store.set_setting("gsheet_gid", form.get("gsheet_gid", "").strip())
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


@app.route("/settings/product-tabs/add", methods=["POST"])
def settings_add_product_tab():
    label = request.form.get("label", "").strip()
    gid = request.form.get("gid", "").strip()
    ga4_property_id = request.form.get("ga4_property_id", "").strip()
    site_base_url = request.form.get("site_base_url", "").strip()
    if label and gid:
        with _store() as store:
            store.add_product_tab(label, gid, ga4_property_id, site_base_url)
    return redirect("/settings?saved=1")


@app.route("/settings/product-tabs/<int:tab_id>/delete", methods=["POST"])
def settings_delete_product_tab(tab_id: int):
    with _store() as store:
        store.delete_product_tab(tab_id)
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
