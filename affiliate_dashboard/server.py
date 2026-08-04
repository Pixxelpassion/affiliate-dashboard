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
from .seo import google_auth, research_agent
from .seo.research_store import ResearchStore
from .seo.seo_store import SeoStore

try:
    import fcntl  # nur auf Linux/Unix verfuegbar (Produktivserver)
except ImportError:
    fcntl = None  # lokale Windows-Entwicklung: kein Cross-Prozess-Lock noetig

app = Flask(__name__)

_SETTINGS_DB = BASE_DIR / "data" / "settings.db"
_RESEARCH_DB = BASE_DIR / "data" / "research.db"
_SYNC_LOCK_PATH = BASE_DIR / "data" / "sync.lock"
_RESEARCH_LOCK_PATH = BASE_DIR / "data" / "research.lock"
_RESEARCH_PROJECT_LOCK_DIR = BASE_DIR / "data"

# gunicorn laeuft mit mehreren Worker-PROZESSEN (-w 4) -- ein einfaches
# threading.Lock() waere je Prozess getrennt und wuerde NICHT verhindern, dass
# mehrere Worker gleichzeitig synchronisieren. Auf Linux nutzen wir daher einen
# echten Datei-Lock (fcntl.flock) auf eine gemeinsame Datei im data/-Volume, das
# von allen Workern geteilt wird. Lokal (Windows, ein einzelner Flask-Prozess)
# reicht ein simples threading.Lock(). Sync und Rechercheagent bekommen getrennte
# Locks (getrennte Datei + getrenntes lokales Lock-Objekt), damit ein laufender
# Sync einen Recherche-Trigger nicht blockiert und umgekehrt.
_local_sync_lock = threading.Lock()
_local_research_lock = threading.Lock()


def _try_acquire_lock(lock_path: Path, local_lock: threading.Lock):
    """Liefert ein offenes File-Handle (muss bis Arbeitsende offen bleiben) oder
    ``None``, wenn bereits ein anderer Worker denselben Job ausfuehrt."""
    if fcntl is None:
        return object() if local_lock.acquire(blocking=False) else None
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except OSError:
        fh.close()
        return None


def _release_lock(handle, local_lock: threading.Lock) -> None:
    if handle is None:
        return
    if fcntl is None:
        local_lock.release()
        return
    try:
        fcntl.flock(handle, fcntl.LOCK_UN)
    except OSError:
        pass
    handle.close()


def _is_locked(lock_path: Path, local_lock: threading.Lock) -> bool:
    if fcntl is None:
        return local_lock.locked()
    if not lock_path.exists():
        return False
    fh = open(lock_path, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fh, fcntl.LOCK_UN)
        return False  # Lock war frei -> niemand arbeitet gerade
    except OSError:
        return True
    finally:
        fh.close()


def _try_acquire_sync_lock():
    return _try_acquire_lock(_SYNC_LOCK_PATH, _local_sync_lock)


def _release_sync_lock(handle) -> None:
    _release_lock(handle, _local_sync_lock)


def _is_sync_running() -> bool:
    return _is_locked(_SYNC_LOCK_PATH, _local_sync_lock)


def _try_acquire_research_lock():
    return _try_acquire_lock(_RESEARCH_LOCK_PATH, _local_research_lock)


def _release_research_lock(handle) -> None:
    _release_lock(handle, _local_research_lock)


def _is_research_running() -> bool:
    return _is_locked(_RESEARCH_LOCK_PATH, _local_research_lock)


# Ein Lock PRO Recherche-Projekt (nicht global) -- Projekt A soll Projekt B nicht
# blockieren. Lazy angelegtes lokales Lock-Objekt je project_id (gunicorn-Worker
# nutzen ohnehin den Datei-Lock, das lokale Dict ist nur der Windows/Einzelprozess-Fallback).
_local_research_project_locks: dict[int, threading.Lock] = {}


def _local_lock_for_project(project_id: int) -> threading.Lock:
    return _local_research_project_locks.setdefault(project_id, threading.Lock())


