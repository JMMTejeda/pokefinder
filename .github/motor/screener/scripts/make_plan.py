"""Plan this run's pages: data/browser/pages.json = [{"i", "site", "label", "card_key", "url", "js"}].

Order: the five Play promos (022 to 026/PLAY) on every site first, then every other Japanese Gold Star, then broad searches on the
European sites. eBay pages are spread out so the 2 to 3 minute gap between eBay search pages is mostly spent on other sites.
Each "js" is browser/readers/_prelude.js + <site>.js + _tail.js plus a filter (KEEP) so only titles naming a tracked Pokémon come back.
SNKRDUNK: once a card's product page is known (data/state/snkr_products.json, learnt by snkr_learn.py) the run opens its
"used" list (every copy for sale); until then it opens SNKRDUNK's search.
Usage: python make_plan.py [quick | three | others]   (three = only Vaporeon 022, Jolteon 023, Flareon 024 /PLAY)   (quick = the five Play promos only)
       (others = every Gold Star except the five Play promos; owner, 22 October 2026)"""
import json, os, re, sys
from urllib.parse import quote
from common import P, load, save, SCREENER

QUICK = len(sys.argv) > 1 and sys.argv[1] in ("quick", "three")
# eBay is read through the official API (ebay_api.py) when the owner's keys are there; --browser-ebay plans the old eBay pages instead
EBAY_API = os.path.exists(os.path.join(os.path.dirname(SCREENER), ".secrets", "ebay_api.json")) and "--browser-ebay" not in sys.argv
THREE = len(sys.argv) > 1 and sys.argv[1] == "three"   # Vaporeon, Jolteon and Flareon Play promos only (owner, 18 October 2026)
OTHERS = len(sys.argv) > 1 and sys.argv[1] == "others"   # every Gold Star except the Play promos (owner, 22 October 2026)
CARDS = load(os.path.join(SCREENER, "cards.json"))["cards"]
if OTHERS: CARDS = [c for c in CARDS if not c["priority"]]
# an others run searches each card with every wording sellers use, as the Play promos are (owner, 22 October 2026: many were missed);
# a full run too (owner, 26 October 2026: "run every Gold Star again, up to date, on more markets")
DEEP = not QUICK
LIGHT = "--light" in sys.argv   # quick refresh (owner, 1 November 2026): eBay (API), Mercari, SNKRDUNK and Magi, one wording each
FULL = not LIGHT                # full refresh: every market, plus Mandarake, Yuyu-tei, Card Labo and the Elite Fourum forum
if LIGHT: DEEP = False
if THREE:
    for c in CARDS:
        if c["key"] in ("espeon_play", "umbreon_play"): c["priority"] = False
snkr = load(P("state", "snkr_products.json"), {})
RD = os.path.join(SCREENER, "browser", "readers")
def part(n): return open(os.path.join(RD, n + ".js"), encoding="utf-8").read().strip()

def keep_regex(cards):
    names = sorted({n for c in cards for n in c["names"]}, key=len, reverse=True)
    return "|".join(re.escape(n) for n in names)

# a kept row must also carry a Gold Star sign (goldstar.py then applies the strict rules)
STAR = r"☆|ゴールドスター|ゴールド☆|gold\s*star|goldstar|\bstar\b|(?<![ァ-ヴー])スター(?![ァ-ヴー])|/\s*play|\bplay\s*promo|プレイヤーズ|estrella|[eé]toile"

def js(site, keep, cards=()):
    """The page script for one site: the shared start, that site's reader, and the filters (a tracked Pokémon's name and a Gold Star
    sign: ☆, 'gold star', スター, PLAY, or the card's own number)."""
    star = STAR + "".join("|" + re.escape(c["number"]).replace("/", r"\s*/\s*") for c in cards)
    return (part("_prelude") + "\n" + part(site) + "\nconst KEEP=" + json.dumps(keep, ensure_ascii=False) + ",STAR="
            + json.dumps(star, ensure_ascii=False) + ";" + part("_tail"))

