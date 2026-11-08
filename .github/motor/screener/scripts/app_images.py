"""Checks every listing the app shows before the owner sees it: can it really be bought today, and what is its photo
(owner, 24 October 2026: "only listings that are really for sale: no 404, no seller who has not logged in for ages, no listing that
cannot be added to the cart"; "each result must show the photo of that listing").

  python app_images.py prepare [--search ID]... [--all] [--days N]
        eBay: the eBay API, at once (404, out of stock, ended or no way to buy -> out).
        Every other site: written to data/app/images/browser/check_queue.json, to open in the browser with
        GS_BROWSER=app/images/browser and `python batch.py photo a b` (browser/photo_pick.js: photo, buy button, blocking messages).
        Mercari and Rakuma are opened on Buyee, where the owner buys them from Spain (Buyee says when a seller is inactive or an item
        cannot be ordered).
        Default: listings never checked or checked more than N days ago (1). --all: every listing again. --search: only those searches.
  python app_images.py apply
        Records each verdict in data/app/checks.json, removes from every search the listings that cannot be bought
        (data/app/images/gone.json, which app_export.py and app_job.py also leave out), adds the photos (data/app/images.json).
Verdicts: yes (buy button and nothing blocking), no (gone, sold, blocked, inactive seller, no buy button), unknown (kept)."""
import datetime as dt, glob, json, os, re, shutil, sys, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor
from common import P, load, save
import app_lib as A

sys.stdout.reconfigure(encoding="utf-8")
CACHE = P("app", "images.json")
CHECKS = P("app", "checks.json")
GONE = P("app", "images", "gone.json")
QDIR = P("app", "images", "browser")
safe = lambda k: re.sub(r"[^\w.-]", "_", k)
STOCK = re.compile(r"/static/media/|pickup_link|/logo|placeholder|spacer|noimage|dummy")   # site pictures, not the listing

def mercari(l):
    m = re.search(r"/item/(m\d+)", l.get("url") or "")
    return f"https://static.mercdn.net/item/detail/orig/photos/{m.group(1)}_1.jpg" if m else None

def check_url(l):
    """The page that shows whether the owner can buy it: Mercari and Rakuma through Buyee."""
    u = l.get("url") or ""
    m = re.search(r"jp\.mercari\.com/item/(m\d+)", u)
    if m: return f"https://buyee.jp/mercari/item/{m.group(1)}"
    m = re.search(r"item\.fril\.jp/([0-9a-f]{20,})", u)
    if m: return f"https://buyee.jp/rakuma/item/{m.group(1)}"
    return u

def ebay_price(d):
    """The listing's price as eBay Spain shows it: euros, and the seller's own currency. An auction's current bid when it has one.
    (owner, 28 October 2026: a listing GempireCards gave as $40 was $40,000 on eBay; the price always comes from eBay itself)."""
    p = d.get("currentBidPrice") if "AUCTION" in (d.get("buyingOptions") or []) and d.get("currentBidPrice") else d.get("price")
    if not p or p.get("value") is None: return None
    v, cur = float(p["value"]), p.get("currency")
    orig = f'{p["convertedFromCurrency"]} {float(p["convertedFromValue"]):,.2f}' if p.get("convertedFromCurrency") else f"{cur} {v:,.2f}"
    from common import to_eur
    eur = round(v, 2) if cur == "EUR" else to_eur(f"{cur} {v:.2f}")[0]
    return {"price_eur": eur, "price_text": orig}

def ebay_check(iid, tok):
    """-> (photo, (verdict, reason), price) from the eBay API, seen from Spain."""
    req = urllib.request.Request("https://api.ebay.com/buy/browse/v1/item/get_item_by_legacy_id?legacy_item_id=" + iid,
                                 headers={"Authorization": "Bearer " + tok, "X-EBAY-C-MARKETPLACE-ID": "EBAY_ES",
                                          "X-EBAY-C-ENDUSERCTX": "contextualLocation=country%3DES"})
    try:
        import ebay_cuota; ebay_cuota.registrar("imagenes")      # counted (not limited): it is part of the owner's searches
        d = json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as e:
        return None, (("no", "404 en eBay") if e.code == 404 else ("unknown", f"eBay {e.code}")), None
    except Exception as e:
        return None, ("unknown", type(e).__name__), None
    img = (d.get("image") or {}).get("imageUrl")
    price = ebay_price(d)
    if price is not None:   # the seller's item specifics (Set: Celebrations, Year: 2021...): a reprint the title does not name
        price["aspects"] = " | ".join(f'{a.get("name")}: {a.get("value")}' for a in d.get("localizedAspects") or []
                                      if a.get("name") and a.get("value"))[:500]
    av = (d.get("estimatedAvailabilities") or [{}])[0]
    end = d.get("itemEndDate")
    if av.get("estimatedAvailabilityStatus") == "OUT_OF_STOCK": return img, ("no", "agotado en eBay"), price
    if end and dt.datetime.fromisoformat(end.replace("Z", "+00:00")) < dt.datetime.now(dt.timezone.utc): return img, ("no", "subasta terminada"), price
    if not d.get("buyingOptions"): return img, ("no", "no se puede comprar"), price
    return img, ("yes", None), price

def searches(only=None):
    out = []
    for f in glob.glob(P("app", "searches", "*.json")):
        s = load(f)
        if s and (not only or s["id"] in only): out.append((f, s))
    return out

