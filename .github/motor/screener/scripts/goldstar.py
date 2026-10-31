"""Japanese Gold Star screener: turn every marketplace page read this run into the dashboard's listings.

Inputs:  screener/cards.json        the Japanese Gold Star cards (names in every language, numbers, editions, priority)
         data/browser/pages.json    the pages planned this run (make_plan.py)
         data/browser/pages/<i>.json what list_reader.js returned for page i
         data/browser/photos/<site_id>.json  photo checks: {"card_number": "022/PLAY" | "015/108" | null, "edition": "1st Edition" |
                                    "Unlimited" | null, "matches": true|false|null, "text": "...", "reason": "..."}
State:   data/state/seen.json       every Gold Star listing ever seen: first seen, last seen, prices, verdicts
Outputs: data/out/*.json for the dashboard, data/out/summary.txt, data/browser/photo_queue.json (listings whose photo must be checked)

Rules (owner, 15 October 2026):
- Japanese Gold Stars only. Priority: the five Play promos 022 to 026/PLAY (Vaporeon, Jolteon, Flareon, Espeon, Umbreon).
  Vaporeon, Jolteon and Flareon count ONLY as the Play promos 022/PLAY, 023/PLAY, 024/PLAY.
- Every other Japanese Gold Star counts; unlimited prints rank above 1st Edition.
- Titles can be wrong both ways, so every listing of a Play promo Pokémon's Gold Star is checked on its photo
  (card number) before it is shown or ruled out; a photo verdict overrides the title.
- Each run reports new listings (first seen this run), listings seen before (with any price change) and listings no longer found.
Usage: python goldstar.py ["note"]"""
import json, os, re, sys, glob, unicodedata, datetime as dt
from common import P, load, save, NOW, TODAY, CFG, money, to_eur, ROOT, SCREENER

CARDS = load(os.path.join(SCREENER, "cards.json"))["cards"]
pages = load(P("browser", "pages.json"), [])
seen = load(P("state", "seen.json"), {})
fx = load(P("fx.json"), {})
RUN = NOW.isoformat(timespec="minutes")
RUN_START = (load(P("state", "run_start.json")) or {}).get("at", RUN)   # set by start_run.py
# an "others" run (make_plan.py others) does not search the Play promos: their listings keep their state and last dashboard rows
OTHERS_RUN = (load(P("browser", "plan_mode.json")) or {}).get("mode") == "others"

def norm(s):
    return unicodedata.normalize("NFKC", s or "").lower()

STAR = re.compile(r"☆|gold\s*star|goldstar|ゴールドスター|estrella\s*dorada|[eé]toile\s*d'?or|goldstern|stella\s*d'?oro|\bstar\b|(?<![ァ-ヴー])スター(?![ァ-ヴー])", re.I)
FAKE = re.compile(r"proxy|fan\s*-?\s*made|hecha por fans|custom|orica|オリカ|レプリカ|replica|r[eé]plica|複製|コピー|\bcopy\b|\bfake\b|\bfals[oa]\b|unofficial|no oficial|非公式|metal card|gold metal|"
                  r"スリーブ|sleeve|プレイマット|playmat|ファイル|シール|sticker|ポスター|poster|フィギュア|figure|ぬいぐるみ|plush|peluche|\bpin\b|ピンズ|lego|camiseta|t-shirt|tシャツ|"
                  r"マスコット|mascot|all star collection|オールスターコレクション|\bmtg\b|未開封ブースター|ブースターパック|booster (box|pack)|アンテナ|テレビ|ケーブル|uhf|パジャマ|ワッペン|アイロン|メタルチャーム|30th celebration|復刻|"
                  r"メザスタ|mezastar|ガオーレ|gaole|keychain|key chain|キーホルダー|portachiavi|llavero|magnetic frame|mini gift|miu ?miu|ミュウミュウ|iphone|スマホケース", re.I)
ENGLISH = re.compile(r"英語版|英語|海外版|\benglish\b|\bingl[eé]s\b|\banglais\b|\benglisch\b|\binglese\b|\b(eng|en)\b|power\s*keepers|ex\s+(deoxys|team rocket|unseen|delta|dragon frontiers|crystal guardians|holon|legend maker|firered|emerald|hidden legends)", re.I)
JAPANESE = re.compile(r"japan|japon|japanisch|giappon|日本|\bjpn?\b|\bjp\b|ポケモンカード|ポケカ|[ぁ-んァ-ン]", re.I)
FIRST = re.compile(r"1\s*ed\b|1st|first\s*edition|初版|ファースト|1\.?\s*[ªa]?\s*edici[oó]n|primera edici[oó]n|1\.?\s*auflage|1[eè]re\s*[ée]dition", re.I)
UNLIM = re.compile(r"アンリミ|unlimited|ilimitad|無印|\bunl\b|再販|再版", re.I)   # 再販: SNKRDUNK's name for the unlimited print (26 October 2026)
GRADE = re.compile(r"(?<![A-Za-z])(PSA|BGS|BECKETT|CGC|SGC|ARS|ACE|TAG)\s*[:#]?\s*(10|9\.5|[1-9](?:\.5)?)(?![\d.])|(PSA|BGS|ARS)(10|[1-9])鑑定|〔(PSA|BGS|ARS)(10|9\.5|[1-9])鑑定済〕", re.I)
# a Mercari title cut on the search page ("…") is completed on the listing page only when nothing in the visible part says modern card
MODERN = re.compile(r"(?<![a-z])(ex|gx|v|vmax|vstar|sar|ar|chr|sr|rr|ur|hr|mega|30th)(?![a-z])|マスターボール|モンスターボール|マスボ|テラスタル|スカーレット|バイオレット|ハイクラス|"
                    r"イーブイヒーローズ|スターター|(?<![a-z])(sv|s|sm)\d+a?(?![a-z])|旧裏|メザスタ|ブレイブサンダース|lv\.|δ|デルタ|ジャングル|151|デッキ", re.I)
