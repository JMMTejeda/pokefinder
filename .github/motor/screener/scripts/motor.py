"""PokéFinder's own search engine (owner, 28 October 2026: "searches typed in the app, on the phone or the computer, must run without
Claude, with the same outcome"; "the hidden browser must be inside the app, so friends who get the app have it too").

A hidden browser that comes with the app (Playwright's Chromium, headless, installed by instalar.bat) opens the same marketplace pages
and runs the same reader scripts (screener/browser/readers) Claude ran in its browser, saving each result where receiver.py did.
What Claude did by eye is done on this computer:
  - which words to type on each site: Pokémon names in Japanese from screener/pokemon_names.json, plus a few card words (plan_spec);
  - grade and edition on the photo: the grading label read with Windows text recognition (leer_etiqueta.py);
  - is the photo the card: compared with confirmed photos of that card (comprobar_foto.py); an unconfirmed one is kept and flagged.
Sites that turn automated browsers away are not opened (settings.json "engine" "skip_sites": Buyee, so Yahoo! Auctions, PayPay Flea
Market and Yahoo! Shopping, and Wallapop): the app lists them under "not read". Never get round a block: a page that answers 403 or a
check page is recorded as blocked and skipped.

server.py starts it with the app. It runs the app's jobs one at a time (typed searches and the Play Promos / Gold Stars refreshes)
and, when this copy owns the phone page (.secrets/cloud.json), picks up the searches asked on the phone and sends results back.
GitHub Actions runs this same engine for the searches typed on the phone page, computer off (cloud/github/buscar.py, 31 October 2026).
  python motor.py              keep running (what server.py starts)
  python motor.py run <job>    run one job now and stop
Log: data/state/motor.log"""
import glob, json, os, random, re, subprocess, sys, time, traceback, unicodedata
import datetime as dt
from common import P, load, save, CFG, SCREENER
import app_lib as A

ROOT = os.path.dirname(SCREENER)
HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = {"skip_sites": ["buyee", "paypay", "yshop", "wallapop"], "same_site_seconds": [5, 10], **CFG.get("engine", {})}
SKIP = set(ENGINE["skip_sites"])
SKIP_HOSTS = re.compile(r"buyee\.jp|wallapop\.com")
BEAT = P("app", "claude.json")   # the app's "who is searching" light (server.py claude_state)
LOG = P("state", "motor.log")
BROWSER_JS = os.path.join(SCREENER, "browser")
PHOTO_JS = open(os.path.join(BROWSER_JS, "photo_pick.js"), encoding="utf-8").read()
LISTING_JS = open(os.path.join(BROWSER_JS, "listing.js"), encoding="utf-8").read()
HAS_KEYS = os.path.exists(os.path.join(ROOT, ".secrets", "ebay_api.json"))
safe = lambda k: re.sub(r"[^\w.-]", "_", k)

def log(*a):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + " ".join(str(x) for x in a)
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f: f.write(line + "\n")

# ---------------------------------------------------------------- the hidden browser
class Browser:
    """One headless Chromium for a job. read() opens a page and runs a reader script; the result is the reader's JSON (a dict)."""
    def __init__(self):
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        self.b = self.pw.chromium.launch(headless=True)
        self.ctx, self.last = {}, {}

    def page(self, vp):
        if vp not in self.ctx:
            tall = vp != "normal"   # "normal" = phone size, for GempireCards (its desktop layout stopped loading results, 18 October 2026)
            # English, as Claude's browser was: with "es-ES" GempireCards and ALT write $24,369 as "$24.369" and Gempire then
            # shows it as $24 (28 October 2026)
            c = self.b.new_context(locale="en-US", timezone_id="Europe/Madrid", is_mobile=not tall, has_touch=not tall,
                                   viewport={"width": 1280, "height": 8000} if tall else {"width": 390, "height": 844})
            self.ctx[vp] = c.new_page()
        return self.ctx[vp]

    def pace(self, url):
        """A person's pace on each site: 5 to 10 seconds between two pages of the same site (pause.py "site")."""
        host = re.sub(r"^www\.", "", re.sub(r"^https?://([^/]+).*", r"\1", url))
        lo, hi = ENGINE["same_site_seconds"]
        wait = self.last.get(host, 0) + random.uniform(lo, hi) - time.time()
        if wait > 0: time.sleep(wait)
        self.last[host] = time.time()
        return host

    def read(self, url, js, vp="tall"):
        host = self.pace(url)
        pg = self.page(vp)
        try:
            resp = pg.goto(url, wait_until="domcontentloaded", timeout=60000)
            title = pg.title()
            if (resp and resp.status in (401, 403, 429)) or re.search(r"403 Forbidden|request could not be satisfied|Just a moment|Attention Required|Access denied|captcha", title, re.I):
                return {"site": host, "blocked": True, "title": title[:80], "status": resp.status if resp else None}
            r = pg.evaluate("async () => await " + js.strip().rstrip(";"))
            d = json.loads(r) if isinstance(r, str) else r
            return d if isinstance(d, dict) else {"site": host, "blocked": True, "title": "no result"}
        except Exception as e:
            if "Execution context was destroyed" in str(e):   # a redirect cut the reader off (Buyee did this on a first visit): once more
                try:
                    pg.wait_for_load_state("domcontentloaded", timeout=30000)
                    d = json.loads(pg.evaluate("async () => await " + js.strip().rstrip(";")))
                    if isinstance(d, dict): return d
                except Exception:
                    pass
            return {"site": host, "blocked": True, "title": f"{type(e).__name__}: {str(e)[:120]}"}

    def close(self):
        try: self.b.close(); self.pw.stop()
        except Exception: pass

