"""SEO-Rechercheagent: verdichtet GSC/GA4/SE-Ranking-Historie + Keyword-Research zu
einem strukturierten Digest, ein einziger Gemini-Completion-Call synthetisiert daraus
einen Markdown-Bericht mit konkreten Handlungsempfehlungen.

Bewusst KEIN Multi-Agenten-System: die Datensammlung/-verdichtung ist deterministisches
Python, das Modell bekommt kein Tool-Use (alle Daten sind vorab bekannt) -- das haelt
Kosten und Verhalten vorhersehbar und reproduzierbar (siehe Architektur-Diskussion).
Gemini statt Claude, damit der Rechercheagent mit nur einem Zugangsdaten-Anbieter
(Google) auskommt -- GSC/GA4 laufen bereits ueber Google-OAuth.

Ablauf: ``python -m affiliate_dashboard.seo.research_agent``
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

from google import genai
from google.genai import types as genai_types

from ..config import BASE_DIR, Config
from ..settings_store import SettingsStore
from . import (
    cannibalization,
    ga4_client,
    google_auth,
    gsc_client,
    seranking_client,
    seranking_keyword_research,
    seranking_pages_sync,
    seo_run,
)
from .seo_store import SeoStore

_SETTINGS_DB = BASE_DIR / "data" / "settings.db"
_WINDOW_DAYS = 30
_LAG_DAYS = 3
_CANNIBALIZATION_WINDOW_DAYS = 90


# --- Zeitfenster --------------------------------------------------------------
def _windows() -> dict:
    end = date.today() - timedelta(days=_LAG_DAYS)
    start = end - timedelta(days=_WINDOW_DAYS - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=_WINDOW_DAYS - 1)
    return {
        "current": (start.isoformat(), end.isoformat()),
        "previous": (prev_start.isoformat(), prev_end.isoformat()),
    }


def _in_window(row_date: str, window: tuple[str, str]) -> bool:
    return window[0] <= row_date <= window[1]


# --- Aggregation (reines Python, aus bereits gesammelter Historie) -------------
def _gsc_stats(rows: list[dict], page: str, window: tuple[str, str]) -> dict:
    matched = [r for r in rows if r["page"] == page and _in_window(r["date"], window)]
    impressions = sum(r.get("impressions") or 0 for r in matched)
    clicks = sum(r.get("clicks") or 0 for r in matched)
    weighted_pos = sum((r.get("position") or 0) * (r.get("impressions") or 0) for r in matched)
    return {
        "impressions": round(impressions),
        "clicks": round(clicks),
        "ctr": round(clicks / impressions, 4) if impressions else 0.0,
        "avg_position": round(weighted_pos / impressions, 1) if impressions else None,
    }


def _ga4_stats(rows: list[dict], page: str, window: tuple[str, str]) -> dict:
    matched = [r for r in rows if r["page"] == page and _in_window(r["date"], window)]
    pageviews = sum(r.get("pageviews") or 0 for r in matched)
    weighted_engagement = sum(
        (r.get("avg_engagement_seconds") or 0) * (r.get("pageviews") or 0) for r in matched
    )
    return {
        "pageviews": round(pageviews),
        "avg_engagement_seconds": round(weighted_engagement / pageviews, 1) if pageviews else None,
    }


def _rank_stats(rows: list[dict], page: str, window: tuple[str, str]) -> dict:
    matched = [
        r for r in rows
        if r["page"] == page and _in_window(r["date"], window) and r.get("position") is not None
    ]
    if not matched:
        return {"avg_position": None, "keywords_tracked": 0}
    return {
        "avg_position": round(sum(r["position"] for r in matched) / len(matched), 1),
        "keywords_tracked": len({r["keyword"] for r in matched}),
    }


# --- Digest ---------------------------------------------------------------------
def build_digest(cfg: Config, seo_store: SeoStore, settings_store: SettingsStore) -> dict:
    windows = _windows()
    payload = seo_run.read_payload(cfg)
    pages_cfg = payload["pages"]

    pages_digest = []
    for entry in pages_cfg:
        page = entry["url"]
        pages_digest.append({
            "url": page or "/",
            "keywords_tracked": entry.get("keywords", []),
            "gsc": {"last_30d": _gsc_stats(payload["gsc"], page, windows["current"]),
                    "prev_30d": _gsc_stats(payload["gsc"], page, windows["previous"])},
            "ga4": {"last_30d": _ga4_stats(payload["ga4"], page, windows["current"]),
                    "prev_30d": _ga4_stats(payload["ga4"], page, windows["previous"])},
            "rank": {"last_30d": _rank_stats(payload["rank"], page, windows["current"]),
                     "prev_30d": _rank_stats(payload["rank"], page, windows["previous"])},
            "events": [e for e in settings_store.list_events(page) if e],
        })

    # Kannibalisierung: frischer, offener GSC-Abruf (kein Keyword-Filter) je Seite.
    cannibalization_findings = []
    try:
        credentials = google_auth.get_credentials(cfg)
        gsc_service = gsc_client.build_service(credentials)
        property_url = cfg.get("seo", {}).get("gsc", {}).get("property", "")
        end = date.today() - timedelta(days=_LAG_DAYS)
        start = end - timedelta(days=_CANNIBALIZATION_WINDOW_DAYS)
        all_query_rows = []
        for entry in pages_cfg:
            rows = gsc_client.fetch_all_queries(
                gsc_service, property_url, entry["url"], start.isoformat(), end.isoformat()
            )
            for r in rows:
                r["window_start"] = start.isoformat()
                r["window_end"] = end.isoformat()
            all_query_rows.extend(rows)
        seo_store.replace_query_discovery(all_query_rows)
        cann_cfg = cfg.get("seo", {}).get("research", {}).get("cannibalization", {})
        cannibalization_findings = cannibalization.detect_cannibalization(
            all_query_rows,
            min_impressions=cann_cfg.get("min_impressions", 50),
            min_page_impressions=cann_cfg.get("min_page_impressions", 3),
            min_pages=cann_cfg.get("min_pages", 2),
            close_position_gap=cann_cfg.get("close_position_gap", 30.0),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Rechercheagent: Kannibalisierungs-Abruf fehlgeschlagen ({exc}) -- "
              "wird im Bericht als 'nicht verfuegbar' markiert.", file=sys.stderr)
        cannibalization_findings = None

    # Unzugeordnete Keywords + Keyword-Research (Cluster-Kandidaten).
    unassigned: list[str] = []
    keyword_research: dict[str, dict] = {}
    se_cfg = cfg.get("seo", {}).get("seranking", {})
    if se_cfg.get("api_key") and se_cfg.get("project_id"):
        try:
            discovery = seranking_pages_sync.discover(
                se_cfg["api_key"], se_cfg["project_id"], cfg.get("seo", {}).get("gsc", {}).get("property", ""),
            )
            unassigned = discovery["unassigned"]
            all_tracked = sorted({kw for e in pages_cfg for kw in e.get("keywords", [])} | set(unassigned))
            volumes = seranking_keyword_research.export_metrics(
                seo_store, se_cfg["api_key"], all_tracked, max_age_days=cfg.get("seo", {}).get(
                    "research", {}).get("cache_days", 30),
            )
            volume_by_kw = {v["keyword"]: v for v in volumes if v.get("is_data_found")}
            for kw in unassigned:
                similar = seranking_keyword_research.fetch_similar(
                    seo_store, se_cfg["api_key"], kw, max_age_days=cfg.get("seo", {}).get(
                        "research", {}).get("cache_days", 30),
                )
                keyword_research[kw] = {
                    "volume": volume_by_kw.get(kw, {}).get("volume"),
                    "similar_keywords": similar.get("keywords", [])[:15],
                }
            for entry in pages_digest:
                entry["keyword_volumes"] = {
                    kw: volume_by_kw.get(kw, {}).get("volume") for kw in entry["keywords_tracked"]
                }
        except Exception as exc:  # noqa: BLE001
            print(f"Rechercheagent: Keyword-Research fehlgeschlagen ({exc}) -- "
                  "wird im Bericht als 'nicht verfuegbar' markiert.", file=sys.stderr)

    return {
        "window": {"current": windows["current"], "previous": windows["previous"]},
        "pages": pages_digest,
        "cannibalization": cannibalization_findings,
        "unassigned_keywords": unassigned,
        "keyword_research": keyword_research,
    }


# --- LLM-Synthese -----------------------------------------------------------------
_REPORT_SYSTEM_PROMPT = """\
Du bist ein erfahrener SEO-Stratege. Du bekommst einen strukturierten JSON-Digest mit \
Ranking-/Klick-/Traffic-Historie, Keyword-Kannibalisierungs-Funden und Keyword-Research-\
Daten fuer eine Nischen-Website. Erstelle daraus einen Markdown-Bericht mit GENAU diesen \
Abschnitten, in dieser Reihenfolge:

## Executive Summary
3-5 Bullet-Points, wichtigster Befund zuerst.

## Trendbewertung je Seite
Fuer jede Seite: Traffic-/Ranking-Trend (wachsend/stabil/fallend, mit Zahlen belegt), \
Einordnung, und falls ein Livegang-Event in der Naehe liegt: Hypothese zum Zusammenhang.

## Keyword-Kannibalisierung
Tabelle: Query | betroffene Seiten | Positionen | Impressionen | Severity | konkrete \
Massnahme (konsolidieren/kanonisieren/differenzieren). Wenn keine Funde vorliegen oder \
die Daten nicht verfuegbar waren, das explizit sagen.

## Ungenutzte Keyword-Chancen
Aus den unzugeordneten Keywords + Keyword-Research: Cluster bilden, Suchvolumen nennen, \
Zuordnungsvorschlag (bestehende Seite erweitern vs. neue Seite).

## Content-/Seitenstruktur-Empfehlung
Konkret: welche Seite bekommt welches Cluster, was wird konsolidiert, Meta-Title/H1-\
Vorschlaege bei Kannibalisierungs-Faellen.

## Priorisierte Massnahmenliste
Tabelle: Massnahme | Seite(n) | erwarteter Impact | Aufwand.

## Anhang: Methodik
Zeitraum, Datenquellen, verwendete Schwellenwerte -- aus dem Digest uebernehmen, nichts \
erfinden.

