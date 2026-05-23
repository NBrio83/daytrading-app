import os
import json
import re
import base64
import sys
import anthropic
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """Du är en expert på teknisk analys och daytrading.
Du analyserar diagram och identifierar handelsmöjligheter på svenska.
Du svarar ALLTID med ett JSON-objekt och INGET annat — inga förklaringar utanför JSON-blocket."""

ANALYSIS_PROMPT = """Analysera detta handeldiagram noggrant och returnera ett JSON-objekt med exakt denna struktur:

{
  "chart_title": "string — kortfattad beskrivande titel, t.ex. 'Gold CFD Analys' eller 'NAS100 Futures Analys'",
  "instrument_info": "string — tidsramar och instrument, t.ex. '15-min · 3-min · TVC · CFDs on Gold (US$/OZ)'",
  "market_overview": "string — marknadsläge på svenska, 2-4 meningar",
  "short_scenario": {
    "label": "string — t.ex. 'SHORT (sälja) — favoriserat scenario'",
    "description": "string — motivering på svenska, 1-2 meningar",
    "entry_low": number,
    "entry_high": number,
    "stop_loss": number,
    "t1": number,
    "t2": number,
    "t3": number,
    "rr_t1": "string — t.ex. '1.5:1'",
    "rr_t2": "string — t.ex. '2.5:1'",
    "rr_t3": "string — t.ex. '3:1'"
  },
  "long_scenario": {
    "label": "string — t.ex. 'LONG (köpa) — kontra-trend, högrisk'",
    "description": "string — motivering på svenska, 1-2 meningar",
    "entry_low": number,
    "entry_high": number,
    "stop_loss": number,
    "t1": number,
    "t2": number,
    "t3": number,
    "rr_t1": "string — t.ex. '1.5:1'",
    "rr_t2": "string — t.ex. '2.5:1'",
    "rr_t3": "string — t.ex. '3:1'"
  },
  "current_price": number,
  "summary": "string — sammanfattning på svenska, 3-5 meningar"
}

Regler:
- Alla priser ska vara exakta numeriska värden utan enheter
- All text ska vara på svenska
- current_price är det senaste synliga priset i diagrammet
- t3 och rr_t3 kan vara null i både short och long om bara två targets är tydliga
- Beräkna R:R korrekt: för SHORT är risk = stop_loss - entry_mid, reward = entry_mid - target
- Om flera diagram visas, integrera alla tidsperspektiv i din analys
- chart_title och instrument_info ska extraheras från vad som syns i diagrammet
- Returnera ENDAST det rå JSON-objektet, inga markdown-kodblock, inga extra ord"""

# ── Guld-specifik prompt ─────────────────────────────────────────────────────

GOLD_SYSTEM_PROMPT = """Du är en expert på teknisk analys och daytrading, specialiserad på guldterminhandel (XAUUSD, Gold CFD, GC Futures).
Du analyserar diagram och identifierar handelsmöjligheter på svenska.
Du ANALYSERAR ALLTID trenden på 1h och 15-min FÖRST — det är obligatoriskt innan du ger några rekommendationer.
Du går ALDRIG emot den dominerande trenden utan tydliga hårda reversal-villkor (stark divergens + nyckelzonsbrott + volymbekräftelse).
Om bilder på USD-styrka (DXY/TVC:DXY) eller real ränta (FRED:DFII10) är uppladdade, analyserar du dem och väger in makrobilden i guldanalysen.
Du svarar ALLTID med ett JSON-objekt och INGET annat — inga förklaringar utanför JSON-blocket."""

