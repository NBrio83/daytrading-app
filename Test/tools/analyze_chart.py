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
    "rr_t1": "string — t.ex. '1.5:1'",
    "rr_t2": "string — t.ex. '2.5:1'"
  },
  "current_price": number,
  "summary": "string — sammanfattning på svenska, 3-5 meningar"
}

Regler:
- Alla priser ska vara exakta numeriska värden utan enheter
- All text ska vara på svenska
- current_price är det senaste synliga priset i diagrammet
- t3 i short_scenario kan vara null om bara två targets är tydliga
- rr_t3 kan vara null om t3 är null
- Beräkna R:R korrekt: för SHORT är risk = stop_loss - entry_mid, reward = entry_mid - target
- Om flera diagram visas, integrera alla tidsperspektiv i din analys
- chart_title och instrument_info ska extraheras från vad som syns i diagrammet
- Returnera ENDAST det rå JSON-objektet, inga markdown-kodblock, inga extra ord"""


def analyze_chart_image(image_data_list: list) -> dict:
    """
    Accepts a list of dicts: [{'data': base64str, 'media_type': 'image/jpeg'}, ...]
    Returns parsed analysis dict or raises on failure.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

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
    content.append({"type": "text", "text": ANALYSIS_PROMPT})

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
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
