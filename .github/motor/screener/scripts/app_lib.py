"""Shared pieces of the search app (ejecutable/app): one listing shape for every marketplace, the searches the app shows, and the
jobs Claude picks up. Used by app_export.py, app_job.py and ejecutable/server.py.

App listing: {id, site, site_name, title, url, price_text, price_eur, sale ("buy" | "auction"), auction_info, region ("EU" | "UK" |
"JP" | "AM" | "OTHER"), country, grader ("PSA" | "BGS" | ... | None), grade, pokemon [names], card, number, edition, status
("New" | "Seen before"), first_seen, image, ships_to_spain, how_to_buy, note}
Files: data/app/index.json (searches, newest first), data/app/searches/<id>.json (one search and its listings),
data/app/jobs/<id>.json (a search waiting for, or being run by, Claude)."""
import hashlib, json, os, re, unicodedata, datetime as dt
from common import P, load, save, to_eur, NOW, SCREENER

CARDS = load(os.path.join(SCREENER, "cards.json"))["cards"]
GROUPS = {
    "play_promos": {"label": "Play Promos", "desc": "Japanese Gold Star Players Club promos 022 to 026/PLAY",
                    "cards": [c for c in CARDS if c.get("priority")]},
    "gold_stars": {"label": "Gold Stars", "desc": "Every other Japanese Gold Star (2004 to 2007)",
                   "cards": [c for c in CARDS if not c.get("priority")]},
}
JP_SITES = {"Yahoo! Auctions (via Jauce)", "Japan TCG", "Mandarake", "Yuyu-tei", "Card Labo", "Mercari", "Rakuma", "Magi", "Card Rush", "Hareruya2", "SNKRDUNK", "Yahoo! Auctions or PayPay Flea Market (via Buyee)", "Buyee",
            "PayPay Flea Market (via Buyee)", "Yahoo! Shopping (via Buyee)", "Rakuten Ichiba"}
