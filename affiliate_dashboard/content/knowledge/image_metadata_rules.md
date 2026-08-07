---
title: Bild-Metadaten-Regelwerk (Titel, Alt-Text, Beschriftung, Beschreibung)
type: content-knowledge
---

# Bild-Metadaten -- vier Felder, vier unterschiedliche Zwecke

WordPress speichert bei jedem Medium vier getrennte Textfelder mit unterschiedlicher
Sichtbarkeit und unterschiedlichem SEO-Wert. NIEMALS denselben Text in alle vier Felder
kopieren (das ist der bisherige, manuelle Fehler, der behoben werden soll).

1. **Titel** -- rein intern (Mediathek-Verwaltung/-Suche), auf der Seite i. d. R.
   NICHT sichtbar, kein direkter SEO-Faktor. Trotzdem konsistent und sprechend halten
   (nie "IMG_1234"). Muster: `<Produktname> - <kurzes Motiv>` (z. B.
   "Bosch GTS 10 XC Tischkreissäge - Blattabdeckung").

2. **Alternativtext (alt_text)** -- das wichtigste SEO-/Barrierefreiheits-Feld. Wird
   von Screenreadern vorgelesen UND von der Google-Bildersuche ausgewertet. Muss eine
   WORTWÖRTLICHE, sachliche Beschreibung dessen sein, was auf dem Bild zu sehen ist --
   kein Marketing-Ton, keine Meinung, kein Keyword-Stuffing. Darf den Produktnamen
   enthalten, wenn es natürlich passt, aber NICHT bei jedem Bild identisch wiederholen.
   Faustregel: 8-15 Wörter, ein vollständiger, objektiver Satz.

3. **Beschriftung (caption)** -- wird im Artikel SICHTBAR unter dem Bild angezeigt
   (anders als Titel/Beschreibung). Darf redaktionell geschrieben sein, im Ton-of-Voice
   der jeweiligen Nische (siehe deren `tone_of_voice.md`) -- erklärt dem Leser, WARUM
   dieses Detail im Test relevant ist. Hier gehört ein einordnender, meinungshaltiger
   Satz hin (z. B. "Ordnungssinn: Die Blattabdeckung kann bei Nichtgebrauch -- wie alles
   andere -- in einer Ablage verstaut werden."), NICHT in den Alternativtext.

4. **Beschreibung (description)** -- am seltensten sichtbar (nur vereinzelt in
   Themes/Anhang-Seiten), niedrigste Priorität. Darf inhaltlich der Beschriftung
   entsprechen oder sie geringfügig ausführlicher wiederholen -- kein separater
   Kreativaufwand nötig.

**Kernregel:** Alternativtext beschreibt das Bild für jemanden, der es nicht sehen
kann (objektiv, bildinhaltlich, wie eine Bildunterschrift in einer Enzyklopädie).
Beschriftung spricht den lesenden Menschen an, der das Bild bereits sieht (subjektiv,
einordnend, im Ton-of-Voice der Nische). Beide Felder dürfen sich thematisch
überschneiden, sollten aber NIE wortgleich sein.
