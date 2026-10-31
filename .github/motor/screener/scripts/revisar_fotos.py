"""Claude checks the photo of every listing before the owner sees it (owner, 24 October 2026: a Gyarados δ that was not a Gold
Star showed up; "look at the card's colours and which card it is").

  python revisar_fotos.py sheets [--search ID]... [--per 24]
        Contact sheets of the photos not reviewed yet: app/review/sheet_<n>.html (open http://localhost:8800/review/sheet_<n>.html
        in the browser, viewport 1280 wide, and look at the screenshot). Each photo has a number and the card it should be.
  python revisar_fotos.py mark <n> [bad 3,7,12] [--why "texto"]
        Sheet n: the numbers given are not the card searched for (not a Gold Star, another Pokémon or card, a fake, a proxy, only a
        box or a sleeve...); every other photo on the sheet is marked right. Stored in data/app/photo_review.json.
  python revisar_fotos.py apply
        Removes the wrong ones from every saved search (app_export.py and app_job.py leave them out next time too).
  python revisar_fotos.py labels [--search ID]
        Grade and edition on the photo (owner, 26 October 2026): sheets data/app/review/label_<n>.jpg of the listings whose grade is
        not certain (SNKRDUNK "PSA8以下" = 8 or lower, 他鑑定品...) or whose edition is not stated: the top of each photo (slab label)
        and the bottom (1st Edition mark of a raw card), large.
  python revisar_fotos.py label <n> "1=PSA 1 1ED" "2=raw UNL" "3=?"   then   python revisar_fotos.py apply-labels
        What the label or card says (data/app/grades.json); it wins over the title in the app and the phone page.
What a Gold Star (☆) looks like: the Pokémon in shiny colours (Gyarados red, Rayquaza black, Umbreon blue rings...), a star ☆ after
the name, foil artwork. A δ (delta species) card without the star, a normal holo or a modern card is wrong."""
import datetime as dt, glob, html, json, os, re, sys
from common import P, load, save, SCREENER
import app_lib as A

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(SCREENER)
REVIEW = P("app", "photo_review.json")
SHEETS = P("app", "review_sheets.json")
OUT = os.path.join(ROOT, "app", "review")

def args(flag):
    return [sys.argv[i + 1] for i, x in enumerate(sys.argv) if x == flag and i + 1 < len(sys.argv)]

def expected(s, l):
    if s.get("kind") == "text": return s.get("label")
    bits = [l.get("card") or " / ".join(l.get("pokemon") or []), l.get("number") or ""]
    return " ".join(b for b in bits if b) + (" (Gold Star ☆)" if "☆" not in (l.get("card") or "") else "")

def sheets():
    only = set(args("--search")); per = int((args("--per") or ["24"])[0])
    rev = load(REVIEW, {})
    items, seen = [], set()
    for f in sorted(glob.glob(P("app", "searches", "*.json"))):
        s = load(f)
        if only and s["id"] not in only: continue
        for l in sorted(s.get("listings", []), key=lambda l: ((l.get("pokemon") or ["~"])[0], l.get("price_eur") or 0)):
            if l["id"] in seen or l["id"] in rev or not l.get("image"): continue
            seen.add(l["id"]); items.append({"id": l["id"], "img": l["image"], "title": l["title"], "want": expected(s, l),
                                             "price": l.get("price_eur"), "site": l.get("site_name"), "search": s["id"]})
    os.makedirs(OUT, exist_ok=True)
    for old in glob.glob(os.path.join(OUT, "sheet_*.html")): os.remove(old)
    book = {}
    for n in range(0, len(items), per):
        chunk = items[n:n + per]; k = n // per + 1
        book[str(k)] = chunk
        cells = "".join(f"""<figure><b>{i + 1}</b><img src="{html.escape(x['img'])}" referrerpolicy="no-referrer">
<figcaption><i>{html.escape(x['want'] or '')}</i><br>{html.escape((x['title'] or '')[:70])}</figcaption></figure>""" for i, x in enumerate(chunk))
        open(os.path.join(OUT, f"sheet_{k}.html"), "w", encoding="utf-8").write(f"""<!doctype html><meta charset=utf-8><title>Hoja {k}</title>
<style>body{{margin:0;background:#111;color:#eee;font:12px system-ui}}main{{display:grid;grid-template-columns:repeat(6,1fr);gap:6px;padding:6px}}
figure{{margin:0;position:relative;background:#222;border-radius:6px;overflow:hidden}}img{{width:100%;height:250px;object-fit:contain;background:#000;display:block}}
b{{position:absolute;top:4px;left:4px;background:#ff0;color:#000;font-size:18px;padding:0 7px;border-radius:5px}}
figcaption{{padding:3px 5px;height:44px;overflow:hidden;line-height:1.25}}i{{color:#7cf}}</style><main>{cells}</main>""")
    save(SHEETS, book)
    jpgs = [picture(k, chunk) for k, chunk in book.items()]
    print(f"{len(items)} photos to review in {len(book)} sheets. Look at each picture (Read tool): " + ", ".join(j for j in jpgs if j))