PLAY_SIGN = re.compile(r"play|players|プレイヤー|プレイ|pts|exp|points|0(2[2-6])\s*/\s*play", re.I)
SET_WORDS = re.compile(r"まとめ|セット|\bset\b|\blot\b|\blote\b|\bbundle\b|[2-9]\s*枚", re.I)

def identify(title, site):
    """Return (card, details) when the title is a Japanese Gold Star listing, else (None, reason)."""
    t = norm(title)
    if FAKE.search(t): return None, "not a genuine card (fake, fan-made or merchandise)"
    hits = []
    for c in CARDS:
        # "エーフィex ☆" or "ブラッキーV" is a later Pokémon-ex / V card (the ☆ there is a rarity mark), not the Gold Star
        pats = [re.escape(norm(x)) + r"(?!ツー|two|tu\b)(?!\s*(?:ex|gx|vmax|vstar|v|lv|δ)(?![a-z]))" for x in c["names"]]
        m = [mm for p_ in pats for mm in re.finditer(p_, t)]
        if not m: continue
        rest = t
        for x in sorted({norm(n) for n in c["names"]}, key=len, reverse=True): rest = rest.replace(x, " ")
        rest = re.sub(r"black\s*star|blackstar|ブラックスター|star\s*wars|スターター|starter|shiny\s*star|シャイニースター", " ", rest)
        num_hit = any(norm(n) in t for n in c.get("numbers", []))
        star_hit = bool(STAR.search(rest)) or any(norm(x) + "☆" in t.replace(" ", "") for x in c["names"])
        if star_hit or num_hit: hits.append((c, num_hit))
    if not hits: return None, "no Gold Star named"
    # Pikachu ☆ and Mewtwo ☆ came in the "Mew" gift box (ギフトボックス ミュウ・ルカリオver.): that Mew is the box, not the Mew ☆ δ card
    if re.search(r"gift\s*b(o)?x|ギフトボックス|caja de regalo|coffret", t) and not re.search(r"015\s*/\s*068|δ|delta|デルタ", t):
        hits = [h for h in hits if h[0]["pokemon"].lower() != "mew"] or hits
    all_hits = list(hits)
    if len({h[0]["pokemon"] for h in hits}) > 1 and not SET_WORDS.search(t):
        hits = [h for h in hits if h[1]] or hits
    c = sorted(hits, key=lambda h: (not h[1], not h[0].get("priority")))[0][0]
    others = sorted({h[0]["name_en"] for h in all_hits if h[0]["pokemon"] != c["pokemon"]})
    # every card (the Play promos since 15 October 2026, the other Gold Stars since 21 October 2026, when a full run let through
    # 「フーディン AR 071/063」, 「エンテイ＆ライコウLEGEND 063/080」 and 30th CELEBRATION reprints): a decorative ☆ (「☆☆ ポケカ サンダース
    # 135/165」) is not enough; the title must name the card as a Gold Star (name☆, gold star, スター), as the Play promo or by its
    # number, and must not carry another card's number (135/165, 015/068, 177/173)
    if True:
        own = [norm(c["number"])] + [norm(n) for n in c.get("numbers", [])] + [norm(k) for v in c.get("other_versions", []) for k in v["keys"] if re.search(r"\d/\d", k)]
        nums = [n for n in re.findall(r"(?<!\d)\d{2,3}\s*/\s*(?:\d{2,3}(?!\d)|(?:bw|xy|sm|sv|dp|s|pcg)-?p\b)", t) if not any(re.sub(r"\s", "", n) == re.sub(r"\s", "", o) for o in own)]
        if nums and not (c.get("priority") and PLAY_SIGN.search(t)): return None, "another card's number in the title (" + nums[0] + ")"
        named_star = (re.search(r"gold\s*star|goldstar|ゴールドスター|(?<![ァ-ヴー])スター(?![ァ-ヴー])|\bstar\b", t)
                      or any(re.search(re.escape(norm(x)) + r"\s*☆", t) for x in c["names"]))
        if not (named_star or PLAY_SIGN.search(t) or any(norm(n) in t for n in c.get("numbers", []))):
            return None, "☆ only as decoration"
    jp_site = site in ("mercari", "rakuma", "magi", "cardrush", "snkrdunk", "buyee", "hareruya2", "paypay", "yshop", "rakuten")
    if ENGLISH.search(t) and not re.search(r"日本語|japanese|japon", t): return None, "English card"
    if not jp_site and not JAPANESE.search(t) and not any(norm(n) in t for n in c.get("numbers", [])):
        return None, "not stated as Japanese"
    g = GRADE.search(title or "")
    grade = None
    if g:
        parts = [x for x in g.groups() if x]
        grade = f"{parts[0].upper().replace('BECKETT', 'BGS')} {parts[1]}" + (" or lower" if re.search(re.escape(parts[0]) + r"\s*" + re.escape(parts[1]) + r"\s*以下", title or "", re.I) else "")
    else:
        cm = re.search(r"〔状態([SABCD][+-]?)〕|状態ランク([SABCD][+-]?)|^(S|A|B|C|D)\s|\[(S|A|B|C|D)\]$", title or "")
        if cm: grade = "Condition " + next(x for x in cm.groups() if x) + " (ungraded)"
    edition = "1st Edition" if FIRST.search(t) else ("Unlimited" if UNLIM.search(t) else "not stated")
    other_versions = [v for v in c.get("other_versions", []) if any(norm(k) in t for k in v["keys"])]
    return c, {"grade": grade, "edition": edition, "set_of_cards": bool(SET_WORDS.search(t)) or bool(others), "also": others,
               "title_says_other_version": other_versions[0]["name"] if other_versions else None}