# ---------------------------------------------------------------- jobs
def job(jid): return load(A.job_path(jid))

def cancelled(jid): return (job(jid) or {}).get("status") == "cancelled"

def put(jid, **kw):
    j = job(jid) or {}
    if j.get("status") == "cancelled": return j
    j.update(kw); save(A.job_path(jid), j)
    save(BEAT, {"listening": True, "engine": True, "working": [jid], "at": time.time(), "pid": os.getpid()})
    phone_job(jid)
    return j

def run(args, gs_browser=None, check=True):
    """One of the screener scripts, as Claude ran them (same folder, UTF-8)."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    env.pop("GS_BROWSER", None)
    if gs_browser: env["GS_BROWSER"] = gs_browser
    r = subprocess.run([sys.executable] + args, cwd=HERE, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (r.stdout + r.stderr).strip()
    log("  $", " ".join(args), "->", out[-300:].replace("\n", " | "))
    if check and r.returncode: raise RuntimeError(f"{args[0]} failed: {out[-200:]}")
    return out

def read_pages(jid, bdir, lo=15, hi=80, label="Leyendo"):
    """Every page of <bdir>/pages.json not read yet -> <bdir>/pages/<i>.json (what receiver.py saved)."""
    pf = os.path.join(P(), bdir, "pages.json")
    pages = load(pf, [])
    todo = [p for p in pages if not p.get("api") and p["site"] not in SKIP
            and not os.path.exists(os.path.join(P(), bdir, "pages", f"{p['i']:03d}.json"))]
    if not todo: return
    os.makedirs(os.path.join(P(), bdir, "pages"), exist_ok=True)
    br = Browser()
    try:
        for n, p in enumerate(todo):
            if cancelled(jid): return
            name = A.SITE_NAME.get(p["site"], p["site"])
            put(jid, progress=lo + int((hi - lo) * n / len(todo)), message=f"{label}: {name} ({n + 1} de {len(todo)})")
            d = br.read(p["url"], p["js"], p.get("viewport", "tall"))
            save(os.path.join(P(), bdir, "pages", f"{p['i']:03d}.json"), d)
            log(f"  page {p['i']} {p['site']}:", "BLOCKED " + str(d.get("title")) if d.get("blocked") else f"{d.get('n')} read, {len(d.get('rows', []))} kept")
    finally:
        br.close()

def read_queue(jid, queue, outdir, js, lo, hi, label, skip_site=None):
    """Listing pages (check_queue.json entries) -> <outdir>/<key>.json, with photo_pick.js or listing.js."""
    os.makedirs(outdir, exist_ok=True)
    todo = [q for q in queue if not os.path.exists(os.path.join(outdir, safe(q["key"]) + ".json"))]
    if not todo: return
    br = Browser()
    try:
        for n, q in enumerate(todo):
            if cancelled(jid): return
            url = direct(q["url"])
            if SKIP_HOSTS.search(url) or (skip_site and skip_site(q)): continue
            # eBay item pages turn the hidden browser away ("Error Page", 28 October 2026); with the API keys eBay rows are live
            # (ebay_api.py, check_all.py, app_images.py ask the API), so the page adds nothing
            if HAS_KEYS and re.search(r"//(?:www\.)?ebay\.", url): continue
            if n % 5 == 0: put(jid, progress=lo + int((hi - lo) * n / len(todo)), message=f"{label} ({n + 1} de {len(todo)})")
            d = br.read(url, js)
            if d.get("blocked"): log("  blocked:", url, d.get("title")); continue   # not saved: no verdict
            save(os.path.join(outdir, safe(q["key"]) + ".json"), d)
    finally:
        br.close()

def direct(url):
    """Mercari and Rakuma were checked on Buyee, which turns automated browsers away: their own item pages instead."""
    m = re.search(r"buyee\.jp/mercari/item/(m\d+)", url)
    if m: return f"https://jp.mercari.com/item/{m.group(1)}"
    m = re.search(r"buyee\.jp/rakuma/item/([0-9a-f]+)", url)
    if m: return f"https://item.fril.jp/{m.group(1)}"
    return url

# ---------------------------------------------------------------- what to type (what Claude decided with app_job.py plan)
NAMES = None
def names():
    global NAMES
    if NAMES is None:
        NAMES = load(os.path.join(SCREENER, "pokemon_names.json"), {}).get("pokemon", [])
        NAMES.sort(key=lambda x: -len(x["en"]))   # "Mr. Mime" before "Mime"
    return NAMES

# card words sellers write in Japanese: English word -> (typed on Japanese sites, also accepted in titles)
WORDS_JA = {"masaki": "マサキ", "promo": "プロモ", "holo": "ホロ", "shiny": "色違い", "delta": "δ", "trainer": "トレーナー",
            "stamp": "スタンプ", "stamped": "スタンプ", "japanese": "", "japan": "", "card": "", "pokemon": "", "pokémon": "",
            "gold": "☆", "star": "", "goldstar": "☆", "1st": "1ED", "first": "1ED", "edition": "", "ed": "", "psa": "PSA",
            "play": "PLAY", "unlimited": "", "lot": "", "rare": ""}

# words that are not part of the card (owner, 28 October 2026: "entei gold star en idioma español" found nothing because every title
# had to contain "en", "idioma" and "español")
FILLER = {"en", "de", "del", "la", "el", "los", "las", "y", "e", "con", "idioma", "language", "lang", "version", "versión", "carta",
          "cartas", "card", "cards", "pokemon", "pokémon", "tcg", "the", "in", "of", "a", "an", "and", "for", "por", "para"}
# a language in the search is a filter: the title must say it (sellers write it), and Japanese-only shops are left out unless Japanese
LANGS = {
    "es": (r"espa[ñn]ol|spanish|castellano|\bspa\b|\besp\b", {"español", "espanol", "spanish", "castellano", "española", "espanola"}),
    "ja": (r"japan\w*|jap[oó]n\w*|japonesa|\bjpn?\b|\bjp\b|日本|[ぁ-んァ-ン]", {"japonés", "japones", "japanese", "japonesa", "japón", "japon", "jpn", "jp"}),
    "en": (r"english|ingl[eé]s|\beng\b|englisch|inglese|anglais", {"inglés", "ingles", "english", "eng"}),
    "fr": (r"french|fran[cç]ais|franc[eé]s|fran[zc]ösisch|francese|\bfra?\b", {"francés", "frances", "french", "français", "francais"}),
    "de": (r"german|deutsch|alem[aá]n|tedesco|allemand|\bger\b", {"alemán", "aleman", "german", "deutsch"}),
    "it": (r"italian\w*|italiano|italien|\bita\b", {"italiano", "italian", "italiana"}),
}
JP_SITES = {"mercari", "rakuma", "magi", "cardrush", "snkrdunk", "hareruya2", "rakuten", "buyee", "paypay", "yshop", "mandarake", "yuyutei", "clabo", "jauce"}
# two kinds of search (owner, 1 November 2026): "light", quick (eBay and the three biggest Japanese sites), and "full", slow (every
# market, plus Japanese shops such as Mandarake, Yuyu-tei and Card Labo, and the collectors' forum Elite Fourum)
LIGHT_SITES = ("mercari", "snkrdunk", "magi")
FULL_SITES = ("mercari", "rakuma", "magi", "cardrush", "snkrdunk", "hareruya2", "rakuten", "mandarake", "yuyutei", "clabo", "gempire", "vinted",
              "elitefourum", "buyee", "wallapop", "jauce", "cherry", "monstermart", "pokemonplug", "japantcg")
def depth_of(j): return "light" if (j or {}).get("depth") == "light" else "full"

def plan_spec(query):
    """Typed search -> app_job.py spec: words every title must have (en), Japanese name (ja), what is typed on Japanese sites (qja),
    the Pokémon named (poke), the Japanese spellings each word is also accepted as (alias) and the card's language (lang)."""
    q = unicodedata.normalize("NFKC", query).strip()
    lang = next((c for c, (_, ws) in LANGS.items() for w in re.findall(r"[^\s,.;]+", q.lower()) if w in ws), None)
    drop = FILLER | {w for _, ws in LANGS.values() for w in ws}
    q = " ".join(w for w in q.split() if w.lower().strip(",.;") not in drop) or q
    low = q.lower()
    poke, ja_names, alias = [], [], {}
    for p in names():
        m = re.search(rf"(?<![a-z]){re.escape(p['en'].lower())}(?![a-z])", low)
        if m and not any(p["en"] in x for x in poke):
            poke.append(p["en"]); ja_names.append(p["ja"])
            key = p["en"].lower().split()[0]
            alias[key] = [p["ja"]] + [n for n in (p.get("fr"), p.get("de"), p.get("es")) if n and n.lower() != p["en"].lower()]
            # sellers drop the accents ("Brasegali" for Braségali)
            plain = lambda s: unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
            alias[key] += [plain(n) for n in alias[key] if plain(n) and plain(n) != n and plain(n).lower() != p["en"].lower()]
    words = re.findall(r"[^\s]+", low)
    qja = list(ja_names)
    for w in words:
        if re.fullmatch(r"#?\d+/\w+", w): qja.append(w.lstrip("#").upper())
        elif w in WORDS_JA and WORDS_JA[w] and WORDS_JA[w] not in qja: qja.append(WORDS_JA[w])
        if w in ("masaki",): alias.setdefault(w, []).append("マサキ")
    has_ja = bool(re.search(r"[぀-ヿ一-鿿]", q))
    # the Pokémon first: the page readers keep rows by the first word and its Japanese name
    lead = [p.lower() for p in poke]
    rest = re.sub("|".join(re.escape(x) for x in lead), " ", low) if lead else low
    en = " ".join(lead + rest.split())
    spec = {"en": en, "ja": ja_names[0] if ja_names else (q if has_ja else ""), "qja": " ".join(qja) if ja_names else (q if has_ja else ""),
            "q": q, "poke": poke, "alias": alias, "must": [], "not": []}
    if lang:
        spec["lang"] = lang; spec["must"] = [LANGS[lang][0]]
        if lang != "ja":   # no Japanese-name search for a Spanish or English card; eBay is also asked with the language word
            spec["ja"], spec["qja"] = "", ""
            spec["extra_q"] = [f'{" ".join(lead + rest.split())} {dict(es="español", en="english", fr="français", de="deutsch", it="italiano")[lang]}']
    if re.search(r"gold\s*star|goldstar", low) and not re.search(r"celebrations|25th|anniversary|classic", low):
        # a Gold Star means the 2004-2007 card, as in the Gold Stars collection: not the 2021 reprints (Celebrations Classic
        # Collection, 25th Anniversary 012/025 s8a-P) nor the toys and decorations Japanese sellers write ☆ on; app_job.goldstar_rule
        # adds the collection's own rules (the Pokémon next to the star, no fakes, no modern cards)
        spec["goldstar"] = True
        spec["not"] = [r"celebrations?|celebraciones|c[ée]l[ée]brations|25th|25\s*th|anniversary|aniversario|anniversario|classic\s*collection|s8a"
                       r"|(?<!\d)0?12\s*/\s*025(?!\d)|25周年|メンコ|☆\s*フレンズ|フレンズ\s*☆",
                       # modern cards, toys and fan-made or fake cards that get ☆ or "gold star" in the title
                       # (not "EX": the Gold Stars are EX-era cards; "☆4" is a Frenda rank, "☆ 004/075" a card number)
                       r"vmax|vstar|\bsv\d|\bs\d{1,2}[a-z]\b|フレンダ|☆\s*[1-6](?![\d/]|\s*(?:ed|st))|ネックレス|ピアス|クリアファイル|マスコット|デュエル"
                       r"|fan[aá]tic|fan[\s-]*made|pixel\s*art|perler|pyssla|database|pok[eé]mon\s*attacks?|pokescam|mercurymoon",
                       # the reprints' other names, "No Rayquaza Gold Star" titles selling another card, and sealed packs
                       r"\bcel\b|gran\w*\s*f[eê]sta|grand\s*party|\b2021\b|25\s*°|\b(?:no|without|sin|sans|ohne|senza)\b[^|]{0,25}(?:gold\s*star|estrella\s*dorada|stella\s*d'?oro)|\bno\s+goldstar"
                       r"|booster\s*pack|\bsealed\b|\bsketch\b|未開封|テープ|シール|ステッカー|グッズ|ポケモンセンター"]   # not パック: 拡張パック is the expansion
    return spec

