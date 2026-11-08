"""Turn the screener's last results (data/out/listings.json, written by goldstar.py) into the app's two group searches:
data/app/searches/play_promos.json and gold_stars.json. Only listings still for sale: sold, no longer found, ruled out and possible
fraud rows are left out. Run it after every goldstar.py run (the skill does), or by hand: python app_export.py [job id to close]"""
import glob, json, os, re, sys
from common import P, load, save
from app_lib import GROUPS, from_screener, save_search, now_iso, job_path

sys.stdout.reconfigure(encoding="utf-8")
L = load(P("out", "listings.json"), [])
run = (load(P("out", "run.json"), []) or [{}])[0]
src = {s["id"]: s for s in load(P("out", "sources.json"), [])}
images = {}
for f in glob.glob(P("browser", "pages", "*.json")):
    d = load(f) or {}
    for r in d.get("rows", []):
        if r.get("image") or r.get("img"): images[str(r["id"])] = r.get("image") or r.get("img")

photos = load(P("app", "images.json"), {})            # app_images.py: photos found on listing pages and through the eBay API
gone = set(load(P("app", "images", "gone.json"), []))  # listings app_images.py found sold, ended or impossible to buy
gone |= {k for k, v in load(P("app", "photo_review.json"), {}).items() if not v.get("ok")}  # photo is not the card (revisar_fotos.py)
gone |= {k for k, v in load(P("app", "photo_auto.json"), {}).items() if v.get("verdict") == "other"}   # motor.py: the photo's label says reprint
LIST = {"play_promos": "Play promo", "gold_stars": "Other Gold Star"}
# the app shows a Play promo only when its title says so (PLAY, Players, points, promo...): a bare "Espeon Gold Star" or a Neo
# Discovery holo whose photo nobody has checked yet is not shown
PLAY_SIGN = re.compile(r"play|players|プレイヤーズ|\bpts\b|points|\bexp\b|プロモ|promo", re.I)
# keyword stuffing: "Shining Steelix ... No Rayquaza Gold Star" sells another card; a lot that adds a Gold Star ("Celebi Gold Star +") stays
STUFFED = re.compile(r"\bno\b[^,;|]{0,25}gold\s*star|\bnot\s+(?:a\s+)?gold\s*star", re.I)
OTHER_CARD = re.compile(r"\bshining\b|\bneo\s*(?:\d|genesis|discovery|revelation|destiny|darkness)|\bvmax\b|\bvstar\b|\bprism\s*star", re.I)
LOT = re.compile(r"gold\s*star\s*\+|\+[^+]*gold\s*star(?!.*\bno\b)", re.I)
# a "quick" run (make_plan.py quick, the Play Promos refresh) only searches the Play promo cards: it must not rewrite Gold Stars with
# the few rows it found by chance (Jesús, 8 November 2026: a Play Promos refresh left Gold Stars with 21 listings out of 1037)
QUICK_RUN = (load(P("browser", "plan_mode.json")) or {}).get("mode") == "quick"
for gid, g in GROUPS.items():
    old = load(P("app", "searches", f"{gid}.json"), {})
    if QUICK_RUN and gid != "play_promos" and old.get("listings"):
        print(f"{g['label']}: not searched on this quick run, kept {len(old['listings'])} listings"); continue
    rows = [r for r in L if r.get("list") == LIST[gid] and (gid != "play_promos" or PLAY_SIGN.search(r.get("title") or ""))
            and not ((STUFFED.search(r.get("title") or "") or OTHER_CARD.search(r.get("title") or "")) and not LOT.search(r.get("title") or ""))]
    rows.sort(key=lambda r: not r.get("site_name"))   # the same listing twice (a row kept from an earlier run): keep the complete one
    seen_url, uniq = set(), []
    for r in rows:
        if r.get("url") in seen_url: continue
        seen_url.add(r.get("url")); uniq.append(r)
    listings = [from_screener(r, photos.get(r["id"]) or images.get(r["id"].split(":", 1)[1]) or images.get(r["id"].split(":")[-1]))
                for r in uniq if r["id"] not in gone]
    for l in listings:   # Mercari photos follow from the item number
        m = re.search(r"/item/(m\d+)", l.get("url") or "")
        if not l["image"] and m: l["image"] = f"https://static.mercdn.net/item/detail/orig/photos/{m.group(1)}_1.jpg"
    if not listings and old.get("listings"):   # this run did not search the group (an "others" or "quick" run): keep what was there
        print(f"{g['label']}: not searched on the last run, kept {len(old['listings'])} listings"); continue
    have = {p for l in listings for p in l["pokemon"]}
    no_cards = [c["name_en"] for c in g["cards"] if c["pokemon"] not in have]
    no_sites = [s["site"] for s in src.values() if s.get("read_automatically") == "Yes" and not s.get("listings_now")]
    save_search({"id": gid, "kind": "group", "group": gid, "label": g["label"], "query": None, "status": "done", "updated": now_iso(),
                 "run_text": run.get("finished_text"), "note": run.get("note"), "fx_text": run.get("fx_text"),
                 "pokemon": [c["pokemon"] for c in g["cards"]], "listings": listings,
                 "no_results": {"cards": no_cards, "sites": no_sites}})
    print(f"{g['label']}: {len(listings)} listings for sale; no listing for {len(no_cards)} cards")

if len(sys.argv) > 1:   # close the app job that asked for this group run
    j = load(job_path(sys.argv[1]))
    if j: j.update(status="done", progress=100, finished=now_iso(), message="Búsqueda terminada"); save(job_path(sys.argv[1]), j)