def site_of(url):
    h = re.sub(r"^https?://", "", url).split("/")[0]
    if "buyee.jp/paypayfleamarket" in url: return "paypay"
    if "/jdirectitems/shopping" in url: return "yshop"
    for k in ("ebay", "mercari", "snkrdunk", "fril", "cardrush", "magi", "wallapop", "vinted", "buyee", "gempire", "hareruya2", "rakuten"):
        if k in h: return {"fril": "rakuma"}.get(k, k)
    return h

# Buy now or auction (owner, 18 October 2026: separate tabs). Auction signs: bids or time left on the search page (eBay "puja",
# Gempire "N bids 3d 16h"), a Yahoo! Auctions page on Buyee, or an auction house lot without a "Buy It Now" label.
AUCTION = re.compile(r"\bbids?\b|\bpujas?\b|\d+\s*[dhm]\s+\d+\s*[hms]\b|time remaining|number of bids|tiempo restante", re.I)
def sale_type(r):
    x, u = (r.get("extra") or ""), (r.get("url") or "")
    if re.search(r"buy it now|c[oó]mpralo ya", x, re.I) and not re.search(r"\bbids?\b|\bpujas?\b", x, re.I): return "Buy now"
    if "/jdirectitems/auction/" in u or AUCTION.search(x): return "Auction"
    return "Buy now"
def auction_info(r):
    if sale_type(r) != "Auction": return None
    bits = re.findall(r"\d+\s*bids?|\d+\s*pujas?|\d+\s*d\s*\d+\s*h|\d+\s*h\s*\d+\s*m(?:\s*\d+\s*s)?|Time Remaining[^|;]*|Number of Bids[^|;]*|ends \d{4}-\d\d-\d\d \d\d:\d\d UTC", r.get("extra") or "", re.I)
    return "; ".join(dict.fromkeys(b.strip() for b in bits)) or "Auction (see the listing for the end time)"

# How a buyer in Spain can buy from each site (sources in settings.json "shipping_to_spain"); eBay is read per listing
SHIPPING = load(os.path.join(SCREENER, "shipping.json"), {})

SITE_NAME = {"ebay": "eBay", "mercari": "Mercari", "snkrdunk": "SNKRDUNK", "rakuma": "Rakuma", "cardrush": "Card Rush", "magi": "Magi", "hareruya2": "Hareruya2",
             "wallapop": "Wallapop", "vinted": "Vinted", "buyee": "Yahoo! Auctions or PayPay Flea Market (via Buyee)", "gempire": "Other auction house (via Gempire)",
             "paypay": "PayPay Flea Market (via Buyee)", "yshop": "Yahoo! Shopping (via Buyee)", "rakuten": "Rakuten Ichiba"}