def q(s): return quote(s, safe="")
pages = []
def add(site, label, url, cards, card_key=None):
    pages.append({"site": site, "label": label, "card_key": card_key, "url": url, "js": js(site, keep_regex(cards), cards)})

def light_pages(c):
    ja = c["names"][0]
    t = f"{ja} {c['number'].split('/')[0]}/PLAY" if c["key"].endswith("_play") else f"{ja} スター"
    add("mercari", f"Mercari: {t}", f"https://jp.mercari.com/search?keyword={q(t)}&status=on_sale", [c], c["key"])
    add("magi", f"Magi: {ja}☆", f"https://magi.camp/items/search?forms_search_items%5Bkeyword%5D={q(ja + '☆')}", [c], c["key"])
    if c["key"] in snkr:
        for pid in snkr[c["key"]]:
            add("snkrdunk", f"SNKRDUNK copies for sale: {c['name_en']} ({pid})", f"https://snkrdunk.com/apparels/{pid}/used", [c], c["key"])
    else:
        add("snkrdunk", f"SNKRDUNK search: {ja} {c['number']}", f"https://snkrdunk.com/search?keywords={q(ja + '☆ ' + c['number'])}", [c], c["key"])

def full_pages(c):
    """The markets only a full search reads (1 November 2026). Mandarake (ships to Spain itself; stores in Ikebukuro, Nakano and
    Akihabara) and Card Labo search by name; Yuyu-tei lists cards by number; the forum is searched in English."""
    ja, en = c["names"][0], c["pokemon"].lower()
    for t in (f"{ja} スター", f"{ja}☆ {c['number'].split('/')[0]}"):
        add("mandarake", f"Mandarake: {t}", f"https://order.mandarake.co.jp/order/listPage/list?keyword={q(t)}", [c], c["key"])
    add("yuyutei", f"Yuyu-tei: {ja}", f"https://yuyu-tei.jp/sell/poc/s/search?search_word={q(ja)}", [c], c["key"])
    add("clabo", f"Card Labo: {ja}☆", f"https://www.c-labo-online.jp/product-list?keyword={q(ja + '☆')}", [c], c["key"])
    add("elitefourum", f"Elite Fourum: {en} gold star", "https://www.elitefourum.com/search?q=" + q(f"{en} gold star #buy-section order:latest"), [c], c["key"])
    # more markets (owner, 1 November 2026): Yahoo! Auctions through Jauce (ships to Spain), and shops whose search answers in plain
    # data, 10 products a time: Cherry Collectables and Monster Mart (Australia), Pokemon Plug (US), Japan TCG
    for t in (f"{ja} ☆", f"{ja} ゴールドスター"):
        add("jauce", f"Yahoo! Auctions (Jauce): {t}", "https://www.jauce.com/search/" + q(t), [c], c["key"])
    for site, host in (("cherry", "www.cherrycollectables.com.au"), ("monstermart", "www.monstermart.com.au"), ("pokemonplug", "pokemonplug.com"),
                       ("japantcg", "japantcg.com")):
        t = f"{c['pokemon']} star" if site == "japantcg" else f"{c['pokemon']} gold star"
        add(site, f"{site}: {t}", f"https://{host}/search/suggest.json?q={q(t)}&resources%5Btype%5D=product&resources%5Blimit%5D=10", [c], c["key"])

