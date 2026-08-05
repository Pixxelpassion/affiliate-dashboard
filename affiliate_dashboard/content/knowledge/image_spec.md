---
width: 840
height: 600
format: webp
quality: 85
keyvisual_width: 800
keyvisual_height: 400
---

# Bild-Zuschnitt-Vorgaben

Gilt fuer alle Tracking-IDs/Nischen (keine Nischen-spezifische Abweichung bislang).

- **Alle Artikelbilder** (Motiv-/In-Text-Fotos): **840 × 600 Pixel**.
- **Keyvisual** (erstes Bild, direkt unter der Überschrift): **800 × 400 Pixel**.
- Format: **WebP**.
- Zuschnitt NICHT stur auf die Bildmitte -- viele Fotos sind "aus der Hüfte" geschossen,
  das interessante Motiv (Produkt) sitzt oft nicht zentriert. Der Zuschnitt-Mittelpunkt
  wird deshalb je Bild von Gemini als Teil desselben Calls geschaetzt, der auch den
  Artikeltext erzeugt (Bilder werden als Input mitgegeben, Output enthaelt fuer jedes
  Bild einen normierten Motiv-Mittelpunkt). Nur wenn das fehlschlaegt: Fallback auf
  Bildmitte.