def _try_acquire_research_project_lock(project_id: int):
    return _try_acquire_lock(_RESEARCH_PROJECT_LOCK_DIR / f"research_project_{project_id}.lock",
                              _local_lock_for_project(project_id))


def _release_research_project_lock(project_id: int, handle) -> None:
    _release_lock(handle, _local_lock_for_project(project_id))


def _is_research_project_running(project_id: int) -> bool:
    return _is_locked(_RESEARCH_PROJECT_LOCK_DIR / f"research_project_{project_id}.lock",
                       _local_lock_for_project(project_id))


def _store() -> SettingsStore:
    return SettingsStore(_SETTINGS_DB)


def _research_store() -> ResearchStore:
    return ResearchStore(_RESEARCH_DB)


def _cfg() -> Config:
    with _store() as store:
        return Config.from_settings_store(store)


def _products_db_path(cfg: Config) -> Path:
    p = Path(cfg.get("products", {}).get("db_path", "data/products.db"))
    return p if p.is_absolute() else (BASE_DIR / p)


def _seo_db_path(cfg: Config) -> Path:
    p = Path(cfg.get("seo", {}).get("db_path", "data/seo.db"))
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


# --- SEO-Rechercheagent -----------------------------------------------------------

@app.route("/api/seo/research", methods=["POST"])
def api_seo_research():
    lock_handle = _try_acquire_research_lock()
    if lock_handle is None:
        return jsonify({"status": "already_running"}), 409

    def _worker():
        try:
            with _store() as store:
                cfg = Config.from_settings_store(store)
                report_path = research_agent.run(cfg, store)
            result = {"status": "ok", "report_file": report_path.name}
        except Exception as exc:  # noqa: BLE001
            result = {"status": "error", "message": str(exc)}
        finally:
            with _store() as store:
                store.set_meta("last_research_result", json.dumps(result))
            _release_research_lock(lock_handle)

    threading.Thread(target=_worker, daemon=True).start()
    return jsonify({"status": "started"}), 202


@app.route("/api/seo/research-form", methods=["POST"])
def api_seo_research_form():
    """Formular-freundlicher Trigger (redirectet zurueck statt JSON zu liefern),
    analog zu /api/sync-form."""
    api_seo_research()
    return redirect("/settings?saved=1")


@app.route("/data/reports/<path:filename>")
def download_report(filename: str):
    report_dir = _cfg().get("seo", {}).get("research", {}).get("report_dir", "data/reports")
    report_dir = Path(report_dir)
    report_dir = report_dir if report_dir.is_absolute() else (BASE_DIR / report_dir)
    return send_from_directory(report_dir, filename)


# --- Recherche-Bereich (Mehr-Nischen-Audits + Dialog, siehe Plan "Recherche-Bereich") --
# Eigener Navigationsbereich, kein Tab im generierten dashboard.html -- Recherche ist
# live/interaktiv (POST-Requests, wachsender Zustand), die bestehenden Tabs sind
# synchronisierte, statisch generierte Ansichten.

