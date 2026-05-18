# Analyze Trading Chart

## Objective
Ta emot en eller flera skärmdumpar av handeldiagram, analysera dem med Claude Vision och producera en strukturerad daytradinganalys på svenska med entry-zoner, stop loss, targets och risk/reward för både SHORT och LONG.

## Inputs
- `images` — en eller flera skärmdumpar (JPEG/PNG/WebP), uppladdade via webbformuläret eller som filsökvägar via CLI

## Steps
1. Validera att minst en bild finns och att formatet stöds (JPEG, PNG, WebP)
2. Base64-enkoda varje bild
3. Anropa `tools/analyze_chart.py` med de enkodade bilderna
4. Parsa returnerat JSON — om parsning misslyckas, kasta undantag med felmeddelande
5. Returnera JSON till Flask-routen som skickar det till frontend som HTTP-svar

## Tools Used
- `tools/analyze_chart.py` — skickar bilder till Claude Sonnet 4.6 Vision och returnerar strukturerat JSON

## Expected Output
JSON-objekt med följande fält:
- `market_overview` — marknadsläge, 2–4 meningar
- `short_scenario` — entry_low/high, stop_loss, t1/t2/t3, rr_t1/t2/t3, label, description
- `long_scenario` — entry_low/high, stop_loss, t1/t2, rr_t1/t2, label, description
- `current_price` — senaste synliga pris i diagrammet
- `summary` — sammanfattning, 3–5 meningar

## Edge Cases & Known Issues
- **Markdown-inlindning:** Om Claude returnerar JSON i ```-block hanteras det automatiskt med regex-strip i verktyget
- **Max bildstorlek:** 20 MB per uppladdning, 5 MB rekommenderas för API-hastighet
- **Format:** JPEG, PNG, WebP stöds — övriga format avvisas med svenska felmeddelanden
- **Flera bilder:** Skickas i ett enda API-anrop för sammanhållen kontext; gör INTE separata anrop per bild
- **Tomma priser:** Om t3 inte är urskiljbart i diagrammet returneras null, vilket hanteras i frontend

## CLI-test (utan webbserver)
```bash
python tools/analyze_chart.py path/to/chart.jpg
python tools/analyze_chart.py chart1.jpg chart2.jpg
```
Kräver giltig `ANTHROPIC_API_KEY` i `.env`.