Nutze NUR die im Digest gegebenen Zahlen/Fakten. Erfinde keine Werte. Wenn eine \
Datenquelle im Digest fehlt/None ist, sag das explizit statt eine Aussage zu erfinden.
"""


_GEMINI_MODEL = "gemini-pro-latest"  # rollierender Alias -- bewusst keine feste Versionsnummer


def build_report(cfg: Config, digest: dict) -> str:
    api_key = cfg.get("seo", {}).get("gemini", {}).get("api_key")
    if not api_key:
        raise RuntimeError(
            "Kein Gemini-API-Key konfiguriert (seo.gemini.api_key) -- "
            "in /settings unter 'SEO-Rechercheagent' eintragen."
        )
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=_GEMINI_MODEL,
        contents=json.dumps(digest, ensure_ascii=False),
        config=genai_types.GenerateContentConfig(
            system_instruction=_REPORT_SYSTEM_PROMPT,
            max_output_tokens=16000,
        ),
    )
    return response.text


# --- Orchestrierung ---------------------------------------------------------------
def run(cfg: Config, settings_store: SettingsStore) -> Path:
    """Baut den Digest, ruft das Modell auf, schreibt den Report. Gibt den Pfad zurueck."""
    se_cfg = cfg.get("seo", {})
    if se_cfg.get("seranking", {}).get("auto_discover_pages"):
        sync_result = seranking_pages_sync.sync_into_settings(cfg, settings_store)
        print(f"Rechercheagent: Seiten-Discovery -- {sync_result['added_pages']} neu, "
              f"{sync_result['updated_pages']} aktualisiert, "
              f"{len(sync_result['unassigned'])} unzugeordnete Keywords.")
        cfg = Config.from_settings_store(settings_store)

    db_path = Path(se_cfg.get("db_path", "data/seo.db"))
    db_path = db_path if db_path.is_absolute() else (BASE_DIR / db_path)

    with SeoStore(db_path) as seo_store:
        digest = build_digest(cfg, seo_store, settings_store)

    report_text = build_report(cfg, digest)

    report_dir = Path(se_cfg.get("research", {}).get("report_dir", "data/reports"))
    report_dir = report_dir if report_dir.is_absolute() else (BASE_DIR / report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"seo-analyse-{date.today().isoformat()}.md"
    report_path.write_text(report_text, encoding="utf-8")
    return report_path


# --- Recherche-Projekte (Mehr-Nischen-Audits + Dialog) -----------------------------
# Explizite Parameter statt Config-Objekt (im Gegensatz zu build_digest()/run() oben,
# die unveraendert bleiben) -- research_projects ist eine variable Liste, kein fester
# Pfad in einem verschachtelten Dict wie seo.gsc.property. gsc_client/ga4_client/
# seranking_client nehmen ohnehin schon explizite Parameter, das passt stilistisch.

def build_project_digest(project: dict, pages: list[dict], gsc_service, ga4_client_obj,
                          seranking_api_key: str, seo_store: SeoStore,
                          window_days: int = _WINDOW_DAYS,
                          cannibalization_window_days: int = _CANNIBALIZATION_WINDOW_DAYS) -> dict:
    """project: {id, label, gsc_property, ga4_property_id, seranking_project_id,
    auto_discover_pages}. Analog build_digest(), aber ALLE Zahlen live abgerufen --
    kein seo_store-Verlauf noetig (im Gegensatz zum globalen, taeglich per Cron
    akkumulierenden SEO-Monitoring). Ein Recherche-Projekt bekommt so ohne vorherige
    Sync-Historie sofort einen vollstaendigen Audit. Rang-Trend wird NICHT weggelassen --
    seranking_client.fetch_daily() liefert die von SE Ranking bereits gespeicherte
    Positions-Historie live per Datumsbereich (genau wie GSC), keine eigene
    Akkumulation noetig (siehe Architektur-Notiz im Plan)."""
    windows = _windows()
    combined_start, combined_end = windows["previous"][0], windows["current"][1]
    property_url = project.get("gsc_property") or ""
    ga4_property_id = project.get("ga4_property_id") or ""
    seranking_project_id = project.get("seranking_project_id") or ""
    label = project.get("label", "")

    pages_digest = []
    all_query_rows = []
    cann_end = date.today() - timedelta(days=_LAG_DAYS)
    cann_start = cann_end - timedelta(days=cannibalization_window_days)

    for entry in pages:
        page = entry["url"]
        keywords = entry.get("keywords", [])

        gsc_rows: list[dict] = []
        if gsc_service is not None and property_url:
            try:
                gsc_rows = gsc_client.fetch_daily(gsc_service, property_url, page, keywords,
                                                   combined_start, combined_end)
                all_query_rows.extend(gsc_client.fetch_all_queries(
                    gsc_service, property_url, page, cann_start.isoformat(), cann_end.isoformat()
                ))
            except Exception as exc:  # noqa: BLE001
                print(f"Recherche-Projekt {label}: GSC-Abruf fuer {page!r} fehlgeschlagen ({exc})",
                      file=sys.stderr)

        ga4_rows: list[dict] = []
        if ga4_client_obj is not None and ga4_property_id:
            try:
                ga4_rows = ga4_client.fetch_daily(ga4_client_obj, ga4_property_id, page,
                                                   combined_start, combined_end)
            except Exception as exc:  # noqa: BLE001
                print(f"Recherche-Projekt {label}: GA4-Abruf fuer {page!r} fehlgeschlagen ({exc})",
                      file=sys.stderr)

        rank_rows: list[dict] = []
        if seranking_api_key and seranking_project_id and keywords:
            try:
                rank_rows = seranking_client.fetch_daily(
                    seranking_api_key, seranking_project_id, page, keywords,
                    combined_start, combined_end,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"Recherche-Projekt {label}: SE-Ranking-Abruf fuer {page!r} fehlgeschlagen ({exc})",
                      file=sys.stderr)

        pages_digest.append({
            "url": page or "/",
            "keywords_tracked": keywords,
            "gsc": {"last_30d": _gsc_stats(gsc_rows, page, windows["current"]),
                    "prev_30d": _gsc_stats(gsc_rows, page, windows["previous"])},
            "ga4": {"last_30d": _ga4_stats(ga4_rows, page, windows["current"]),
                    "prev_30d": _ga4_stats(ga4_rows, page, windows["previous"])},
            "rank": {"last_30d": _rank_stats(rank_rows, page, windows["current"]),
                     "prev_30d": _rank_stats(rank_rows, page, windows["previous"])},
            "events": [],  # projekt-eigene Livegang-Marker sind nicht Teil dieses Plans
        })

    cannibalization_findings = (
        cannibalization.detect_cannibalization(all_query_rows) if all_query_rows else []
    )

    # Unzugeordnete Keywords + Keyword-Research (identisch zur Logik in build_digest()).
    unassigned: list[str] = []
    keyword_research: dict[str, dict] = {}
    if seranking_api_key and seranking_project_id:
        try:
            discovery = seranking_pages_sync.discover(seranking_api_key, seranking_project_id, property_url)
            unassigned = discovery["unassigned"]
            all_tracked = sorted({kw for e in pages for kw in e.get("keywords", [])} | set(unassigned))
            volumes = seranking_keyword_research.export_metrics(seo_store, seranking_api_key, all_tracked)
            volume_by_kw = {v["keyword"]: v for v in volumes if v.get("is_data_found")}
            for kw in unassigned:
                similar = seranking_keyword_research.fetch_similar(seo_store, seranking_api_key, kw)
                keyword_research[kw] = {
                    "volume": volume_by_kw.get(kw, {}).get("volume"),
                    "similar_keywords": similar.get("keywords", [])[:15],
                }
            for entry in pages_digest:
                entry["keyword_volumes"] = {
                    kw: volume_by_kw.get(kw, {}).get("volume") for kw in entry["keywords_tracked"]
                }
        except Exception as exc:  # noqa: BLE001
            print(f"Recherche-Projekt {label}: Keyword-Research fehlgeschlagen ({exc})", file=sys.stderr)

    return {
        "niche": label,
        "window": {"current": windows["current"], "previous": windows["previous"]},
        "pages": pages_digest,
        "cannibalization": cannibalization_findings,
        "unassigned_keywords": unassigned,
        "keyword_research": keyword_research,
    }


_PROJECT_AUDIT_SYSTEM_PROMPT = _REPORT_SYSTEM_PROMPT.replace(
    "## Ungenutzte Keyword-Chancen",
    """## Wettbewerbs-/Marktkontext
