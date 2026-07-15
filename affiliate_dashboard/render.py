"""Generiert die statische, self-contained ``dashboard.html``.

Design im Corporate Design von Pixxelpassion (Logo, Markenfarben, Schriften).

Die **Tracking-ID** ist globaler Filter ganz oben: steuert Kennzahlen, Pivot und Trend.

Datengrundlage ist reine Monats-/Tracking-ID-Aggregation (kein Produkt-/ASIN-Level,
da Amazon dies nicht mehr per Export bereitstellt).
"""

from __future__ import annotations

import base64
import json
from datetime import date as _date, datetime, timedelta
from pathlib import Path

_LOGO_PATH = Path(__file__).resolve().parent / "assets" / "logo_pixxelpassion.webp"


def _payload(monthly, meta, seo=None):
    facts = [{
        "month": r["month"],
        "tid": r["tracking_id"],
        "earnings": round(float(r.get("earnings") or 0), 2),
        "revenue": round(float(r.get("revenue") or 0), 2),
        "items": round(float(r.get("items_shipped") or 0), 3),
        "returns": round(float(r.get("returns") or 0), 3),
        "clicks": round(float(r.get("clicks") or 0), 0),
    } for r in monthly]
    months = sorted({f["month"] for f in facts})
    tids = sorted({f["tid"] for f in facts})
    return {"facts": facts, "months": months, "tids": tids, "meta": meta,
            "seo": _seo_payload(seo)}


def _week_bucket(date_str: str) -> str:
    """Montag der ISO-Kalenderwoche des Datums, als ``YYYY-MM-DD`` (Bucket-Schluessel
    fuer die Wochenansicht -- glaettet die naturgemaess verrauschten Tageswerte)."""
    d = _date.fromisoformat(date_str)
    monday = d - timedelta(days=d.weekday())
    return monday.isoformat()


def _aggregate_weekly_gsc(rows: list[dict], page_url: str) -> list[dict]:
    """GSC-Zeilen je (Wochenbeginn, Keyword): Impressionen/Klicks summiert, CTR/Position
    gemittelt."""
    buckets: dict[tuple, dict] = {}
    for r in rows:
        key = (_week_bucket(r["date"]), r["query"])
        b = buckets.setdefault(key, {"impressions": 0.0, "clicks": 0.0, "ctr_sum": 0.0, "pos_sum": 0.0, "n": 0})
        b["impressions"] += float(r.get("impressions") or 0)
        b["clicks"] += float(r.get("clicks") or 0)
        b["ctr_sum"] += float(r.get("ctr") or 0)
        b["pos_sum"] += float(r.get("position") or 0)
        b["n"] += 1
    return [
        {
            "date": week, "page": page_url, "query": query,
            "impressions": round(b["impressions"]),
            "clicks": round(b["clicks"]),
            "ctr": b["ctr_sum"] / b["n"] if b["n"] else 0.0,
            "position": round(b["pos_sum"] / b["n"], 2) if b["n"] else 0.0,
        }
        for (week, query), b in buckets.items()
    ]


def _aggregate_weekly_ga4(rows: list[dict], page_url: str) -> list[dict]:
    """GA4-Zeilen je Wochenbeginn: Seitenviews summiert, Engagement-Zeit gemittelt."""
    buckets: dict[str, dict] = {}
    for r in rows:
        key = _week_bucket(r["date"])
        b = buckets.setdefault(key, {"pageviews": 0.0, "eng_sum": 0.0, "n": 0})
        b["pageviews"] += float(r.get("pageviews") or 0)
        b["eng_sum"] += float(r.get("avg_engagement_seconds") or 0)
        b["n"] += 1
    return [
        {
            "date": week, "page": page_url,
            "pageviews": round(b["pageviews"]),
            "avg_engagement_seconds": round(b["eng_sum"] / b["n"], 1) if b["n"] else 0.0,
        }
        for week, b in buckets.items()
    ]


def _aggregate_weekly_rank(rows: list[dict], page_url: str) -> list[dict]:
    """SE-Ranking-Zeilen je (Wochenbeginn, Keyword): Position gemittelt."""
    buckets: dict[tuple, dict] = {}
    for r in rows:
        key = (_week_bucket(r["date"]), r["keyword"])
        b = buckets.setdefault(key, {"pos_sum": 0.0, "n": 0})
        b["pos_sum"] += float(r.get("position") or 0)
        b["n"] += 1
    return [
        {"date": week, "page": page_url, "keyword": keyword,
         "position": round(b["pos_sum"] / b["n"], 2) if b["n"] else 0.0}
        for (week, keyword), b in buckets.items()
    ]