def exact_card(spec):
    """When the search names a set or a number, the exact card (carta.py): titles must name its set in any language or its number
    instead of the English set words ("Gardiens du Pouvoir" for Power Keepers), and a stamped search must say stamp in the title."""
    import carta
    try:
        card = carta.identify(spec)
    except Exception as e:
        log("  card not identified:", type(e).__name__); card = None
    if not card or spec.get("goldstar"): return spec
    spec["card"] = card
    setw = {w for n in card["set_names"] for w in carta._words(n)}
    spec["en"] = " ".join(w for w in spec["en"].split() if w not in setw and not re.fullmatch(r"#?\d+/\d+", w)) or spec["en"]
    spec["must"] = list(spec.get("must") or []) + [carta.must(card)]
    if card["stamped"]:
        spec["not"] = list(spec.get("not") or []) + [r"\b(?:no|non|not|sin|without|sans|ohne)[\s-]*(?:stamp|stamped|sello|tampon)\w*|\bunstamped\b"]
    if card["name"].lower() in [p.lower() for p in spec.get("poke") or []]:   # the plain card: not its ex, GX, V, δ... versions
        names = [card["name"]] + spec.get("alias", {}).get(card["name"].lower().split()[0], [])
        spec["not"] = list(spec.get("not") or []) + [r"(?:" + "|".join(map(re.escape, names)) + r")[\s-]*(?:ex|gx|v|vmax|vstar|lv\.?\s*x|δ|delta|break|prime|legend)\b"]
    return spec