Nutze das Search-Tool, um aktuell fuer die wichtigsten Keywords im Digest zu recherchieren:
wer rankt gerade vorne (Wettbewerber-Domains), gibt es auffaellige Aenderungen im
Suchverhalten (z. B. zunehmende KI-Suche/AI Overviews, steigende Wettbewerbsdichte)?
Diese Daten liegen NICHT im Digest -- hole sie aktiv per Suche und belege sie mit Quellen.
Kein SE-Ranking-SERP-Datensatz vorhanden; das ist bewusst so, siehe oben.

## Ungenutzte Keyword-Chancen""",
)

_DIALOG_SYSTEM_PROMPT = """\
Du bist derselbe SEO-Stratege, der den obigen Bericht erstellt hat. Beantworte \
Rueckfragen zum Bericht praezise, auf Basis des mitgegebenen Digests und des bisherigen \
Gespraechsverlaufs. Nutze bei Bedarf das Search-Tool fuer aktuelle Zusatzinformationen \
(z. B. neue Wettbewerber, aktuelle Rankingaenderungen). Erfinde keine Zahlen, die nicht \
im Digest stehen oder durch eine eigene Suche belegt sind.
"""


def _extract_sources(response) -> list[dict]:
    """Grounding-Quellen aus einer Gemini-Antwort extrahieren (leer, wenn das Modell
    das Search-Tool fuer diese Antwort nicht genutzt hat)."""
    sources = []
    try:
        grounding = response.candidates[0].grounding_metadata
        for chunk in (grounding.grounding_chunks or []) if grounding else []:
            if chunk.web:
                sources.append({"title": chunk.web.title, "uri": chunk.web.uri,
                                 "domain": chunk.web.domain})
    except (AttributeError, IndexError):
        pass
    return sources


