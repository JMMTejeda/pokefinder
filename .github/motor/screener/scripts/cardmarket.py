"""Cardmarket in PokéFinder, from Cardmarket's own public files (owner, 28 October 2026: "Spanish Entei Gold Stars are on Cardmarket;
they must show in the app, phone and computer, without Claude and without tokens").

Cardmarket's pages turn automated browsers away (Cloudflare) and its API is closed to private users, so the app never opens them.
Cardmarket publishes, for anyone, a daily price guide and its product lists on its download server (no account, no token):
  priceGuide/price_guide_6.json        every Pokémon product: lowest offer today, trend, averages (all languages and conditions)
  productList/products_singles_6.json  every single card: name, edition (idExpansion), when Cardmarket added it
  productList/products_nonsingles_6.json  boosters and boxes, whose names give each edition's name
They are downloaded once a day into data/cardmarket/. A search gets one result per matching Cardmarket product ("Entei Gold Star ·
EX Unseen Forces — from 100 €"), with the card's picture (pokemontcg.io, English prints) and a link to its offers on Cardmarket.
Individual offers (each seller, their photos) are only on Cardmarket's own pages: the link opens them in the owner's browser.
For a Gold Star, editions Cardmarket created in 2021 are the Celebrations / 25th Anniversary reprints and are left out.
  python cardmarket.py "<search>"     prints what a search would show"""
import json, os, re, sys, time, urllib.parse, urllib.request
from common import P, load, save

BASE = "https://downloads.s3.cardmarket.com/productCatalog/"
FILES = {"guide": "priceGuide/price_guide_6.json", "singles": "productList/products_singles_6.json",
         "sealed": "productList/products_nonsingles_6.json"}
DIR = P("cardmarket")
_DATA = None

def fetch(max_age_h=20):
    """The three files, downloaded again when older than a day (a failed download keeps yesterday's)."""
    os.makedirs(DIR, exist_ok=True)
    for k, rel in FILES.items():
        f = os.path.join(DIR, os.path.basename(rel))
        if os.path.exists(f) and time.time() - os.path.getmtime(f) < max_age_h * 3600: continue
        try:
            body = urllib.request.urlopen(urllib.request.Request(BASE + rel, headers={"user-agent": "PokeFinder"}), timeout=120).read()
            json.loads(body)   # only a complete file replaces the old one
            open(f, "wb").write(body)
        except Exception as e:
            print(f"Cardmarket {k} file not updated ({type(e).__name__})", file=sys.stderr)

def data():
    global _DATA
    if _DATA is None:
        fetch()
        rd = lambda rel: load(os.path.join(DIR, os.path.basename(rel)), {}) or {}
        g = rd(FILES["guide"]); singles = rd(FILES["singles"]).get("products", []); sealed = rd(FILES["sealed"]).get("products", [])
        guide = {x["idProduct"]: x for x in g.get("priceGuides", [])}
        # an edition's name: its booster's or box's name without "Booster", "Booster Box", "Theme Deck"...
        names = {}
        for p in sealed:
            n = re.sub(r"\s*(?:[:\-–]\s*)?(?:Booster(?:\s*(?:Box|Display|Bundle|Pack))?|Theme Deck.*|Elite Trainer Box.*|Collection.*|Blister.*|Tin.*|Starter Set.*).*$", "", p["name"]).strip()
            if n and (p["idExpansion"] not in names or len(n) < len(names[p["idExpansion"]])): names[p["idExpansion"]] = n
        # when Cardmarket created each edition: its singles' earliest date ("0000" = before Cardmarket kept dates: an old set)
        year = {}
        for p in singles:
            y = (p.get("dateAdded") or "0000")[:4]
            year[p["idExpansion"]] = min(year.get(p["idExpansion"], "9999"), y)
        _DATA = {"guide": guide, "singles": singles, "names": names, "year": year, "date": (g.get("createdAt") or "")[:10]}
    return _DATA

def _num(v): return None if v in (None, 0, 0.0) else float(v)