# ---------------------------------------------------------------- the checks Claude did by eye
def check_photos(sid=None, group=False):
    """Grade/edition from the label and photo-vs-card for the listings of one search (or both groups). Writes data/app/grades.json
    (only listings nobody read by hand) and data/app/photo_auto.json; save_search applies them."""
    import leer_etiqueta as E, comprobar_foto as C
    grades, auto = load(P("app", "grades.json"), {}) or {}, load(P("app", "photo_auto.json"), {}) or {}
    checks = load(P("app", "checks.json"), {}) or {}
    files = [A.search_path(g) for g in A.GROUPS] if group else [A.search_path(sid)]
    n_g = n_p = n_out = n_doubt = 0
    for f in files:
        s = load(f)
        if not s: continue
        spec = s.get("spec") if s.get("kind") == "text" else None
        snots = [re.compile(x, re.I) for x in (spec or {}).get("not", [])]
        keep = []
        for l in s.get("listings", []):
            img = l.get("image")
            k = l["id"]
            # a collection's card: its other prints named in cards.json ("25th Anniversary reprint 012/025", World Champions Pack...)
            nots = snots or other_prints(l.get("card"))
            if img and k not in grades:
                r = E.read(img)
                grades[k] = {"at": A.now_iso(), "image": img, "title": l.get("title"), "said": "auto",
                             **({"grade": r["grade"], "edition": r.get("edition"), "text": r.get("text")} if r else {})}
                n_g += bool(r)
            if img and l.get("card") and k not in auto:
                v, sc = C.check(k, img, l["card"])
                auto[k] = {"at": A.now_iso(), "verdict": v, "score": sc}; n_p += v == "ok"
            # a typed search: what the photo says counts like the title (owner, 28 October 2026: "Umbreon Gold Star Japanese PSA 10"
            # was the 2021 25th Anniversary reprint; its PSA label says so)
            if nots:
                # and so do the eBay item specifics (app_images.py: "Set: Celebrations", "Year Manufactured: 2021")
                asp = ((checks.get(k) or {}).get("price") or {}).get("aspects") or ""
                hit = next((m.group(0) for x in nots for m in [x.search(asp)] if m), None)
                if hit:
                    auto[k] = {"at": A.now_iso(), "verdict": "other", "why": f"el anuncio de eBay dice «{hit}»"}; n_out += 1; continue
            if img and nots:
                g = grades.setdefault(k, {"at": A.now_iso(), "image": img, "title": l.get("title"), "said": "auto"})
                if "ocr" not in g: g["ocr"] = E.text(img)[:600]
                hit = next((m.group(0) for x in nots for m in [x.search(g["ocr"])] if m), None)
                if hit:
                    auto[k] = {"at": A.now_iso(), "verdict": "other", "why": f"la foto dice «{hit}»"}; n_out += 1; continue
            keep.append(l)
        # the card's art against its official scan: a Gold Star search, or a collection (each listing against its own Pokémon)
        if spec and spec.get("card") and spec["card"].get("image"):   # one exact card: its own official art
            n_doubt += art_check(keep, spec["poke"], auto, C, refs=C.card_refs(spec["card"]["image"]))
        elif spec and spec.get("goldstar") and spec.get("poke"): n_doubt += art_check(keep, spec["poke"], auto, C)
        elif spec: n_doubt += same_card(keep, spec, auto, C)
        else: n_doubt += art_check(keep, None, auto, C)
        if spec and spec.get("goldstar"):
            # an ungraded copy at a tenth of the cheapest graded one is a reprint, a fake or a wreck (owner, 28 October 2026: the
            # ungraded "2007 POP Series 5" Umbreons at 19-200 euros were 2021 reprints, the 25th logo on the card): hidden like a
            # doubtful photo, one tap away. Auctions are left alone (their price is the bid so far).
            graded = [l["price_eur"] for l in keep if l.get("grader") and l.get("price_eur") and l.get("sale") != "auction"]
            floor = min(graded) * 0.1 if graded else None
            for l in keep:
                if floor and not l.get("grader") and l.get("price_eur") and l["price_eur"] < floor and l.get("sale") != "auction":
                    l["price_warn"] = True
                else: l.pop("price_warn", None)
        s["listings"] = keep
        save(P("app", "grades.json"), grades); save(P("app", "photo_auto.json"), auto)
        A.save_search(s)
    log(f"  photo checks: {n_g} labels read, {n_p} photos confirmed, {n_out} left out by what the photo says, {n_doubt} photos unlike the rest")

