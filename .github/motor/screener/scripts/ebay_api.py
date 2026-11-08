"""eBay through the official Browse API (owner, 23 October 2026: "use my eBay developer keys so the searches are much faster").

Replaces the eBay pages read in the browser: no 40-second pauses, eBay worldwide (several eBay sites, so sellers that do not ship
to Spain are found too), and the API says directly whether a listing is an auction (bids, end time) or Buy It Now, and what
delivery to Spain costs when the seller ships here.

Keys: ROOT/.secrets/ebay_api.json (app_id = Client ID, cert_id = Client Secret). Local only: never print, upload or publish them.
The access token (2 hours) is cached in data/state/ebay_token.json.
Output: one result per card, appended to data/browser/pages.json as {"site": "ebay", "api": true, ...} with its rows in
data/browser/pages/<i>.json, in the same shape the browser readers return, so goldstar.py reads them like any other page.
Usage: python ebay_api.py [quick | others]   (same card choice as make_plan.py: quick = the five Play promos, others = the rest)"""
import base64, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from common import P, load, save, SCREENER

ROOT = os.path.dirname(SCREENER)
MODE = sys.argv[1] if len(sys.argv) > 1 else "full"
KEYS = load(os.path.join(ROOT, ".secrets", "ebay_api.json"))
# owner, 26 October 2026 ("search more markets: Canada, Australia..."): every eBay site the Browse API serves; each one tested
# with "gold star pokemon japanese" brought listings the first five did not (Canada 16, Netherlands 92, Belgium 102, Hong Kong 44...)
MARKETS = ["EBAY_US", "EBAY_GB", "EBAY_DE", "EBAY_ES", "EBAY_AU", "EBAY_CA", "EBAY_FR", "EBAY_IT", "EBAY_NL", "EBAY_IE", "EBAY_AT",
           "EBAY_CH", "EBAY_BE", "EBAY_PL", "EBAY_HK", "EBAY_SG"]
API = "https://api.ebay.com/buy/browse/v1/item_summary/search?"
SYM = {"USD": "USD ", "EUR": "EUR ", "GBP": "GBP ", "AUD": "AUD ", "CAD": "CAD ", "JPY": "JPY ", "CHF": "CHF "}

def token():
    t = load(P("state", "ebay_token.json"), {})
    if t.get("access_token") and t.get("until", 0) > time.time() + 300: return t["access_token"]
    auth = base64.b64encode(f"{KEYS['app_id']}:{KEYS['cert_id']}".encode()).decode()
    req = urllib.request.Request("https://api.ebay.com/identity/v1/oauth2/token", headers={"Authorization": "Basic " + auth, "Content-Type": "application/x-www-form-urlencoded"},
                                 data=urllib.parse.urlencode({"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"}).encode())
    d = json.load(urllib.request.urlopen(req, timeout=30))
    save(P("state", "ebay_token.json"), {"access_token": d["access_token"], "until": time.time() + int(d["expires_in"])})
    return d["access_token"]

def search(q, market, tok, max_items=1000, origen="manual"):
    """Every listing eBay returns for q on one eBay site (200 per call), seen from Spain (shipping costs to Spain).
    origen: what asked for it ("manual" = the owner's searches, "foto" = the daily snapshot); every call is counted in ebay_cuota.py and an automatic origin stops at the reserve."""
    import ebay_cuota as Q
    out, offset = [], 0
    while offset < max_items:
        url = API + urllib.parse.urlencode({"q": q, "limit": 200, "offset": offset})
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok, "X-EBAY-C-MARKETPLACE-ID": market,
                                                   "X-EBAY-C-ENDUSERCTX": "contextualLocation=country%3DES"})
        for attempt in range(3):
            if not Q.permitido(origen): return out, f"Presupuesto automático del día agotado ({origen}): quedan reservadas {Q.RESERVA_MANUAL} llamadas para tus búsquedas"
            Q.registrar(origen)
            try:
                d = json.load(urllib.request.urlopen(req, timeout=40)); break
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503) and attempt < 2: time.sleep(5 * (attempt + 1)); continue
                return out, f"HTTP {e.code} on {market}: {q}"
            except Exception as e:
                if attempt < 2: time.sleep(5); continue
                return out, f"{type(e).__name__} on {market}: {q}"
        items = d.get("itemSummaries", [])
        out += items
        if len(items) < 200 or offset + 200 >= d.get("total", 0): break
        offset += 200
    return out, None

def money(p):
    return (SYM.get(p["currency"], p["currency"] + " ") + p["value"]) if p and p.get("value") else ""