def _generate_with_search(contents, system_instruction: str, api_key: str,
                           max_output_tokens: int = 16000) -> tuple[str, list[dict]]:
    """Ein generate_content()-Call MIT Google-Search-Grounding-Tool -- bewusste, auf
    diesen einen Zweck begrenzte Ausnahme von der sonstigen "kein Tool-Use fuers
    Modell"-Architektur: Wettbewerberkontext laesst sich nicht vorab deterministisch
    enumerieren (im Gegensatz zu den eigenen GSC/GA4/SE-Ranking-Zahlen)."""
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=_GEMINI_MODEL,
        contents=contents,
        config=genai_types.GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=max_output_tokens,
            tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())],
        ),
    )
    return response.text, _extract_sources(response)


def generate_audit_report(digest: dict, api_key: str) -> tuple[str, list[dict]]:
    return _generate_with_search(json.dumps(digest, ensure_ascii=False),
                                  _PROJECT_AUDIT_SYSTEM_PROMPT, api_key)


def generate_dialog_reply(digest: dict, messages: list[dict], api_key: str) -> tuple[str, list[dict]]:
    """``messages`` = kompletter bisheriger Thread (inkl. der neuen User-Frage) --
    Gemini ist zustandslos, der ganze Verlauf muss bei jeder Nachricht erneut mit."""
    contents = [genai_types.Content(
        role="user", parts=[genai_types.Part(text=json.dumps(digest, ensure_ascii=False))],
    )]
    for m in messages:
        role = "model" if m["role"] == "assistant" else "user"
        contents.append(genai_types.Content(role=role, parts=[genai_types.Part(text=m["content"])]))
    return _generate_with_search(contents, _DIALOG_SYSTEM_PROMPT, api_key)