def cardmarket_guide(spec):
    """Cardmarket's price guide for the card searched, as pokemontcg.io republishes it (owner, 28 October 2026: "Spanish Entei Gold
    Stars are on Cardmarket"; Cardmarket turns automated browsers away and its API is closed to private users, so the app shows its
    published prices with a link to the offers there). English-print cards only; the date says how fresh the figures are."""
    import urllib.request, urllib.parse
    poke = spec.get("poke") or []
    num = re.search(r"(?<!\d)(\d{1,3})\s*/\s*\d{2,3}(?!\d)", spec.get("q") or "")
    if not poke or not (spec.get("goldstar") or num): return []
    out = []
    for p in poke[:2]:
        url = "https://api.pokemontcg.io/v2/cards?" + urllib.parse.urlencode({"q": f'name:"{p}*"', "select": "id,name,set,number,cardmarket", "pageSize": 250})
        data = None
        for attempt in range(3):   # the free API sometimes answers 5xx or times out
            try:
                data = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"user-agent": "PokeFinder"}), timeout=40)).get("data", [])
                break
            except Exception as e:
                err = type(e).__name__; time.sleep(4)
        if data is None:
            log("  Cardmarket price guide not available:", err); return out
        for c in data:
            if spec.get("goldstar") and not re.search(r"★|☆|\bstar\b", c["name"], re.I): continue
            if num and c.get("number") != num.group(1).lstrip("0"): continue
            pr = (c.get("cardmarket") or {}).get("prices") or {}
            if not pr.get("trendPrice") and not pr.get("lowPrice"): continue
            out.append({"name": c["name"], "set": c["set"]["name"], "number": f'{c["number"]}/{c["set"].get("printedTotal")}',
                        "url": c["cardmarket"].get("url"), "low": pr.get("lowPrice"), "trend": pr.get("trendPrice"),
                        "avg30": pr.get("avg30"), "updated": c["cardmarket"].get("updatedAt")})
    return out[:6]

