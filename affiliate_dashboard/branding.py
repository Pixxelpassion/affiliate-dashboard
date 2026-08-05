"""Gemeinsame Marken-Bausteine (Logo, Favicon, Header-Navigation) fuer dashboard.html
(render.py) und alle Flask-Seiten (server.py) -- EINE Quelle, damit die vier Bereiche
(Analytics/Recherche/Content-Erstellung/Einstellungen) nirgends auseinanderlaufen.

Favicon ist identisch zum Nachbarprojekt parqet-dashboard uebernommen
(Konsistenz ueber beide Pixxelpassion-Tools hinweg). Nav-Styling (schlichte Textlinks,
aktive Seite in Akzentgruen mit Unterstrich statt Button-Rahmen) orientiert sich am
echten Header auf pixxelpassion.de (Astra-Theme, "header-navigation-style-underline") --
dessen Farben #b7cb3a/#717e21 entsprechen bereits exakt unseren bestehenden
--pp-green/--pp-green-dark-Variablen.
"""

from __future__ import annotations

import base64
from pathlib import Path

# Reihenfolge + Label + Ziel-URL der vier Navigationsbereiche -- einzige Stelle, die das
# festlegt. Jede Seite bindet render_nav() mit ihrer eigenen URL als `active` ein, damit
# ueberall exakt dieselben vier Links in derselben Reihenfolge erscheinen (auch der
# Eigenlink, nur optisch als aktiv markiert -- wie "Home" im echten Pixxelpassion-Header).
NAV_ITEMS = [
    ("Analytics", "/"),
    ("Recherche", "/recherche"),
    ("Content-Erstellung", "/content"),
    ("Einstellungen", "/settings"),
]

NAV_CSS = """
header .nav{display:flex;gap:1.6rem;align-items:center}
header .nav-link{color:var(--pp-ink);font-size:.92rem;text-decoration:none;padding:.2rem 0;border-bottom:2px solid transparent;white-space:nowrap}
header .nav-link:hover{color:var(--pp-green-dark)}
header .nav-link.active{color:var(--pp-green-dark);font-weight:600;border-bottom-color:var(--pp-green)}
"""


def render_nav(active: str) -> str:
    """Gibt die Navigationslinks als HTML zurueck. ``active`` ist die URL der
    aktuellen Seite (z. B. ``/recherche``) -- deren Link wird optisch hervorgehoben,
    bleibt aber (anders als die bisherige Loesung) als Link sichtbar."""
    links = [
        f'<a class="nav-link{" active" if href == active else ""}" href="{href}">{label}</a>'
        for label, href in NAV_ITEMS
    ]
    return '<nav class="nav">' + "".join(links) + "</nav>"


def render_header(active: str, extra_html: str = "") -> str:
    """Kompletter ``<header>``-Block (Topbar + Logo + Nav, OHNE Titel-Text -- der
    hervorgehobene Nav-Link zeigt bereits, wo man ist). ``extra_html`` haengt
    optionalen Seiteninhalt nach der Nav an (z. B. den Sync-Stand auf Analytics).
    Nutzt bereits aufgeloeste Werte (``logo_data_uri()``), ist also per direktem
    Python-Aufruf sowohl in ``render.py``s String-Ersetzung als auch in Flask/Jinja
    einsetzbar -- EIN Aufrufer, EINE Ausgabe, kein Auseinanderlaufen mehr moeglich."""
    return (
        '<div class="topbar"></div>\n'
        "<header>\n"
        f'  <img class="logo" src="{logo_data_uri()}" alt="Pixxelpassion">\n'
        '  <div class="spacer"></div>\n'
        f"  {render_nav(active)}\n"
        f"  {extra_html}\n"
        "</header>"
    )


_LOGO_PATH = Path(__file__).resolve().parent / "assets" / "logo_pixxelpassion.webp"

FAVICON_LINK = (
    '<link rel="icon" href="data:image/x-icon;base64,'
    "AAABAAEAEBAAAAEACABoBQAAFgAAACgAAAAQAAAAIAAAAAEACAAAAAAAAAEAABILAAASCwAAAAEAAAABAADy9vUAJSw4ACs5SgBNwLMAXmRsAFPVyACGqaMAR66kAEmBewBLxrsAH3FkAD2vpAAgMUYATLuxAOvr7QA1n5QARb2yADpBTAAjM0kALUdkACY5UwBEu68AMj1LAHyjnQA/npMAIS9DACk/WgAyTm0AHSc2ABonOQBQz8IAUc7CACWBdQCas7EA3+roADBKZQAYJTUA9vf4AOby8QBJsqcAqL26AB4vQwDz8/QA+fv6ACF5bABAoZYAkZSbAMjU0gAtPFIAUM/DAB8sPQBKxLgAJDZPAK+2vwDr8O8AnrayAF+LhQBLtq0AzM/TAElbcABWh34AUtPGABskMwD29vcAV2yCAExRWwC5zssAzdvZAMrT0QCvvMAANlVzADNQbgBvd38ATMe7AE/MvwBSpZoAnba7ACp9cgBQsaYAR4uDAPL5+ADb5ugAk7GsAG9+jwB5h4sAapKOAIWPmwAzjIIAiZKcACyQhQDP0NIAbnyQAB0oNgCjpqoAgMnAADaDegDi5OUATXJtADSQhQA6mI0AQameADpGVAAwQFgAQZ6VAKqyugBveYQA5fDvAMTh3gCZtbAALHJoAFWIgwDe7uwASbGoAFGBeQDHzdIAisnCAC2EeQBOX3oA4unoAOXr6gBQzsIApLm2AEJ7cgA2SF4AUNDDAB8rPQD///8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAfn5+fn5+JV0EEQEBAQEEf35+fn5+DkE+HBwcXBwcEX9+fn42bFQ+fTJ9fX19fRZ/fn53ejhIHRkZGRkZGRkCf34rPAooLiQZEhISEhISAn9+KAosQ2ABHSkMDBI0FDB/AHEgdCJ+WgQWAmUCFBp7fy9tWWJqfn5+Kg4/aRoTO383TQ8PayZvAH5+flgTG1N/BlcLCycHZE5zUH5WR0c1fxdjFRAQEBAQFV5+W0ZAJX8XGDNJCQkJCUkDUXUjcn5/Bi1KfB4eHjF4A0xmaH5+f1IYHwUFBT0fA0tFOn5+fn95X3ANDTkHZ09Cfn5+fn5/RGEICAhuVSF2fn5+fn5+fwABAAAAAQAAAAEAAAABAAAAAQAAAAEAAAABAAAAAQAAAAEAAAABAAAAAQAAAAEAAAABAAAAAQAAAAEAAAABAAA="
    '">'
)


def logo_data_uri() -> str:
    """Base64-Data-URI des Pixxelpassion-Logos (WebP), leer bei Fehler."""
    try:
        data = _LOGO_PATH.read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:image/webp;base64,{b64}"
    except Exception:
        return ""