_RECHERCHE_TEMPLATE = """
<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Recherche – Affiliate-Dashboard</title>
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
main{padding:1.4rem 2rem 3rem;max-width:900px;margin:0 auto}
h2{font-family:var(--head-font);font-size:1.1rem;margin-top:2rem;border-bottom:1px solid var(--pp-border);padding-bottom:.3rem}
label{display:block;margin-top:.9rem;font-size:.85rem;color:var(--pp-muted)}
input[type=text]{width:100%;padding:.5rem .65rem;border:1px solid var(--pp-border);border-radius:5px;font-size:.95rem;margin-top:.25rem;font-family:var(--body-font);color:var(--pp-ink)}
input:focus,textarea:focus{outline:2px solid color-mix(in srgb,var(--pp-green) 55%,transparent);border-color:var(--pp-green)}
select{padding:.5rem .65rem;border:1px solid var(--pp-border);border-radius:5px;font-size:.95rem;font-family:var(--body-font);color:var(--pp-ink)}
textarea{width:100%;min-height:5rem;padding:.5rem .65rem;border:1px solid var(--pp-border);border-radius:5px;font-size:.95rem;margin-top:.25rem;font-family:var(--body-font);color:var(--pp-ink);resize:vertical}
button{font-family:var(--body-font);margin-top:1.2rem;padding:.5rem 1.1rem;border-radius:5px;border:none;background:var(--pp-green);color:#fff;font-weight:500;font-size:.9rem;cursor:pointer}
button:hover{background:var(--pp-green-dark)}
button:disabled{background:var(--pp-border);color:var(--pp-muted);cursor:not-allowed}
table{width:100%;border-collapse:collapse;margin-top:.6rem;font-size:.88rem}
td,th{text-align:left;padding:.4rem .5rem;border-bottom:1px solid var(--pp-border)}
th{font-family:var(--head-font);color:var(--pp-muted);font-weight:600}
.small-btn{margin-top:0;padding:.3rem .6rem;font-size:.8rem;background:var(--pp-card);color:var(--pp-ink);border:1px solid var(--pp-border)}
.small-btn:hover{background:var(--pp-card);border-color:var(--pp-neg,#b82105);color:#b82105}
.flash{background:color-mix(in srgb,var(--pp-green) 18%,var(--pp-card));border:1px solid var(--pp-green);padding:.6rem 1rem;border-radius:5px;margin-bottom:1rem}
.flash.error{background:color-mix(in srgb,#b82105 12%,var(--pp-card));border-color:#b82105}
.audit-list{list-style:none;padding:0;margin:.6rem 0}
.audit-list li{margin-bottom:.3rem}
.audit-list a{text-decoration:none;color:var(--pp-ink);border:1px solid var(--pp-border);border-radius:5px;padding:.35rem .7rem;display:inline-block;font-size:.85rem}
.audit-list a.active{border-color:var(--pp-green);background:color-mix(in srgb,var(--pp-green) 14%,var(--pp-card))}
.thread{margin-top:1rem}
.msg{border:1px solid var(--pp-border);border-radius:8px;padding:.9rem 1.1rem;margin-bottom:.8rem}
.msg.assistant{background:var(--pp-card)}
.msg.user{background:color-mix(in srgb,var(--pp-green) 8%,var(--pp-card))}
.msg .role{font-family:var(--head-font);font-weight:600;font-size:.78rem;color:var(--pp-muted);margin-bottom:.4rem;text-transform:uppercase;letter-spacing:.03em}
.msg .content{white-space:pre-wrap;font-size:.92rem;line-height:1.5}
.msg .sources{margin-top:.6rem;font-size:.78rem;color:var(--pp-muted)}
.msg .sources a{color:var(--pp-muted)}
</style></head><body>
<div class="topbar"></div>
<header>
  <img class="logo" src="{{ logo }}" alt="Pixxelpassion">
  <div class="titles">
    <h1>Recherche</h1>
    <div class="sub">Affiliate-Dashboard</div>
  </div>
  <div class="spacer"></div>
  <a class="nav-link" href="/">← Reporting &amp; Analyse</a>
  <a class="nav-link" href="/settings">⚙ Einstellungen</a>
</header>
<main>

<form method="get" action="/recherche">
  <label>Projekt <select name="project" onchange="this.form.submit()">
    {% for p in projects %}
    <option value="{{ p.id }}" {{ 'selected' if p.id == project_id else '' }}>{{ p.label }}</option>
    {% endfor %}
  </select></label>
  <noscript><button type="submit">Anzeigen</button></noscript>
</form>

{% if not projects %}
<p>Noch kein Recherche-Projekt angelegt. Unter <a href="/settings">Einstellungen</a> im
Abschnitt „Recherche-Projekte" eines hinzufügen.</p>
{% elif project %}

{% if run_status %}
  {% if run_status.status == 'error' %}
  <div class="flash error">Letzter Lauf fehlgeschlagen: {{ run_status.message }}</div>
  {% endif %}
{% endif %}

<form method="post" action="/recherche/run">
  <input type="hidden" name="project_id" value="{{ project.id }}">
  <button type="submit" {{ 'disabled' if running else '' }}>{{ 'Läuft bereits…' if running else 'Recherche jetzt starten' }}</button>
</form>

<h2>Seiten + Keywords ({{ project.label }})</h2>
<table>
  <tr><th>URL</th><th>Keywords</th><th></th></tr>
  {% for pg in pages %}
  <tr>
    <td>{{ pg.url }}</td>
    <td>{{ pg.keywords|join(', ') }}</td>
    <td><form method="post" action="/recherche/pages/{{ pg.id }}/delete" style="margin:0">
      <input type="hidden" name="project_id" value="{{ project.id }}">
      <button type="submit" class="small-btn">Löschen</button>
    </form></td>
  </tr>
  {% endfor %}
</table>
<form method="post" action="/recherche/{{ project.id }}/pages/add">
  <label>Neue Seite (Pfad relativ zur GSC-Property) <input type="text" name="url" placeholder="ratgeber/beispiel-seite/"></label>
  <label>Keywords (Komma-getrennt) <input type="text" name="keywords" placeholder="keyword eins, keyword zwei"></label>
  <button type="submit">Seite hinzufügen</button>
</form>

<h2>Audits</h2>
{% if not audits %}
<p>Noch kein Audit für dieses Projekt. Oben auf „Recherche jetzt starten" klicken.</p>
{% else %}
<ul class="audit-list">
  {% for a in audits %}
  <li><a class="{{ 'active' if a.id == audit_id else '' }}" href="/recherche?project={{ project.id }}&audit={{ a.id }}">{{ a.created_at[:16] }}</a></li>
  {% endfor %}
</ul>
{% endif %}

{% if audit_id and messages %}
<div class="thread">
  {% for m in messages %}
  <div class="msg {{ m.role }}">
    <div class="role">{{ 'Bericht / Antwort' if m.role == 'assistant' else 'Du' }}</div>
    <div class="content">{{ m.content }}</div>
    {% if m.sources %}
    <div class="sources">Quellen:
      {% for s in m.sources %}<a href="{{ s.uri }}" target="_blank" rel="noopener">{{ s.title or s.domain or s.uri }}</a>{{ ', ' if not loop.last else '' }}{% endfor %}
    </div>
    {% endif %}
  </div>
  {% endfor %}
</div>

<form method="post" action="/recherche/{{ audit_id }}/message">
  <label>Rückfrage <textarea name="message" placeholder="z.B. Welche Massnahme zuerst umsetzen?"></textarea></label>
  <button type="submit">Senden</button>
</form>
{% endif %}

{% endif %}
</main>
</body></html>
"""