def add_cardmarket(s, spec, group=None):
    """Cardmarket's products for the search (cardmarket.py, from Cardmarket's public daily files): replaces last run's. A collection
    gets only Japanese editions (Cardmarket added its Japanese sets from 2023 on; the collection is Japanese Gold Stars only)."""
    import cardmarket as CM
    s["listings"] = [l for l in s.get("listings", []) if l.get("site") != "cardmarket"]
    s["cardmarket"] = []   # the old price-guide box (pokemontcg.io, months old): the results themselves carry today's prices
    try:
        if group:
            for c in group["cards"]:
                for pr in CM.products(c["pokemon"], goldstar=True):
                    if pr["year"] < "2023": continue
                    l = CM.listing(pr, c["pokemon"], None); l["card"] = c["name_en"]; s["listings"].append(l)
        elif spec and spec.get("card"):     # one exact card: only its Cardmarket product (reverse-holo prices when stamped)
            s["listings"] += CM.card_listings(spec)
        elif spec and spec.get("goldstar") and spec.get("poke"):
            s["listings"] += CM.listings(spec)
        # any other search names no single card: Cardmarket would list every card of the Pokémon, so it is left out
        # no picture of the card (Japanese prints, or the picture service did not answer): the photo of a genuine listing of the
        # same Pokémon in the same search, a graded one when there is one
        own = [l for l in s["listings"] if l.get("site") != "cardmarket" and l.get("image") and not l.get("photo_doubt") and not l.get("price_warn")]
        for l in s["listings"]:
            if l.get("site") == "cardmarket" and not l.get("image"):
                same = [o for o in own if set(o.get("pokemon") or []) & set(l["pokemon"])]
                pick = next((o for o in same if o.get("grader")), same[0] if same else None)
                if pick: l["image"] = pick["image"]
    except Exception as e:
        log("  Cardmarket not added:", type(e).__name__, e)

_PRINTS = {}
def other_prints(card):
    """Patterns of a tracked card's other prints (cards.json other_versions keys), for its label and eBay item specifics."""
    if not card: return []
    if card not in _PRINTS:
        # not "1st" / "1ed": sellers tick "1st Edition" in eBay's item specifics on cards that have no editions
        keys = [k for c in A.CARDS if c["name_en"] == card for v in c.get("other_versions", []) for k in v.get("keys", [])
                if k.lower() not in ("1ed", "1st")]
        _PRINTS[card] = [re.compile("|".join(re.escape(k) for k in keys), re.I)] if keys else []
    return _PRINTS[card]

def art_check(listings, poke, auto, C, refs=None):
    """Owner, 28 October 2026: "if the card in the photo is not the card searched for, it is not, whatever the title says". Each
    photo against the official art of the Pokémon's Gold Star (comprobar_foto.art_score); under ART_MIN it is another card: hidden
    (photo_doubt), one tap away. Scores are kept per photo, so a refresh only looks at new photos."""
    n = 0
    grades = load(P("app", "grades.json"), {}) or {}
    for l in listings:
        img, k = l.get("image"), l["id"]
        if l.get("site") == "cardmarket" or not img: continue
        mine = [p for p in (l.get("pokemon") or []) if not poke or p in poke] or (poke or [])[:1]
        if not mine: continue
        prev = auto.get(k) or {}
        if prev.get("verdict") == "other": continue
        # the grading label says Gold Star ("TREECKO-HOLO/G.S.", "GOLD STAR"): the grader held the card, that wins over the photo
        lab = " ".join(str((grades.get(k) or {}).get(x) or "") for x in ("text", "ocr")).upper()
        if re.search(r"GOLD\s*STAR|\bG\.\s*S\.|GLD\.?\s*STAR", lab):
            auto[k] = {"at": A.now_iso(), "verdict": "ok", "by": "label says Gold Star", "art_img": img}; continue
        against = "card" if refs is not None else "goldstar"
        if prev.get("art_img") == img and "art" in prev and prev.get("art_vs") == against:
            sc = prev["art"]
        else:
            rf = refs if refs is not None else C.art_refs(mine[0], True)
            if not rf: continue
            sc = C.art_score(img, rf)
        if sc is None: continue
        v = "wrong" if sc < C.ART_MIN else ("ok" if sc >= 40 else None)
        auto[k] = {"at": A.now_iso(), "verdict": v, "art": sc, "art_img": img, "art_vs": against, "by": "art",
                   **({"why": "el dibujo de la foto no es el de la carta"} if v == "wrong" else {})}
        n += v == "wrong"
    return n

def same_card(listings, spec, auto, C):
    """A typed search: each photo compared with the other results' photos (and the collection's confirmed photos of that Pokémon's
    Gold Star). One that looks like none of them (a Pikachu, another Umbreon card) is flagged photo_doubt, hidden until asked for."""
    refs = [u for c in A.CARDS if c["pokemon"] in (spec.get("poke") or []) for k, u in C.references().get(c["name_en"], [])][:12]
    photos = [(l["id"], l["image"]) for l in listings if l.get("image")]
    if len(photos) + len(refs) < 5: return 0
    desc = {}
    for k, u in photos + [("ref", u) for u in refs]:
        try: desc[u] = C.descriptors(u)
        except Exception: desc[u] = None
    n = 0
    for k, u in photos:
        others = [x for kk, x in photos if kk != k]
        random.seed(k); others = random.sample(others, min(15, len(others))) + refs
        best = max([C.score(desc[u], desc[o]) for o in others] or [0])
        v = "wrong" if best < 30 else ("ok" if best >= C.RIGHT else None)
        if (auto.get(k) or {}).get("verdict") != "other": auto[k] = {"at": A.now_iso(), "verdict": v, "score": best, "by": "same search"}
        n += v == "wrong"
    return n

