"""After the SNKRDUNK search pages are read: learn each card's SNKRDUNK product page (data/state/snkr_products.json) and add
that product's "copies for sale" page to this run's plan (data/browser/pages.json), so every copy is read.
A product is kept only when its name has the card's Japanese name with ☆ and the card's number (for example シャワーズ☆ ... 022/PLAY).
Usage: python snkr_learn.py"""
import os, re, json, glob, unicodedata
from common import P, load, save, SCREENER
CARDS = {c["key"]: c for c in load(os.path.join(SCREENER, "cards.json"))["cards"]}
pages = load(P("browser", "pages.json"), [])
known = load(P("state", "snkr_products.json"), {})
added = 0
n = lambda s: unicodedata.normalize("NFKC", s or "").lower()
for f in sorted(glob.glob(P("browser", "pages", "*.json"))):
    i = int(os.path.basename(f).split(".")[0])
    if i >= len(pages) or pages[i]["site"] != "snkrdunk" or "/used" in pages[i]["url"]: continue
    c = CARDS.get(pages[i]["card_key"]); d = load(f) or {}
    if not c or d.get("blocked"): continue
    for r in d.get("rows", []):
        m = re.search(r"product (\d+)", r.get("extra", ""))
        if not m: continue
        t = n(r["title"])
        if n(c["names"][0] + "☆") in t and n(c["number"]) in t:
            if m.group(1) not in known.setdefault(c["key"], []): known[c["key"]].append(m.group(1))
for key, pids in known.items():
    c = CARDS[key]
    for pid in pids:
        url = f"https://snkrdunk.com/apparels/{pid}/used"
        if any(p["url"] == url for p in pages): continue
        tmpl = next((p for p in pages if p["site"] == "snkrdunk" and p["card_key"] == key), None)
        if not tmpl: continue
        pages.append({**tmpl, "i": len(pages), "label": f"SNKRDUNK copies for sale: {c['name_en']} ({pid})", "url": url}); added += 1
save(P("state", "snkr_products.json"), known); save(P("browser", "pages.json"), pages)
print(f"SNKRDUNK products known for {len(known)} cards; {added} 'copies for sale' pages added to this run (pages {len(pages) - added} to {len(pages) - 1})")