def jp_pages(c):
    """Japanese sites. Play promos get several wordings (owner, 15 October 2026: Jolteon listings were being missed), because sellers
    write the same card as サンダース☆, サンダース スター, サンダース PLAY, 023/PLAY or プレイヤーズ."""
    ja, num = c["names"][0], c["number"].split("/")[0]
    play = c["key"].endswith("_play")
    mer = [f"{ja} PLAY", f"{ja} スター プロモ", f"{ja} スター", f"{ja} {num}/PLAY"] if play else [f"{ja} スター {c['number']}"] + ([f"{ja}☆", f"{ja} スター", f"{ja} ゴールドスター"] if DEEP else [])
    for t in mer:
        # relevance order for the short wordings (newest-first buries an old listing under hundreds of modern cards)
        sort = "" if t == f"{ja} スター" else "&sort=created_time&order=desc"
        add("mercari", f"Mercari: {t}", f"https://jp.mercari.com/search?keyword={q(t)}&status=on_sale{sort}", [c], c["key"])
    for t in ([f"{ja} スター プロモ", f"{ja} PLAY"] if play else [f"{ja} スター"] + ([f"{ja}☆"] if DEEP else [])):
        add("rakuma", f"Rakuma: {t}", f"https://fril.jp/s?query={q(t)}&order=desc&sort=created_at&transaction=selling", [c], c["key"])
    for t in ([f"{ja}☆", f"{ja} スター PLAY"] if play else [f"{ja}☆"] + ([f"{ja} スター"] if DEEP else [])):
        add("buyee", f"Yahoo! Auctions via Buyee: {t}", f"https://buyee.jp/item/search/query/{q(t)}?translationType=98", [c], c["key"])
    for t in [f"{ja}☆"] + ([f"{ja} ゴールドスター", f"{ja} スター {c['number']}"] if DEEP and not play else []):
        add("magi", f"Magi: {t}", f"https://magi.camp/items/search?forms_search_items%5Bkeyword%5D={q(t)}", [c], c["key"])
    add("cardrush", f"Card Rush: {ja} {c['number']}", f"https://www.cardrush-pokemon.jp/product-list?keyword={q(ja + ' ' + num)}", [c], c["key"])
    # Hareruya2 (added 21 October 2026): a Japanese card shop that stocks Players Club era cards, graded copies included. Its search
    # by name ranks modern cards first; by card number (022/PLAY, 066/082) it finds the Gold Star's own product page.
    add("hareruya2", f"Hareruya2: {c['number']}", f"https://www.hareruya2.com/search?q={q(c['number'])}", [c], c["key"])
    # added 26 October 2026 (owner: "more markets, also small Japanese shops that are not on every site"): PayPay Flea Market and
    # Yahoo! Shopping (both closed to European visitors, read through Buyee) and Rakuten Ichiba, where hundreds of card shops sell
    for t in ([f"{ja} PLAY", f"{ja}☆ プロモ"] if play else [f"{ja} ゴールドスター", f"{ja}☆"]):
        add("paypay", f"PayPay Flea Market via Buyee: {t}", f"https://buyee.jp/paypayfleamarket/search?keyword={q(t)}", [c], c["key"])
    t = f"{ja} PLAY" if play else f"{ja} ゴールドスター"
    add("yshop", f"Yahoo! Shopping via Buyee: {t}", f"https://buyee.jp/item/search/jdirectitems/shopping?query={q(t)}", [c], c["key"])
    t = f"{ja} {num}/PLAY" if play else f"{ja} {c['number']}"
    add("rakuten", f"Rakuten Ichiba: {t}", "https://search.rakuten.co.jp/search/mall/" + q(t).replace("%20", "+") + "/", [c], c["key"])
    if c["key"] in snkr:
        for pid in snkr[c["key"]]:
            add("snkrdunk", f"SNKRDUNK copies for sale: {c['name_en']} ({pid})", f"https://snkrdunk.com/apparels/{pid}/used", [c], c["key"])
    else:
        add("snkrdunk", f"SNKRDUNK search: {ja} {c['number']}", f"https://snkrdunk.com/search?keywords={q(ja + '☆ ' + c['number'])}", [c], c["key"])

