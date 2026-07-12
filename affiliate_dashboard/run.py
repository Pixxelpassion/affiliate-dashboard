"""Orchestrierung + CLI: Quelle einlesen -> aggregieren -> speichern -> dashboard.html.

Beispiele:
    python -m affiliate_dashboard.run                      # Quelle aus config.json
    python -m affiliate_dashboard.run --source gsheet
    python -m affiliate_dashboard.run --source csv --inbox data/inbox
    python -m affiliate_dashboard.run --no-open
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from .config import Config
from .adapters import get_adapter
from .aggregate import aggregate_monthly
from .store import Store
from . import render


def run_once(cfg: Config, *, source: str | None = None) -> dict:
    """Ein vollstaendiger Ingest -> Aggregat -> Render-Durchlauf.

    Genutzt sowohl vom CLI-Entry-Point (``main()``) als auch von ``server.py``s
    ``/api/sync``-Route, damit die Pipeline-Logik nicht dupliziert wird. Wirft bei
    Fehlern (Adapter/Netzwerk) die zugrundeliegende Exception weiter -- die Aufrufer
    entscheiden je nach Kontext (CLI-Exitcode vs. HTTP-Antwort), wie sie reagieren.

    Gibt ein Stats-Dict zurueck (Zeilen/Pfade fuer Logging/Status).
    """
    source = source or cfg.get("source", "gsheet")
    print(f"Quelle: {source}")

    adapter = get_adapter(source, cfg)
    result = adapter.load()

    s = result.stats or {}
    print(f"Eingelesen: {s.get('rows', len(result.items))} Zeilen"
          + (f", ohne Tracking-ID: {s['no_tracking_id']}" if s.get("no_tracking_id") else "")
          + (f", ohne Monat: {s['no_month']}" if s.get("no_month") else ""))

    monthly = aggregate_monthly(result.items)
    print(f"Aggregiert: {len(monthly)} Monats-/Tracking-ID-Kombinationen")

    db_path = cfg.path("db_path")
    with Store(db_path) as store:
        kwargs = dict(marketplace=cfg.get("marketplace", "amazon.de"),
                      currency=cfg.get("currency", "EUR"),
                      source_file=result.source_file)
        if result.full_snapshot:
            store.replace_source(source, monthly, result.items, **kwargs)
        else:
            store.upsert_monthly(source, monthly, result.items, **kwargs)

        all_monthly = store.all_monthly()

    seo_payload = None
    if cfg.get("seo", {}).get("enabled"):
        from .seo import seo_run
        seo_run.sync(cfg)
        seo_payload = seo_run.read_payload(cfg)

    out_path = cfg.path("out_file")
    render.render_to_file(
        out_path, all_monthly,
        source=source,
        marketplace=cfg.get("marketplace", "amazon.de"),
        currency=cfg.get("currency", "EUR"),
        seo=seo_payload,
    )
    print(f"Dashboard erzeugt: {out_path}")
    print(f"Datenbank: {db_path} ({len(all_monthly)} Zeilen gesamt)")

    return {
        "source": source,
        "rows": s.get("rows", len(result.items)),
        "monthly_rows": len(monthly),
        "out_path": str(out_path),
        "seo_enabled": bool(seo_payload),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="affiliate_dashboard.run",
        description="Amazon-PartnerNet-Einnahmen nach Monat × Tracking-ID als dashboard.html.",
    )
    parser.add_argument("--config", help="Pfad zu config.json (Standard: ./config.json)")
    parser.add_argument("--source", choices=["gsheet", "csv", "s3"],
                        help="Datenquelle (ueberschreibt config.json)")
    parser.add_argument("--inbox", help="Eingangsordner fuer den CSV-Adapter")
    parser.add_argument("--out", help="Ausgabedatei (Standard: dashboard.html)")
    parser.add_argument("--no-open", action="store_true", help="Browser nicht oeffnen")
    args = parser.parse_args(argv)

    cfg = Config.load(args.config)
    source = args.source or cfg.get("source", "gsheet")
    if args.inbox:
        cfg._data["inbox_dir"] = args.inbox
    if args.out:
        cfg._data["out_file"] = args.out

    try:
        stats = run_once(cfg, source=source)
    except (ValueError, RuntimeError, NotImplementedError) as exc:
        print(f"\nFEHLER: {exc}", file=sys.stderr)
        return 2

    if cfg.get("open_browser", True) and not args.no_open:
        try:
            webbrowser.open(Path(stats["out_path"]).resolve().as_uri())
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