# ---- read this run's pages
read_ok, refused, found, title_checks = set(), [], {}, []
safe = lambda k: re.sub(r"[^\w.-]", "_", k)
PRI = {c["key"] for c in CARDS if c.get("priority")}
for f in sorted(glob.glob(P("browser", "pages", "*.json"))):
    i = int(os.path.basename(f).split(".")[0]); d = load(f) or {}
    if i >= len(pages): continue   # left over from an earlier plan of this run (not part of the current plan)
    plan = pages[i]
    site = plan.get("site") or site_of(d.get("url", ""))
    via_gempire = site == "gempire"
    if d.get("blocked"): refused.append(f"{SITE_NAME.get(site, site)}: {plan.get('label', '')}"); continue
    read_ok.add((site, plan.get("card_key") or "*"))
    for r in d.get("rows", []):
        if r.get("status") not in ("on sale", None): continue
        if via_gempire:   # Gempire rows are eBay listings (id = eBay item number) or another auction house ("goldin_123")
            site = "ebay" if r["id"].isdigit() else "gempire"
            if f"{site}:{r['id']}" in found: continue   # already read on ebay.es (price in euros there)
        key = f"{site}:{r['id']}"
        title = r.get("title", "")
        if title.endswith("…"):   # cut on the search page (Mercari): use the full title from the listing page when it has been read
            lp_t = (load(P("browser", "listing", safe(key) + ".json")) or {}).get("title") or (seen.get(key) or {}).get("full_title")
            if lp_t: title = re.sub(r"\s*(by\s*メルカリ|-\s*メルカリ|\|\s*メルカリ.*)$", "", lp_t)
        card, info = identify(title, site)
        if not card:
            eur_ = to_eur(r.get("price_text") or "")[0]   # Mercari may show euros to a visitor from Spain (28 October 2026)
            yen = round(eur_ * 176) if eur_ and "€" in (r.get("price_text") or "") else int(re.sub(r"\D", "", r.get("price_text") or "") or 0)
            if (title.endswith("…") and plan.get("card_key") in PRI and not MODERN.search(norm(title)) and yen >= 20000
                    and not FAKE.search(norm(title)) and load(P("browser", "listing", safe(key) + ".json")) is None):
                title_checks.append({"key": key, "url": r["url"], "card": plan["card_key"], "site": site, "price_text": r.get("price_text"),
                                     "why": "title cut on the search page: open it to read the full title"})
            continue
        r = {**r, "title": title}
        house = {"alt": "ALT", "fanatics": "Fanatics Collect", "goldin": "Goldin", "heritage": "Heritage"}.get(r["id"].split("_")[0], r["id"].split("_")[0]) if site == "gempire" else None
        found[key] = {"key": key, "site": site, "site_name": f"{house} (via Gempire)" if house else SITE_NAME.get(site, site), "id": r["id"], "url": r["url"], "title": r["title"],
                      "price_text": r.get("price_text"), "extra": r.get("extra"), "card_key": card["key"], "card": card["name_en"] + ("".join(" + " + o for o in info["also"]) + " (several cards)" if info["also"] else ""),
                      "card_ja": card["name_ja"], "number": card.get("number"), "set": card.get("set_en"), "priority": card.get("priority", False),
                      **info}

# ---- listing-page checks (browser/listing.js): every Play promo listing is opened each run to confirm it is still for sale
# (search pages can show sold copies, for example SNKRDUNK's "Sold" badge) and to read what it says about delivery to Spain
check_queue = list({t["key"]: t for t in title_checks}.values())
for k, r in found.items():
    r["listing"] = load(P("browser", "listing", safe(k) + ".json"))
    ph_known = load(P("browser", "photos", safe(k) + ".json")) or seen.get(k, {}).get("photo") or {}
    title_out = bool(r.get("title_says_other_version")) and not PLAY_SIGN.search(norm(r["title"]))   # ruled out on the title below
    if r["priority"] and r["listing"] is None and ph_known.get("matches") is not False and not title_out:   # ruled out on the photo: no need to open it again
        check_queue.append({"key": k, "url": r["url"], "card": r["card"], "site": r["site"], "price_text": r["price_text"]})
save(P("browser", "check_queue.json"), check_queue)

# ---- photo verdicts: required for every listing of the three Play-promo Pokémon (titles can be wrong both ways)
photo_queue = []
for k, r in found.items():
    card = next(c for c in CARDS if c["key"] == r["card_key"])
    ph = load(P("browser", "photos", re.sub(r"[^\w.-]", "_", k) + ".json")) or (seen.get(k, {}).get("photo"))
    r["photo"] = ph
    catalogue = r["site"] in ("snkrdunk", "cardrush")   # the shop or platform files each copy under its own 022/PLAY product
    r["catalogue"] = catalogue
    # the title names the other print (World Champions Pack 015/108, 25th Anniversary 012/025) and nothing of the Play promo:
    # ruled out on the title, no photo needed (owner, 15 October 2026: dozens of such listings on eBay and Gempire)
    r["title_ruled_out"] = bool(r.get("title_says_other_version")) and not PLAY_SIGN.search(norm(r["title"]))
    if card.get("needs_photo_check") and not ph and not catalogue and not r["title_ruled_out"]:
        photo_queue.append({"key": k, "url": r["url"], "card": r["card"], "title": r["title"], "site": r["site"]})
save(P("browser", "photo_queue.json"), photo_queue)