def gempire(c):
    """GempireCards (owner, 15 October 2026): eBay worldwide, including US sellers that ebay.es hides because they do not ship to Spain.
    It shows at most 50 results per search, so each card gets narrow searches."""
    en = c["pokemon"].lower()
    terms = [f"{en} play promo", f"{en} gold star"] if c["key"].endswith("_play") else [f"{en} gold star japanese"] + (
        [f"{en} {c['number']}", f"{en} gold star psa japanese", f"{en} star japanese"] if DEEP and not EBAY_API else [])
    # with the eBay API (eBay worldwide), Gempire is only needed for the auction houses (ALT, Fanatics Collect, Goldin): one search per card
    for t in terms:
        add("gempire", f"Gempire (eBay worldwide): {t}", "https://www.gempirecards.com/listings?q=" + quote(t).replace("%20", "+"), [c], c["key"])

ebay = []
PRI = [c for c in CARDS if c["priority"]]
for c in PRI:
    en = c["pokemon"].lower()
    # newest first (new listings) and best match (older listings that newest-first pushes past the first 240)
    ebay.append(("ebay", f"eBay: {c['name_en']} Play promo (newest)", f"https://www.ebay.es/sch/i.html?_nkw={q(en + ' (play,players,☆) (star,promo,psa,japanese)')}&_sop=10&_ipg=240&LH_PrefLoc=2", [c], c["key"]))
    ebay.append(("ebay", f"eBay: {c['name_en']} gold star (best match)", f"https://www.ebay.es/sch/i.html?_nkw={q(en + ' (star,☆,players)')}&_ipg=240&LH_PrefLoc=2", [c], c["key"]))
# the Japanese names on eBay (Japanese sellers sometimes list in Japanese only)
if PRI: ebay.append(("ebay", "eBay: Play promos in Japanese", "https://www.ebay.es/sch/i.html?_nkw=" + q("(" + ",".join(c["names"][0] for c in PRI) + ") (☆,スター,play)") + "&_ipg=240&LH_PrefLoc=2", PRI, None))
if not QUICK:
    ebay.append(("ebay", "eBay: Japanese Gold Star (newest)", "https://www.ebay.es/sch/i.html?_nkw=" + q("(gold star,goldstar,☆) (japanese,japan,jpn,japonesa)") + "&_sop=10&_ipg=240&LH_PrefLoc=2", CARDS, None))
    ebay.append(("ebay", "eBay: Japanese ☆ graded (newest)", "https://www.ebay.es/sch/i.html?_nkw=" + q("pokemon ☆ japanese (psa,bgs,1ed,unlimited)") + "&_sop=10&_ipg=240&LH_PrefLoc=2", CARDS, None))
if DEEP:   # one eBay search per card: the two broad searches stop at 240 results each
    for c in CARDS:
        en = c["pokemon"].lower()
        ebay.append(("ebay", f"eBay: {c['name_en']} Japanese", "https://www.ebay.es/sch/i.html?_nkw=" + q(f"{en} (gold star,goldstar,☆,star,{c['number']}) (japanese,japan,jpn,japonesa,pcg)") + "&_ipg=240&LH_PrefLoc=2", [c], c["key"]))

order = ([] if OTHERS else [c for c in CARDS if c["priority"]]) + ([] if QUICK else [c for c in CARDS if not c["priority"]])
if EBAY_API: ebay = []   # read by ebay_api.py instead (no pauses, eBay worldwide)
if LIGHT:
    for c in order: light_pages(c)
else:
    for c in order: gempire(c)
    for c in order: jp_pages(c)
    pages.append({"site": "mandarake", "label": "Mandarake: entrada a la tienda", "card_key": None, "url": "https://order.mandarake.co.jp/order/",
                  "js": "(async()=>JSON.stringify({blocked:false,n:0,rows:[]}))()"})   # its search needs one visit to the shop first (a cookie)
    for c in order: full_pages(c)
