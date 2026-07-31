"""Crawlt die eigene Website (kein Amazon-Bezug) und baut eine Zuordnung
ASIN -> Liste eigener Seiten auf, die einen Amazon-Link zu dieser ASIN enthalten.

Genutzt, um im "Verfuegbarkeit pruefen"-Overlay sofort zu zeigen, auf welchen
eigenen Seiten ein Produkt aktuell beworben wird (z. B. Bestenlisten-Seiten,
nicht nur der dedizierte Testartikel). Liest die eigene Sitemap (kein
Amazon-Scraping, kein ToS-Risiko) und durchsucht jede gefundene Seite per Regex
nach ausgehenden Amazon-Links.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.request import Request, urlopen

_USER_AGENT = "Mozilla/5.0 (affiliate-dashboard site-crawler; +https://localhost)"
_MAX_PAGES = 500

_ASIN_LINK_RE = re.compile(
    r"amazon\.[a-z.]+/(?:[^\"'\s]*/)?(?:dp|gp/product)/([A-Z0-9]{10})", re.IGNORECASE
)
_SHORT_LINK_RE = re.compile(r"https?://amzn\.to/[A-Za-z0-9]+")

# Cache fuer aufgeloeste amzn.to-Kurzlinks, gueltig fuer die Laufzeit eines
# Crawl-Prozesses (vermeidet doppelte Redirect-Aufloesung innerhalb eines Syncs).
_short_link_cache: dict[str, str | None] = {}


def _fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": _USER_AGENT})
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _locs(root, tag: str) -> list[str]:
    """Alle <loc>-Texte unterhalb von Elementen mit gegebenem (namespace-egalem) Tag.

    Nutzt bewusst keinen ``{*}``-Wildcard (in ``Element.iter()`` je nach
    Python-Version unzuverlaessig), sondern vergleicht den lokalen Tag-Namen
    nach Abtrennen des Namespace-Praefixes -- funktioniert unabhaengig von
    der jeweils deklarierten Sitemap-Namespace-URI.
    """
    out = []
    for el in root.iter():
        if _local_name(el.tag) != tag:
            continue
        for child in el:
            if _local_name(child.tag) == "loc" and child.text:
                out.append(child.text.strip())
    return out


def _looks_like_sitemap(text: str) -> bool:
    """Manche Server liefern fuer eine nicht existierende Sitemap-URL still eine
    normale HTML-Seite mit Status 200 statt eines Fehlers -- daher Inhalt statt
    nur den Fetch-Erfolg pruefen."""
    head = text.lstrip()[:200].lower()
    return head.startswith("<?xml") or "<urlset" in head or "<sitemapindex" in head


def _sitemap_urls(base_url: str) -> list[str]:
    """Liste aller Seiten-URLs aus der Sitemap (folgt Sitemap-Index-Verschachtelung).

    Probiert mehrere gaengige Pfade (Yoast/RankMath, WordPress-Core-Sitemaps),
    da nicht jede Website dieselbe Konvention nutzt.
    """
    base = base_url.rstrip("/")
    text = None
    for path in ("/sitemap_index.xml", "/sitemap.xml", "/wp-sitemap.xml"):
        try:
            candidate = _fetch(base + path)
        except Exception:
            continue
        if _looks_like_sitemap(candidate):
            text = candidate
            break
    if text is None:
        raise RuntimeError(
            f"Keine gueltige Sitemap gefunden unter {base} "
            f"(/sitemap_index.xml, /sitemap.xml, /wp-sitemap.xml probiert)."
        )

    root = ET.fromstring(text)

    # Sitemap-Index: <sitemapindex><sitemap><loc>...</loc></sitemap>...</sitemapindex>
    sub_locs = _locs(root, "sitemap")

    urls: list[str] = []
    if sub_locs:
        for sub_url in sub_locs:
            try:
                sub_root = ET.fromstring(_fetch(sub_url))
                urls.extend(_locs(sub_root, "url"))
            except Exception as exc:
                print(f"Site-Crawl: Sub-Sitemap {sub_url} uebersprungen ({exc})")
                continue
    else:
        # Flaches urlset: <urlset><url><loc>...</loc></url>...</urlset>
        urls.extend(_locs(root, "url"))

    if len(urls) > _MAX_PAGES:
        print(f"Site-Crawl: {len(urls)} Seiten in der Sitemap gefunden, kappe auf {_MAX_PAGES}.")
        urls = urls[:_MAX_PAGES]
    return urls


def _resolve_short_link(short_url: str) -> str | None:
    """Loest einen amzn.to-Kurzlink per Redirect auf die finale Amazon-URL auf (gecacht).

    Dies ist ein Request an den eigenen ausgehenden Kurzlink, kein Abgreifen von
    Amazon-Produktdaten -- nur das Redirect-Ziel wird gelesen.
    """
    if short_url in _short_link_cache:
        return _short_link_cache[short_url]
    try:
        req = Request(short_url, headers={"User-Agent": _USER_AGENT})
        with urlopen(req, timeout=15) as resp:
            final_url = resp.geturl()
    except Exception:
        final_url = None
    _short_link_cache[short_url] = final_url
    return final_url


def _extract_asins(html: str) -> set[str]:
    asins = {m.group(1).upper() for m in _ASIN_LINK_RE.finditer(html)}
    for short_url in set(_SHORT_LINK_RE.findall(html)):
        resolved = _resolve_short_link(short_url)
        if not resolved:
            continue
        m = _ASIN_LINK_RE.search(resolved)
        if m:
            asins.add(m.group(1).upper())
    return asins


def crawl(base_url: str) -> dict[str, list[str]]:
    """Crawlt eine Website und gibt ``{asin: [seiten-urls]}`` zurueck.

    Eine kaputte/unerreichbare Seite bricht den Crawl nicht ab -- sie wird
    uebersprungen und geloggt.
    """
    page_urls = _sitemap_urls(base_url)
    result: dict[str, set[str]] = {}
    for page_url in page_urls:
        try:
            html = _fetch(page_url)
        except Exception as exc:
            print(f"Site-Crawl: Seite {page_url} uebersprungen ({exc})")
            continue
        for asin in _extract_asins(html):
            result.setdefault(asin, set()).add(page_url)
    return {asin: sorted(urls) for asin, urls in result.items()}