def play_photos(jid):
    """Play promo photo checks (goldstar.py photo_queue.json -> browser/photos/<key>.json), what Claude read on the label or card."""
    import leer_etiqueta as E, comprobar_foto as C
    q = load(P("browser", "photo_queue.json"), [])
    outdir = P("browser", "photos"); os.makedirs(outdir, exist_ok=True)
    todo = [x for x in q if not os.path.exists(os.path.join(outdir, safe(x["key"]) + ".json"))]
    if not todo: return False
    imgs = {}
    read_queue(jid, todo, P("browser", "photo_pick"), PHOTO_JS, 86, 89, "Mirando las fotos de los Play promos")
    for x in todo:
        d = load(os.path.join(P("browser", "photo_pick"), safe(x["key"]) + ".json")) or {}
        img = d.get("img")
        out = {"card_number": None, "edition": None, "matches": None, "text": "", "reason": "photo not read"}
        if img:
            r = E.read(img) or {}
            text = (r.get("text") or "").upper()
            num = re.search(r"#?0?(2[2-6])\b.*(?:PLAY|PROMO|PTS)|(?:PLAY|PROMO|PTS).*#?0?(2[2-6])\b", text)
            if re.search(r"WORLD\s*CHAMP|0?\d{2}\s*/\s*108|2007", text):
                out.update(matches=False, text=text[:200], reason="label of another print (World Champions Pack / 108)")
            elif num:
                out.update(card_number=f"0{num.group(1) or num.group(2)}/PLAY", matches=True, text=text[:200], reason=None)
            else:
                v, sc = C.check(x["key"], img, x.get("card"))
                if v == "ok": out.update(matches=True, reason=f"photo matches confirmed photos of the card ({sc})")
                else: out.update(reason=f"not confirmed on the photo ({sc})", text=text[:200])
        save(os.path.join(outdir, safe(x["key"]) + ".json"), out)
    return True

def buyable(jid, searches, lo, hi):
    """app_images.py prepare -> every non-eBay listing page opened -> apply (what cannot be bought leaves every search)."""
    run(["app_images.py", "prepare"] + [a for s in searches for a in ("--search", s)])
    qdir = P("app", "images", "browser")
    queue = load(os.path.join(qdir, "check_queue.json"), [])
    read_queue(jid, queue, os.path.join(qdir, "photo"), PHOTO_JS, lo, hi, "Comprobando que se pueden comprar")
    run(["app_images.py", "apply"])

# ---------------------------------------------------------------- the two kinds of job
def typed(jid):
    j = job(jid); bdir = j["browser_dir"]
    if HAS_KEYS and not os.path.exists(os.path.join(P(), bdir, "pages", "000.json")):
        put(jid, status="ebay", progress=6, message="Buscando en eBay (API)…")
        run(["app_job.py", "ebay", jid], check=False)
    spec = exact_card(plan_spec(j["query"]))
    jj = job(jid); jj["spec"] = spec; save(A.job_path(jid), jj)
    sites = [s for s in (LIGHT_SITES if depth_of(j) == "light" else FULL_SITES)
             if s not in SKIP and not (spec.get("lang") not in (None, "ja") and s in JP_SITES)]   # Japanese shops sell Japanese cards
    run(["app_job.py", "plan", jid, "--q", spec["q"], "--sites", ",".join(sites)])
    put(jid, status="running", message="Buscando en los mercados…")
    read_pages(jid, bdir, 15, 75, "Leyendo")
    if cancelled(jid): return
    run(["app_job.py", "finish", jid])
    partial(j["search_id"])
    put(jid, status="running", progress=78, message="Comprobando anuncios…")
    buyable(jid, [j["search_id"]], 78, 90)
    put(jid, progress=91, message="Leyendo las notas en las fotos…")
    check_photos(j["search_id"])
    s = load(A.search_path(j["search_id"]))
    if s:
        s["status"] = "done"
        add_cardmarket(s, spec)
        A.save_search(s)
    phone_results([j["search_id"]])
    put(jid, status="done", progress=100, finished=A.now_iso(), message="Búsqueda terminada")

def group(jid):
    j = job(jid); g = j["group"]
    mode = "quick" if g == "play_promos" else "others"
    if not j.get("planned"):   # a refresh cut off (the app closed) carries on from the pages already read
        put(jid, status="running", progress=5, started=A.now_iso(), message="Preparando la búsqueda…")
        run(["start_run.py"]); run(["fx.py"], check=False)
        run(["make_plan.py", mode] + (["--light"] if depth_of(j) == "light" else []))
        if HAS_KEYS:
            put(jid, progress=8, message="Buscando en eBay (API)…"); run(["ebay_api.py", mode])
        put(jid, planned=True)
    else:
        put(jid, status="running", message="Sigue la búsqueda donde se quedó…")
    read_pages(jid, "browser", 10, 55, "Leyendo")
    run(["snkr_learn.py"], check=False)
    read_pages(jid, "browser", 55, 62, "Leyendo SNKRDUNK")
    if cancelled(jid): return
    run(["goldstar.py"])
    if mode == "others": run(["check_all.py"], check=False)
    q = load(P("browser", "check_queue.json"), [])
    read_queue(jid, q, P("browser", "listing"), LISTING_JS, 62, 80, "Comprobando que siguen a la venta",
               skip_site=lambda x: mode == "others" and "mercari" in (x.get("url") or ""))   # Mercari is searched on_sale only
    run(["goldstar.py"])
    if play_photos(jid): run(["goldstar.py"])
    run(["app_export.py"])
    put(jid, progress=90, message="Comprobando anuncios…")
    buyable(jid, [g], 90, 95)
    put(jid, progress=95, message="Leyendo las notas en las fotos…")
    check_photos(group=True)
    for gid in A.GROUPS:
        s = load(A.search_path(gid))
        if s: add_cardmarket(s, None, group=A.GROUPS[gid]); A.save_search(s)
    phone_results(list(A.GROUPS))
    put(jid, status="done", progress=100, finished=A.now_iso(), message="Búsqueda terminada")