shown, ruled_out, sold = [], [], []
for k, r in found.items():
    lp = r.get("listing") or {}
    if lp and not lp.get("blocked") and lp.get("available") is False:
        sold.append({**r, "reason": "not for sale on the listing page" + (f" ('{lp.get('sold_text')}')" if lp.get("sold_text") else (f" ('{', '.join(lp.get('sold_buttons') or [])}')" if lp.get("sold_buttons") else " (no buy button)"))}); continue
    card = next(c for c in CARDS if c["key"] == r["card_key"])
    ph = r.get("photo") or {}
    flags = []
    if card.get("needs_photo_check") and r.get("catalogue") and not ph:
        flags.append(f"Listed under {r['site_name']}'s own {card['number']} product page")
    elif card.get("needs_photo_check"):
        if not ph and r.get("title_ruled_out"):
            ruled_out.append({**r, "reason": "the title says " + r["title_says_other_version"] + " and nothing of the Play promo (ruled out on the title)"}); continue
        if ph.get("matches") is False:
            ruled_out.append({**r, "reason": "photo shows " + (ph.get("card_number") or ph.get("text") or "a different card") + ": " + (ph.get("reason") or "not the Play promo")}); continue
        if ph.get("matches") is None:
            if ph: flags.append("Photo checked but the card number is not readable" + (f" ({ph['reason']})" if ph.get("reason") else "") + ": check it shows " + card["number"])
            else: flags.append("Photo not checked yet: confirm the card shows " + card["number"] + " before buying")
            if r.get("title_says_other_version"): flags.append("The title suggests " + r["title_says_other_version"] + "; the photo decides")
        elif ph.get("matches") is True and r.get("title_says_other_version"):
            flags.append(f"The title says {r['title_says_other_version']} but the photo shows {card['number']}: the title is wrong")
    if ph.get("edition"): r["edition"] = ph["edition"] + " (from the photo)"
    if r["priority"] and not lp: flags.append("Not yet confirmed on the listing page that it is still for sale")
    elif r["priority"] and lp.get("available") is None: flags.append("Listing page shows no sold notice but no buy button either (normal on Mercari for buyers outside Japan): still listed")
    if r["set_of_cards"]: flags.append("Several cards in one listing")
    price_eur, _ = to_eur(r["price_text"])
    if price_eur is None and r["price_text"]:
        price_eur, _ = to_eur(r["price_text"] + " EUR") if re.search(r"€", r["price_text"]) else (None, None)
    # a Japanese Gold Star in any condition sold for well over 400 euros on 21 October 2026; far cheaper is usually the English
    # print, a reprint, a fake or an auction's opening price
    if price_eur is not None and price_eur < 400 and "Auction" != sale_type(r):
        flags.append("Price far below what Japanese Gold Stars sell for: check on the photo that it is not the English print, a reprint or a fake")
    prev = seen.get(k)
    status = "New" if (not prev or prev.get("first_seen", "") >= RUN_START) else "Seen before"
    change = None
    if prev and prev.get("price_text") and prev["price_text"] != r["price_text"]:
        change = f"price was {prev['price_text']} on {prev['last_seen'][:10]}"
    jp = r["site"] in ("mercari", "rakuma", "magi", "cardrush", "snkrdunk", "buyee", "hareruya2", "paypay", "yshop", "rakuten")
    ship_rule = SHIPPING.get(r["site"], {})
    ship_page = "; ".join(lp.get("ship") or []) if lp else ""
    if lp.get("no_ship_to_spain"): ships, how = "No", "The listing says it does not ship to Spain"
    elif r["site"] == "ebay" and re.search(r"no (se )?realiza(n)? env[ií]os|does(n't| not) ship|no env[ií]a|no env[ií]e a espa", ship_page, re.I):
        ships, how = "No, or not stated (eBay: the seller may not ship to Spain)", "eBay shows: " + ship_page[:160] + ". Ask the seller before buying, or use a parcel forwarder in the seller's country"
    elif r["site"] == "ebay" and ship_page: ships, how = "Yes, direct", ship_page[:200]
    elif r["site"] == "ebay" and "Ships to Spain:" in (r.get("extra") or ""):   # eBay API, asked as a buyer in Spain
        ships, how = "Yes, direct", "eBay: delivery to Spain " + re.search(r"Ships to Spain: ([^;]*)", r["extra"]).group(1) + " (eBay API, seen from Spain)"
    elif r["site"] == "ebay" and "eBay API" in (r.get("extra") or ""):
        ships, how = "No, or not stated (eBay: the seller may not ship to Spain)", "eBay gives no delivery option to Spain for this listing: ask the seller, or use a parcel forwarder in the seller's country"
    elif r["site"] == "ebay" and "via Gempire" in (r.get("extra") or ""):
        ships, how = "Not checked yet", "Found through Gempire (eBay worldwide); open the listing to see delivery to Spain"
    else: ships, how = ship_rule.get("direct", "Not checked"), ship_rule.get("how", "")
    note = ("Buying from a Japanese site usually needs a proxy service (for example Buyee or ZenMarket); its fees and the international postage are not included."
            if jp else "")
    rows_entry = {**{x: r[x] for x in ("key", "site_name", "url", "title", "price_text", "card", "card_ja", "number", "set", "priority", "grade", "edition", "extra")},
                  "id": k, "status": status, "first_seen": (prev or {}).get("first_seen", RUN), "last_seen": RUN, "price_change": change,
                  "price_eur": price_eur, "check": "; ".join(flags), "note": note, "ships_to_spain": ships, "how_to_buy": how,
                  "photo": (ph.get("card_number") or ph.get("text")) if ph else None,
                  "sale_type": sale_type(r), "auction_info": auction_info(r),
                  "rank": (0 if r["priority"] else 1, 0 if status == "New" else 1, {"Unlimited": 0, "not stated": 1, "1st Edition": 2}.get(r["edition"].split(" (")[0], 1), price_eur or 9e9)}
    shown.append(rows_entry)
    seen[k] = {**(prev or {}), "first_seen": rows_entry["first_seen"], "last_seen": RUN, "price_text": r["price_text"], "title": r["title"],
               "card": r["card"], "url": r["url"], "site_name": r["site_name"], "priority": r["priority"], "photo": ph or (prev or {}).get("photo"),
               "status": "listed", **({"full_title": r["title"]} if r["title"] else {})}