def args(flag):
    return [sys.argv[i + 1] for i, x in enumerate(sys.argv) if x == flag and i + 1 < len(sys.argv)]

def prepare():
    only = set(args("--search")); days = float((args("--days") or ["1"])[0]); every = "--all" in sys.argv
    cache, checks = load(CACHE, {}), load(CHECKS, {})
    def fresh(k):
        """¿Hace falta volver a preguntar a eBay por este anuncio? Lo que ya se vio «comprable» se vuelve a mirar a los 7 días, no cada día (Fernando, 7 nov: «no tiene sentido mirar otra vez lo ya hecho»:
        eran 1.200 a 2.800 llamadas al día, casi todas anuncios ya comprobados); lo dudoso («unknown») se reintenta al día siguiente."""
        if every or k not in checks: return False
        ok = checks[k].get("buy") == "yes"; return (dt.datetime.now().timestamp() - checks[k]["at"]) < (max(days, 7) if ok else days) * 86400
    todo_ebay, queue, seen = {}, [], set()
    for f, s in searches(only):
        for l in s.get("listings", []):
            k = l["id"]
            if k in seen: continue
            seen.add(k)
            if l["site"] == "mercari" and not l.get("image") and mercari(l): cache[k] = mercari(l)
            # an eBay listing checked before prices came from eBay (28 October 2026) is asked again for its price
            if fresh(k) and (l.get("image") or cache.get(k)) and (l["site"] != "ebay" or "aspects" in (checks[k].get("price") or {})): continue
            if l["site"] == "ebay":
                m = re.search(r"(\d{9,})", l.get("url") or k)
                if m: todo_ebay[k] = m.group(1)
            else:
                queue.append({"key": k, "url": check_url(l), "site": l["site_name"]})
    gone = set(load(GONE, []))
    n_no = 0
    if todo_ebay and os.path.exists(os.path.join(os.path.dirname(P()), ".secrets", "ebay_api.json")):
        from ebay_api import token
        tok = token()
        with ThreadPoolExecutor(8) as ex:
            res = dict(zip(todo_ebay, ex.map(lambda i: ebay_check(i, tok), todo_ebay.values())))
        now = dt.datetime.now().timestamp()
        for k, (img, (verdict, why), price) in res.items():
            if img: cache[k] = img
            checks[k] = {"at": now, "buy": verdict, "reason": why, "via": "eBay API", "price": price}
            if verdict == "no": gone.add(k); n_no += 1
    save(CACHE, cache); save(CHECKS, checks); save(GONE, sorted(gone))
    for d in ("photo", "listing"): shutil.rmtree(os.path.join(QDIR, d), ignore_errors=True)
    save(os.path.join(QDIR, "check_queue.json"), queue)
    print(f"eBay checked through the API: {len(todo_ebay)} ({n_no} cannot be bought). "
          f"To open in the browser: {len(queue)} listings (GS_BROWSER=app/images/browser python batch.py photo 0 {max(0, len(queue) - 1)}, "
          f"7 per browser_batch). Then: python app_images.py apply")

def apply():
    cache, checks = load(CACHE, {}), load(CHECKS, {})
    gone = set(load(GONE, []))
    queue = {safe(q["key"]): q for q in load(os.path.join(QDIR, "check_queue.json"), [])}
    reasons = {}
    for f in glob.glob(os.path.join(QDIR, "photo", "*.json")):
        r = load(f) or {}; q = queue.get(os.path.basename(f)[:-5])
        if not q: continue
        k = q["key"]
        verdict = r.get("buy") or ("no" if r.get("gone") else "unknown")
        checks[k] = {"at": os.path.getmtime(f), "buy": verdict, "reason": r.get("reason"), "via": r.get("host")}
        if verdict == "no":
            gone.add(k); reasons[r.get("reason") or "?"] = reasons.get(r.get("reason") or "?", 0) + 1
        elif verdict == "yes":
            gone.discard(k)
        if r.get("img") and verdict != "no" and not STOCK.search(r["img"]): cache[k] = r["img"]
    save(CACHE, cache); save(CHECKS, checks); save(GONE, sorted(gone))
    n_img = n_gone = n_price = 0
    for f, s in searches():
        before = len(s.get("listings", []))
        s["listings"] = [l for l in s.get("listings", []) if l["id"] not in gone]
        n_gone += before - len(s["listings"])
        for l in s["listings"]:
            if not l.get("image") and cache.get(l["id"]): l["image"] = cache[l["id"]]; n_img += 1
            c = checks.get(l["id"])
            if c: l["checked"] = {"at": dt.datetime.fromtimestamp(c["at"]).isoformat(timespec="minutes"), "buy": c["buy"]}
            if c and (c.get("price") or {}).get("price_eur") is not None:   # eBay's own price wins over a search page's
                if abs((l.get("price_eur") or 0) - c["price"]["price_eur"]) > 1: n_price += 1
                l["price_eur"], l["price_text"] = c["price"]["price_eur"], c["price"]["price_text"]
        A.save_search(s)
    print(f"Photos added: {n_img}. Listings removed because they cannot be bought: {n_gone}. Reasons: {reasons}. "
          f"eBay prices corrected from eBay itself: {n_price}")

if __name__ == "__main__":
    {"prepare": prepare, "apply": apply}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__))()