EU_SITES = {"Wallapop", "Vinted"}
EU_ISO = set("AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split())
AM_ISO = set("US CA MX BR AR CL CO PE".split())
COUNTRY_ISO = {"united states": "US", "estados unidos": "US", "japan": "JP", "japón": "JP", "united kingdom": "GB", "reino unido": "GB",
               "canada": "CA", "canadá": "CA", "germany": "DE", "alemania": "DE", "france": "FR", "francia": "FR", "italy": "IT", "italia": "IT",
               "spain": "ES", "españa": "ES", "netherlands": "NL", "países bajos": "NL", "china": "CN", "hong kong": "HK", "australia": "AU",
               "taiwan": "TW", "taiwán": "TW", "south korea": "KR", "corea del sur": "KR", "singapore": "SG", "singapur": "SG", "belgium": "BE",
               "bélgica": "BE", "portugal": "PT", "austria": "AT", "ireland": "IE", "irlanda": "IE", "poland": "PL", "polonia": "PL",
               "switzerland": "CH", "suiza": "CH", "thailand": "TH", "tailandia": "TH", "mexico": "MX", "méxico": "MX"}
GRADERS = r"PSA|BGS|CGC|ARS|TAG|SGC|Beckett|ACE|AGS|PCA|CCC"
JP_KANA = "ァ-ヴー"

def name_re(n):
    """A Pokémon name inside a title: whole word in Latin script; in Japanese not followed by more katakana (ミュウ, not ミュウツー),
    except スター, which sellers glue to the name (「レックウザスター☆」, 「ラティオスゴールドスター」)."""
    if re.search(f"[{JP_KANA}]", n): return re.escape(n) + f"(?=スター|ゴールドスター|[^{JP_KANA}]|$)"
    return r"(?<![A-Za-z])" + re.escape(n) + r"(?![A-Za-z])"

POKEMON = {}   # English Pokémon name -> regex of every name it goes by
for c in CARDS:
    names = set(c["names"]) | {c["pokemon"]}
    pat = POKEMON.get(c["pokemon"])
    POKEMON[c["pokemon"]] = re.compile("|".join(name_re(n) for n in sorted(names, key=len, reverse=True)) + (("|" + pat.pattern) if pat else ""), re.I)

# set and product names that contain a Pokémon's name without selling it ("Gift Box Mew & Lucario" holds Pikachu and Mewtwo ☆)
NOT_A_CARD = re.compile(r"gift\s*box\s*(?:mew|ミュウ)[\s&・and/]*(?:lucario|ルカリオ)?|(?:mew|ミュウ)\s*(?:and|&|・|/)?\s*(?:lucario|ルカリオ)"
                        r"(?:\s*(?:ver\.?|gift\s*box|ギフトボックス))?|(?:mew|ミュウ)\s*gift\s*box|ギフトボックス\s*ミュウ", re.I)

def pokemon_in(title, extra_names=()):
    """Every tracked Pokémon named in a title (a lot of three cards gives three), plus the searched names."""
    title = NOT_A_CARD.sub(" ", title or "")
    out = [p for p, rx in POKEMON.items() if rx.search(title)]
    for n in extra_names:
        if n and re.search(name_re(n), title or "", re.I) and n.title() not in out: out.append(n.title())
    return out

def iso_of(text):
    if not text: return None
    m = re.search(r"Located in ([A-Za-z ]+?)(?:;|$)", text) or re.search(r"desde ([A-Za-zÁ-úñ ]+?)(?:\s+beyon|;|$|\s{2})", text)
    if not m: return None
    v = m.group(1).strip()
    if len(v) == 2 and v.isupper(): return v
    return COUNTRY_ISO.get(v.lower())

def region_of(site_name, extra):
    if site_name in JP_SITES or "Buyee" in (site_name or ""): return "JP", "JP"
    if site_name in EU_SITES: return "EU", "ES"
    iso = iso_of(extra)
    if not iso: return ("AM", "US") if "via Gempire" in (site_name or "") else ("OTHER", None)
    if iso == "GB": return "UK", iso
    if iso in EU_ISO: return "EU", iso
    if iso == "JP": return "JP", iso
    if iso in AM_ISO: return "AM", iso
    return "OTHER", iso

def grade_of(text):
    """Grader and grade written in a title. "PSA8以下" / "PSA 8 or lower" is SNKRDUNK's group for every slab graded 8 or less, not a
    grade (owner, 26 October 2026: a PSA 1 Treecko showed as PSA 8): it gives "PSA ≤8" until the label is read (grades.json)."""
    m = re.search(rf"\b({GRADERS})\s*-?\s*(\d+(?:\.\d)?)(\s*(?:以下|or lower|o menos))?", text or "", re.I)
    if not m: return None, None
    g = m.group(1).upper().replace("BECKETT", "BGS")
    return g, f"{g} ≤{m.group(2)}" if m.group(3) else f"{g} {m.group(2)}"

# Edition (owner, 26 October 2026: "Gold Stars: a filter for First Edition or Unlimited"). Words sellers use; SNKRDUNK writes 1ED / 再販
# (its name for the later, unlimited print). Cards printed once (the Gift Box ☆) are "One printing".
FIRST_ED = re.compile(r"1\s*ED\b|1st|first\s*edition|初版|ファースト|1\.?\s*[ªa]?\s*edici[oó]n|primera edici[oó]n|1\.?\s*auflage|1[eè]re\s*[ée]dition|1ST ED", re.I)
UNLIMITED = re.compile(r"アンリミ|unlimited|ilimitad|無印|\bunl\b|再販|再版|\breprint\b", re.I)
EDITIONS = {c["name_en"]: c.get("editions") for c in CARDS}
def edition_of(title, card=None, given=None):
    printings = (EDITIONS.get(card) or "").lower()
    if printings == "one printing": return "One printing"
    if printings == "none": return None   # the Play promos have no edition
    if given in ("1st Edition", "Unlimited", "One printing"): return given
    t = title or ""
    if FIRST_ED.search(t) and not UNLIMITED.search(t): return "1st Edition"
    if UNLIMITED.search(t) and not FIRST_ED.search(t): return "Unlimited"
    return "not stated"

# What Claude read on the photo (revisar_fotos.py labels): the slab label's grade and "1ST ED.", or the 1st Edition mark on the card.
# It wins over the title everywhere, so the app shows the grade the listing really has.
def label_reads(): return load(P("app", "grades.json"), {}) or {}
def apply_label(l, reads=None):
    o = (reads if reads is not None else label_reads()).get(l["id"])
    if not o: return l
    if o.get("grade"): l["grade"], l["grader"], l["grade_checked"] = o["grade"], o["grade"].split()[0], True
    elif o.get("grade") == "" and o.get("raw"): l["grade"], l["grader"] = None, None
    if o.get("edition"): l["edition"] = o["edition"]
    return l

def sale_of(site_name, extra, sale_type=None):
    if sale_type: return "auction" if sale_type.lower().startswith("auction") else "buy"
    e = (extra or "").lower()
    if "buyee" in (site_name or "").lower() or re.search(r"\b\d+ (bids?|pujas?)\b|auction|subasta", e): return "auction"
    return "buy"

def from_screener(r, image=None):
    """A row of data/out/listings.json (goldstar.py) -> app listing."""
    reg, iso = region_of(r.get("site_name"), r.get("extra"))
    grader, grade = grade_of(r.get("grade") or r.get("title"))
    return {"id": r["id"], "site": (r["id"].split(":")[0]), "site_name": r.get("site_name"), "title": r.get("title"), "url": r.get("url"),
            "price_text": r.get("price_text"), "price_eur": r.get("price_eur"), "sale": sale_of(r.get("site_name"), r.get("extra"), r.get("sale_type")),
            "auction_info": r.get("auction_info"), "region": reg, "country": iso, "grader": grader, "grade": grade or r.get("grade"),
            "pokemon": list(dict.fromkeys([re.sub(r"\s*☆.*", "", r.get("card") or "").strip()] + pokemon_in(r.get("title")))),
            "card": r.get("card"), "number": r.get("number"), "edition": edition_of(r.get("title"), r.get("card"), r.get("edition")), "status": r.get("status"),
            "first_seen": r.get("first_seen"), "image": image, "ships_to_spain": r.get("ships_to_spain"), "how_to_buy": r.get("how_to_buy"),
            "note": r.get("note") or r.get("check") or ""}

SITE_NAME = {"ebay": "eBay", "gempire": "Gempire", "mercari": "Mercari", "rakuma": "Rakuma", "buyee": "Yahoo! Auctions (Buyee)", "magi": "Magi",
             "cardrush": "Card Rush", "hareruya2": "Hareruya2", "snkrdunk": "SNKRDUNK", "wallapop": "Wallapop", "vinted": "Vinted",
             "paypay": "PayPay Flea Market (via Buyee)", "yshop": "Yahoo! Shopping (via Buyee)", "rakuten": "Rakuten Ichiba",
             # full search only (owner, 1 November 2026: "more markets: Japanese shops like Ikebukuro's, forums, odd sites that ship to Spain")
             "mandarake": "Mandarake", "yuyutei": "Yuyu-tei", "clabo": "Card Labo", "elitefourum": "Elite Fourum (foro)",
             # more markets (owner, 1 November 2026: "Australia, more Japanese shops, more sites"): Yahoo! Auctions through the proxy Jauce
             # (ships to Spain), the Australian shops Cherry Collectables and Monster Mart, Pokemon Plug (US) and Japan TCG
             "jauce": "Yahoo! Auctions (via Jauce)", "cherry": "Cherry Collectables (Australia)", "monstermart": "Monster Mart (Australia)",
             "pokemonplug": "Pokemon Plug", "japantcg": "Japan TCG"}

BAD_PHOTO = re.compile(r"dummy|placeholder|loading|blank|spacer|noimage|lazy-", re.I)
def photo_of(site, r):
    """The listing photo a reader saw; Mercari items without one get it from the item number."""
    img = r.get("image") or r.get("img")
    if img and not BAD_PHOTO.search(img): return img
    m = site == "mercari" and re.search(r"(m\d{8,})", str(r.get("id")) + " " + (r.get("url") or ""))
    return f"https://static.mercdn.net/item/detail/orig/photos/{m.group(1)}_1.jpg" if m else None

def from_page_row(site, r, names=()):
    """A row a marketplace reader (or ebay_api.row) returned -> app listing (searches typed in the app)."""
    site_name = SITE_NAME.get(site, site)
    if site == "gempire":
        house = r["id"].split("_")[0] if not r["id"].isdigit() else "ebay"
        site_name = "eBay" if house == "ebay" else {"alt": "ALT", "fanatics": "Fanatics Collect", "goldin": "Goldin"}.get(house, house) + " (via Gempire)"
        site = "ebay" if house == "ebay" else "gempire"
    reg, iso = region_of(site_name, r.get("extra"))
    eur, _ = to_eur(r.get("price_text"))
    grader, grade = grade_of(r.get("title"))
    return {"id": f"{site}:{r['id']}", "site": site, "site_name": site_name, "title": r.get("title"), "url": r.get("url"),
            "price_text": r.get("price_text"), "price_eur": eur, "sale": sale_of(site_name, r.get("extra")),
            "auction_info": (re.search(r"(\d+ (?:bids?|pujas?)[^;]*)", r.get("extra") or "") or [None, None])[1],
            "region": reg, "country": iso, "grader": grader, "grade": grade, "pokemon": pokemon_in(r.get("title"), names),
            "card": None, "number": None, "edition": edition_of(r.get("title")), "status": "New", "first_seen": now_iso(),
            "image": photo_of(site, r), "ships_to_spain": None, "how_to_buy": None, "note": r.get("extra") or ""}

# ---- searches and jobs
def search_path(sid): return P("app", "searches", f"{sid}.json")
def job_path(jid): return P("app", "jobs", f"{jid}.json")

def slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    if s: return ("q-" + s)[:60]
    # no letters a-z (a search in Japanese only): a name made from the text itself, the same every time, so refreshing the search
    # updates it instead of starting another (it was the time of day until 31 October 2026)
    t = unicodedata.normalize("NFKC", text or "").strip().lower()
    return "q-" + (hashlib.sha1(t.encode()).hexdigest()[:10] if t else dt.datetime.now().strftime("%H%M%S"))

def save_search(s):
    """Saves the search and its card in data/app/index.json (the "Búsquedas recientes" folder). Cards keep their place: they are
    ordered by when the search was first made, so refreshing one does not move it; thumbs are the photos of its cheapest listings."""
    old = load(P("app", "index.json"), [])
    reads = label_reads()
    # motor.py's photo comparison: a photo that does not look like the confirmed photos of its card is shown with a warning
    # (not removed: 1.7 % of right photos score that low too); a photo confirmed by hand (revisar_fotos.py) never gets it
    auto, hand = load(P("app", "photo_auto.json"), {}) or {}, load(P("app", "photo_review.json"), {}) or {}
    for l in s.get("listings", []):
        if (auto.get(l["id"]) or {}).get("verdict") == "wrong" and not (hand.get(l["id"]) or {}).get("ok"): l["photo_doubt"] = True
        else: l.pop("photo_doubt", None)
    for l in s.get("listings", []):   # grades left as "PSA ≤8" by an older run, and what Claude read on the photos
        if l.get("grade") and re.search(r"以下|or lower", l.get("title") or "") and "≤" not in l["grade"] and not l.get("grade_checked"):
            l["grader"], l["grade"] = grade_of(l["title"])
        if l.get("edition") in (None, "not stated") or l.get("card"):
            l["edition"] = edition_of(l.get("title"), l.get("card"), l.get("edition"))
        apply_label(l, reads)
    s["updated"] = s.get("updated") or now_iso()
    s["created"] = s.get("created") or next((x.get("created") or x.get("updated") for x in old if x["id"] == s["id"]), None) or now_iso()
    save(search_path(s["id"]), s)
    L = sorted((l for l in s.get("listings", []) if l.get("price_eur") is not None), key=lambda l: l["price_eur"])
    card = {k: s.get(k) for k in ("id", "kind", "label", "group", "query", "updated", "created", "status")} | {
        "count": len(s.get("listings", [])), "min_eur": L[0]["price_eur"] if L else None,
        "thumbs": [l["image"] for l in L if l.get("image")][:4]}
    idx = [x for x in old if x["id"] != s["id"]] + [card]
    idx.sort(key=lambda x: (x.get("kind") != "group", -(dt.datetime.fromisoformat(x.get("created") or x.get("updated") or "2000-01-01T00:00").timestamp())))
    save(P("app", "index.json"), idx[:60])

def now_iso(): return dt.datetime.now(NOW.tzinfo).isoformat(timespec="minutes")

# Searches with their own rules (owner, 1 November 2026: "Pokémon Present Campaign: Suicune, Entei, Raikou, Ho-Oh, Lugia, in Japanese,
# in a folder like the Gold Stars, full search"): the five shiny cosmos-holo promos of the 2010 「色違いポケモンプレゼント」 lottery,
# 1,000 of each (pokumon.com/shiny-pokemon-present-campaign). Any search typed in the app or on the phone that says "present campaign"
# uses them: one folder for the five cards, each searched by its number and as a shiny promo, in every market.
PC_NAMES = {"Entei": ("エンテイ", "062"), "Suicune": ("スイクン", "063"), "Raikou": ("ライコウ", "064"), "Ho-Oh": ("ホウオウ", "065"), "Lugia": ("ルギア", "066")}
PRESETS = [{
    "match": r"present\s*campaign|プレゼントキャンペーン",
    "spec": {"en": "pokemon", "ja": " ".join(v[0] for v in PC_NAMES.values()), "q": "Pokémon Present Campaign", "poke": list(PC_NAMES),
             "alias": {"pokemon": [v[0] for v in PC_NAMES.values()], **{p.lower(): [v[0], p.replace("-", "")] for p, v in PC_NAMES.items()}},
             # one of the five, and the campaign: its number (062/L-P to 066/L-P) or the campaign named. "色違い プロモ" alone is
             # usually the shiny dogs given at cinemas in 2010 (059 to 061/L-P, a few euros), not these (hundreds of euros and up)
             "must": [r"(?<![a-z])(?:entei|suicune|raikou|ho-?oh|lugia)(?![a-z])|エンテイ|スイクン|ライコウ|ホウオウ|ルギア",
                      r"(?<!\d)0?6[2-6]\s*/\s*l\s*-?\s*p|色(?:ちがい|違い)の?ポケモンプレゼント|プレゼントキャンペーン|present\s*campaign|shiny\s*(?:pok[eé]mon\s*)?present"
                      r"|抽選|lottery|1000\s*(?:名|枚|printed|copies)"],
             # not the cinema promos, the English reprints (Call of Legends, SL numbers), the LEGEND halves, later ex / V cards,
             # Shining Ho-Oh (2017), Shiny Treasure and other modern sets
             "not": [r"映画|劇場|movie|cinema|theat|デジモン|digimon|メザスタ|mezastar|ナノブロック|プラモ|おもちゃ|玩具|フィギュア|figure|ぬいぐるみ|plush|"
                     r"(?<!\d)0?(?:59|60|61)\s*/\s*l\s*-?\s*p|call\s*of\s*legends|コールオブレジェンド|\bcol\b|\bsl\s*\d|(?<![a-z])(?:ex|gx|v|vmax|vstar|legend)(?![a-z])|レジェンド|ひかる|shining|シャイニー|"
                     r"(?<![a-z])(?:sv|sm|s)\d+[a-z]?(?![a-z])|\d{2,3}\s*/\s*(?:sv|sm|s|xy|bw|dp)-?p\b|\benglish\b|英語|pok[eé]mon\s*go"]},
    "q_en": [f"{p} {v[1]}/L-P" for p, v in PC_NAMES.items()] + [f"shiny {p} promo japanese" for p in PC_NAMES],
    "q_ja": [f"{v[0]} {v[1]}/L-P" for v in PC_NAMES.values()] + [f"{v[0]} 色違い プロモ" for v in PC_NAMES.values()],
}]
def preset_of(query):
    """The search with its own rules that a typed search means, or None."""
    return next((p for p in PRESETS if re.search(p["match"], query or "", re.I)), None)