GOLD_ANALYSIS_PROMPT = """Analysera dessa bilder för guldhandel. Om DXY- eller DFII10-chart är inkluderat bland bilderna, identifiera det och väg in makrobilden. Börja obligatoriskt med trendanalys på 1h och 15-min. Returnera ett JSON-objekt med exakt denna struktur:

{
  "chart_title": "string — t.ex. 'Gold CFD Analys' eller 'XAUUSD Futures Analys'",
  "instrument_info": "string — tidsramar och instrument, t.ex. '15-min · 1h · XAUUSD · Gold Futures'",
  "market_overview": "string — BÖRJA med: '1h-trend: [Bullish/Bearish/Neutral]. 15-min-trend: [Bullish/Bearish/Neutral].' Om DXY är synlig: 'DXY: [stigande/fallande/neutral] — [hur det påverkar guld].' Om DFII10 är synlig: 'Realränta: [stigande/fallande/neutral] — [hur det påverkar guld].' Fortsätt med marknadsläge och nyckelnivåer. Totalt 4-6 meningar.",
  "confidence": "string — konfidensgrad för det primära scenariot, t.ex. 'Hög (80%)' eller 'Medel (55%)'",
  "invalidation": "string — vad som ogiltigförklarar analysen på svenska, 1-2 meningar. T.ex. 'Analysen ogiltigförklaras om priset stänger över X på 15-min, eller om DXY bryter under Y.'",
  "short_scenario": {
    "label": "string — t.ex. 'SHORT (sälja) — favoriserat scenario' eller 'SHORT (sälja) — kontra-trend, högrisk'",
    "description": "string — motivering inkl. om scenariot följer eller går mot dominerande trend samt makrostöd, 1-2 meningar",
    "entry_low": number,
    "entry_high": number,
    "stop_loss": number,
    "t1": number,
    "t2": number,
    "t3": number,
    "rr_t1": "string",
    "rr_t2": "string",
    "rr_t3": "string"
  },
  "long_scenario": {
    "label": "string — t.ex. 'LONG (köpa) — favoriserat scenario' eller 'LONG (köpa) — kontra-trend, högrisk'",
    "description": "string — motivering inkl. om scenariot följer eller går mot dominerande trend samt makrostöd, 1-2 meningar",
    "entry_low": number,
    "entry_high": number,
    "stop_loss": number,
    "t1": number,
    "t2": number,
    "t3": number,
    "rr_t1": "string",
    "rr_t2": "string",
    "rr_t3": "string"
  },
  "current_price": number,
  "summary": "string — sammanfattning 3-5 meningar. Ange vilket scenario som är primärt baserat på dominerande trend. Om DXY eller DFII10 är synliga, nämn hur de stödjer eller motverkar scenariot."
}

Regler:
- OBLIGATORISKT: bedöm 1h-trenden och 15-min-trenden innan du väljer primärt scenario
- Om 1h är bullish → LONG är primärt, SHORT är kontra-trend och märks som högrisk
- Om 1h är bearish → SHORT är primärt, LONG är kontra-trend och märks som högrisk
- Gå INTE emot dominerande trend utan stark divergens + nyckelzonsbrott + volymbekräftelse
- DXY: stigande dollar är generellt negativt för guld (bearish signal), fallande dollar är positivt (bullish signal)
- DFII10 (real ränta): stigande realränta är negativt för guld, fallande realränta är positivt för guld
- Väg in RSI (14), Volym, EMA 9/20/50/200 om synliga
- Alla priser ska vara exakta numeriska värden utan enheter
- All text ska vara på svenska
- current_price är det senaste synliga priset i guldchartet
- t3 och rr_t3 kan vara null i både short och long om bara två targets är tydliga
- Beräkna R:R korrekt: SHORT: risk = stop_loss − entry_mid, reward = entry_mid − target; LONG: risk = entry_mid − stop_loss, reward = target − entry_mid
- Returnera ENDAST det rå JSON-objektet, inga markdown-kodblock, inga extra ord"""

# ── Nasdaq-specifik prompt ────────────────────────────────────────────────────

NASDAQ_SYSTEM_PROMPT = """Du är en expert på teknisk analys och daytrading, specialiserad på Nasdaq/NAS100-index.
Du analyserar diagram och identifierar handelsmöjligheter på svenska.
Du ANALYSERAR ALLTID trenden på 1h och 15-min FÖRST — det är obligatoriskt innan du ger några rekommendationer.
Du går ALDRIG emot den dominerande trenden utan tydliga hårda reversal-villkor (stark divergens + nyckelzonsbrott + volymbekräftelse).
Du svarar ALLTID med ett JSON-objekt och INGET annat — inga förklaringar utanför JSON-blocket."""

