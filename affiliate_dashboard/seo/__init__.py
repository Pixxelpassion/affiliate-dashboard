"""SEO-Monitoring (Search Console + GA4 + SE Ranking).

Eigenstaendiges Unterpaket, getrennt von der Affiliate-Pipeline (andere
Granularitaet: Datum x Seite x Keyword statt Monat x Tracking-ID, andere
Auth-Art: OAuth statt CSV-URL). Aktiv nur wenn ``seo.enabled`` in
``config.json`` gesetzt ist.
"""
