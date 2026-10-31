"""Shared paths, settings and small helpers for the Pokémon screener (ebay.es, euros, Madrid time)."""
import json, os, re, datetime as dt
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
SCREENER = os.path.dirname(HERE)
ROOT = os.path.dirname(SCREENER)
DATA = os.path.join(ROOT, "data")
CFG = json.load(open(os.path.join(ROOT, "settings.json"), encoding="utf-8"))
TZ = ZoneInfo(CFG["owner"]["time_zone"])
NOW = dt.datetime.now(TZ)
TODAY = NOW.date()

def P(*a):
    # a search started from the app reads its pages in its own folder (GS_BROWSER=app/jobs/<id>/browser), not in data/browser
    if a and a[0] == "browser" and os.environ.get("GS_BROWSER"): return os.path.join(DATA, os.environ["GS_BROWSER"], *a[1:])
    return os.path.join(DATA, *a)

def load(path, default=None):
    if not os.path.exists(path): return default
    d = json.load(open(path, encoding="utf-8"))
    return json.loads(d) if isinstance(d, str) else d

def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(obj, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)

def eur(text):
    """First euro amount in a Spanish-format text: '2 099,00 EUR' -> 2099.0. None if there is none."""
    if not text: return None
    m = re.search(r"([\d.\s  ]*\d,\d{2})\s?EUR", text)
    if not m: return None
    return float(re.sub(r"[.\s  ]", "", m.group(1)).replace(",", "."))

def money(v): return "—" if v is None else f"€{v:,.2f}"

EU = {"España", "Alemania", "Francia", "Italia", "Irlanda", "Países Bajos", "Holanda", "Bélgica", "Dinamarca", "Austria", "Portugal",
      "Polonia", "Suecia", "Finlandia", "Luxemburgo", "República Checa", "Chequia", "Grecia", "Hungría", "Eslovaquia", "Eslovenia",
      "Croacia", "Rumanía", "Rumania", "Bulgaria", "Lituania", "Letonia", "Estonia", "Malta", "Chipre"}
EUROPE_NON_EU = {"Reino Unido", "Suiza", "Noruega", "Islandia", "Liechtenstein", "Mónaco", "Andorra", "San Marino", "Ciudad del Vaticano",
                 "Gibraltar", "Guernsey", "Jersey", "Isla de Man", "Serbia", "Albania", "Bosnia y Herzegovina", "Montenegro",
                 "Macedonia del Norte", "Macedonia", "Moldavia", "Ucrania", "Kosovo"}
COUNTRY_EN = {"España": "Spain", "Alemania": "Germany", "Francia": "France", "Italia": "Italy", "Irlanda": "Ireland", "Países Bajos": "Netherlands",
              "Holanda": "Netherlands", "Bélgica": "Belgium", "Dinamarca": "Denmark", "Austria": "Austria", "Portugal": "Portugal", "Polonia": "Poland",
              "Suecia": "Sweden", "Finlandia": "Finland", "Luxemburgo": "Luxembourg", "República Checa": "Czech Republic", "Chequia": "Czech Republic",
              "Grecia": "Greece", "Hungría": "Hungary", "Eslovaquia": "Slovakia", "Eslovenia": "Slovenia", "Croacia": "Croatia", "Rumanía": "Romania",
              "Rumania": "Romania", "Bulgaria": "Bulgaria", "Lituania": "Lithuania", "Letonia": "Latvia", "Estonia": "Estonia", "Malta": "Malta",
              "Chipre": "Cyprus", "Reino Unido": "United Kingdom", "Suiza": "Switzerland", "Noruega": "Norway", "Islandia": "Iceland",
              "Estados Unidos": "United States", "Japón": "Japan", "Canadá": "Canada", "China": "China", "Hong Kong": "Hong Kong",
              "Corea del Sur": "South Korea", "Australia": "Australia", "Taiwán": "Taiwan", "Singapur": "Singapore", "Tailandia": "Thailand"}

def region(country):
    if country == "España": return "Spain"
    if country in EU: return "EU"
    if country in EUROPE_NON_EU: return "Europe outside the EU"
    return "Rest of the world"

def country_en(c): return COUNTRY_EN.get(c, c)

def card_names():
    """Card key -> readable card name and set, from searches.json and the key itself."""
    S = load(os.path.join(SCREENER, "searches.json"))
    out = {}
    for s in S["searches"]:
        for slug, _ in s["cards"]:
            set_part, card_part = slug.split("/", 1)
            set_name = set_part.replace("pokemon-", "").replace("-", " ").replace("&", "and").title().replace("'S", "'s")
            card = re.sub(r"-(\d+[a-z]*)$", r" #\1", card_part).replace("-", " ").title()
            out[slug] = {"card": s.get("name") or card, "set": s.get("set_name") or set_name, "group": s.get("group") or "main", "search": s["q"],
                         "japanese": "japanese" in slug}
    return out

def to_eur(text):
    """An amount in any currency eBay shows ('£383.20', 'GBP 70,20', 'USD5 350,00', '83,09 EUR') -> euros, using data/fx.json
    (European Central Bank reference rates). Returns (euros, original text) or (None, text)."""
    if not text: return None, text
    m = re.search(r"(£|GBP|US ?\$|USD|HK ?\$|HKD|S ?\$|SGD|PLN|SEK|NOK|DKK|NZD|CZK|HUF|\$|EUR|€|JPY|¥|CHF|CAD|C \$|AU ?\$|AUD)\s?([\d.,\s  ]*\d)|([\d.,\s  ]*\d)\s?(EUR|€|GBP|USD|JPY|CHF|CAD|AUD|HKD|SGD|PLN|SEK|NOK|DKK|NZD|CZK|HUF|zł)", text)
    if not m: return None, text
    cur = (m.group(1) or m.group(4)).replace(" ", ""); num_s = re.sub(r"[\s  ]", "", m.group(2) or m.group(3))
    if "," in num_s and "." in num_s:
        num_s = num_s.replace(".", "").replace(",", ".") if num_s.rfind(",") > num_s.rfind(".") else num_s.replace(",", "")
    elif "," in num_s: num_s = num_s.replace(",", ".") if re.search(r",\d{2}$", num_s) else num_s.replace(",", "")
    elif re.search(r"\.\d{3}$", num_s): num_s = num_s.replace(".", "")
    v = float(num_s)
    code = {"£": "GBP", "US$": "USD", "$": "USD", "€": "EUR", "¥": "JPY", "C$": "CAD", "AU$": "AUD", "HK$": "HKD", "S$": "SGD", "zł": "PLN"}.get(cur, cur)
    if code == "EUR": return round(v, 2), text
    fx = load(P("fx.json"), {}).get("rates", {})
    return (round(v / fx[code], 2), text) if code in fx else (None, text)