NASDAQ_ANALYSIS_PROMPT = """Analysera detta Nasdaq-diagram. Börja obligatoriskt med trendanalys på 1h och 15-min. Returnera ett JSON-objekt med exakt denna struktur:

{
  "chart_title": "string — t.ex. 'NAS100 Cash CFD Analys'",
  "instrument_info": "string — tidsramar och instrument, t.ex. '15-min · 1h · NAS100 Cash CFD'",
  "market_overview": "string — BÖRJA med: '1h-trend: [Bullish/Bearish/Neutral]. 15-min-trend: [Bullish/Bearish/Neutral].' Fortsätt sedan med marknadsläge, nyckelnivåer och vad som driver rörelsen. Totalt 3-5 meningar.",
  "confidence": "string — konfidensgrad för det primära scenariot, t.ex. 'Hög (80%)' eller 'Medel (55%)'",
  "invalidation": "string — vad som ogiltigförklarar analysen på svenska, 1-2 meningar. T.ex. 'Analysen ogiltigförklaras om priset stänger över X på 15-min med volymbekräftelse.'",
  "short_scenario": {
    "label": "string — t.ex. 'SHORT (sälja) — favoriserat scenario' eller 'SHORT (sälja) — kontra-trend, högrisk'",
    "description": "string — motivering inkl. om scenariot följer eller går mot dominerande trend, 1-2 meningar",
    "entry_low": number,
    "entry_high": number,
    "stop_loss": number,
    "t1": number,
    "t2": number,
    "t3": number,
    "rr_t1": "string",
    "rr_t2": "string",
    "rr_t3": "string"
  },
  "long_scenario": {
    "label": "string — t.ex. 'LONG (köpa) — favoriserat scenario' eller 'LONG (köpa) — kontra-trend, högrisk'",
    "description": "string — motivering inkl. om scenariot följer eller går mot dominerande trend, 1-2 meningar",
    "entry_low": number,
    "entry_high": number,
    "stop_loss": number,
    "t1": number,
    "t2": number,
    "t3": number,
    "rr_t1": "string",
    "rr_t2": "string",
    "rr_t3": "string"
  },
  "current_price": number,
  "summary": "string — sammanfattning 3-5 meningar. Ange vilket scenario som är primärt baserat på dominerande trend och varför."
}

Regler:
- OBLIGATORISKT: bedöm 1h-trenden och 15-min-trenden innan du väljer primärt scenario
- Om 1h är bullish → LONG är primärt, SHORT är kontra-trend och märks som högrisk
- Om 1h är bearish → SHORT är primärt, LONG är kontra-trend och märks som högrisk
- Gå INTE emot dominerande trend utan stark divergens + nyckelzonsbrott + volymbekräftelse
- Volym (inkl. VWAP), EMA 9/20/50/200, ATR 14 och Gårdagens High/Low ska vägas in om synliga
- Alla priser ska vara exakta numeriska värden utan enheter
- All text ska vara på svenska
- current_price är det senaste synliga priset i diagrammet
- t3 och rr_t3 kan vara null i både short och long om bara två targets är tydliga
- Beräkna R:R korrekt: SHORT: risk = stop_loss − entry_mid, reward = entry_mid − target; LONG: risk = entry_mid − stop_loss, reward = target − entry_mid
- Om flera diagram visas, integrera alla tidsperspektiv
- Returnera ENDAST det rå JSON-objektet, inga markdown-kodblock, inga extra ord"""


def analyze_chart_image(image_data_list: list, panel: str = "a") -> dict:
    """
    Accepts a list of dicts: [{'data': base64str, 'media_type': 'image/jpeg'}, ...]
    Returns parsed analysis dict or raises on failure.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    if panel == "a":
        system = GOLD_SYSTEM_PROMPT
        prompt = GOLD_ANALYSIS_PROMPT
    elif panel == "b":
        system = NASDAQ_SYSTEM_PROMPT
        prompt = NASDAQ_ANALYSIS_PROMPT
    else:
        system = SYSTEM_PROMPT
        prompt = ANALYSIS_PROMPT

    content = []
    for img in image_data_list:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": img["media_type"],
                "data": img["data"],
            },
        })
    content.append({"type": "text", "text": prompt})

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": content}],
    )

    raw_text = response.content[0].text.strip()

    # Strip markdown code fences if present
    if raw_text.startswith("```"):
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw_text)
        if match:
            raw_text = match.group(1).strip()

    return json.loads(raw_text)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Användning: python tools/analyze_chart.py <bildfil> [<bildfil2> ...]")
        sys.exit(1)

    image_data_list = []
    for path in sys.argv[1:]:
        ext = os.path.splitext(path)[1].lower()
        media_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
        media_type = media_types.get(ext, "image/jpeg")
        with open(path, "rb") as f:
            data = base64.standard_b64encode(f.read()).decode("utf-8")
        image_data_list.append({"data": data, "media_type": media_type})
        print(f"Laddar: {path} ({media_type})")

    result = analyze_chart_image(image_data_list)
    print(json.dumps(result, indent=2, ensure_ascii=False))