def row(it):
    iid = it["itemId"].split("|")[1] if "|" in it["itemId"] else it.get("legacyItemId") or it["itemId"]
    opts = it.get("buyingOptions") or []
    auction = "AUCTION" in opts
    price = it.get("currentBidPrice") if auction and it.get("currentBidPrice") else it.get("price")
    bits = []
    if auction:
        bits.append(f"{it.get('bidCount', 0)} bids")
        if it.get("itemEndDate"): bits.append("ends " + it["itemEndDate"][:16].replace("T", " ") + " UTC")
        if "FIXED_PRICE" in opts and it.get("price"): bits.append("or Buy It Now " + money(it["price"]))
    else:
        bits.append("Buy It Now" + (" or Best Offer" if "BEST_OFFER" in opts else ""))
    loc = (it.get("itemLocation") or {}).get("country")
    if loc: bits.append("Located in " + loc)
    ship = [s for s in it.get("shippingOptions") or [] if s.get("shippingCost")]
    if ship: bits.append("Ships to Spain: " + (money(ship[0]["shippingCost"]) if float(ship[0]["shippingCost"].get("value", 0)) else "free"))
    if it.get("condition"): bits.append(it["condition"])
    if it.get("seller", {}).get("username"): bits.append("seller " + it["seller"]["username"] + (f" ({it['seller'].get('feedbackPercentage')}%)" if it["seller"].get("feedbackPercentage") else ""))
    return {"id": iid, "url": f"https://www.ebay.es/itm/{iid}", "title": it.get("title", ""), "price_text": money(price), "status": "on sale",
            "extra": "eBay API; " + "; ".join(bits), "image": (it.get("image") or {}).get("imageUrl")}

def queries(c):
    en, ja = c["pokemon"].lower(), c["names"][0]
    if c["key"].endswith("_play"):
        return [f"{en} (play,players,☆) (star,promo,psa,japanese)", f"{en} gold star (play,promo,players)", f"{ja} (☆,スター,play)"]
    return [f"{en} gold star japanese", f"{en} (gold star,☆,goldstar) {c['number']}", f"{ja} (☆,スター)"]

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if not KEYS: sys.exit("No eBay keys in .secrets/ebay_api.json")
    CARDS = load(os.path.join(SCREENER, "cards.json"))["cards"]
    if MODE == "quick": CARDS = [c for c in CARDS if c.get("priority")]
    elif MODE == "others": CARDS = [c for c in CARDS if not c.get("priority")]
    jobs = [(c["key"], c["name_en"], q, m) for c in CARDS for q in queries(c) for m in MARKETS]
    if MODE != "quick":
        jobs += [(None, "Japanese Gold Stars (broad)", q, m) for q in ["(gold star,goldstar) (japanese,japan,jpn)", "pokemon ☆ japanese (psa,bgs,cgc,1st,unlimited)"] for m in MARKETS]
    tok = token(); t0 = time.time()
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda j: (j, *search(j[2], j[3], tok)), jobs))
    pages = load(P("browser", "pages.json"), [])
    for p in [p for p in pages if p.get("api")]:   # an earlier pass of this run
        f = P("browser", "pages", f"{p['i']:03d}.json")
        if os.path.exists(f): os.remove(f)
    pages = [p for p in pages if not p.get("api")]
    groups, errors = {}, []
    for (key, name, q, m), items, err in res:
        if err: errors.append(err)
        g = groups.setdefault(key, {"name": name, "rows": {}, "n": 0, "queries": set()})
        g["n"] += len(items); g["queries"].add(q)
        for it in items:
            r = row(it); g["rows"].setdefault(r["id"], r)
    for key, g in groups.items():
        i = len(pages)
        pages.append({"i": i, "site": "ebay", "api": True, "card_key": key, "label": f"eBay API: {g['name']} ({len(MARKETS)} eBay sites)",
                      "url": "https://api.ebay.com/buy/browse/v1/item_summary/search", "viewport": "tall"})
        save(P("browser", "pages", f"{i:03d}.json"), {"site": "api.ebay.com", "blocked": False, "n": g["n"], "rows": list(g["rows"].values()),
                                                       "queries": sorted(g["queries"]), "markets": MARKETS})
    save(P("browser", "pages.json"), pages)
    total = sum(len(g["rows"]) for g in groups.values())
    print(f"eBay API: {len(jobs)} searches on {len(MARKETS)} eBay sites in {time.time() - t0:.0f} s; {total} different listings for {len(groups)} cards"
          + (f"; {len(errors)} searches failed (first: {errors[0]})" if errors else ""))