@app.route("/recherche", methods=["GET"])
def recherche_page():
    project_id = request.args.get("project", type=int)
    audit_id = request.args.get("audit", type=int)

    with _store() as store:
        projects = store.list_research_projects()
        if project_id is None and projects:
            project_id = projects[0]["id"]
        project = store.get_research_project(project_id) if project_id else None
        pages = store.list_research_project_pages(project_id) if project_id else []
        raw_status = store.get_meta(f"research_run_status:{project_id}") if project_id else None

    run_status = json.loads(raw_status) if raw_status else None

    audits = []
    messages = []
    with _research_store() as rstore:
        if project_id:
            audits = rstore.list_audits(project_id)
            if audit_id is None and audits:
                audit_id = audits[0]["id"]
            if audit_id:
                messages = rstore.list_messages(audit_id)

    return render_template_string(
        _RECHERCHE_TEMPLATE, projects=projects, project=project, project_id=project_id,
        pages=pages, audits=audits, audit_id=audit_id, messages=messages,
        run_status=run_status,
        running=_is_research_project_running(project_id) if project_id else False,
        favicon=branding.FAVICON_LINK, logo=branding.logo_data_uri(),
    )


@app.route("/recherche/run", methods=["POST"])
def recherche_run():
    project_id = request.form.get("project_id", type=int)
    if project_id is None:
        return redirect("/recherche")

    lock_handle = _try_acquire_research_project_lock(project_id)
    if lock_handle is None:
        return redirect(f"/recherche?project={project_id}")

    def _worker():
        try:
            with _store() as store:
                project = store.get_research_project(project_id)
                cfg = Config.from_settings_store(store)
                seranking_api_key = cfg.get("seo", {}).get("seranking", {}).get("api_key", "")
                gemini_api_key = cfg.get("seo", {}).get("gemini", {}).get("api_key", "")
                try:
                    credentials = google_auth.get_credentials(cfg)
                except Exception:  # noqa: BLE001
                    credentials = None
                with SeoStore(_seo_db_path(cfg)) as seo_store, _research_store() as rstore:
                    audit_id = research_agent.start_project_audit(
                        project, store, rstore, seo_store, credentials,
                        seranking_api_key, gemini_api_key,
                    )
            result = {"status": "ok", "audit_id": audit_id}
        except Exception as exc:  # noqa: BLE001
            result = {"status": "error", "message": str(exc)}
        finally:
            with _store() as store:
                store.set_meta(f"research_run_status:{project_id}", json.dumps(result))
            _release_research_project_lock(project_id, lock_handle)

    threading.Thread(target=_worker, daemon=True).start()
    return redirect(f"/recherche?project={project_id}")


