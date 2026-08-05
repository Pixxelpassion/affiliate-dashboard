---
title: Artikelstruktur -- Tischkreissägen
tracking_id: tischkreissaegen
type: content-knowledge
---

# Artikelstruktur (aus 3 echten Testberichten verifiziert)

Verbindliche Reihenfolge der Abschnitte -- die genaue Überschriften-Formulierung darf
variieren (nicht stur immer derselbe Wortlaut, das wirkt sonst wie ein Formular), die
REIHENFOLGE UND FUNKTION der Abschnitte bleibt aber gleich:

1. **H1-Titel:** `Test: [Produktname]`
2. **Kurzintro** (2-3 Sätze): nennt explizit, welche Kriterien geprüft werden (z. B.
   "Verarbeitung, Materialqualität, Lieferumfang, Schnittqualität und besondere
   Features") -- das setzt die Erwartung für den Rest des Artikels.
3. **Technische Daten** -- als ECHTE HTML-`<table>` (2 Spalten, `<tr><td>Label:</td>
   <td>Wert</td></tr>`, KEINE `<th>`-Kopfzeile). Überschrift z. B. "Der Aufbau der...",
   "Technische Daten der...". Pflichtfelder, sofern aus Anleitung/Hersteller-Recherche
   verfügbar: Hersteller, Leistung (Watt), Leerlaufzahl (U/min), Schnitthöhe,
   Schrägstellung/Sägeblattneigung, Sägeblattdurchmesser, Sägetischgröße, Gewicht.
   Werte dürfen inline-Links auf verwandte Ratgeber/Zubehör enthalten (z. B.
   "Sägeblattdurchmesser: 250mm (gleich passende Sägeblätter dazubestellen)").
4. **Montage/Lieferumfang** -- Praxisbericht zum Auspacken/Aufbau, konkrete Zeitangabe
   wenn möglich ("in 15 Minuten aufgebaut"), was liegt bei (Anschläge, Sägeblatt,
   Schiebestock, Absaugadapter etc.), ob eine Anleitung beiliegt und wie gut sie ist.
5. **Praxistest** -- der umfangreichste, flexibelste Teil. Je nach Produkt/Preisklasse
   in mehrere thematische Unterabschnitte gegliedert (z. B. Verarbeitung, Arbeitsfläche/
   Tischerweiterung, Anschläge, Sägewinkel, Motor, Staubabführung, Sägeblattwechsel).
   NICHT jeden dieser Unterpunkte erzwingen -- ein einfaches Einsteigergerät bekommt
   einen kürzeren, generischeren Praxistest-Abschnitt, ein Premium-Gerät mehr Tiefe.
   Konkrete Messwerte/Beobachtungen nennen, nicht nur Marketing-Sprache.
6. **Kundenmeinungen** (optional, nicht in jedem Artikel vorhanden) -- Synthese
   FREMDER Bewertungen (nicht der eigene Test!): grobe Prozentangabe Zustimmung,
   dann "Positiv genannt wurde häufig:" / "Konstruktive Kritik äußerten einige bei:"
   als zwei getrennte Aufzählungen.
7. **Häufige Fragen** (optional, nicht in jedem Artikel vorhanden) -- klassisches
   FAQ-Format, kurze konkrete Frage als Zwischenüberschrift, 2-4 Sätze Antwort.
8. **Fazit** -- kurzer Fließtext-Absatz (4-6 Sätze), beginnt mit "Fazit:", fasst
   stärkste Stärke + wichtigste Schwäche zusammen, endet mit einer klaren
   Kauf-Einschätzung.
9. **Bewertungsbox** (Scores + Pro/Kontra) -- wird NICHT als Teil des Fließtexts von
   der KI generiert, sondern separat als strukturierte Werte ausgegeben (Plugin
   "WP Product Review", Shortcode `[P_REVIEW]`, eigene Post-Meta-Felder -- nicht ohne
   Weiteres per REST-API schreibbar). Gemini liefert trotzdem Vorschläge für:
   Gesamt-Score, Einzel-Scores (Montage, Schnittqualität, Arbeitskomfort, Zubehör,
   Preis-/Leistung, je 0-10), sowie Pro-/Kontra-Stichpunkte -- diese werden im
   Review-UI angezeigt, der Nutzer trägt sie manuell ins Review-Widget ein.

**NICHT durch die KI zu erzeugen** (Theme-/Plugin-Furniture, kein Editorial-Content):
"Weitere Angebote..."-Produktwidget (Affiliate-Amazon-Shortcode-Plugin) und "Diese
Testberichte könnten dich auch interessieren"-Verwandte-Artikel-Liste -- beides wird
automatisch vom Theme/Plugin ergänzt, nicht Teil von `body_html`.