eu = [("wallapop", "Wallapop: gold star pokemon", "https://es.wallapop.com/search?keywords=" + q("gold star pokemon") + "&order_by=newest"),
      ("wallapop", "Wallapop: pokemon estrella japonesa", "https://es.wallapop.com/search?keywords=" + q("pokemon star japonesa") + "&order_by=newest"),
      ("vinted", "Vinted: gold star pokemon", "https://www.vinted.es/catalog?search_text=" + q("gold star pokemon") + "&order=newest_first"),
      ("vinted", "Vinted: pokemon star japanese", "https://www.vinted.es/catalog?search_text=" + q("pokemon star japanese") + "&order=newest_first")]
if DEEP:
    for t in ("goldstar pokemon", "gold star japonesa", "pokemon ☆ japonesa", "estrella dorada pokemon", "pokemon gold star psa"):
        eu.append(("wallapop", f"Wallapop: {t}", "https://es.wallapop.com/search?keywords=" + q(t) + "&order_by=newest"))
        eu.append(("vinted", f"Vinted: {t}", "https://www.vinted.es/catalog?search_text=" + q(t) + "&order=newest_first"))
if not QUICK:   # broad searches on the new Japanese markets (26 October 2026): sellers who do not name the Pokémon the usual way
    for s, label, url in (("paypay", "PayPay Flea Market via Buyee: ゴールドスター ポケモンカード", "https://buyee.jp/paypayfleamarket/search?keyword=" + q("ゴールドスター ポケモンカード")),
                          ("paypay", "PayPay Flea Market via Buyee: ポケモンカード ☆ 1ED", "https://buyee.jp/paypayfleamarket/search?keyword=" + q("ポケモンカード ☆ 1ED")),
                          ("yshop", "Yahoo! Shopping via Buyee: ゴールドスター ポケモンカード", "https://buyee.jp/item/search/jdirectitems/shopping?query=" + q("ゴールドスター ポケモンカード")),
                          ("rakuten", "Rakuten Ichiba: ポケモンカード ゴールドスター", "https://search.rakuten.co.jp/search/mall/" + q("ポケモンカード ゴールドスター").replace("%20", "+") + "/")):
        eu.append((s, label, url))
if QUICK:
    eu = [("wallapop", "Wallapop: gold star play pokemon", "https://es.wallapop.com/search?keywords=" + q("gold star play pokemon") + "&order_by=newest"),
          ("vinted", "Vinted: gold star pokemon", "https://www.vinted.es/catalog?search_text=" + q("gold star pokemon") + "&order=newest_first")]
if LIGHT: eu = []   # a quick refresh skips the broad European and Japanese searches
for s, label, url in eu: pages.append({"site": s, "label": label, "card_key": None, "url": url, "js": js(s, keep_regex(CARDS), CARDS)})

# spread the eBay pages through the plan (other sites are read in between; pause.py keeps eBay pages 2 minutes apart)
step = max(5, len(pages) // max(1, len(ebay)))
for n, e in enumerate(ebay):
    pos = min(len(pages), n * (step + 1))
    pages.insert(pos, {"site": e[0], "label": e[1], "card_key": e[4], "url": e[2], "js": js("ebay", keep_regex(e[3]), e[3])})
for i, p in enumerate(pages):
    p["i"] = i
    # Mercari only draws the results near the screen, so the hidden browser pane needs a tall page; Gempire only loads its results in its phone layout (18 October 2026)
    p["viewport"] = "normal" if p["site"] == "gempire" else "tall"
os.makedirs(P("browser", "pages"), exist_ok=True)
save(P("browser", "pages.json"), pages)
save(P("browser", "plan_mode.json"), {"mode": "others" if OTHERS else "three" if THREE else "quick" if QUICK else "full"})
from collections import Counter
print(len(pages), "pages planned" + (" (quick: Play promos only)" if QUICK else " (others: Play promos left out)" if OTHERS else ""), dict(Counter(p["site"] for p in pages)))