def start_project_audit(project: dict, settings_store: SettingsStore, research_store,
                         seo_store: SeoStore, credentials, seranking_api_key: str,
                         gemini_api_key: str) -> int:
    """Optionaler Auto-Discover-Schritt, dann Digest + EIN Gemini-Call (mit
    Search-Grounding), legt Audit + erste Thread-Nachricht an. Gibt audit_id zurueck."""
    project_id = project["id"]
    if project.get("auto_discover_pages"):
        sync_result = seranking_pages_sync.sync_into_research_project(
            seranking_api_key, project.get("seranking_project_id", ""),
            project.get("gsc_property", ""), project_id, settings_store,
        )
        print(f"Recherche-Projekt {project['label']}: Seiten-Discovery -- "
              f"{sync_result['added_pages']} neu, {sync_result['updated_pages']} aktualisiert, "
              f"{len(sync_result['unassigned'])} unzugeordnete Keywords.")

    pages = settings_store.list_research_project_pages(project_id)

    gsc_service = None
    ga4_client_obj = None
    if credentials is not None:
        try:
            gsc_service = gsc_client.build_service(credentials)
        except Exception as exc:  # noqa: BLE001
            print(f"Recherche-Projekt {project['label']}: GSC-Service-Aufbau fehlgeschlagen ({exc})",
                  file=sys.stderr)
        try:
            ga4_client_obj = ga4_client.build_client(credentials)
        except Exception as exc:  # noqa: BLE001
            print(f"Recherche-Projekt {project['label']}: GA4-Client-Aufbau fehlgeschlagen ({exc})",
                  file=sys.stderr)

    digest = build_project_digest(project, pages, gsc_service, ga4_client_obj,
                                   seranking_api_key, seo_store)
    report_text, sources = generate_audit_report(digest, gemini_api_key)
    return research_store.create_audit(project_id, digest, report_text, sources)


def continue_dialog(audit_id: int, user_message: str, research_store, gemini_api_key: str) -> str:
    """Haengt ``user_message`` an, schickt den gesamten Thread + Digest erneut an
    Gemini, haengt die Antwort (inkl. Quellen) an, gibt den Antworttext zurueck."""
    audit = research_store.get_audit(audit_id)
    if audit is None:
        raise ValueError(f"Audit {audit_id} nicht gefunden")
    research_store.add_message(audit_id, "user", user_message)
    reply_text, sources = generate_dialog_reply(audit["digest"], research_store.list_messages(audit_id),
                                                 gemini_api_key)
    research_store.add_message(audit_id, "assistant", reply_text, sources)
    return reply_text


def main() -> int:
    with SettingsStore(_SETTINGS_DB) as store:
        cfg = Config.from_settings_store(store)
        report_path = run(cfg, store)
    print(f"Bericht geschrieben: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