# sold listings (owner, 3 November 2026: "see which have sold since the last search, as a filter, in green"): a listing of the last
# run that this run no longer finds is kept, marked sold, when its market was read this time (it has listings in this run) or the
# listing page said it can no longer be bought; a market that could not be read (eBay's daily limit, a security check) proves nothing.
# A listing that is gone may also have been withdrawn by its seller: the app says "sold or withdrawn". Kept 90 days.
SOLD_DAYS = 90
def mark_sold(sid, prev):
    s = load(A.search_path(sid))
    if not s or not prev: return 0
    today = A.now_iso()[:10]
    live = [l for l in s.get("listings", []) if not l.get("sold")]
    ids, read = {l["id"] for l in live}, {l["site"] for l in live}
    gone = set(load(P("app", "images", "gone.json"), []))
    old = (dt.date.today() - dt.timedelta(days=SOLD_DAYS)).isoformat()
    sold, n = [], 0
    for l in prev:
        if l["id"] in ids or l.get("site") == "cardmarket": continue   # still for sale; Cardmarket shows products, not listings
        if l.get("sold"):
            if (l.get("sold_at") or today) >= old: sold.append(l)
        elif l["id"] in gone or l.get("site") in read:
            sold.append({**l, "sold": True, "sold_at": today, "status": "Sold"}); n += 1
    s["listings"] = live + sold
    A.save_search(s)
    log(f"  {sid}: {n} listings sold or withdrawn since the last run ({len(sold)} kept as sold)")
    return n

def run_job(jid):
    j = job(jid)
    if not j: return
    log(f"job {jid} [{j['kind']}] {j['label']}")
    sids = list(A.GROUPS) if j["kind"] == "group" else [j["search_id"]]   # a collection run refreshes both collections
    prev = {sid: (load(A.search_path(sid)) or {}).get("listings", []) for sid in sids}
    try:
        (group if j["kind"] == "group" else typed)(jid)
        if not cancelled(jid) and (job(jid) or {}).get("status") == "done":
            if sum(mark_sold(sid, prev[sid]) for sid in sids): phone_results(sids)
        log(f"job {jid} done")
    except Exception as e:
        log(f"job {jid} failed:", traceback.format_exc()[-800:])
        put(jid, status="error", message=f"No se pudo terminar la búsqueda ({type(e).__name__}).")
        s = load(A.search_path(j["search_id"]))
        if s: s["status"] = "done" if s.get("listings") else "error"; A.save_search(s)

# ---------------------------------------------------------------- the phone page (only the copy that owns it)
def cloud_on():
    try:
        import nube
        return nube.enabled()
    except Exception:
        return False

def phone_job(jid):
    if not cloud_on(): return
    try:
        import nube, io, contextlib
        with contextlib.redirect_stdout(io.StringIO()): nube.job_cmd(jid)
    except (Exception, SystemExit):
        pass

def phone_results(sids):
    if not cloud_on(): return
    try:
        import nube
        for sid in sids: nube.push_results(sid)
    except (Exception, SystemExit) as e:
        log("  phone page not updated:", e)

def partial(sid):
    """Every market read, before the checks. Nothing to do here; a phone search on GitHub (cloud/github/buscar.py) sends the
    results so far to the phone at this point."""

def phone_requests():
    if not cloud_on(): return
    try:
        import nube, io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            nube.status_cmd(True, quiet=True); nube.requests_cmd()
    except (Exception, SystemExit) as e:
        log("  phone page:", type(e).__name__, e)

# ---------------------------------------------------------------- the loop
def waiting():
    out = []
    for f in sorted(glob.glob(P("app", "jobs", "*.json")), key=os.path.getmtime):
        try: j = load(f)
        except (OSError, ValueError): continue
        if not j or j.get("status") not in ("queued", "waiting_claude", "claimed", "running"): continue
        if j.get("status") == "ebay": continue
        out.append(j)
    # a typed search takes minutes, a collection refresh up to two hours: typed searches go first
    return sorted(out, key=lambda j: j.get("kind") == "group")

def server_up():
    import socket
    try:
        socket.create_connection(("127.0.0.1", int(os.environ.get("PORT", "8800"))), timeout=2).close(); return True
    except OSError:
        return False

def main():
    first = True; next_cloud = 0; down_since = None
    while True:
        if server_up(): down_since = None
        else:   # the app was closed: stop with it (server.py starts a new engine next time)
            down_since = down_since or time.time()
            if time.time() - down_since > 120: log("the app is closed: engine stops"); return
        save(BEAT, {"listening": True, "engine": True, "at": time.time(), "pid": os.getpid()})
        if time.time() > next_cloud:
            phone_requests(); next_cloud = time.time() + 60
        jobs = waiting()
        for j in jobs:
            if j["status"] in ("claimed", "running") and not first: continue   # someone else (Claude) has it
            save(BEAT, {"listening": True, "engine": True, "working": [j["id"]], "at": time.time(), "pid": os.getpid()})
            run_job(j["id"])
        first = False
        time.sleep(3)

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 2 and sys.argv[1] == "run":
        run_job(sys.argv[2])
    else:
        old = load(BEAT, {}) or {}
        if old.get("engine") and time.time() - old.get("at", 0) < 20 and old.get("pid") != os.getpid():
            sys.exit("motor.py is already running")
        main()