@app.route("/recherche/<int:audit_id>/message", methods=["POST"])
def recherche_message(audit_id: int):
    """Bewusst SYNCHRON (kein Hintergrund-Thread) -- ein einzelner Gemini-Call ist
    schnell genug, und der Nutzer erwartet die Antwort direkt nach dem Formular-Reload."""
    message = request.form.get("message", "").strip()
    with _research_store() as rstore:
        audit = rstore.get_audit(audit_id)
        if audit is None:
            return redirect("/recherche")
        project_id = audit["research_project_id"]
        if message:
            gemini_api_key = _cfg().get("seo", {}).get("gemini", {}).get("api_key", "")
            if gemini_api_key:
                try:
                    research_agent.continue_dialog(audit_id, message, rstore, gemini_api_key)
                except Exception as exc:  # noqa: BLE001
                    rstore.add_message(audit_id, "assistant", f"Fehler bei der Anfrage: {exc}")
    return redirect(f"/recherche?project={project_id}&audit={audit_id}")


@app.route("/recherche/<int:project_id>/pages/add", methods=["POST"])
def recherche_add_page(project_id: int):
    url = request.form.get("url", "").strip()
    keywords = [k.strip() for k in request.form.get("keywords", "").split(",") if k.strip()]
    if keywords:
        with _store() as store:
            store.add_research_project_page(project_id, url, keywords)
    return redirect(f"/recherche?project={project_id}")


@app.route("/recherche/pages/<int:page_id>/delete", methods=["POST"])
def recherche_delete_page(page_id: int):
    project_id = request.form.get("project_id", type=int)
    with _store() as store:
        store.delete_research_project_page(page_id)
    return redirect(f"/recherche?project={project_id}" if project_id else "/recherche")


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
  <a class="nav-link" href="/">← Reporting &amp; Analyse</a>
  <a class="nav-link" href="/recherche">Recherche</a>
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

<form method="post" action="/settings">
  <h2>SEO-Rechercheagent</h2>
  <input type="hidden" name="research_form" value="1">
  <label><input type="checkbox" name="seranking_auto_discover_pages" {{ 'checked' if s.get('seranking_auto_discover_pages')=='true' else '' }}> Seiten/Keywords automatisch aus SE-Ranking-Projekt übernehmen</label>
  <label>Gemini API-Key <input type="password" name="gemini_api_key" value="{{ s.get('gemini_api_key','') }}"></label>
  <button type="submit">Speichern</button>
</form>