for r in ruled_out:
    seen[r["key"]] = {**seen.get(r["key"], {}), "first_seen": seen.get(r["key"], {}).get("first_seen", RUN), "last_seen": RUN,
                      "title": r["title"], "card": r["card"], "url": r["url"], "site_name": r["site_name"], "photo": r.get("photo"), "status": "ruled out", "reason": r["reason"]}

# listings seen before but not found this run, on a page that was read this run
gone = []
for k, s in list(seen.items()):
    if k in found or s.get("status") not in ("listed", "no longer found"): continue
    if s.get("first_seen", "") >= RUN_START:   # kept by an earlier pass of this same run, dropped by a later filter: never really listed
        del seen[k]; continue
    site = k.split(":")[0]
    card_key = next((c["key"] for c in CARDS if c["name_en"] == s.get("card")), None)
    if OTHERS_RUN and card_key in PRI: continue
    if s.get("status") == "listed" and ((site, card_key) in read_ok or (site, "*") in read_ok):
        s["status"] = "no longer found"; s["gone_since"] = RUN
    if s.get("status") == "no longer found" and s.get("gone_since", RUN)[:10] >= (TODAY - dt.timedelta(days=14)).isoformat():
        gone.append({"id": k, "card": s.get("card"), "site_name": s.get("site_name"), "title": s.get("title"), "url": s.get("url"),
                     "last_price": s.get("price_text"), "first_seen": s.get("first_seen"), "last_seen": s.get("last_seen")})

shown.sort(key=lambda r: r["rank"])
for r in shown: r.pop("rank", None)
last = load(P("state", "last_run.json"), {})
pri = [r for r in shown if r["priority"]]
pri_new = [r for r in pri if r["status"] == "New"]
def line(r): return f"{r['card']} ({r['number']}){' ' + r['grade'] if r['grade'] else ''}, {r['site_name']}, {r['price_text']}" + (f" ({money(r['price_eur'])})" if r["price_eur"] else "") + f": {r['url']}"
summary = [f"Play promos ({', '.join(c['pokemon'] + ' ' + c['number'].split('/')[0] for c in CARDS if c.get('priority'))} /PLAY): {len(pri_new)} new, {len(pri) - len(pri_new)} seen before."]
if OTHERS_RUN: summary = ["Play promos: not searched on this run (Other Gold Stars only); the last run's Play promo listings stay on the dashboard."]
for c in [c for c in CARDS if c.get("priority") and not OTHERS_RUN]:
    n_c = sum(1 for r in pri if r["card"].startswith(c["name_en"]) or c["name_en"] in r["card"])
    if not n_c: summary.append(f"- {c['name_en']} {c['number']}: none for sale on the sites read this run")
summary += ["- NEW " + line(r) for r in pri_new] + ["- " + line(r) for r in pri if r["status"] != "New"]
others = [r for r in shown if not r["priority"]]
o_new = [r for r in others if r["status"] == "New"]
summary.append(f"Other Japanese Gold Stars: {len(o_new)} new, {len(others) - len(o_new)} seen before.")
summary += ["- NEW " + line(r) + (f" [{r['edition']}]" if r["edition"] != "not stated" else "") for r in o_new[:40]]
if ruled_out: summary.append("Ruled out on the photo: " + "; ".join(f"{r['card']} on {r['site_name']} ({r['reason']}) {r['url']}" for r in ruled_out))
if gone: summary.append(f"No longer found since the last run: {len(gone)}")
if sold: summary.append("Shown as for sale on a search page but sold or unavailable on the listing page: " + "; ".join(f"{r['card']} {r['site_name']} {r['price_text']}" for r in sold))
if check_queue: summary.append(f"Listing pages still to check (availability and delivery): {len(check_queue)}")
if photo_queue: summary.append(f"Photos still to check: {len(photo_queue)}")
if refused: summary.append("Pages refused: " + "; ".join(refused))
note = " ".join(sys.argv[1:])
if note: summary.append("Problems: " + note)

