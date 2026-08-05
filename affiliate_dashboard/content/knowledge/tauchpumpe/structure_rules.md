---
title: Artikelstruktur -- Tauchpumpen
tracking_id: tauchpumpe
type: content-knowledge
---

# Artikelstruktur (aus 3 echten Testberichten verifiziert)

Verbindliche Reihenfolge der Abschnitte -- die genaue Überschriften-Formulierung darf
variieren, REIHENFOLGE UND FUNKTION der Abschnitte bleiben aber gleich. Wichtig: diese
Nische unterscheidet sich in mehreren Punkten spürbar von z. B. Tischkreissägen (siehe
Hinweise unten) -- nicht blind die dortige Struktur übernehmen.

1. **H1-Titel:** `Test: [Produktname]`
2. **Kurzintro** (2-4 Sätze): beschreibt oft szenariohaft den Einsatzkontext/die
   Kernfrage statt trocken Testkriterien aufzuzählen (z. B. "Du möchtest eine
   sorgenfreie Lösung für die Bewässerung deines Gartens...?").
3. **Produktlinien-Vergleich (OPTIONAL)** -- nur wenn der Hersteller mehrere
   Kapazitätsvarianten derselben Baureihe anbietet (z. B. Gardena 9000/16000/20000/
   25000): kurze Übersicht mit Kern-Specs je Variante (Einsatzgebiet, Watt, Liter/
   Stunde, Förderhöhe, Druck) VOR den technischen Daten des eigentlichen Testkandidaten.
4. **Technische Daten (OPTIONAL, NICHT in jedem Artikel!)** -- als echte HTML-`<table>`
   (2 Spalten, `<tr><td>Label:</td><td>Wert</td></tr>`, KEINE `<th>`-Kopfzeile) --
   genau wie bei anderen Nischen, ABER anders als z. B. Tischkreissägen NICHT
   verpflichtend: nur setzen, wenn belastbare Herstellerangaben vorliegen. Pflichtfelder
   falls vorhanden: Netzanschluss, Leistung (Watt), Maximale Fördermenge (Liter/Stunde),
   Maximale Förderhöhe, Maximale Eintauchtiefe, Maximale Partikelgröße, Kabellänge,
   Gewicht.
5. **Lieferumfang** -- was liegt bei (Pumpe, Netzkabel/Befestigungsseil, Adapter/
   Schlauchanschlüsse, Anleitung), Verpackungsqualität (Plastik-Anteil wird explizit
   gelobt/kritisiert).
6. **Verarbeitung** -- Materialqualität (häufiger Fokus auf Edelstahl vs. Kunststoff-
   Anteile), Bauform/Durchmesser (wichtig für Einsatz in engen Brunnen/Schächten/IBC-
   Containern), Gewicht/Tragekomfort.
7. **Anschlüsse** -- Gewindegröße/Anschlusssystem, mit expliziter Schlauchdurchmesser-
   Empfehlung (fast immer der Rat zu MINDESTENS 3/4" bzw. 1", da dünnere Schläuche die
   Fördermenge spürbar drosseln -- konkrete Prozentangabe des Leistungsverlusts, wenn
   möglich).
8. **Modellspezifischer Ein-/Ausschalt-Mechanismus** -- Überschrift variiert je
   Modelltyp (z. B. "Schwimmerschalter", "Schwimmerschalter vs. Automatik",
   "Abschaltautomatik"): erklärt WIE das Gerät steuert (mechanischer Schwimmerschalter
   vs. elektronische Drucksteuerung) und was das praktisch bedeutet (Kleinstmengen-
   programm für Tröpfchenbewässerung, Leckageerkennung, Trockenlaufschutz).
9. **Praxistest** -- umfangreichster Abschnitt, meist mehrere Testszenarien
   (Regenfass/Zisterne/Brunnen/Bassin/verschmutztes Wasser) mit konkreten Messwerten
   (Zeit für X Liter, reale l/h vs. Herstellerangabe, Restwasserhöhe, Einschalthöhe des
   Schwimmerschalters). Die Szenarien stehen NICHT als eigene H3-Überschriften, sondern
   als benannte Absätze/Aufzählungen ("Szenario 1: ...") direkt im Fließtext.
10. **Fazit** -- **WICHTIGER NISCHEN-UNTERSCHIED:** die Überschrift selbst lautet
    `Fazit:` (MIT Doppelpunkt als Teil der Überschrift). Der folgende Absatz
    WIEDERHOLT "Fazit:" NICHT am Anfang, sondern beginnt direkt mit der inhaltlichen
    Kernaussage (anders als z. B. Tischkreissägen, wo die Überschrift nur "Fazit" ohne
    Doppelpunkt lautet und der Fließtext selbst mit "Fazit:" beginnt).
11. **Bewertungsbox** -- gleiches Plugin/Mechanismus wie in anderen Nischen ("WP
    Product Review", `[P_REVIEW]`, Klasse `review-wrap-up cwpr_clearfix`) -- wird NICHT
    von der KI in `body_html` erzeugt, sondern separat als strukturierte Werte
    ausgegeben. Gesamt-Score + 5 Einzelkategorien, ABER ANDERE Kategorien als
    Tischkreissägen: **Materialqualität/Verarbeitung, Förderleistung,
    Schmutzpartikelgröße, Ausstattung/Extras, Preis-/Leistung.** Pro-/Kontra-
    Stichpunkte als getrennte Überschriften+Listen im Anschluss.

**In diesen 3 Beispielen NICHT vorhanden** (im Unterschied zu Tischkreissägen): kein
FAQ-Abschnitt, keine "Kundenmeinungen"-Synthese fremder Bewertungen. Falls für ein
Produkt trotzdem sinnvoll (z. B. viele widersprüchliche Rezensionen im Netz), können
diese optionalen Abschnitte nach demselben Muster wie bei Tischkreissägen ergänzt
werden -- sie sind hier aber nicht der Standard, also nicht erzwingen.

**NICHT durch die KI zu erzeugen** (Theme-/Plugin-Furniture, kein Editorial-Content):
"Weitere Angebote, Zubehör und Alternativen..."-Amazon-Widget, "Diese Testberichte
könnten dich auch interessieren"-Liste, "Was musst du beim Tauchpumpe-Kauf
beachten?"-Leadmagnet-Widget (Einkaufsführer-Formular-Werbung), "Über mich"-Autoren-Bio,
"Bleib immer informiert!"-Newsletter-Anmeldung -- alle automatisch vom Theme/Plugin
ergänzte Seitenbausteine, kein Teil von `body_html`.