def images(poke):
    """pokemontcg.io pictures of a Pokémon's cards, keyed by (card name, set name), for the English prints."""
    cache = os.path.join(DIR, "images.json")   # kept: the free API sometimes does not answer
    saved = load(cache, {}) or {}
    if poke in saved: return {tuple(k.split("\t")): v for k, v in saved[poke].items()}
    out = {}
    url = "https://api.pokemontcg.io/v2/cards?" + urllib.parse.urlencode({"q": f'name:"{poke}*"', "select": "name,set,images", "pageSize": 250})
    for _ in range(4):
        try:
            for c in json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"user-agent": "PokeFinder"}), timeout=40)).get("data", []):
                out[(c["name"], c["set"]["name"])] = (c.get("images") or {}).get("small")
            saved[poke] = {"\t".join(k): v for k, v in out.items()}; save(cache, saved)
            break
        except Exception:
            time.sleep(6)
    return out

def products(poke, goldstar=False, words=()):
    """Cardmarket's single cards of a Pokémon (Gold Stars only when goldstar), with their edition and today's prices."""
    d = data(); out = []
    name_re = re.compile(rf"^{re.escape(poke)}(?![a-z])", re.I)
    for p in d["singles"]:
        n = re.sub(r"\s*\[.*\]$", "", p["name"])   # the attacks in brackets are not the card's name ("[Star Blaze | ...]")
        if not name_re.search(n): continue
        if goldstar and not re.search(r"gold\s*star|(?<!v)\bstar\b|☆|★", n, re.I): continue
        if any(not re.search(re.escape(w), n, re.I) for w in words): continue
        if goldstar and d["year"].get(p["idExpansion"]) == "2021": continue   # Celebrations / 25th Anniversary reprints
        # World Championship Decks: reprints with a different back, not the card
        if re.match(r"WCD\b|World Championship", d["names"].get(p["idExpansion"], ""), re.I): continue
        g = d["guide"].get(p["idProduct"]) or {}
        low, trend, avg30 = _num(g.get("low")), _num(g.get("trend")), _num(g.get("avg30"))
        if low is None and trend is None: continue   # nothing for sale and no recent sales
        out.append({"id": p["idProduct"], "name": n, "edition": d["names"].get(p["idExpansion"], ""),
                    "year": d["year"].get(p["idExpansion"], "0000"), "low": low, "trend": trend, "avg30": avg30, "date": d["date"],
                    # Cardmarket's "holo" columns are the reverse holo copies (the stamped ones in sets like EX Power Keepers)
                    "low_rh": _num(g.get("low-holo")), "trend_rh": _num(g.get("trend-holo")), "avg30_rh": _num(g.get("avg30-holo"))})
    return out

def card_listings(spec):
    """The Cardmarket product of the one card a search names (carta.py): same name, edition named after its set. A stamped or reverse
    search gets the reverse holo prices."""
    card = spec["card"]; poke = (spec.get("poke") or [card["name"]])[0]
    setn = card["set"].lower()
    rev = card.get("stamped") or card.get("reverse")
    out = []
    for pr in products(poke):
        if pr["name"].lower() != card["name"].lower() or setn not in pr["edition"].lower(): continue
        if rev:
            if pr["low_rh"] is None and pr["trend_rh"] is None: continue
            pr = {**pr, "low": pr["low_rh"], "trend": pr["trend_rh"], "avg30": pr["avg30_rh"], "name": pr["name"] + " (reverse holo)"}
        url = product_url(card["id"])
        out.append(listing(pr, poke, card.get("image"), link(pr, url, spec.get("lang")), spec.get("lang") if url else None))
    return out

# Cardmarket's language filter on a product page (?language=N): the offers in that language only
CM_LANG = {"en": 1, "fr": 2, "de": 3, "es": 4, "it": 5, "ja": 7}