run = [{"id": "run", "finished_at": RUN, "finished_text": NOW.strftime("%A ") + str(NOW.day) + NOW.strftime(" %B %Y at %H:%M") + " Madrid time",
        "previous_run": last.get("finished_at"), "pages_planned": len(pages), "pages_read": len(glob.glob(P("browser", "pages", "*.json"))) - len(refused),
        "pages_refused": len(refused), "play_promos_new": len(pri_new), "play_promos_listed": len(pri), "others_new": len(o_new), "others_listed": len(others),
        "ruled_out": len(ruled_out), "no_longer_found": len(gone), "sold_or_unavailable": len(sold), "photos_to_check": len(photo_queue),
        "headline": summary[0], "refused_text": "; ".join(refused) or "none", "fx_text": f"European Central Bank rates of {fx.get('date')}: 1 EUR = {fx.get('rates', {}).get('JPY')} JPY, {fx.get('rates', {}).get('GBP')} GBP, {fx.get('rates', {}).get('USD')} USD",
        "note": note}]
# one file for the dashboard (an empty file cannot be loaded there): listed now, no longer found, ruled out on the photo
blank = {k: None for k in ("sale_type", "auction_info", "ships_to_spain", "how_to_buy", "price_text", "card_ja", "number", "set", "grade", "edition", "extra", "price_change", "price_eur", "photo", "note", "check", "first_seen", "last_seen")}
# owner, 23 October 2026: other Gold Stars priced far below the market go to their own "Possible fraud" tab, so the Buy Now and
# Auction tabs only show listings that can really be at that price; sold copies of them are not shown anywhere
FRAUD = "Price far below what Japanese Gold Stars sell for"
allrows = [{**r, "list": "Play promo" if r["priority"] else ("Possible fraud" if FRAUD in (r.get("check") or "") else "Other Gold Star")} for r in shown]
for g in gone:
    allrows.append({**blank, "id": g["id"], "key": g["id"], "site_name": g["site_name"], "url": g["url"], "title": g["title"], "card": g["card"],
                    "price_text": g["last_price"], "first_seen": g["first_seen"], "last_seen": g["last_seen"], "priority": None,
                    "status": "No longer found", "list": "No longer found", "check": "Not found on this run's search page (sold, ended or removed)"})
for r in sold:
    if r["priority"]:   # sold copies of the other Gold Stars are not shown at all (owner, 23 October 2026)
        allrows.append({**blank, "id": r["key"], "key": r["key"], "site_name": r["site_name"], "url": r["url"], "title": r["title"], "card": r["card"],
                        "price_text": r["price_text"], "priority": r["priority"], "grade": r.get("grade"), "status": "Sold or unavailable", "list": "Sold or unavailable",
                        "check": r["reason"], "last_seen": RUN})
    seen[r["key"]] = {**seen.get(r["key"], {}), "first_seen": seen.get(r["key"], {}).get("first_seen", RUN), "last_seen": RUN, "title": r["title"],
                      "card": r["card"], "url": r["url"], "site_name": r["site_name"], "status": "sold", "price_text": r["price_text"]}
for r in ruled_out:
    allrows.append({**blank, "id": r["key"], "key": r["key"], "site_name": r["site_name"], "url": r["url"], "title": r["title"], "card": r["card"],
                    "price_text": r["price_text"], "priority": r["priority"], "status": "Ruled out", "list": "Ruled out",
                    "check": r["reason"], "photo": (r.get("photo") or {}).get("text")})
if OTHERS_RUN:   # keep the Play promo rows of the last run that searched them
    have = {r["id"] for r in allrows}
    allrows += [r for r in load(P("out", "listings.json"), []) if r.get("priority") and r.get("list") == "Play promo" and r["id"] not in have]
save(P("out", "listings.json"), allrows)
save(P("out", "run.json"), run)
save(P("state", "seen.json"), seen)
save(P("state", "last_run.json"), {"finished_at": RUN})
open(P("out", "summary.txt"), "w", encoding="utf-8").write("\n".join(summary))
print("\n".join(summary))

