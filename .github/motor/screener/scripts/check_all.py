"""Confirm that every Other Gold Star listing on the dashboard is still for sale (owner, 23 October 2026: "some are already sold
on the site; remove every sold one"). Search pages can show sold copies (Magi's sold icon, SNKRDUNK's badge).
- eBay listings found through GempireCards are asked to the eBay API one by one (get_item_by_legacy_id): gone or out of stock = sold.
- Listings of the other sites go to data/browser/check_queue.json, to open with `python batch.py listing a b` (browser/listing.js).
eBay API search rows are live when read and ALT, Fanatics Collect and Goldin rows come from live auctions: not checked again.
goldstar.py then moves every listing whose page says sold or unavailable to "Sold or unavailable".
Usage: python check_all.py   (after goldstar.py), then the listing batches, then goldstar.py again"""
import json, re, sys, urllib.error, urllib.request
from common import P, load, save
from ebay_api import token

safe = lambda k: re.sub(r"[^\w.-]", "_", k)
sys.stdout.reconfigure(encoding="utf-8")
rows = [r for r in load(P("out", "listings.json"), []) if r.get("list") == "Other Gold Star"]
queue, ebay_sold, ebay_ok = [], 0, 0
tok = None
for r in rows:
    k = r["key"]
    if load(P("browser", "listing", safe(k) + ".json")) is not None: continue
    if "Gempire" in r["site_name"] or "eBay API" in (r.get("extra") or ""): continue
    if r["site_name"] == "eBay":
        tok = tok or token()
        iid = re.search(r"(\d{9,})", r["url"] or k).group(1)
        req = urllib.request.Request("https://api.ebay.com/buy/browse/v1/item/get_item_by_legacy_id?legacy_item_id=" + iid,
                                     headers={"Authorization": "Bearer " + tok, "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"})
        try:
            d = json.load(urllib.request.urlopen(req, timeout=30))
            avail = (d.get("estimatedAvailabilities") or [{}])[0].get("estimatedAvailabilityStatus")
            gone = avail == "OUT_OF_STOCK"
            res = {"blocked": False, "title": d.get("title"), "available": False if gone else True,
                   "sold_text": "eBay: out of stock" if gone else None, "ship": []}
        except urllib.error.HTTPError as e:
            if e.code != 404: print("eBay", iid, "HTTP", e.code); continue
            res = {"blocked": False, "title": r["title"], "available": False, "sold_text": "eBay: the listing has ended", "ship": []}
        save(P("browser", "listing", safe(k) + ".json"), res)
        ebay_sold += res["available"] is False; ebay_ok += res["available"] is True
        continue
    queue.append({"key": k, "url": r["url"], "card": r["card"], "site": r["site_name"], "price_text": r["price_text"]})
order = {"Magi": 0, "Rakuma": 1, "SNKRDUNK": 2, "Card Rush": 3, "Vinted": 4, "Wallapop": 5}
queue.sort(key=lambda q: order.get(q["site"], 9))
save(P("browser", "check_queue.json"), queue)
print(f"eBay (through Gempire) asked to the eBay API: {ebay_ok} still for sale, {ebay_sold} ended or sold. "
      f"Listing pages to open in the browser: {len(queue)} (" + ", ".join(f"{s} {sum(q['site'] == s for q in queue)}" for s in dict.fromkeys(q["site"] for q in queue)) + ")")