<form method="post" action="/api/seo/research-form">
  <button type="submit">Recherche jetzt starten</button>
  {% if last_research %}
    {% if last_research.status == 'ok' %}
      <span> Letzter Bericht: <a href="/data/reports/{{ last_research.report_file }}" target="_blank">{{ last_research.report_file }}</a></span>
    {% elif last_research.status == 'error' %}
      <span style="color:#b82105"> Letzter Lauf fehlgeschlagen: {{ last_research.message }}</span>
    {% endif %}
  {% endif %}
</form>

<h2>Recherche-Projekte (eine Nische je Zeile)</h2>
<table>
  <tr><th>Label</th><th>GSC-Property</th><th>GA4-Property-ID</th><th>SE-Ranking-Projekt-ID</th><th>Auto-Discover</th><th></th></tr>
  {% for p in research_projects %}
  <tr>
    <td>{{ p.label }}</td>
    <td>{{ p.gsc_property }}</td>
    <td>{{ p.ga4_property_id }}</td>
    <td>{{ p.seranking_project_id }}</td>
    <td>{{ 'ja' if p.auto_discover_pages else 'nein' }}</td>
    <td><form method="post" action="/settings/research-projects/{{ p.id }}/delete" style="margin:0">
      <button type="submit" class="small-btn">Löschen</button>
    </form></td>
  </tr>
  {% endfor %}
</table>

<form method="post" action="/settings/research-projects/add">
  <label>Label (Nische) <input type="text" name="label" placeholder="Tischkreissägen"></label>
  <label>GSC-Property <input type="text" name="gsc_property" placeholder="https://tischkreissaege-tests.de/"></label>
  <label>GA4-Property-ID <input type="text" name="ga4_property_id" placeholder="386535911"></label>
  <label>SE-Ranking-Projekt-ID <input type="text" name="seranking_project_id" placeholder="12711020"></label>
  <label><input type="checkbox" name="auto_discover_pages"> Seiten/Keywords automatisch aus SE-Ranking-Projekt übernehmen</label>
  <button type="submit">Projekt hinzufügen</button>
</form>
<p style="font-size:.82rem;color:var(--pp-muted)">Seiten/Keywords je Projekt werden direkt unter <a href="/recherche">Recherche</a> gepflegt, nicht hier.</p>

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
        research_projects = store.list_research_projects()
        raw_research = store.get_meta("last_research_result")
    last_research = json.loads(raw_research) if raw_research else None
    return render_template_string(_SETTINGS_TEMPLATE, s=s, pages=pages, product_tabs=product_tabs,
                                   research_projects=research_projects,
                                   last_research=last_research,
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
    is_research_form = "research_form" in form
    is_products_form = "products_form" in form

    with _store() as store:
        if is_seo_form:
            store.set_setting("seo_enabled", "true" if form.get("seo_enabled") else "false")
            store.set_setting("gsc_property", form.get("gsc_property", "").strip())
            store.set_setting("ga4_property_id", form.get("ga4_property_id", "").strip())
            store.set_setting("seranking_api_key", form.get("seranking_api_key", "").strip())
            store.set_setting("seranking_project_id", form.get("seranking_project_id", "").strip())
        elif is_research_form:
            store.set_setting("seranking_auto_discover_pages",
                               "true" if form.get("seranking_auto_discover_pages") else "false")
            store.set_setting("gemini_api_key", form.get("gemini_api_key", "").strip())
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


@app.route("/settings/research-projects/add", methods=["POST"])
def settings_add_research_project():
    label = request.form.get("label", "").strip()
    gsc_property = request.form.get("gsc_property", "").strip()
    ga4_property_id = request.form.get("ga4_property_id", "").strip()
    seranking_project_id = request.form.get("seranking_project_id", "").strip()
    auto_discover_pages = bool(request.form.get("auto_discover_pages"))
    if label:
        with _store() as store:
            store.add_research_project(label, gsc_property, ga4_property_id,
                                        seranking_project_id, auto_discover_pages)
    return redirect("/settings?saved=1")


@app.route("/settings/research-projects/<int:project_id>/delete", methods=["POST"])
def settings_delete_research_project(project_id: int):
    with _store() as store:
        store.delete_research_project(project_id)
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