def _seo_payload(seo):
    """SEO-Rohdaten (gsc/ga4/rank je Datum+Seite(+Keyword)) zu Wochen-Buckets
    aggregieren und in eine je Seite datumsausgerichtete Serien-Liste umformen --
    fertig fuer den normalisierten Mehrlinien-Chart im Dashboard. ``None``, wenn
    SEO-Monitoring nicht aktiv ist.
    """
    if not seo or not seo.get("pages"):
        return None

    gsc_rows = seo.get("gsc", [])
    ga4_rows = seo.get("ga4", [])
    rank_rows = seo.get("rank", [])

    pages_out = []
    for entry in seo["pages"]:
        page_url = entry["url"]
        keywords = entry.get("keywords", [])

        page_gsc = _aggregate_weekly_gsc([r for r in gsc_rows if r["page"] == page_url], page_url)
        page_ga4 = _aggregate_weekly_ga4([r for r in ga4_rows if r["page"] == page_url], page_url)
        page_rank = _aggregate_weekly_rank([r for r in rank_rows if r["page"] == page_url], page_url)

        dates = sorted({r["date"] for r in page_gsc}
                        | {r["date"] for r in page_ga4}
                        | {r["date"] for r in page_rank})
        if not dates:
            continue
        date_index = {d: i for i, d in enumerate(dates)}
        n = len(dates)

        series = []

        if page_ga4:
            pageviews = [None] * n
            engagement = [None] * n
            for r in page_ga4:
                i = date_index[r["date"]]
                pageviews[i] = r.get("pageviews")
                engagement[i] = r.get("avg_engagement_seconds")
            series.append({"key": "pageviews", "label": "Seitenviews",
                           "unit": "count", "values": pageviews})
            series.append({"key": "engagement", "label": "Ø Engagement-Zeit (Sek.)",
                           "unit": "seconds", "values": engagement})

        for kw in keywords:
            kw_rows = [r for r in page_gsc if r["query"].strip().lower() == kw.strip().lower()]
            if not kw_rows:
                continue
            impressions = [None] * n
            clicks = [None] * n
            ctr = [None] * n
            position = [None] * n
            for r in kw_rows:
                i = date_index[r["date"]]
                impressions[i] = r.get("impressions")
                clicks[i] = r.get("clicks")
                ctr[i] = round(float(r.get("ctr") or 0) * 100, 2)
                position[i] = r.get("position")
            series.append({"key": f"impressions::{kw}", "label": f"Impressionen — {kw}",
                           "unit": "count", "values": impressions})
            series.append({"key": f"clicks::{kw}", "label": f"Klicks — {kw}",
                           "unit": "count", "values": clicks})
            series.append({"key": f"ctr::{kw}", "label": f"CTR — {kw}",
                           "unit": "percent", "values": ctr})
            series.append({"key": f"position_gsc::{kw}", "label": f"Position GSC — {kw}",
                           "unit": "position", "values": position})

        for kw in keywords:
            kw_rows = [r for r in page_rank if r["keyword"].strip().lower() == kw.strip().lower()]
            if not kw_rows:
                continue
            position = [None] * n
            for r in kw_rows:
                i = date_index[r["date"]]
                position[i] = r.get("position")
            series.append({"key": f"position_rank::{kw}", "label": f"Position SE Ranking — {kw}",
                           "unit": "position", "values": position})

        if series:
            pages_out.append({"url": page_url, "keywords": keywords, "dates": dates, "series": series})

    return {"pages": pages_out} if pages_out else None


def _json(obj):
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def _logo_data_uri():
    try:
        data = _LOGO_PATH.read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:image/webp;base64,{b64}"
    except Exception:
        return ""


def build_html(monthly, *, source, marketplace, currency, seo=None):
    months = sorted({r["month"] for r in monthly})
    total_earnings = round(sum(float(r.get("earnings") or 0) for r in monthly), 2)
    total_revenue = round(sum(float(r.get("revenue") or 0) for r in monthly), 2)
    meta = {
        "generated": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "period": f"{months[0]} – {months[-1]}" if months else "—",
        "source": source,
        "marketplace": marketplace,
        "currency": currency,
        "totalEarnings": total_earnings,
        "totalRevenue": total_revenue,
    }
    payload = _payload(monthly, meta, seo)
    html = _TEMPLATE.replace("@@PAYLOAD@@", _json(payload))
    html = html.replace("@@LOGO@@", _logo_data_uri())
    html = html.replace("@@GENERATED@@", meta["generated"])
    html = html.replace("@@PERIOD@@", meta["period"])
    html = html.replace("@@SOURCE@@", source)
    return html


def render_to_file(path, monthly, *, source, marketplace, currency, seo=None):
    html = build_html(monthly, source=source, marketplace=marketplace, currency=currency, seo=seo)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Affiliate-Einnahmen – Pixxelpassion</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Montserrat:wght@500;600;700;800&family=Poppins:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
