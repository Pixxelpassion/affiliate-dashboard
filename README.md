# Affiliate-Einnahmen-Dashboard (Amazon PartnerNet)

Liest deine Amazon-PartnerNet-Affiliate-Einnahmen ein und erzeugt eine einzelne,
durchsuchbare **`dashboard.html`** — aufgeschlüsselt nach **Monat × Tracking-ID**
(Pivot-Tabelle, Trend-Diagramm; optional ein drittes **SEO-Monitoring**-Tab, siehe unten).
Läuft entweder rein **lokal** (Doppelklick, kein Server, Zugangsdaten in `config.json`)
oder als **Live-Webapp** (`server.py`, Zugangsdaten DB-gestützt über eine `/settings`-
Weboberfläche, siehe „Deployment auf Hostinger" unten) — beide Wege nutzen dieselbe
Ingest-/Render-Pipeline.

> **Kein Produkt-/ASIN-Level mehr:** Amazon liefert im PartnerNet-Export inzwischen nur noch
> Monats-/Tag-Aggregate je Tracking-ID, keine Einzelprodukt-Exports mehr. Das Dashboard bildet
> deshalb ausschließlich die Granularität **Monat × Tracking-ID** ab.

**Design:** Im Corporate Design von **Pixxelpassion** (Logo, Markenfarben Limette/Oliv
`#b7cb3a`/`#717e21`, Schriften Poppins/Montserrat). Das Logo ist als Data-URI eingebettet
(`affiliate_dashboard/assets/logo_pixxelpassion.webp`), die Google-Fonts werden online
geladen mit System-Fallback (offline funktioniert alles bis auf die exakte Schriftart).

**Globaler Tracking-ID-Filter:** Ganz oben (über den Kennzahl-Karten) steht die
**Tracking-ID**-Auswahl. Sie steuert **alles darunter** auf einmal:
- **Kennzahl-Karten** (bei Einzelauswahl: gefilterte Einnahmen/Umsatz, die ID und ihr
  prozentualer Anteil an den Gesamteinnahmen),
- **Pivot-Tabelle** (nur die gewählte ID bzw. „Gesamt"-Spalte oder alle IDs),
- **Trend-Diagramm** (auf die gewählte ID gefiltert).
Optionen: „Alle Tracking-IDs", „Gesamt (Summe aller IDs)" oder eine einzelne ID.

**Trend-Diagramm:** Liniendiagramm des Verlaufs über den gesamten Zeitraum, gesteuert vom
globalen Filter und der **Kennzahl** (Einnahmen / Umsatz / Gelieferte Artikel / Klicks).
Bei einer einzelnen ID wird nur deren Verlauf mit Flächenfüllung samt Gesamt- und
Bestmonat-Angabe gezeigt; bei „Alle" die Top 12 als Mehrlinien-Chart mit klickbarer Legende.
Die X-Achse zeigt einheitliche Jahres-Ticks (erster verfügbarer Monat je Kalenderjahr),
Hover über einen Datenpunkt zeigt den exakten Wert.

## Datenquellen (austauschbar)

Für Affiliate-**Einnahmen** gibt es keine offene öffentliche API (die PA-API 5.0 /
Creators API liefern nur Produktdaten). Dieses Tool unterstützt deshalb drei Quellen
hinter einem gemeinsamen Adapter — umschaltbar über `source` in `config.json`:

| `source` | Beschreibung | Status |
|---|---|---|
| `gsheet` | Liest ein veröffentlichtes **Google Sheet** (CSV-Export-URL). **Dauerhafte Quelle.** | aktiv |
| `csv`    | Liest PartnerNet-Exporte (`.csv`/`.txt`/`.xlsx`) aus `data/inbox/`. | aktiv |
| `s3`     | Amazons **S3 Data Feed / Activity Report**. | von Amazon abgelehnt, Code bleibt als Stub |

Das Sheet enthält aktuell das Tabellenblatt **„AmazonDatenMonatlich"** (`gid=767104803`):
Monat/Jahr, Tracking-ID, Klicks, bestellte/versendete Artikel, Rückgaben, Umsatz (bestellt/
versendet), Einnahmen — **kein Produkt-/ASIN-Level** mehr (siehe Hinweis oben).

> **Wichtig:** Die Werte sind **Schätzungen laut Bericht** (verdiente Werbekosten­erstattung
> inkl. Prämien). Die offizielle Monatsabrechnung kann durch Retouren, Stornos, Steuern und
> Anpassungen abweichen. Negative Werte = Retouren (werden korrekt verrechnet).

## Schnellstart (Google Sheet)

1. **Sheet freigeben:** In Google Sheets → *Freigeben* → „Jeder mit dem Link" auf
   **Betrachter**, oder *Datei → Freigeben → Im Web veröffentlichen*.
2. **`config.json` prüfen** (aus `config.example.json` kopieren, falls nicht vorhanden):
   - `source: "gsheet"`
   - `gsheet.sheet_id` = die ID aus der Sheet-URL
     (`docs.google.com/spreadsheets/d/`**`<ID>`**`/edit`)
   - `gsheet.gid` = die Tab-ID (`…#gid=`**`<gid>`**)
3. **Lauf starten:** `Aktualisieren.bat` doppelklicken (oder per CLI, siehe unten).
   Danach öffnet sich `dashboard.html` im Browser.

Der Kernpfad (Google Sheet → Dashboard) nutzt nur die **Python-Standardbibliothek** —
es ist **keine Installation** nötig (Python 3.10+ vorausgesetzt).

## Nutzung (CLI)

```powershell
python -m affiliate_dashboard.run                  # Quelle aus config.json
python -m affiliate_dashboard.run --source gsheet
python -m affiliate_dashboard.run --source csv --inbox data/inbox
python -m affiliate_dashboard.run --no-open        # ohne Browser (z. B. fuer Tasks)
```

## CSV-Variante (PartnerNet-Export)

Falls du statt des Sheets direkt PartnerNet-Berichte nutzen willst:
PartnerNet → *Berichte* → gewünschten Bericht (Tracking-ID-Zusammenfassung / Einnahmen)
→ Zeitraum wählen → herunterladen (`.csv`/`.txt`/`.xlsx`) → Datei in `data/inbox/` legen →
`Aktualisieren.bat --source csv`. Verarbeitete Dateien wandern nach `data/archive/<datum>/`.
Spaltennamen werden automatisch erkannt (Deutsch/Englisch, Tab- oder Komma-getrennt).

## Wöchentliche Aktualisierung

```powershell
powershell -ExecutionPolicy Bypass -File .\Register-WeeklyTask.ps1
# anpassbar:
.\Register-WeeklyTask.ps1 -Day Friday -Time "16:30"
```

Registriert einen Windows-Task (Standard: montags 07:00). Bei `gsheet` aktualisiert er
sich vollautomatisch; bei `csv` nur, wenn frische Exporte in `data/inbox/` liegen.

## SEO-Monitoring einrichten (optional)

Ein zusätzlicher **„SEO-Monitoring"**-Tab zeigt, wie sich Impressionen, Klicks, CTR,
Rankingposition (Google Search Console + SE Ranking), Seitenviews und Ø Engagement-Zeit
(GA4) für einzelne Unterseiten entwickeln — z. B. um den Effekt einer SEO-Optimierung ab
dem Livegang-Zeitpunkt zu verfolgen. Standardmäßig deaktiviert (`seo.enabled: false`, der
Tab bleibt dann unsichtbar), da drei zusätzliche Zugänge nötig sind. Läuft im selben
wöchentlichen Lauf mit wie die Affiliate-Daten.

**Voraussetzungen:**

1. **Google Cloud Projekt** anlegen: [console.cloud.google.com](https://console.cloud.google.com) →
   neues Projekt → *APIs & Dienste → Bibliothek* → **Search Console API** und
   **Google Analytics Data API** aktivieren.
2. **OAuth-Client:** *APIs & Dienste → Anmeldedaten → Anmeldedaten erstellen → OAuth-Client-ID*,
   Anwendungstyp **„Desktop-App"**. JSON-Datei herunterladen, im Projektordner als
   `seo_client_secret.json` ablegen (Pfad über `config.json` → `seo.google.client_secret_path`
   anpassbar; die Datei ist gitignored).
3. **GSC-Property:** die in der Search Console verifizierte Property-URL deiner Seite
   (z. B. `https://example.de/`) → `config.json` → `seo.gsc.property`.
4. **GA4-Property-ID:** in Google Analytics unter *Verwaltung → Property-Details* zu finden
   (Format `properties/123456789`) → `config.json` → `seo.ga4.property_id`.
5. **SE-Ranking-Projekt:** API-Key (API Dashboard → *Data API key*) sowie die Projekt-/Site-ID
   deiner Seite → `config.json` → `seo.seranking.api_key` / `seo.seranking.project_id`.
6. **Watchlist:** die Unterseiten + Keywords, die du beobachten willst, in
   `config.json` → `seo.pages` eintragen:
   ```json
   "pages": [
     { "url": "/ratgeber/beispiel-seite/", "keywords": ["beispiel keyword"] }
   ]
   ```
   `url` ist der Pfad relativ zur Property (wird für GSC intern mit der Property-URL
   kombiniert, für GA4 als `pagePath`-Filter genutzt).

**Einmaliger Login** (danach `seo.enabled: true` setzen):

```powershell
python -m affiliate_dashboard.seo.google_auth
```

Öffnet den Browser für den Google-Consent-Flow und speichert den Token unter
`data/google_token.json` (gitignored). Ab dann läuft `Aktualisieren.bat` normal weiter —
der Token erneuert sich automatisch, solange der Refresh-Token gültig bleibt.

**Bedienung:** Seiten-Auswahl + Metrik-Checkboxen (je Keyword: Impressionen, Klicks, CTR,
Position GSC, Position SE Ranking; je Seite: Seitenviews, Ø Engagement-Zeit). Der Chart
normalisiert alle gewählten Metriken auf einen Index (= 100 am Referenzdatum), damit trotz
unterschiedlicher Skalen ein direkter Vergleich möglich ist — bei Rankingposition gilt
„niedriger = besser". Über das Eingabefeld lassen sich „Livegang"-Ereignisse (Datum +
Kurzbeschreibung) als senkrechte Marker im Chart hinterlegen.

> **Events-Speicherung hängt vom Betriebsmodus ab:** Im **Server-Betrieb** (`server.py`,
> siehe „Deployment auf Hostinger" unten) werden Events dauerhaft in `settings.db`
> gespeichert (`/api/seo/events`) — überleben Rechner-/Browserwechsel automatisch. Im
> rein **lokalen** Betrieb ohne Server gibt es diese API nicht; das Eingabefeld im
> SEO-Tab setzt dann eine laufende Instanz von `server.py` voraus (z. B. lokal per
> `python -m affiliate_dashboard.server` gestartet).

**Fehlerresilienz:** Schlägt eine der drei Quellen fehl (z. B. abgelaufener Google-Token,
leere SE-Ranking-Credits), werden die anderen beiden trotzdem aktualisiert — der Lauf
protokolliert den Fehler, bricht aber nicht ab.

## Deployment auf Hostinger (Live-Webapp)

Analog zum bestehenden `parqet-dashboard` (https://portfolio.pixxelpassion.de) lässt sich
das Affiliate-Dashboard als **Live-Webapp** auf demselben Hostinger-VPS betreiben —
mit einer `/settings`-Weboberfläche statt einer lokal editierten `config.json`, und
einem `/api/sync`-Endpunkt statt `Aktualisieren.bat`.

**Was fertig gebaut ist:** `server.py` (Flask-App), `settings_store.py` (DB-gestützte
Einstellungen in `data/settings.db`), `migrate_config_to_db.py` (Einmal-Migration einer
bestehenden lokalen `config.json`). **Was du selbst am Server/GitHub erledigen musst**
(kein SSH-/GitHub-Zugriff durch das Tool, das dieses Projekt gebaut hat), Schritt für Schritt:

1. **Eigenes inneres Git-Repo anlegen** — analog zu `parqet-dashboard/`, das explizit ein
   **eigenes** Repo mit eigenem GitHub-Remote ist (Branch `main`). **Nicht** über das äußere
   „Projekt 1"-Repo deployen — das kommt am Server nachweislich nie an (siehe
   `parqet-dashboard`-Erfahrung). Neues GitHub-Repo anlegen (z. B.
   `github.com/pixxelpassion/affiliate-dashboard`), diesen Ordner hineinpushen.
2. **Subdomain wählen** (z. B. `affiliate.pixxelpassion.de`) und per DNS-A-Record auf
   dieselbe VPS-IP wie `portfolio.pixxelpassion.de` zeigen lassen.
3. **Auf dem Server** (Hostinger hPanel → VPS → Terminal, kein SSH nötig): einen neuen
   Ordner anlegen (z. B. `/opt/affiliate-dashboard`), Repo dort klonen. `Dockerfile` und
   `docker-compose.yml` direkt auf dem Server per `cat >` erstellen (liegen bewusst nicht
   im Repo, genau wie bei `parqet-dashboard`):
   - `Dockerfile`: Python-Basis-Image, `pip install -r requirements.txt`, Start via
     `gunicorn -w 4 -b 0.0.0.0:8000 affiliate_dashboard.server:app`.
   - `docker-compose.yml`: Container ins bestehende Traefik-Netz (`n8n_default`) hängen,
     Traefik-Labels für die neue Subdomain + HTTPS (siehe Hinweis zum ungültigen
     SSL-Zertifikat bei `parqet-dashboard` — dort fehlt ein `letsencrypt`-Certresolver;
     das hier gleich mitkonfigurieren, wenn möglich). `data/`-Ordner als Volume mounten
     (enthält `settings.db`, `affiliate.db`, `seo.db`, `google_token.json`).
   - Env-Vars in `docker-compose.yml`: `DASHBOARD_USER`, `DASHBOARD_PASSWORD_HASH`.
4. **Cron-Jobs** (Host-Crontab, analog zu den bewährten `parqet-dashboard`-Einträgen):
   - `*/5 * * * *` → eigenes `deploy.sh` (git pull, Container-Rebuild nur bei neuem Commit
     — **nicht** bei jedem Cron-Tick neu bauen, das killt laufende Syncs, siehe
     `parqet-dashboard`-Lektion).
   - täglicher Sync-Trigger, z. B. `0 7 * * *`:
     ```bash
     curl -u "$DASHBOARD_USER:$DASHBOARD_PASSWORD" -X POST http://127.0.0.1:8000/api/sync
     ```
5. **Google-OAuth-Token übertragen** (nur falls SEO-Monitoring genutzt wird): einmalig
   **lokal** `python -m affiliate_dashboard.seo.google_auth` ausführen (Google erlaubt nur
   `localhost` als OAuth-Redirect, bleibt daher lokal), danach die entstandene
   `data/google_token.json` einmalig auf den Server nach `/opt/affiliate-dashboard/data/`
   kopieren (Hostinger-Terminal-Heredoc).
6. **Passwort-Hash erzeugen** (lokal, nie das Klartext-Passwort ablegen):
   ```powershell
   python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('DEIN_PASSWORT'))"
   ```
   Den Hash als `DASHBOARD_PASSWORD_HASH` in `docker-compose.yml` eintragen.
7. **Erstbefüllung:** entweder `python -m affiliate_dashboard.migrate_config_to_db` lokal
   gegen deine bestehende `config.json` laufen lassen und `data/settings.db` mit
   hochladen, oder nach dem ersten Deploy `https://<subdomain>/settings` öffnen und
   Sheet-ID/gid, SE-Ranking-Key/Projekt-ID, GSC-Property, GA4-Property-ID sowie die
   Watchlist-Seiten dort eintragen.

**Lokal testen, bevor du deployst:**

```powershell
$env:DASHBOARD_USER = "admin"
$env:DASHBOARD_PASSWORD_HASH = "<hash aus Schritt 6>"
python -m affiliate_dashboard.server
```

Öffnet auf `http://127.0.0.1:5050` — `/settings` zum Eintragen der Zugangsdaten,
`/api/sync` (POST) zum Auslösen eines Durchlaufs, `/` zeigt das zuletzt generierte
Dashboard. Ohne gesetzte Env-Vars läuft der Server **ungeschützt** (nur für lokale
Entwicklung gedacht, niemals so deployen).

## Optionale Pakete

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

- `openpyxl` — nur für `.xlsx`-Import im CSV-Adapter.
- `boto3` — nur für den späteren S3-Adapter.
- `google-auth`, `google-auth-oauthlib`, `google-api-python-client`, `google-analytics-data`
  — nur für das SEO-Monitoring (`seo.enabled: true`).

## Später

Der `s3_adapter.py`-Stub bleibt im Code, wird aber nicht mehr aktiviert — Amazon hat den
Antrag auf den Activity-Report-Feed abgelehnt. Webserver-Betrieb siehe „Deployment auf
Hostinger" oben.

## Dateien

| Pfad | Zweck |
|---|---|
| `affiliate_dashboard/run.py` | Orchestrierung + CLI |
| `affiliate_dashboard/columns.py` | Schema-tolerante Spaltenerkennung + Parser (Kern) |
| `affiliate_dashboard/aggregate.py` | Aggregation Monat × Tracking-ID |
| `affiliate_dashboard/store.py` | SQLite-Persistenz + Dedupe |
| `affiliate_dashboard/render.py` | erzeugt `dashboard.html` |
| `affiliate_dashboard/adapters/` | `gsheet` / `csv` / `s3` (+ `base.py`) |
| `affiliate_dashboard/seo/` | SEO-Monitoring: `google_auth.py`, `gsc_client.py`, `ga4_client.py`, `seranking_client.py`, `seo_store.py`, `seo_run.py` |
| `affiliate_dashboard/server.py` | Flask-App fuer den Live-Betrieb (`/`, `/api/sync`, `/settings`, `/api/seo/events`) |
| `affiliate_dashboard/settings_store.py` | DB-gestützte Einstellungen (`data/settings.db`) statt `config.json` im Server-Betrieb |
| `affiliate_dashboard/migrate_config_to_db.py` | Einmal-Migration `config.json` → `settings.db` |
| `Aktualisieren.bat` | Lauf per Doppelklick (lokaler Betrieb) |
| `Register-WeeklyTask.ps1` | Windows-Aufgabenplanung (lokaler Betrieb) |
| `data/` | Rohdaten-Snapshots, SQLite-DBs (`affiliate.db`/`seo.db`/`settings.db`), Google-Token (gitignored) |

## Bekannte Grenzen (Stand Juli 2026)

- **Keine offizielle Einnahmen-API:** PA-API 5.0 (abgeschaltet 15.05.2026) bzw. Creators API
  liefern nur Produktdaten. Einnahmen nur per S3-Feed oder Bericht/CSV.
- **Kein Produkt-/ASIN-Level:** Amazons Exporte liefern nur noch Monats-/Tag-Aggregate je
  Tracking-ID, keine Einzelprodukt-Daten mehr.
- **Schätzwerte:** siehe Hinweis oben — nicht mit der finalen Monatsabrechnung identisch.
- **Manuelle Pflege:** Sheet bzw. CSV müssen aktuell gehalten werden.
- **S3-Zugang abgelehnt:** Amazon hat den Antrag auf den Activity-Report-Feed abgelehnt;
  das Google Sheet ist die dauerhafte Quelle.
- **Kein Scraping:** Nur offizielle Wege (veröffentlichtes Sheet, Bericht-Export).
- **SEO-Monitoring, GA4 „Ø Engagement-Zeit":** GA4 kennt keine 1:1-Entsprechung zur alten
  "Time on Page" mehr; die Kennzahl ist eine Näherung (`userEngagementDuration /
  screenPageViews`), keine exakte Verweildauer je Seitenaufruf.
- **SEO-Monitoring, SE-Ranking-Endpunkte:** `seranking_client.py` ist gegen die öffentliche
  API-Dokumentation gebaut, aber noch **nicht gegen einen echten API-Key end-to-end
  getestet** (kein Zugriff auf ein reales SE-Ranking-Projekt beim Bauen). Beim ersten Lauf
  mit echten Zugangsdaten die Response genau prüfen (siehe Verifikationsschritte im Plan).
- **Deployment auf Hostinger nicht selbst durchgeführt:** `server.py`/`settings_store.py`
  sind lokal vollständig getestet (Basic Auth, `/api/sync`, `/settings`,
  `/api/seo/events`), aber der eigentliche Server-Teil (Docker/Traefik-Konfiguration,
  Cron, DNS/Subdomain) wurde mangels SSH-/Hostinger-Zugriff **nicht** durchgeführt/
  verifiziert — die Anleitung oben ist 1:1 aus dem bewährten `parqet-dashboard`-Vorgehen
  abgeleitet, aber der erste echte Deploy sollte entsprechend sorgfältig geprüft werden
  (inkl. des dort bekannten SSL-Zertifikatsproblems, siehe Hinweis im Deployment-Abschnitt).