# ---- sources for the dashboard: what each site gave this run, and the sites that cannot be read automatically
SITES = [("ebay", "eBay (official API since 23 October 2026, seen from Spain; since 26 October 2026 sixteen eBay sites: US, UK, Germany, Spain, Australia, Canada, France, Italy, Netherlands, Ireland, Austria, Switzerland, Belgium, Poland, Hong Kong, Singapore)", "https://www.ebay.es/sch/i.html?_nkw=gold+star+japanese&_sop=10"),
         ("gempire", "GempireCards (eBay worldwide and auction houses)", "https://www.gempirecards.com/listings?q=vaporeon+play+promo"),
         ("mercari", "Mercari (Japan)", "https://jp.mercari.com/search?keyword=%E3%82%B9%E3%82%BF%E3%83%BC%20PLAY&status=on_sale"),
         ("snkrdunk", "SNKRDUNK (Japan)", "https://snkrdunk.com/search?keywords=%E2%98%86%20PLAY"),
         ("rakuma", "Rakuma (Japan)", "https://fril.jp/s?query=%E3%82%B9%E3%82%BF%E3%83%BC%20PLAY"),
         ("cardrush", "Card Rush (Japan)", "https://www.cardrush-pokemon.jp/product-list?keyword=PLAY"),
         ("buyee", "Yahoo! Auctions Japan (read through Buyee)", "https://buyee.jp/item/search/query/%E3%82%B7%E3%83%A3%E3%83%AF%E3%83%BC%E3%82%BA%E2%98%86?translationType=98"),
         ("magi", "Magi (Japan)", "https://magi.camp/items/search?forms_search_items%5Bkeyword%5D=PLAY%20%E2%98%86"),
         ("hareruya2", "Hareruya2 (Japan, card shop)", "https://www.hareruya2.com/search?q=%E2%98%86+PCG"),
         ("paypay", "PayPay Flea Market (Japan, read through Buyee)", "https://buyee.jp/paypayfleamarket/search?keyword=%E3%82%B4%E3%83%BC%E3%83%AB%E3%83%89%E3%82%B9%E3%82%BF%E3%83%BC"),
         ("yshop", "Yahoo! Shopping Japan (small shops, read through Buyee)", "https://buyee.jp/item/search/jdirectitems/shopping?query=%E3%82%B4%E3%83%BC%E3%83%AB%E3%83%89%E3%82%B9%E3%82%BF%E3%83%BC"),
         ("rakuten", "Rakuten Ichiba (Japan, card shops)", "https://search.rakuten.co.jp/search/mall/%E3%83%9D%E3%82%B1%E3%83%A2%E3%83%B3%E3%82%AB%E3%83%BC%E3%83%89+%E3%82%B4%E3%83%BC%E3%83%AB%E3%83%89%E3%82%B9%E3%82%BF%E3%83%BC/"),
         ("wallapop", "Wallapop (Spain)", "https://es.wallapop.com/search?keywords=gold%20star%20pokemon&order_by=newest"),
         ("vinted", "Vinted (Spain)", "https://www.vinted.es/catalog?search_text=gold%20star%20pokemon&order=newest_first")]
src = []
for k, name, url in SITES:
    planned = [p for p in pages if p["site"] == k]
    files = [load(P("browser", "pages", f"{p['i']:03d}.json")) for p in planned]
    got = [f for f in files if f is not None]
    src.append({"id": k, "site": name, "read_automatically": "Yes", "pages_planned": len(planned), "pages_read": sum(1 for f in got if not f.get("blocked")),
                "pages_refused": sum(1 for f in got if f.get("blocked")), "listings_now": sum(1 for r in shown if r["site_name"] == SITE_NAME.get(k)),
                "search_link": url, "note": ""})
for k, name, url, why in [("yahoo", "Yahoo! Auctions Japan (direct)", "https://auctions.yahoo.co.jp/search/search?p=%E3%82%B7%E3%83%A3%E3%83%AF%E3%83%BC%E3%82%BA%E2%98%86", "Not available from the European Union since April 2022 (Yahoo Japan's own decision); read through Buyee instead (row above)"),
                          ("cardmarket", "Cardmarket", "https://www.cardmarket.com/es/Pokemon/Products/Search?searchString=star+play", "Security check blocks automated reading (15 October 2026); open it yourself"),
                          ("surugaya", "Suruga-ya (Japan)", "https://www.suruga-ya.jp/search?category=&search_word=%E3%82%B4%E3%83%BC%E3%83%AB%E3%83%89%E3%82%B9%E3%82%BF%E3%83%BC", "Security check blocks automated reading (21 October 2026); open it yourself"),
                          ("yuyutei", "Yuyu-tei (Japan, card shop)", "https://yuyu-tei.jp/sell/poc/s/search?search_word=%E2%98%86", "Checked 21 October 2026: it stocks only the 2021 25th Anniversary reprints, not the Gold Stars of 2004 to 2007, so it is not read"),
                          ("facebook", "Facebook Marketplace (Madrid)", "https://www.facebook.com/marketplace/madrid/search?query=gold%20star%20pokemon", "Needs signing in; open it yourself")]:
    src.append({"id": k, "site": name, "read_automatically": "No", "pages_planned": 0, "pages_read": 0, "pages_refused": 0, "listings_now": None, "search_link": url, "note": why})
save(P("out", "sources.json"), src)