def product_url(card_id):
    """The card's own Cardmarket page, as pokemontcg.io links it (its redirect is read, Cardmarket itself is not opened). Kept."""
    import http.client
    cache = os.path.join(DIR, "urls.json"); saved = load(cache, {}) or {}
    if card_id in saved: return saved[card_id]
    try:
        c = http.client.HTTPSConnection("prices.pokemontcg.io", timeout=30)
        c.request("HEAD", f"/cardmarket/{card_id}", headers={"user-agent": "PokeFinder"})
        loc = c.getresponse().getheader("Location") or ""
    except Exception:
        return None
    url = loc.split("?")[0] if "cardmarket.com" in loc else None
    if url: saved[card_id] = url; save(cache, saved)
    return url

def link(prod, url=None, lang=None):
    """The offers of that card on Cardmarket, in the search's language when it named one; else Cardmarket's search for the card."""
    if url: return url + (f"?language={CM_LANG[lang]}" if lang in CM_LANG else "")
    return "https://www.cardmarket.com/es/Pokemon/Products/Search?searchString=" + urllib.parse.quote(prod["name"])

def listings(spec):
    """App listings for a typed search: one per Cardmarket product (site "cardmarket")."""
    poke = spec.get("poke") or []
    if not poke: return []
    out = []
    for pk in poke[:2]:
        imgs = images(pk)
        for pr in products(pk, goldstar=bool(spec.get("goldstar"))):
            # Cardmarket keeps Japanese prints in their own editions, added from 2023 on: a Spanish search does not want those,
            # a Japanese one wants only those
            lang = spec.get("lang")
            if lang and (lang == "ja") != (pr["year"] >= "2023"): continue
            img = next((u for (cn, sn), u in imgs.items() if u and pr["edition"] and sn.lower() in pr["edition"].lower()
                        and bool(re.search(r"★|☆|star", cn, re.I)) == bool(re.search(r"star|☆|★", pr["name"], re.I))), None)
            m = re.search(r"images\.pokemontcg\.io/([^/]+)/([^/.]+)\.", img or "")
            url = product_url(f"{m.group(1)}-{m.group(2)}") if m else None
            out.append(listing(pr, pk, img, link(pr, url, spec.get("lang")), spec.get("lang") if url else None))
    return out

LANG_NAME = {"es": "español", "en": "inglés", "fr": "francés", "de": "alemán", "it": "italiano", "ja": "japonés"}

def listing(pr, poke, img, url=None, lang=None):
    """One Cardmarket product as an app listing (site "cardmarket"): price = the cheapest offer today, trend in the text."""
    eur = lambda v: f"{v:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    return {"id": f'cardmarket:{pr["id"]}', "site": "cardmarket", "site_name": "Cardmarket", "url": url or link(pr), "cm_lang": LANG_NAME.get(lang),
            "title": pr["name"] + (f' · {pr["edition"]}' if pr["edition"] else ""), "price_eur": pr["low"] if pr["low"] is not None else pr["trend"],
            "price_text": "desde " + (eur(pr["low"]) if pr["low"] is not None else "—") + (f' · tendencia {eur(pr["trend"])}' if pr["trend"] else ""),
            "sale": "buy", "auction_info": None, "region": "EU", "country": None, "grader": None, "grade": None,
            "pokemon": [poke], "card": None, "number": None, "edition": None, "status": "on sale", "image": img,
            "first_seen": pr["date"], "cardmarket": True,
            "note": f'Cardmarket ({pr["date"]}): la oferta más barata de hoy (cualquier idioma y estado) y la tendencia. '
                    "Las ofertas una a una, con sus fotos, están en Cardmarket."}

def guide(spec):
    """The summary box under the search's title (same data as the listings)."""
    out = []
    for l in listings(spec):
        out.append({"name": l["title"], "set": "", "number": "", "url": l["url"], "low": l["price_eur"], "trend": None, "avg30": None,
                    "updated": data()["date"]})
    return out

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    import motor
    for l in listings(motor.plan_spec(" ".join(sys.argv[1:]))): print(l["price_text"], "|", l["title"], "|", l["image"])