:root{--pp-green:#b7cb3a;--pp-green-dark:#717e21;--pp-ink:#1A202C;--pp-teal:#09adbe;--pp-orange:#f76a0c;--pp-muted:#6b7280;--pp-bg:#fbfbfb;--pp-bg2:#f3f3f3;--pp-card:#ffffff;--pp-border:#e6e8e1;--pp-neg:#b82105;--body-font:'Poppins','Segoe UI',system-ui,sans-serif;--head-font:'Montserrat','Poppins','Segoe UI',sans-serif}
*{box-sizing:border-box}
body{font-family:var(--body-font);margin:0;background:var(--pp-bg);color:var(--pp-ink);-webkit-font-smoothing:antialiased}
.topbar{height:6px;background:linear-gradient(90deg,var(--pp-green) 0%,var(--pp-green-dark) 60%,var(--pp-teal) 100%)}
header{display:flex;align-items:center;gap:1.1rem;padding:1.1rem 2rem;background:var(--pp-card);border-bottom:1px solid var(--pp-border);flex-wrap:wrap}
header img.logo{height:46px;width:auto}
header .titles{line-height:1.15}
header h1{font-family:var(--head-font);font-weight:800;font-size:1.4rem;margin:0;letter-spacing:.2px}
header .sub{color:var(--pp-muted);font-size:.82rem;margin-top:.15rem}
header .spacer{flex:1}
header .stand{color:var(--pp-muted);font-size:.78rem;text-align:right}
main{padding:1.4rem 2rem 2.5rem;max-width:1290px;margin:0 auto}
.filterbar{display:flex;align-items:center;gap:1rem;flex-wrap:wrap;background:linear-gradient(90deg,color-mix(in srgb,var(--pp-green) 16%,var(--pp-card)),var(--pp-card) 70%);border:1px solid color-mix(in srgb,var(--pp-green) 40%,var(--pp-border));border-left:6px solid var(--pp-green);border-radius:14px;padding:.85rem 1.15rem;margin-bottom:1.2rem}
.filterbar .bigctl{font-family:var(--head-font);font-weight:700;font-size:1.02rem;display:flex;align-items:center;gap:.6rem;color:var(--pp-ink)}
.filterbar select{font-family:var(--body-font);font-size:1rem;font-weight:600;padding:.5rem .75rem;min-width:280px;border:1px solid var(--pp-border);border-radius:9px;background:var(--pp-card);color:var(--pp-ink)}
.filterbar select:focus{outline:2px solid color-mix(in srgb,var(--pp-green) 55%,transparent);border-color:var(--pp-green)}
.filterhint{color:var(--pp-gray);font-size:.8rem}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:1rem;margin-bottom:1.4rem}
.card{background:var(--pp-card);border:1px solid var(--pp-border);border-radius:14px;padding:.9rem 1.1rem;position:relative;overflow:hidden}
.card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--pp-green)}
.card .k{color:var(--pp-muted);font-size:.76rem;text-transform:uppercase;letter-spacing:.4px}
.card .v{font-family:var(--head-font);font-size:1.5rem;font-weight:700;margin-top:.2rem;color:var(--pp-ink)}
.card .v.small{font-size:1.15rem;word-break:break-all}
.tabs{display:flex;gap:.2rem;border-bottom:2px solid var(--pp-border);margin-bottom:1.1rem;flex-wrap:wrap}
.tab{font-family:var(--head-font);padding:.6rem 1.1rem;cursor:pointer;border:none;background:none;color:var(--pp-gray);font-size:.92rem;font-weight:600;border-bottom:3px solid transparent;margin-bottom:-2px}
.tab:hover{color:var(--pp-green-dark)}
.tab.active{color:var(--pp-green-dark);border-bottom-color:var(--pp-green)}
.controls{display:flex;gap:.9rem;align-items:center;flex-wrap:wrap;margin-bottom:1rem}
label.ctl{font-size:.82rem;color:var(--pp-muted);display:flex;align-items:center;gap:.4rem}
.controls select,.controls input[type=search]{font-family:var(--body-font);padding:.45rem .65rem;font-size:.9rem;border:1px solid var(--pp-border);border-radius:8px;background:var(--pp-card);color:var(--pp-ink)}
.controls select:focus,.controls input:focus{outline:2px solid color-mix(in srgb,var(--pp-green) 55%,transparent);border-color:var(--pp-green)}
.controls input[type=search]{width:300px}
.count{color:var(--pp-muted);font-size:.82rem}
.panel{background:var(--pp-card);border:1px solid var(--pp-border);border-radius:14px;padding:1rem 1.1rem}
.wrap{overflow:auto;max-height:70vh}
table{border-collapse:collapse;width:100%;font-size:.87rem}
th,td{text-align:right;padding:.45rem .65rem;white-space:nowrap;border-bottom:1px solid var(--pp-border)}
th:first-child,td:first-child{text-align:left}
th{font-family:var(--head-font);cursor:pointer;user-select:none;position:sticky;top:0;background:var(--pp-bg2);color:var(--pp-ink);font-weight:600}
tbody tr{cursor:pointer}
tbody tr:hover td{background:color-mix(in srgb,var(--pp-green) 10%,transparent)}
tbody tr.active td{background:color-mix(in srgb,var(--pp-green) 18%,transparent);border-bottom-color:var(--pp-green)}
tfoot td{font-weight:700;border-top:2px solid var(--pp-green);background:var(--pp-bg2)}
.neg{color:var(--pp-neg)}
svg{width:100%;height:440px;display:block}
.axis{stroke:var(--pp-border);stroke-width:1.5}
.gl{stroke:color-mix(in srgb,var(--pp-gray) 14%,transparent);stroke-width:1}
.lbl{fill:var(--pp-muted);font-size:11px;font-family:var(--body-font)}
.chart-cap{font-size:.85rem;color:var(--pp-gray);margin-bottom:.3rem}
.chart-cap b{color:var(--pp-green-dark)}
.hidden{display:none}
.chart-tooltip{position:fixed;pointer-events:none;background:var(--pp-ink);color:#fff;font-family:var(--body-font);font-size:.78rem;padding:.4rem .6rem;border-radius:8px;box-shadow:0 4px 14px rgba(0,0,0,.25);z-index:50;white-space:nowrap;opacity:0;transition:opacity .08s}
.chart-tooltip.show{opacity:1}
.chart-tooltip b{color:var(--pp-green)}
.note{color:var(--pp-muted);font-size:.78rem;margin-top:1rem;max-width:80ch}
footer{color:var(--pp-muted);font-size:.75rem;text-align:center;padding:1rem}
.seo-metrics{display:flex;flex-wrap:wrap;gap:.5rem 1.2rem;margin-bottom:1rem}
.seo-metrics label{display:flex;align-items:center;gap:.4rem;font-size:.85rem;cursor:pointer;color:var(--pp-ink)}
.seo-event-row{display:flex;gap:.8rem;align-items:flex-end;flex-wrap:wrap;margin-top:1.2rem;padding-top:1rem;border-top:1px solid var(--pp-border)}
.seo-event-row input[type=date],.seo-event-row input[type=text]{font-family:var(--body-font);padding:.45rem .65rem;font-size:.9rem;border:1px solid var(--pp-border);border-radius:8px;background:var(--pp-card);color:var(--pp-ink)}
.seo-event-text{flex:1;min-width:220px}
.seo-event-text input{width:100%}
.btn-primary,.btn-secondary{font-family:var(--body-font);padding:.5rem 1rem;border-radius:8px;font-weight:600;font-size:.88rem;cursor:pointer}
.btn-primary{border:1px solid var(--pp-green-dark);background:var(--pp-green);color:var(--pp-ink)}
.btn-secondary{border:1px solid var(--pp-border);background:var(--pp-card);color:var(--pp-ink)}
</style>
</head>
<body>
<div class="topbar"></div>
<header>
  <img class="logo" src="@@LOGO@@" alt="Pixxelpassion">
  <div class="titles">
    <h1>Affiliate-Einnahmen</h1>
    <div class="sub">Amazon PartnerNet · Monat × Tracking-ID</div>
  </div>
  <div class="spacer"></div>
  <div class="stand">Stand: @@GENERATED@@<br>Zeitraum: @@PERIOD@@ · Quelle: @@SOURCE@@</div>
</header>

<main>
  <div class="filterbar">
    <label class="bigctl">Tracking-ID
      <select id="tidSelect"></select>
    </label>
    <span class="filterhint">Globaler Filter – steuert alles darunter.</span>
  </div>

  <div class="cards" id="cards"></div>

  <div class="tabs">
    <button class="tab active" data-view="pivot">Pivot (Monat × Tracking-ID)</button>
    <button class="tab" data-view="trend">Trend-Diagramm</button>
    <button class="tab hidden" data-view="seo" id="seoTabBtn">SEO-Monitoring</button>
  </div>

  <div class="controls">
    <label class="ctl" id="metricWrap">Kennzahl:
      <select id="metric">
        <option value="earnings">Einnahmen (€)</option>
        <option value="revenue">Umsatz (€)</option>
        <option value="items">Gelieferte Artikel</option>
        <option value="clicks">Klicks</option>
      </select>
    </label>
    <span class="count" id="count"></span>
  </div>

  <div id="view-pivot" class="panel wrap"></div>
  <div id="view-trend" class="panel hidden">
    <div class="chart-cap" id="chartCap"></div>
    <svg id="chart" viewBox="0 0 1000 440" preserveAspectRatio="xMidYMid meet"></svg>
  </div>
  <div id="view-seo" class="panel hidden">
    <div class="controls" style="margin-top:0;">
      <label class="ctl">Seite:
        <select id="seoPageSelect"></select>
      </label>
      <span class="count" id="seoCount"></span>
    </div>
    <div id="seoMetrics" class="seo-metrics"></div>
    <div class="chart-cap" id="seoChartCap"></div>
    <svg id="seoChart" viewBox="0 0 1000 440" preserveAspectRatio="xMidYMid meet"></svg>
    <div class="seo-event-row">
      <label class="ctl">Datum:
        <input type="date" id="seoEventDate">
      </label>
      <label class="ctl seo-event-text">Beschreibung:
        <input type="text" id="seoEventText" placeholder="z. B. H1 + Meta-Description überarbeitet">
      </label>
      <button type="button" id="seoEventSave" class="btn-primary">Event speichern</button>
    </div>
    <div class="note" id="seoEventNote">Events werden serverseitig gespeichert.</div>
  </div>
</main>
<div class="chart-tooltip" id="chartTooltip"></div>
<footer>Pixxelpassion · Affiliate-Einnahmen-Dashboard</footer>

<script>
const DB = @@PAYLOAD@@;
const FACTS = DB.facts, MONTHS = DB.months, TIDS = DB.tids, META = DB.meta, SEO = DB.seo;

const fmtEur = new Intl.NumberFormat('de-DE', {style:'currency', currency: META.currency || 'EUR'});
const fmtNum = new Intl.NumberFormat('de-DE', {maximumFractionDigits: 0});
const METRIC_LABEL = {earnings:'Einnahmen', revenue:'Umsatz', items:'Gelieferte Artikel', clicks:'Klicks'};
function isMoney(m){ return m==='earnings'||m==='revenue'; }
function fmt(v, m){ return isMoney(m) ? fmtEur.format(v) : fmtNum.format(Math.round(v)); }
function esc(v){ return String(v ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
const SEP = '~~';

// Tooltip fuer Chart-Datenpunkte (ersetzt natives <title>, folgt der Maus)
const _tip = document.getElementById('chartTooltip');
function showTip(evt, html){
  _tip.innerHTML = html;
  _tip.classList.add('show');
  moveTip(evt);
}
function moveTip(evt){
  const pad = 14;
  let x = evt.clientX + pad, y = evt.clientY + pad;
  const rect = _tip.getBoundingClientRect();
  if(x + rect.width > window.innerWidth - 8) x = evt.clientX - rect.width - pad;
  if(y + rect.height > window.innerHeight - 8) y = evt.clientY - rect.height - pad;
  _tip.style.left = x + 'px';
  _tip.style.top = y + 'px';
}
function hideTip(){ _tip.classList.remove('show'); }

// Jahres-Ticks: Beschriftung nur beim ersten Monat jedes Kalenderjahres (einheitliche Aufteilung)
function yearTickIndices(months){
  const idx = [];
  let lastYear = null;
  months.forEach((mo, i) => {
    const year = mo.slice(0, 4);
    if(year !== lastYear){ idx.push(i); lastYear = year; }
  });
  return idx;
}

let metric = 'earnings', view = 'pivot', selectedTid = '__all__';
const PALETTE = ['#717e21','#09adbe','#f76a0c','#b7cb3a','#2b6cb0','#b82105','#4e5652','#f5a524','#13612e','#9333ea','#1159af','#db2777'];

function isSingle(){ return selectedTid !== '__all__' && selectedTid !== '__total__'; }
function pivotMap(m){
  const map = new Map();
  for(const f of FACTS){ const k=f.month+SEP+f.tid; map.set(k, (map.get(k)||0)+(+f[m]||0)); }
  return map;
}
function tidsByTotal(m){
  return TIDS.map(t => [t, MONTHS.reduce((s,mo)=>s+(pivotMap(m).get(mo+SEP+t)||0),0)])
             .sort((a,b)=>Math.abs(b[1])-Math.abs(a[1]));
}

// Kennzahlen-Karten
function renderCards(){
  let cards;
  if(isSingle()){
    const fs = FACTS.filter(f=>f.tid===selectedTid);
    const earn = fs.reduce((s,f)=>s+f.earnings,0);
    const rev = fs.reduce((s,f)=>s+f.revenue,0);
    const share = META.totalEarnings ? (earn/META.totalEarnings*100) : 0;
    cards = [
      ['Einnahmen (gefiltert)', fmtEur.format(earn), false],
      ['Umsatz (gefiltert)', fmtEur.format(rev), false],
      ['Tracking-ID', selectedTid, true],
      ['Anteil an Einnahmen', share.toLocaleString('de-DE',{maximumFractionDigits:1})+' %', false],
    ];
  } else {
    cards = [
      ['Einnahmen gesamt', fmtEur.format(META.totalEarnings), false],
      ['Umsatz gesamt', fmtEur.format(META.totalRevenue), false],
      ['Tracking-IDs', fmtNum.format(TIDS.length), false],
      ['Monate', fmtNum.format(MONTHS.length), false],
    ];
  }
  document.getElementById('cards').innerHTML = cards.map(c =>
    '<div class="card"><div class="k">'+esc(c[0])+'</div><div class="v'+(c[2]?' small':'')+'">'+esc(c[1])+'</div></div>').join('');
}

// Pivot-Tabelle
let pivotSort = {col:null, dir:1};
function renderPivot(){
  const map = pivotMap(metric);
  const isTotal = selectedTid==='__total__';
  const cols = isTotal ? ['Gesamt'] : (isSingle() ? [selectedTid] : tidsByTotal(metric).map(t=>t[0]));
  const val = (mo,c) => isTotal ? TIDS.reduce((s,t)=>s+(map.get(mo+SEP+t)||0),0) : (map.get(mo+SEP+c)||0);

  let rows = MONTHS.map(mo => ({mo, cells: cols.map(c => val(mo,c)), sum: cols.reduce((a,b,i)=>a+val(mo,cols[i]),0)}));
  if(pivotSort.col==='__month__') rows.sort((a,b)=>a.mo.localeCompare(b.mo)*pivotSort.dir);
  else if(pivotSort.col==='__sum__') rows.sort((a,b)=>(a.sum-b.sum)*pivotSort.dir);
  else if(pivotSort.col!==null){ const i=cols.indexOf(pivotSort.col); if(i>=0) rows.sort((a,b)=>(a.cells[i]-b.cells[i])*pivotSort.dir); }

  const colTotals = cols.map((t,i)=>rows.reduce((s,r)=>s+r.cells[i],0));
  const grand = colTotals.reduce((a,b)=>a+b,0);
  const cell = v => '<td class="'+(v<0?'neg':'')+'">'+(v?fmt(v,metric):'·')+'</td>';

  let head = '<th onclick="sortPivot(\'__month__\')">Monat</th>' + cols.map(t=>'<th onclick="sortPivot(\''+esc(t)+'\')">'+esc(t)+'</th>').join('');
  let body = rows.map(r=>'<tr><td>'+esc(r.mo)+'</td>'+r.cells.map(cell).join('')+'<td><b>'+fmt(r.sum,metric)+'</b></td></tr>').join('');
  let foot = '<tr><td>Σ Gesamt</td>'+colTotals.map(v=>'<td>'+fmt(v,metric)+'</td>').join('')+'<td>'+fmt(grand,metric)+'</td></tr>';

  document.getElementById('view-pivot').innerHTML='<table><thead><tr>'+head+'</tr></thead><tbody>'+body+'</tbody><tfoot>'+foot+'</tfoot></table>';
  document.getElementById('count').textContent=MONTHS.length+' Monate × '+(isTotal?'Gesamt':cols.length+' Tracking-ID'+(cols.length>1?'s':''));
}
function sortPivot(key){ if(pivotSort.col===key)pivotSort.dir=-pivotSort.dir; else {pivotSort.col=key; pivotSort.dir=-1;} renderPivot(); }

// Trend-Diagramm
function seriesForSelection(){
  const map = pivotMap(metric);
  if(selectedTid==='__all__'){
    const top = tidsByTotal(metric).slice(0,12).map(t=>t[0]);
    let series = top.map((t,i)=>({tid:t, color:PALETTE[i%PALETTE.length],
      pts: MONTHS.map(mo=>map.get(mo+SEP+t)||0)}));
    if(visibleSeries.size > 0) series = series.filter((s,i)=>visibleSeries.has(i));
    if(visibleSeries.size === 0) visibleSeries = new Set(series.map((_,i)=>i));
    return {single:false, series: series, allSeries: top.map((t,i)=>({tid:t, color:PALETTE[i%PALETTE.length]}))};
  }
  if(selectedTid==='__total__'){
    return {single:true, label:'Gesamt (alle Tracking-IDs)',
      series:[{tid:'Gesamt', color:'#717e21', pts: MONTHS.map(mo=>TIDS.reduce((s,t)=>s+(map.get(mo+SEP+t)||0),0))}]};
  }
  return {single:true, label:selectedTid, series:[{tid:selectedTid, color:'#717e21',
    pts: MONTHS.map(mo=>map.get(mo+SEP+selectedTid)||0)}]};
}
function shortNum(v){ const a=Math.abs(v); if(a>=1000) return fmtNum.format(Math.round(v/1000))+'k';
  return fmtNum.format(Math.round(v*100)/100); }
function renderTrend(){
  const sel = seriesForSelection();
  let series = sel.series;
  const W=1000,H=440,padL=78,padR=24,padT=20,padB=58;
  const innerW=W-padL-padR, innerH=H-padT-padB;
  let maxV=0,minV=0;
  for(const s of series) for(const v of s.pts){ if(v>maxV)maxV=v; if(v<minV)minV=v; }
  if(maxV===0&&minV===0) maxV=1;
  maxV = maxV + (maxV-minV)*0.05;
  const x = i => padL + (MONTHS.length<=1?innerW/2 : innerW*i/(MONTHS.length-1));
  const y = v => padT + innerH*(1-(v-minV)/((maxV-minV)||1));

  let svg='';
  for(let k=0;k<=5;k++){ const val=minV+(maxV-minV)*k/5, yy=y(val);
    svg+='<line class="gl" x1="'+padL+'" y1="'+yy+'" x2="'+(W-padR)+'" y2="'+yy+'"/>';
    svg+='<text class="lbl" x="'+(padL-8)+'" y="'+(yy+4)+'" text-anchor="end">'+esc(shortNum(val))+'</text>'; }
  yearTickIndices(MONTHS).forEach(i => { const xx=x(i);
    svg+='<line class="gl" x1="'+xx+'" y1="'+padT+'" x2="'+xx+'" y2="'+(H-padB)+'"/>';
    svg+='<text class="lbl" x="'+xx+'" y="'+(H-padB+18)+'" text-anchor="middle">'+esc(MONTHS[i].slice(0,4))+'</text>'; });
  svg+='<line class="axis" x1="'+padL+'" y1="'+padT+'" x2="'+padL+'" y2="'+(H-padB)+'"/>';
  svg+='<line class="axis" x1="'+padL+'" y1="'+y(0)+'" x2="'+(W-padR)+'" y2="'+y(0)+'"/>';

  for(const s of series){
    const linePts = s.pts.map((v,i)=>x(i)+' '+y(v));
    if(sel.single){
      const area = 'M'+x(0)+' '+y(0)+' L'+linePts.join(' L')+' L'+x(s.pts.length-1)+' '+y(0)+' Z';
      svg+='<path d="'+area+'" fill="#b7cb3a" fill-opacity="0.18"/>';
    }
    svg+='<path d="M'+linePts.join(' L')+'" fill="none" stroke="'+s.color+'" stroke-width="'+(sel.single?2.6:2)+'" stroke-linejoin="round"/>';
    const r = sel.single?3:2.2;
    for(let i=0;i<s.pts.length;i++){
      const tipHtml = '<b>'+esc(s.tid)+'</b> · '+esc(MONTHS[i])+'<br>'+esc(fmt(s.pts[i],metric));
      svg+='<circle cx="'+x(i)+'" cy="'+y(s.pts[i])+'" r="'+(r+4)+'" fill="transparent" '+
        'onmouseenter="showTip(event, \''+tipHtml.replace(/'/g,"\\'")+'\')" onmousemove="moveTip(event)" onmouseleave="hideTip()"/>';
      svg+='<circle cx="'+x(i)+'" cy="'+y(s.pts[i])+'" r="'+r+'" fill="'+s.color+'" style="pointer-events:none"/>';
    }
  }
  document.getElementById('chart').innerHTML = svg;
  const cap=document.getElementById('chartCap');
  if(sel.single){
    const pts=sel.series[0].pts, sum=pts.reduce((a,b)=>a+b,0);
    const peakI=pts.reduce((bi,v,i)=>v>pts[bi]?i:bi,0);
    cap.innerHTML='<b>'+esc(sel.label)+'</b> · '+METRIC_LABEL[metric]+' im Zeitverlauf · Gesamt: '+
      fmt(sum,metric)+' · Bestmonat: '+esc(MONTHS[peakI])+' ('+fmt(pts[peakI],metric)+')';
  } else {
    let legend = '<b>Top 12 Tracking-IDs</b> · '+METRIC_LABEL[metric]+' · Klick auf Legende zum An/Ausschalten:<br>';
    legend += sel.allSeries.map((s, i) => '<span style="display:inline-block;margin-right:1rem;cursor:pointer;opacity:'+(visibleSeries.has(i)?'1':'0.3')+'" onclick="toggleSeries('+i+')" title="Klick zum An/Ausschalten"><span style="display:inline-block;width:12px;height:12px;background:'+s.color+';margin-right:.3rem;vertical-align:middle;border:1px solid #ccc;"></span>'+esc(s.tid)+'</span>').join('');
    cap.innerHTML = legend;
  }
}

let visibleSeries = new Set();
function toggleSeries(idx){
  if(visibleSeries.has(idx)) visibleSeries.delete(idx);
  else visibleSeries.add(idx);
  renderTrend();
}

// SEO-Monitoring: normalisierter Mehrlinien-Chart je Seite + Event-Marker (localStorage)
let seoPage = null;
let seoSelectedKeys = new Set();
let seoEvents = [];

function monthTickIndices(dates){
  const idx = [];
  let last = null;
  dates.forEach((d, i) => { const ym = d.slice(0,7); if(ym !== last){ idx.push(i); last = ym; } });
  return idx;
}
async function loadSeoEvents(){
  try {
    const resp = await fetch('/api/seo/events');
    return resp.ok ? await resp.json() : [];
  } catch(e){ return []; }
}
async function postSeoEvent(page, date, text){
  await fetch('/api/seo/events', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({page, date, text}),
  });
}
function currentSeoPage(){ return SEO.pages.find(p => p.url === seoPage); }

function renderSeoControls(){
  document.getElementById('seoPageSelect').innerHTML = SEO.pages.map(p =>
    '<option value="'+esc(p.url)+'">'+esc(p.url)+'</option>').join('');
  if(!seoPage) seoPage = SEO.pages[0].url;
  document.getElementById('seoPageSelect').value = seoPage;

  const page = currentSeoPage();
  if(seoSelectedKeys.size === 0) page.series.forEach(s => seoSelectedKeys.add(s.key));

  document.getElementById('seoMetrics').innerHTML = page.series.map(s =>
    '<label><input type="checkbox" data-key="'+esc(s.key)+'" '+(seoSelectedKeys.has(s.key)?'checked':'')+'> '+esc(s.label)+'</label>'
  ).join('');
  document.querySelectorAll('#seoMetrics input[type=checkbox]').forEach(cb => {
    cb.addEventListener('change', e => {
      if(e.target.checked) seoSelectedKeys.add(e.target.dataset.key);
      else seoSelectedKeys.delete(e.target.dataset.key);
      renderSeoChart();
    });
  });
}

function seoFmtRaw(raw, unit){
  if(raw === null || raw === undefined) return '–';
  if(unit === 'percent') return raw.toFixed(2)+' %';
  if(unit === 'seconds') return raw.toFixed(1)+' s';
  if(unit === 'position') return raw.toFixed(1);
  return fmtNum.format(raw);
}

function weekBucketOf(dateStr){
  // Montag der ISO-Kalenderwoche, wie serverseitig in render.py::_week_bucket() --
  // Events tragen ein exaktes Tagesdatum, die Chart-Daten sind aber jetzt
  // wochenweise gebuckelt, daher hier auf denselben Wochen-Schluessel "einrasten".
  const d = new Date(dateStr + 'T00:00:00Z');
  const day = (d.getUTCDay() + 6) % 7; // Montag=0 .. Sonntag=6
  d.setUTCDate(d.getUTCDate() - day);
  return d.toISOString().slice(0, 10);
}

function renderSeoChart(){
  const page = currentSeoPage();
  if(!page) return;
  const dates = page.dates;
  const events = seoEvents.filter(e => e.page === page.url).sort((a,b)=>a.date.localeCompare(b.date));
  const refDate = events.length ? events[0].date : dates[0];
  let refIdx = dates.indexOf(weekBucketOf(refDate));
  if(refIdx < 0) refIdx = 0;

  const series = page.series.filter(s => seoSelectedKeys.has(s.key));
  const W=1000,H=440,padL=60,padR=24,padT=20,padB=58;
  const innerW=W-padL-padR, innerH=H-padT-padB;

  const normed = series.map((s, si) => {
    let ref = s.values[refIdx];
    if(ref === null || ref === undefined || ref === 0) ref = s.values.find(v => v!==null && v!==undefined && v!==0);
    const pts = s.values.map(v => (v===null || v===undefined || !ref) ? null : (v/ref*100));
    return {...s, color: PALETTE[si % PALETTE.length], pts};
  });

  let maxV = 100, minV = 100;
  normed.forEach(s => s.pts.forEach(v => { if(v!==null){ if(v>maxV)maxV=v; if(v<minV)minV=v; } }));
  const pad = (maxV-minV)*0.08 || 15;
  maxV += pad; minV -= pad*0.4;

  const x = i => padL + (dates.length<=1?innerW/2 : innerW*i/(dates.length-1));
  const y = v => padT + innerH*(1-(v-minV)/((maxV-minV)||1));

  let svg='';
  for(let k=0;k<=5;k++){ const val=minV+(maxV-minV)*k/5, yy=y(val);
    svg+='<line class="gl" x1="'+padL+'" y1="'+yy+'" x2="'+(W-padR)+'" y2="'+yy+'"/>';
    svg+='<text class="lbl" x="'+(padL-8)+'" y="'+(yy+4)+'" text-anchor="end">'+Math.round(val)+'</text>'; }
  monthTickIndices(dates).forEach(i => { const xx=x(i);
    svg+='<line class="gl" x1="'+xx+'" y1="'+padT+'" x2="'+xx+'" y2="'+(H-padB)+'"/>';
    svg+='<text class="lbl" x="'+xx+'" y="'+(H-padB+18)+'" text-anchor="middle">'+esc(dates[i].slice(0,7))+'</text>'; });
  svg+='<line class="axis" x1="'+padL+'" y1="'+padT+'" x2="'+padL+'" y2="'+(H-padB)+'"/>';
  svg+='<line class="axis" x1="'+padL+'" y1="'+(H-padB)+'" x2="'+(W-padR)+'" y2="'+(H-padB)+'"/>';
  const y100 = y(100);
  svg += '<line x1="'+padL+'" y1="'+y100+'" x2="'+(W-padR)+'" y2="'+y100+'" stroke="#9aa08f" stroke-dasharray="2,3" stroke-width="1"/>';

  events.forEach(ev => {
    const i = dates.indexOf(weekBucketOf(ev.date));
    if(i < 0) return;
    const xx = x(i);
    const tipHtml = '<b>'+esc(ev.date)+'</b><br>'+esc(ev.text);
    svg += '<line x1="'+xx+'" y1="'+padT+'" x2="'+xx+'" y2="'+(H-padB)+'" stroke="var(--pp-orange)" stroke-width="1.5" stroke-dasharray="4,3"/>';
    svg += '<polygon points="'+xx+','+(padT+6)+' '+(xx-5)+','+(padT-2)+' '+(xx+5)+','+(padT-2)+'" fill="var(--pp-orange)" '+
      'onmouseenter="showTip(event,\''+tipHtml.replace(/'/g,"\\'")+'\')" onmousemove="moveTip(event)" onmouseleave="hideTip()"/>';
  });

  normed.forEach(s => {
    let segment = [], d = '';
    s.pts.forEach((v,i) => {
      if(v === null){ if(segment.length>1) d += (d?' M':'M')+segment.join(' L'); segment = []; return; }
      segment.push(x(i)+' '+y(v));
    });
    if(segment.length>1) d += (d?' M':'M')+segment.join(' L');
    if(d) svg += '<path d="'+d+'" fill="none" stroke="'+s.color+'" stroke-width="2.4" stroke-linejoin="round"/>';

    s.pts.forEach((v,i) => {
      if(v === null) return;
      const tipHtml = '<b>'+esc(s.label)+'</b> · '+esc(dates[i])+'<br>'+esc(seoFmtRaw(s.values[i], s.unit));
      svg += '<circle cx="'+x(i)+'" cy="'+y(v)+'" r="6" fill="transparent" '+
        'onmouseenter="showTip(event,\''+tipHtml.replace(/'/g,"\\'")+'\')" onmousemove="moveTip(event)" onmouseleave="hideTip()"/>';
      svg += '<circle cx="'+x(i)+'" cy="'+y(v)+'" r="2.6" fill="'+s.color+'" style="pointer-events:none"/>';
    });
  });

  document.getElementById('seoChart').innerHTML = svg;

  let legend = '<b>'+esc(page.url)+'</b> · Wochenwerte, Index = 100 in der Woche ab '+esc(dates[refIdx])+
    (events.length ? ' (erstes Event)' : ' (erster Datenpunkt)') + ' · Position: niedriger = besser<br>';
  legend += normed.map(s => '<span style="display:inline-block;margin-right:1rem;">'+
    '<span style="display:inline-block;width:12px;height:12px;background:'+s.color+';margin-right:.3rem;vertical-align:middle;border:1px solid #ccc;"></span>'+
    esc(s.label)+'</span>').join('');
  document.getElementById('seoChartCap').innerHTML = legend;
  document.getElementById('seoCount').textContent = dates.length+' Tage · '+events.length+' Event(s)';
}

async function renderSeo(){
  if(!SEO || !SEO.pages || !SEO.pages.length) return;
  seoEvents = await loadSeoEvents();
  renderSeoControls();
  renderSeoChart();
}

// Initialisierung
function init(){
  // TID-Auswahl
  const opts = ['Alle', ...TIDS, 'Gesamt'];
  document.getElementById('tidSelect').innerHTML = opts.map((t,i) =>
    '<option value="'+(i===0?'__all__':i===opts.length-1?'__total__':t)+'">'+esc(t)+'</option>').join('');
  document.getElementById('tidSelect').addEventListener('change', e => {
    selectedTid = e.target.value;
    visibleSeries = new Set();
    renderCards();
    renderPivot();
    renderTrend();
  });

  // Metric-Auswahl
  document.getElementById('metric').addEventListener('change', e => {
    metric = e.target.value;
    renderCards();
    renderPivot();
    renderTrend();
  });

  // Tabs
  document.querySelectorAll('.tab').forEach(btn => btn.addEventListener('click', e => {
    view = e.target.dataset.view;
    document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('[id^="view-"]').forEach(p => p.classList.add('hidden'));
    e.target.classList.add('active');
    document.getElementById('view-'+view).classList.remove('hidden');
    document.querySelector('main > .controls').classList.toggle('hidden', view === 'seo');
    if(view==='pivot') renderPivot();
    else if(view==='trend') renderTrend();
    else if(view==='seo') renderSeo();
  }));

  // SEO-Monitoring (nur sichtbar, wenn Daten vorhanden)
  if(SEO && SEO.pages && SEO.pages.length){
    document.getElementById('seoTabBtn').classList.remove('hidden');

    document.getElementById('seoPageSelect').addEventListener('change', e => {
      seoPage = e.target.value;
      seoSelectedKeys = new Set();
      renderSeoControls();
      renderSeoChart();
    });

    document.getElementById('seoEventSave').addEventListener('click', async () => {
      const d = document.getElementById('seoEventDate').value;
      const t = document.getElementById('seoEventText').value.trim();
      if(!d || !t) return;
      await postSeoEvent(seoPage, d, t);
      seoEvents = await loadSeoEvents();
      document.getElementById('seoEventText').value = '';
      renderSeoChart();
    });
  }

  renderCards();
  renderPivot();
}
init();
</script>
</body>
</html>
"""