def picture(k, chunk):
    """The sheet as one picture (data/app/review/sheet_<k>.jpg): 8 photos a row, each numbered, with the card it should be."""
    from PIL import Image, ImageDraw, ImageFont
    import nube
    W, H, CAP, COLS = 150, 200, 38, 8
    rows = (len(chunk) + COLS - 1) // COLS
    im = Image.new("RGB", (W * COLS, (H + CAP) * rows), (20, 20, 20)); d = ImageDraw.Draw(im)
    try: big, small = ImageFont.truetype("arialbd.ttf", 18), ImageFont.truetype("arial.ttf", 11)
    except OSError: big = small = ImageFont.load_default()
    for i, x in enumerate(chunk):
        cx, cy = (i % COLS) * W, (i // COLS) * (H + CAP)
        f = nube.fetch_thumb(x["img"])
        if f: im.paste(Image.open(f), (cx, cy))
        d.rectangle([cx, cy, cx + 30, cy + 22], fill=(255, 230, 0)); d.text((cx + 3, cy + 1), str(i + 1), font=big, fill=(0, 0, 0))
        want = (x["want"] or "").replace("☆", "*")
        d.text((cx + 3, cy + H + 2), want[:26], font=small, fill=(120, 200, 255))
        d.text((cx + 3, cy + H + 18), "".join(ch for ch in x["title"] if ord(ch) < 0x2000)[:26], font=small, fill=(220, 220, 220))
    out = P("app", "review", f"sheet_{k}.jpg"); os.makedirs(os.path.dirname(out), exist_ok=True)
    im.save(out, "JPEG", quality=85)
    return out

def mark():
    k = sys.argv[2]; book = load(SHEETS, {}); chunk = book.get(k)
    if not chunk: sys.exit(f"no sheet {k}")
    bad = set()
    if "bad" in sys.argv:
        bad = {int(x) for x in sys.argv[sys.argv.index("bad") + 1].split(",") if x.strip()}
    why = (args("--why") or ["no es la carta buscada"])[0]
    rev = load(REVIEW, {}); now = dt.datetime.now().isoformat(timespec="minutes")
    for i, x in enumerate(chunk, 1):
        rev[x["id"]] = {"ok": i not in bad, "why": why if i in bad else None, "at": now, "title": x["title"][:80]}
    save(REVIEW, rev)
    print(f"Sheet {k}: {len(chunk) - len(bad)} right, {len(bad)} wrong: " + "; ".join(chunk[i - 1]["title"][:50] for i in sorted(bad)))

def wrong_ids():
    return {k for k, v in load(REVIEW, {}).items() if not v.get("ok")}

def apply():
    rev = load(REVIEW, {}); bad = wrong_ids(); n = 0
    for f in glob.glob(P("app", "searches", "*.json")):
        s = load(f); before = len(s.get("listings", []))
        s["listings"] = [l for l in s.get("listings", []) if l["id"] not in bad]
        for l in s["listings"]:
            if l["id"] in rev: l["photo_ok"] = True
        n += before - len(s["listings"]); A.save_search(s)
    print(f"Removed {n} listings whose photo is not the card searched for.")

# ---- grade and edition read on the photo (owner, 26 October 2026: "the PSA the listing shows must be the one in the app"; a SNKRDUNK
# Treecko titled PSA8以下 was a PSA 1. And "Gold Stars: filter First Edition or Unlimited")
LABELS = P("app", "grades.json")
LSHEETS = P("app", "label_sheets.json")
FULL = P("cloud", "full")

def needs_label(l):
    """Grade not certain (SNKRDUNK's ≤8 groups, 他鑑定品, a grader without a number) or edition not known on a card printed twice."""
    g, t = l.get("grade") or "", l.get("title") or ""
    unsure_grade = "≤" in g or bool(re.search(r"以下|他鑑定|or lower", t)) or (bool(l.get("grader")) and not re.search(r"\d", g))
    unsure_ed = l.get("edition") == "not stated"
    return unsure_grade or unsure_ed

def full_photo(url):
    import hashlib, io, urllib.request
    from PIL import Image
    f = os.path.join(FULL, hashlib.sha1(url.encode()).hexdigest()[:20] + ".jpg")
    if os.path.exists(f): return f
    big = re.sub(r"(\?|&)size=[sm]\b", r"\1size=l", url)   # SNKRDUNK serves a large size
    try:
        req = urllib.request.Request(big, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/140.0", "Accept": "image/*"})
        im = Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=30).read())).convert("RGB")
    except Exception:
        return None
    im.thumbnail((1400, 1400)); os.makedirs(FULL, exist_ok=True); im.save(f, "JPEG", quality=88)
    return f

def labels():
    """Sheets of 4 listings: for each, the top of the photo (a slab's label: grade, "1ST ED.", certificate) and the bottom (a raw card's
    1st Edition mark, lower left), large enough to read. data/app/review/label_<n>.jpg."""
    from concurrent.futures import ThreadPoolExecutor
    from PIL import Image, ImageDraw, ImageFont
    only = set(args("--search")); per = int((args("--per") or ["4"])[0])
    done = load(LABELS, {})
    items, seen = [], set()
    for f in sorted(glob.glob(P("app", "searches", "*.json"))):
        s = load(f)
        if only and s["id"] not in only: continue
        for l in s.get("listings", []):
            if l["id"] in seen or l["id"] in done or not l.get("image") or not needs_label(l): continue
            seen.add(l["id"]); items.append({"id": l["id"], "img": l["image"], "title": l["title"], "grade": l.get("grade"),
                                             "edition": l.get("edition"), "card": l.get("card") or " / ".join(l.get("pokemon") or [])})
    with ThreadPoolExecutor(6) as ex: files = list(ex.map(lambda x: full_photo(x["img"]), items))
    items = [dict(x, file=f) for x, f in zip(items, files) if f]
    try: big, small = ImageFont.truetype("arialbd.ttf", 26), ImageFont.truetype("arial.ttf", 15)
    except OSError: big = small = ImageFont.load_default()
    W, CROP, CAP = 700, 330, 46
    LOUT = P("app", "review")   # next to the photo sheets, outside the published app folder
    os.makedirs(LOUT, exist_ok=True)
    for old in glob.glob(os.path.join(LOUT, "label_*.jpg")) + glob.glob(os.path.join(OUT, "label_*.jpg")): os.remove(old)
    book, out = {}, []
    for n in range(0, len(items), per):
        chunk = items[n:n + per]; k = str(n // per + 1); book[k] = chunk
        cols = 2; rows = (len(chunk) + 1) // 2
        sheet = Image.new("RGB", (W * cols, (CAP + 2 * CROP) * rows), (16, 16, 16)); d = ImageDraw.Draw(sheet)
        for i, x in enumerate(chunk):
            im = Image.open(x["file"]); w, h = im.size
            top, bot = im.crop((0, 0, w, int(h * 0.34))), im.crop((0, int(h * 0.62), w, h))
            cx, cy = (i % cols) * W, (i // cols) * (CAP + 2 * CROP)
            for j, part in enumerate((top, bot)):
                part.thumbnail((W - 8, CROP - 6), Image.LANCZOS)
                sheet.paste(part, (cx + 4, cy + CAP + j * CROP))
            d.rectangle([cx, cy, cx + 40, cy + 34], fill=(255, 230, 0)); d.text((cx + 8, cy + 2), str(i + 1), font=big, fill=(0, 0, 0))
            cap = f"{x['card']} | now: {x['grade'] or 'no grade'}, {x['edition'] or '-'}"
            d.text((cx + 48, cy + 2), "".join(ch for ch in cap if ord(ch) < 0x2000)[:70], font=small, fill=(120, 200, 255))
            d.text((cx + 48, cy + 22), "".join(ch for ch in x["title"] if ord(ch) < 0x2000)[:70], font=small, fill=(220, 220, 220))
        p = os.path.join(LOUT, f"label_{k}.jpg"); sheet.save(p, "JPEG", quality=86); out.append(p)
    save(LSHEETS, book)
    print(f"{len(items)} photos to read in {len(book)} sheets (4 listings each: top of the photo = slab label, bottom = card's lower edge). "
          "Read each with the Read tool, then: python revisar_fotos.py label <n> \"1=PSA 1 1ED\" \"2=raw UNL\" \"3=?\" ...  Sheets: " + ", ".join(out))

def label():
    """label <n> "1=PSA 1 1ED" "2=BGS 8.5" "3=UNL" "4=raw 1ED" "5=?" : grade (grader + number as on the label; "raw" = ungraded) and/or
    edition (1ED = "1ST ED." on the label or the 1st Edition mark on the card; UNL = a PSA label without 1ST ED., or no mark on a clearly
    visible card corner). Anything not legible: leave it out or "?" (it keeps what the title says)."""
    k = sys.argv[2]; chunk = load(LSHEETS, {}).get(k)
    if not chunk: sys.exit(f"no label sheet {k}")
    reads = load(LABELS, {}); now = dt.datetime.now().isoformat(timespec="minutes"); said = {}
    for a in sys.argv[3:]:
        m = re.match(r"\s*(\d+)\s*=\s*(.*)$", a)
        if m: said[int(m.group(1))] = m.group(2).strip()
    out = []
    for i, x in enumerate(chunk, 1):
        v = said.get(i, "?"); o = {"at": now, "image": x["img"], "title": x["title"][:80], "said": v}
        g = re.search(rf"\b({A.GRADERS})\s*(10|9\.5|[1-9](?:\.5)?)\b", v, re.I)
        if g: o["grade"] = f"{g.group(1).upper().replace('BECKETT', 'BGS')} {g.group(2)}"
        if re.search(r"\braw\b", v, re.I): o["raw"] = True; o["grade"] = ""
        if re.search(r"\b1ED\b|1st", v, re.I): o["edition"] = "1st Edition"
        elif re.search(r"\bUNL\b|unlimited", v, re.I): o["edition"] = "Unlimited"
        reads[x["id"]] = o; out.append(f"{i}: {v}")
    save(LABELS, reads)
    print(f"Label sheet {k}: " + "; ".join(out))

def apply_labels():
    reads = load(LABELS, {}); n = 0
    for f in glob.glob(P("app", "searches", "*.json")):
        s = load(f)
        for l in s.get("listings", []):
            before = (l.get("grade"), l.get("edition")); A.apply_label(l, reads); n += before != (l.get("grade"), l.get("edition"))
        A.save_search(s)
    print(f"{n} listings now show the grade or edition read on the photo.")

if __name__ == "__main__":
    {"sheets": sheets, "mark": mark, "apply": apply, "labels": labels, "label": label, "apply-labels": apply_labels}.get(
        sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__))()
