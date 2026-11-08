"""Market tracking, phase 1 (owner, 2 November 2026: "analisis de mercado"): one eBay snapshot per day of the cards the owner follows.

What is followed: the Gold Star cards (screener/cards.json, first query of ebay_api.queries) and every query of the folders in data/app/folders.
Each snapshot asks the eBay Browse API (the same keys as the searches, .secrets/ebay_api.json) for the listings of each one on a few eBay sites and
saves data/mercado/AAAA-MM-DD.json. Compared with the previous snapshot it gives: listings now, new ones, ones that no longer appear, price changes,
minimum and median price in euros. Browse cannot see sold items, so "ya no aparecen" means sold, ended or pushed out of the first
MAX_ITEMS results: it is never called "sold".
Files: data/mercado/ultimo.json (diff of the latest snapshot), historial.json (per-card numbers day by day, for the charts), estado.json (running or not).
The server asks toca() every half hour and starts "python mercado.py" once a day when the computer is on; "Hacer foto ahora" in the app does it too.
Usage: python mercado.py [--lista] [--max N]   (--lista only prints what would be asked; --max N follows only the first N cards)"""
import datetime as dt, json, math, os, re, statistics, subprocess, sys, time, unicodedata
from concurrent.futures import ThreadPoolExecutor
from common import P, load, save, SCREENER, ROOT, TZ

MARKETS = ["EBAY_US", "EBAY_GB", "EBAY_DE", "EBAY_ES", "EBAY_FR", "EBAY_IT"]   # a snapshot has to be cheap: the eBay quota is 5,000 calls a day, shared with the searches
MAX_ITEMS = 400            # per card and eBay site (2 calls of 200)
CALL_BUDGET = 1800         # stop asking after this many calls: the searches of the day keep the rest of the quota
KEEP_DAYS = 120
DIR = P("mercado")

def today(): return dt.datetime.now(TZ).date().isoformat()
def now_iso(): return dt.datetime.now(TZ).isoformat(timespec="minutes")

REQ = {}      # track key -> what a listing's title must name to count as THAT card (filled by tracks())
STOP = {"japanese", "japan", "english", "card", "cards", "pokemon", "pokémon", "gold", "star", "call", "of", "legends", "campaign", "set", "promo", "promos",
        "present", "the", "and", "holo", "rare", "play", "players"}
STAR = re.compile(r"[☆★]|gold\s*star|goldstar|(?<!black\s)\bstar\b(?!\s*promo)|スター|ゴールド|\bgs\b", re.I)   # "Black Star Promo" is a set, not a Gold Star

def _word(w, t): return re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", t) is not None

NOT_CARD = re.compile(r"jewel\w*|joyer[ií]a|earrings?|ear\s*cuff|necklace|pendant|bracelet|\bring\b|\bcharm\b|lanyard|\bhoodie\b|\bhat\b|\bcap\b|\bbag\b|\bpouch\b|\bbox\s*set\b|\bmetal\b|(?:display|art(?:work)?|extended|magnetic|magn[eé]tic[oa]?|acrylic|acr[ií]lic[oa]|protective|graded|slab|top\s*loader|toploader|one\s*touch|screw\s*down)\s*(?:art(?:work)?\s*)?(?:case|holder|stand|frame|display|sleeve)\b|estuche|custodia|\bfunda\b|etui|\bh[uü]lle\b|coque|schl\w*ssel|anh\w*nger|\binserto?s?\b|\binserts?\b|carpeta|metal\s*card|for\s*display|acryl|magnet|sticker|pegatina|adesiv\w+|aufkleber|keyring|llavero|portachiavi|fan\s*art|\bproxy\b|replica|reproduction|inspired|\borica\b|custom\s*card|mystery|loot\s*box|lucky\s*(?:pack|box)|blind\s*(?:pack|box)|surprise|skin\s*slab|slab\s*skin|\bskin\b|decal|vinyl|wall\s*(?:art|decor)|canvas|lienzo|poster|p[oó]ster|\bframe[sd]?\b|marco\b|cornice|cadre|rahmen|mousepad|mouse\s*pad|tappetino|alfombrilla|playmat|mauspad|sleeves?\b|binder|figur(?:e|ine)|plush|peluche|keychain|\bcoin\b|\btoy\b|funko|\bdvd\b|\bcd\b|\bt-?shirt\b|\bpin\b|badge|manga|artbook|puzzle|\bmug\b|\bglitch\b|sellad[oa]\s*booster|booster\s*(?:box|pack)"
                      # fakes and altered cards (owner, 2 November 2026: "que no se cuelen fakes"): gold-foil and metal copies, customs, reprints, altered art
                      r"|gold\s*foil|goldfoil|metall[oi]\b|\bargento\b|\bcustom\b(?!\s*(?:case|display|stand|box))|(?<!not\s)(?<!no\s)\balter(?:ed|ation)?\b"
                      r"|(?<!not\s)(?<!not\sa\s)(?<!no\s)\breprints?\b|(?<!not\s)(?<!not\sa\s)(?<!no\s)\bfakes?\b|counterfeit|bootleg|unofficial|novelty|fan\s*-?\s*made|hand\s*-?\s*made"
                      r"|not\s*(?:real|original|authentic|official)\b"
                      # slab accessories: "Extended Artwork For PSA CGC BGS or TAG", "Vitrina de arte extendido"
                      r"|extended\s*art(?:work)?\b|vitrina|\bfor\s+(?:psa|cgc|bgs|tag|beckett)\b", re.I)
# not ONE card: lots and bundles ("ALL 151+ COMPLETE SETS", "Celebi Gold Star + Shining Celebi + ...", "9-Card Holo Lot", Italian "Lotto")
LOTE = re.compile(r"\blot\b|\blotto\b|\blote\b|\bbundle\b|complete\s*sets?\b|\bset\s*of\s*\d|\d+\s*-?\s*cards?\s*(?:holo\s*)?lot|\s\+\s*(?:[a-z]+\s+)?(?:shining|gold\s*star|others?|more|extras?|bonus|cards?)\b", re.I)
# languages these cards were never printed in: a Chinese or Korean "Gold Star" or "Shining" is another product or a fake (unless the search asks for it)
OTRO_IDIOMA = re.compile(r"\bchinese\b|\bsimplified\b|\bkorean\b|\bkor\b|\bchn\b|\bthai\b|\bindonesian\b|中文|简体|繁體|한국", re.I)

def _ruido(req, title):
    """Not that card even though it names it: an object that is not a card (sticker, Mezastar tag, plush, a gold-foil fake...), a lot, a language the search
    does not ask for, or a title padded with the names of the OTHER cards followed."""
    t = (title or "").lower()
    if NOT_CARD.search(title or "") or LOTE.search(title or ""): return True
    if OTRO_IDIOMA.search(title or "") and not any(OTRO_IDIOMA.search(w) for w in (req.get("words") or []) + (req.get("incluir") or [])): return True
    return any(_word(o, t) or (not o.isascii() and o in title) for o in req.get("others") or [])

# the grade may come after a few words ("PSA MINT 9", "CGC Graded Pristine 10", "PSA GEM MT 10")
GRADER_RX = re.compile(r"\b(psa|bgs|beckett|cgc|sgc|ace|tag|csg|ags|ars|pca)\s*-?\s*(?:(?:gem|mint|mt|nm|near|pristine|perfect|black|gold|label|graded?|grade)[\s\-]+){0,3}(\d{1,2}(?:\.\d)?)\b", re.I)
HOUSE_RX = re.compile(r"\b(psa|bgs|beckett|cgc|sgc|csg|ags|ars|pca)\b", re.I)
SLAB_HINT = re.compile(r"authentic|\bauth\b|\bau\b|appraised|label|slab|graded|\bcert|\bpop\s*\d|encapsulated|pristine", re.I)
RAW_WORD = re.compile(r"\braw\b|ungraded|not\s*graded|\b(?:lp|mp|dmg|damaged|played)\b", re.I)
GRADED_WORD = re.compile(r"(?<!not\s)(?<!non-)(?<!non\s)(?<!never\s)\b(?:graded|slab(?:bed)?|encapsulated)\b", re.I)
RAW_AFTER = re.compile(r"\s*(?:\?|candidat|ready|worthy|potential|quality|possible|contender)", re.I)          # "PSA 10 candidate", "PSA 9 quality": raw
RAW_BEFORE = re.compile(r"\b(?:potential|possible|future|candidate\s*for|ready\s*for|for|to|not(?:\s+an?)?|no|non)[\s\-]*$", re.I)   # "potential PSA 10", "ready for PSA", "not a PSA 10"
# Fernando, 5 nov: un Umbreon salió como chollo y el anuncio decía «not PSA 10». Una frase que dice que la carta NO está gradeada manda sobre el «PSA 10» que aparezca en el título:
# «ungraded, would grade PSA 10», «PSA 10 (not graded yet)», «raw»…
RAW_ANY = re.compile(r"\b(?:ungraded|not\s+(?:yet\s+)?graded|(?:would|could|should|might|may)\s+(?:grade|get|be|make|easily|likely)|grade\s+it\s+yourself|you\s+(?:can\s+)?grade|sin\s+gradear|no\s+graduad[ao])\b", re.I)
KANA_RX = re.compile(r"[぀-ヿ]")
JA_RX = re.compile(r"japan\w*|\bjpn\b|\bjp\b|\bjap\b|日本語", re.I)
OT_RX = re.compile(r"\bnachtara\b|\bnoctali\b|drachenwandel|evolution celeste|cieli in evoluzione|cielos evolutivos|\bevoluzione\b|\bvmax\s+(?:gigamax|alternativa)\b|\b(?:ita|ger|deu|fra|kor|esp)\b|\b(?:italiano|italian|deutsch|german|french|francais|spanish|espanol|korean|chinese|portugues)\b|\b(?:carta|carte|karte|tarjeta)\b", re.I)

def _grado(title):
    """(grader, grade) written in a title: ("PSA", "10"); ("PSA", None) for a slab whose grade is not written; or (None, None).
    "PSA 10 candidate", "PSA ready" or "potential PSA 10" describe a raw card."""
    t = title or ""
    if RAW_ANY.search(t): return None, None
    for m in GRADER_RX.finditer(t):
        if RAW_AFTER.match(t, m.end()) or RAW_BEFORE.search(t[max(0, m.start() - 20):m.start()]): continue
        return m.group(1).upper().replace("BECKETT", "BGS"), m.group(2)
    # without a grade: one house and a slab word ("PSA AUTHENTIC", "ARS AU", "CGC slab"); "PSA BGS CGC TAG" in a title is keyword padding
    houses = {h.upper().replace("BECKETT", "BGS") for h in HOUSE_RX.findall(t)}
    if len(houses) == 1 and SLAB_HINT.search(t) and not RAW_WORD.search(t): return houses.pop(), None
    return None, None

def _gradeada(it):
    """Graded, by eBay's own flag (condition "Graded"), a grading house in the title or the words "graded" / "slab"."""
    if RAW_ANY.search(it.get("t") or ""): return bool(it.get("g"))      # el título dice que NO está gradeada: solo vale el aviso propio de eBay (condición «Graded»)
    return bool(it.get("g")) or bool(_grado(it.get("t"))[0]) or bool(GRADED_WORD.search(it.get("t") or ""))

def _estado_ok(req, title, graded):
    """The owner's filter on raw / graded cards. graded: eBay's own flag (condition "Graded"), when the listing has it; the title's "PSA 10" counts too."""
    est = req.get("estado") or "todos"; g, n = _grado(title); es = _gradeada({"t": title, "g": graded})
    if est == "raw" and es: return False
    if est == "gradeadas" and not es: return False
    if est == "psa" and g != "PSA" and not (graded and re.search(r"\bpsa\b", title or "", re.I)): return False
    nota = str(req.get("nota") or "").strip()
    if nota:
        try:
            if not (n and abs(float(n) - float(nota)) < 1e-9): return False
        except ValueError: return False
    return True

def _idioma_ok(req, title):
    i = req.get("idioma") or "any"
    if i == "any": return True
    ja = bool(KANA_RX.search(title or "") or JA_RX.search(title or "")); ot = bool(OT_RX.search(_norm(title)))
    return (not ja and not ot) if i == "en" else (ja and not ot)

def _casa_label(it):
    g, n = _grado(it.get("t"))
    return g or ("Gradeada (otra casa)" if _gradeada(it) else "Sin gradear")

HOUSES = ["PSA", "TAG", "BGS", "CGC", "SGC", "ACE", "CSG", "AGS", "ARS"]
def _nota_orden(row):
    """PSA first, then TAG and the rest, each from its best grade down; ungraded last."""
    lab = row[0]; parts = lab.split()
    if parts[0] in HOUSES:
        try: return (HOUSES.index(parts[0]), -float(parts[1]))
        except (ValueError, IndexError): return (HOUSES.index(parts[0]), 0)
    return (50, 0) if lab.startswith("Gradeada") else (60, 0)

def _nota_label(it):
    g, n = _grado(it.get("t"))
    if g: return f"{g} {n}" if n else f"{g} (nota no indicada)"
    return "Gradeada (nota no indicada)" if _gradeada(it) else "Sin gradear"

def _norm(s):
    """Lower case without accents: "Pokémon" and "pokemon" are the same word in a title."""
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)).lower()

def matches(req, title, graded=None):
    """Does the title name THIS card? eBay's search returns whatever it finds (a seller's Chinese Gem Pack cards came up for "mew gold star"), so a listing counts
    only if it names the Pokémon (any of its names) and, for a Gold Star, a star (or the card's own number); for a folder card or a search of the owner's own,
    every word of the query and its number, plus the words the owner asked to include and none of the ones to exclude."""
    if _ruido(req, title): return False
    t = _norm(title); t2 = re.sub(r"\s+", "", t)
    if req.get("names"):
        if not any(_word(_norm(n), t) or (not n.isascii() and n in (title or "")) for n in req["names"]): return False
        return bool(STAR.search(title or "")) or any(n.lower() in t or n.lower() in t2 for n in req.get("numbers") or [])
    if not all(_word(_norm(w), t) for w in req.get("words") or []): return False
    if not all(_has(w, t) for w in req.get("incluir") or []): return False
    if any(_has(w, t) for w in req.get("excluir") or []): return False
    if not _estado_ok(req, title, graded) or not _idioma_ok(req, title): return False
    if req.get("num"):
        nn, dd = req["num"]
        for m in re.finditer(r"(?<!\d)(\d{1,3})\s*/\s*(\d{1,3})(?!\d)", title or ""):
            if int(m.group(2)) == dd and int(m.group(1)) != nn: return False          # another card of the same set
    for n in req.get("nums") or []:
        if n.isdigit():
            if not _word(n, t): return False       # "10" (PSA 10) is a word of its own, not the 10 inside 100
            continue
        if n in t or n in t2: continue
        m = re.match(r"0*(\d+)\s*/\s*0*(\d+)", n)
        if not (m and re.search(r"(?<!\d)0*%s\s*/\s*0*%s(?!\d)" % (m.group(1), m.group(2)), t)): return False
    return True

def _query_req(q):
    toks = q.lower().split()
    return {"words": [w for w in toks if re.fullmatch(r"[a-zà-ÿ'\-]+", w) and w not in STOP], "nums": [w for w in toks if re.search(r"\d", w)]}

# a search the owner writes himself ("Umbreon VMAX Evolving Skies PSA 10", "Call of Legends"): every word must be in the title, except the ones sellers often leave out
STOP_OWN = {"of", "the", "and", "a", "de", "la", "el", "pokemon", "card", "cards", "carta", "cartas", "english", "japanese", "japan", "ingles", "japones", "tcg", "ptcg", "en", "in"}
def _query_req_own(q):
    """A search line of the owner, with eBay's own syntax: «(a,b,c)» = any of them, «-(a,b)» or «-word» = none of them, everything else must be in the title."""
    inc, exc = [], []
    def grab(m):
        items = [_norm(x).strip() for x in m.group(2).split(",") if x.strip()]
        if items: (exc if m.group(1) else inc).append("|".join(items))
        return " "
    rest = re.sub(r"(-?)\(([^)]*)\)", grab, q or "")
    toks = []
    for w in _norm(rest).split():
        if w.startswith("-") and len(w) > 1: exc.append(w[1:])
        else: toks.append(re.sub(r"[\",]", "", w))
    return {"words": [w for w in toks if re.fullmatch(r"[a-z'\-]+", w) and w not in STOP_OWN], "nums": [w for w in toks if re.search(r"\d", w)], "inc": inc, "exc": exc}

def _plano(q):
    """A search line without the eBay syntax ((a,b), -(a,b), -word): the other markets' search boxes do not understand it and answer nothing. The fine filter is applied afterwards by matches()."""
    t = re.sub(r"-?\([^)]*\)", " ", q or "")
    return " ".join(w for w in t.split() if not w.startswith("-"))

def _linea(q):
    """«Etiqueta :: búsqueda» -> (label, search text); without «::» the line is both."""
    if "::" in (q or ""):
        lab, txt = q.split("::", 1); return lab.strip() or txt.strip(), txt.strip()
    return (q or "").strip(), (q or "").strip()

def _has(entry, t):
    """An entry of «include»/«exclude»: one word, or several joined by | (any of them)."""
    return any(_word(_norm(a), t) for a in entry.split("|") if a)

def tracks():
    """[(key, label, group, query)]: Gold Stars first, then the folders (same card in two folders is asked once)."""
    out, seen = [], set()
    cards = (load(os.path.join(SCREENER, "cards.json"), {}) or {}).get("cards", [])
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import importlib; qmod = importlib.import_module("ebay_api")
    allnames = {c["pokemon"]: [n.lower() for n in (c.get("names") or [c["pokemon"]])] for c in cards}
    for c in cards:
        q = qmod.queries(c)[0]
        out.append(("gs-" + c["key"], c["name_en"], "Gold Stars", q)); seen.add(q.lower())
        REQ["gs-" + c["key"]] = {"names": c.get("names") or [c["pokemon"]], "numbers": [x.lower() for x in c.get("numbers") or []],
                                 "others": sorted({n for p, ns in allnames.items() if p != c["pokemon"] for n in ns if n not in [x.lower() for x in (c.get("names") or [])]})}
    fd = P("app", "folders")
    for fn in sorted(os.listdir(fd)) if os.path.isdir(fd) else []:
        f = load(os.path.join(fd, fn), {}) or {}
        for it in f.get("items") or []:
            q = " ".join(str(it.get("query") or "").split())
            if q and q.lower() not in seen:
                seen.add(q.lower()); out.append(("q-" + it.get("search_id", q)[:60], q, f.get("label") or "Carpeta", q)); REQ["q-" + it.get("search_id", q)[:60]] = _query_req(q)
    for a in analisis_lista():   # the owner's own: a set, a theme, one specific card
        for i, line in enumerate(a["consultas"]):
            key = f"a-{a['id']}-{i}"; lab, q = _linea(line); r = _query_req_own(q); out.append((key, lab, a["nombre"], q))
            incl = (a.get("incluir") or []) + r["inc"]
            nm = next((re.match(r"0*(\d+)\s*/\s*0*(\d+)$", alt.strip()) for e in incl for alt in e.split("|") if re.match(r"\s*0*\d+\s*/\s*0*\d+$", alt)), None) or next((re.match(r"0*(\d+)\s*/\s*0*(\d+)$", n) for n in r["nums"] if re.match(r"0*\d+\s*/\s*0*\d+$", n)), None)
            REQ[key] = {"words": r["words"], "nums": r["nums"], "incluir": incl, "excluir": (a.get("excluir") or []) + r["exc"],
                        "estado": a.get("estado"), "nota": a.get("nota"), "idioma": a.get("idioma"), "num": (int(nm.group(1)), int(nm.group(2))) if nm else None}
    return out

def estado(**kw):
    e = load(os.path.join(DIR, "estado.json"), {}) or {}
    e.update(kw); save(os.path.join(DIR, "estado.json"), e); return e

def en_marcha():
    e = load(os.path.join(DIR, "estado.json"), {}) or {}
    return bool(e.get("running")) and time.time() - e.get("beat", 0) < 600   # a snapshot that stopped beating 10 minutes ago died

def hecha_hoy(): return os.path.exists(os.path.join(DIR, today() + ".json"))

def _antes_de_hora():
    """True before the snapshot hour of this computer: 10:00, and 10:30 on Jesús's, so the owner's photo comes first and Jesús imports it instead of asking eBay again."""
    try: import compartir; extra = 0.5 if compartir.rama() == "jesus" else 0.0
    except Exception: extra = 0.0
    n = dt.datetime.now(TZ); return n.hour + n.minute / 60 < 10 + extra

def toca():
    """True when the server should start a snapshot: keys present, none running, past 10:00 in Madrid (10:30 on Jesús's), a collection that is due (its own frequency), and no failed
    attempt today (a broken run must not retry every half hour)."""
    if not os.path.exists(os.path.join(ROOT, ".secrets", "ebay_api.json")) or en_marcha() or _antes_de_hora(): return False   # 10:00 (Fernando) / 10:30 (Jesús): eBay's daily count restarts at midnight Pacific (09:00 in Madrid, I believe); Fernando goes first, so Jesús finds his photo and imports it (compartir.py)
    e = load(os.path.join(DIR, "estado.json"), {}) or {}
    if e.get("error") and str(e.get("finished") or "")[:10] == today(): return False
    return any(debido(t[2], "ebay") for t in tracks())

def lanzar(forzar=False):
    """forzar: the button «Hacer foto ahora»: every collection that is not switched off, due or not."""
    if en_marcha(): return estado()
    os.makedirs(P("state"), exist_ok=True)
    estado(running=True, beat=time.time(), started=now_iso(), message="Empezando…", done=0, total=0, error=None)
    log = open(P("state", "mercado.log"), "a", encoding="utf-8")
    subprocess.Popen([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "mercado.py")] + (["--todo"] if forzar else []), cwd=os.path.dirname(os.path.abspath(__file__)),
                     env={**os.environ, "PYTHONIOENCODING": "utf-8"}, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return estado()

def rates():
    r = (load(P("fx.json"), {}) or {}).get("rates") or {}
    return {**r, "EUR": 1.0}

def to_eur(price, fx):
    try: v = float(price["value"]); c = price["currency"]
    except (TypeError, KeyError, ValueError): return None
    return round(v / fx[c], 2) if fx.get(c) else None

def item_of(it, fx, market):
    iid = it["itemId"].split("|")[1] if "|" in it["itemId"] else it["itemId"]
    opts = it.get("buyingOptions") or []
    price = it.get("currentBidPrice") if "AUCTION" in opts and it.get("currentBidPrice") else it.get("price")
    row = {"t": (it.get("title") or "")[:90], "e": to_eur(price, fx), "m": market[5:], "c": (it.get("itemLocation") or {}).get("country"),
           "s": (it.get("seller") or {}).get("username"), "a": "AUCTION" in opts, "g": it.get("conditionId") == "2750"}
    im = (it.get("image") or {}).get("imageUrl")
    if im: row["i"] = im
    return iid, row

def ask(job, tok, E):
    (key, label, group, q), market = job
    items, err = E.search(q, market, tok, MAX_ITEMS, origen="foto")
    return key, market, items, err, max(1, math.ceil(len(items) / 200))

def sospechosos(items, minimo=15, frac=0.07):
    """Ids of the listings priced under 7 % of the card's median when there are at least 15: accessories, proxies, cheap lots; they are not counted, only reported."""
    p = sorted(i["e"] for i in items.values() if i["e"] is not None)
    if len(p) < minimo: return set()
    med = statistics.median(p)
    return {k for k, i in items.items() if i["e"] is not None and i["e"] < frac * med}

def limpios(items):
    bad = sospechosos(items)
    return {k: v for k, v in items.items() if k not in bad} if bad else items

def stats(items):
    items = limpios(items)
    p = sorted(i["e"] for i in items.values() if i["e"] is not None)
    return {"n": len(items), "min": p[0] if p else None, "med": round(statistics.median(p), 2) if p else None}

def previous(date):
    ds = sorted(f[:-5] for f in os.listdir(DIR) if len(f) == 15 and f.endswith(".json") and f[:-5] < date) if os.path.isdir(DIR) else []
    return (ds[-1], load(os.path.join(DIR, ds[-1] + ".json"), {})) if ds else (None, None)

def diff(snap, prev):
    """New / gone / price changes of the latest snapshot against the previous one, per card and in total."""
    rows, nuevos, fuera, cambios = [], [], [], []
    for key, t in snap["tracks"].items():
        real = t.get("fecha", snap["date"]) == snap["date"]
        old = ((prev or {}).get("tracks") or {}).get(key) if real else None
        s = stats(t["items"]); n_new = n_gone = n_chg = 0
        if old:
            for iid, it in t["items"].items():
                o = old["items"].get(iid)
                if o is None:
                    n_new += 1; nuevos.append({**it, "id": iid, "k": key, "l": t["label"]})
                elif it["e"] and o["e"] and abs(it["e"] - o["e"]) / o["e"] >= 0.01:
                    n_chg += 1; cambios.append({**it, "id": iid, "k": key, "l": t["label"], "antes": o["e"], "pct": round(100 * (it["e"] - o["e"]) / o["e"], 1)})
            for iid, o in old["items"].items():
                if iid not in t["items"]: n_gone += 1; fuera.append({**o, "id": iid, "k": key, "l": t["label"]})
        rows.append({"key": key, "label": t["label"], "group": t["group"], **s, "nuevos": n_new if old else None, "fuera": n_gone if old else None,
                     "cambios": n_chg if old else None, "antes": old and len(old["items"]), "fecha": t.get("fecha", snap["date"]), "descartados": t.get("descartados", 0)})
    by_eur = lambda x: -(x.get("e") or 0)
    nuevos.sort(key=by_eur); fuera.sort(key=by_eur); cambios.sort(key=lambda x: -abs(x["pct"]))
    return rows, nuevos, fuera, cambios

def refiltrar(date=None, completo=False):
    """Applies the noise rules (_ruido) to a snapshot already saved, without asking eBay again (its titles are cut at 90 characters, so only the rules that look at names run)."""
    date = date or today(); snap = load(os.path.join(DIR, date + ".json"), None)
    if not snap: return None
    tracks()
    for k, t in snap["tracks"].items():
        if k not in REQ or t.get("fecha", date) != date: continue
        keep = {i: it for i, it in t["items"].items() if (matches(REQ[k], it["t"], it.get("g")) if completo else not _ruido(REQ[k], it["t"]))}
        t["descartados"] = t.get("descartados", 0) + len(t["items"]) - len(keep); t["items"] = keep
    return _cerrar(snap)

def update_history(date, rows):
    h = load(os.path.join(DIR, "historial.json"), {}) or {}
    for r in rows:
        e = h.setdefault(r["key"], {"label": r["label"], "group": r["group"], "puntos": []})
        e["label"], e["group"] = r["label"], r["group"]
        e["puntos"] = [p for p in e["puntos"] if p[0] != date][-(KEEP_DAYS - 1):] + [[date, r["n"], r["min"], r["med"]]]
    save(os.path.join(DIR, "historial.json"), h)

def _heredar(snap, T_all):
    """The cards not asked today keep their latest real data, with the date it is from (a collection checked once a week still shows on the other days)."""
    need = {t[0] for t in T_all if t[0] not in snap["tracks"]}
    ds = sorted((f[:-5] for f in os.listdir(DIR) if len(f) == 15 and f.endswith(".json")), reverse=True) if os.path.isdir(DIR) else []
    for d in ds:
        if not need: break
        s = load(os.path.join(DIR, d + ".json"), {}) or {}
        for k in list(need):
            tr = (s.get("tracks") or {}).get(k)
            if tr: snap["tracks"][k] = {**tr, "fecha": tr.get("fecha", d)}; need.discard(k)

def snapshot(limit=None, forzar=False):
    import ebay_api as E
    if not E.KEYS: raise SystemExit("No hay claves de eBay en .secrets/ebay_api.json")
    T_all = tracks()
    T = [t for t in T_all if (freq(t[2], "ebay") > 0 if forzar else debido(t[2], "ebay"))]; T = T[:limit] if limit else T   # only what the owner left on and is due
    if not T: raise SystemExit("Ninguna colección toca hoy en la foto de eBay")
    date = today(); importadas, quien = {}, ""
    if not forzar and not limit:      # what the other owner already read today is imported, not asked again (compartir.py); the button «Hacer foto ahora» always asks eBay
        try:
            import compartir; aj = compartir.foto_ajena(date)
            if aj: quien = aj["quien"]; importadas = {t[0]: aj["snap"]["tracks"][t[0]] for t in T if (aj["snap"]["tracks"].get(t[0]) or {}).get("query") == t[3] and aj["snap"]["tracks"][t[0]].get("items")}
        except Exception as e: print("compartir:", e)
    Tp = [t for t in T if t[0] not in importadas]          # what this computer still has to ask eBay
    jobs = [(t, m) for t in Tp for m in MARKETS]
    fx, tok = rates(), (E.token() if jobs else "")
    snap = {"date": date, "markets": MARKETS, "tracks": {t[0]: {"label": t[1], "group": t[2], "query": t[3], "items": {}, "fecha": date} for t in Tp}}
    for k, v in importadas.items(): snap["tracks"][k] = {**v, "fecha": date, "de": quien}
    if importadas:
        print(f"Importadas {len(importadas)} cartas de la foto de {quien}; se preguntan a eBay {len(Tp)}")
        try: compartir.avisar_equipo(f"Foto de eBay de {date}: importada la de {quien} ({len(importadas)} cartas), sin gastar llamadas" + (f"; faltaban {len(Tp)} y las pido yo." if Tp else "."))
        except Exception: pass
    calls = errors = done = 0; t0 = time.time(); first_err = None
    estado(total=len(jobs), done=0, message=f"Preguntando a eBay (0/{len(jobs)})")
    with ThreadPoolExecutor(5) as ex:
        for i in range(0, len(jobs), 15):
            if calls >= CALL_BUDGET: first_err = first_err or "Tope de llamadas del día alcanzado: foto incompleta"; break
            for key, market, items, err, n in ex.map(lambda j: ask(j, tok, E), jobs[i:i + 15]):
                calls += n; done += 1
                if err: errors += 1; first_err = first_err or err
                for it in items:
                    iid, row = item_of(it, fx, market)
                    if key in REQ and not matches(REQ[key], it.get("title"), it.get("conditionId") == "2750"): snap["tracks"][key]["descartados"] = snap["tracks"][key].get("descartados", 0) + 1; continue
                    snap["tracks"][key]["items"].setdefault(iid, row)
            estado(done=done, beat=time.time(), message=f"Preguntando a eBay ({done}/{len(jobs)})")
    # a card whose every call failed gives an empty list, not "everything disappeared": keep the day out of the comparison
    if done and errors >= done: raise SystemExit(f"Todas las llamadas fallaron: {first_err}")
    snap.update(calls=calls, errors=errors, seconds=round(time.time() - t0), taken=now_iso(), first_error=first_err)
    _heredar(snap, T_all)
    res = _cerrar(snap)
    if not limit: marcar({t[2] for t in T}, "ebay")
    if not limit and Tp and not first_err:
        try: import compartir; compartir.publicar_foto(snap, {t[0] for t in Tp})      # the first to read it shares it: the other computer will not spend calls on the same cards
        except Exception as e: print("compartir:", e)
    return res

def _cerrar(snap):
    """Saves a snapshot and everything derived from it (diff against the previous one, history, latest). Also used to re-filter a snapshot already taken."""
    date, calls, errors, first_err = snap["date"], snap["calls"], snap["errors"], snap.get("first_error")
    pdate, prev = previous(date)
    rows, nuevos, fuera, cambios = diff(snap, prev)
    save(os.path.join(DIR, date + ".json"), snap)
    import historial; historial.exportar(snap)   # permanent Parquet copy (KEEP_DAYS below only trims the JSON); never raises
    update_history(date, [r for r in rows if r["fecha"] == date])
    keep = sorted(f for f in os.listdir(DIR) if len(f) == 15 and f.endswith(".json"))[:-KEEP_DAYS]
    for f in keep: os.remove(os.path.join(DIR, f))
    comp = lambda v: sum(r[v] or 0 for r in rows) if pdate else None
    save(os.path.join(DIR, "ultimo.json"), {
        "date": date, "prev_date": pdate, "taken": snap["taken"], "calls": calls, "errors": errors, "first_error": first_err, "seconds": snap["seconds"],
        "descartados": sum(t.get("descartados", 0) for t in snap["tracks"].values() if t.get("fecha", date) == date),
        "totals": {"n": sum(r["n"] for r in rows), "nuevos": comp("nuevos"), "fuera": comp("fuera"), "cambios": comp("cambios")},
        "tracks": rows, "nuevos": nuevos[:60], "fuera": fuera[:60], "cambios": cambios[:40]})
    try: import oficina; oficina.registrar("foto_ebay", f"Foto del {date}: {calls} llamadas, {errors} errores", ok=not errors)
    except Exception: pass
    return calls, errors

BUCKETS = [(0, 5, "< 5 €"), (5, 20, "5–20 €"), (20, 50, "20–50 €"), (50, 100, "50–100 €"), (100, 300, "100–300 €"), (300, 1000, "300–1.000 €"), (1000, 1e12, "> 1.000 €")]
_cache = {}

def snaps():
    """(latest snapshot, previous snapshot) as dicts; cached until the file changes."""
    ds = sorted(f[:-5] for f in os.listdir(DIR) if len(f) == 15 and f.endswith(".json")) if os.path.isdir(DIR) else []
    if not ds: return None, None
    out = []
    for d in ds[-2:][::-1]:
        f = os.path.join(DIR, d + ".json"); k = (d, os.path.getmtime(f))
        if _cache.get(d, (None,))[0] != k: _cache[d] = (k, load(f, None))
        out.append(_cache[d][1])
    for d in list(_cache):
        if d not in ds[-2:]: _cache.pop(d)
    return out[0], (out[1] if len(out) > 1 else None)

def _enrich(rows, u, h):
    ref_day = (dt.date.fromisoformat(u["date"]) - dt.timedelta(days=7)).isoformat()
    for r in rows:
        pts = (h.get(r["key"]) or {}).get("puntos") or []
        r["serie"] = [[p[1], p[3]] for p in pts[-30:]]
        ref = next((p for p in pts if ref_day <= p[0] < u["date"]), None)
        r["d7_n"] = (r["n"] - ref[1]) if ref else None
        r["d7_med"] = round(100 * (r["med"] - ref[3]) / ref[3], 1) if ref and ref[3] and r["med"] else None
    return rows

def _breakdown(items):
    """The numbers of a set of listings {id: item}: by eBay site, country, price range, auction or Buy It Now, and the sellers with most listings."""
    L = list(items.values()); prices = [i["e"] for i in L if i["e"] is not None]
    def grp(f):
        g = {}
        for i in L: g.setdefault(f(i), []).append(i)
        return g
    def st(v):
        p = sorted(i["e"] for i in v if i["e"] is not None)
        return {"n": len(v), "min": p[0] if p else None, "med": round(statistics.median(p), 2) if p else None}
    mk = grp(lambda i: i["m"]); pa = grp(lambda i: i["c"] or "?"); se = grp(lambda i: i["s"] or "?")
    se.pop("?", None)
    return {"n": len(L), **st(L), "p25": round(statistics.quantiles(prices, n=4)[0], 2) if len(prices) >= 4 else None,
            "p75": round(statistics.quantiles(prices, n=4)[2], 2) if len(prices) >= 4 else None, "max": max(prices) if prices else None,
            "por_mercado": sorted(([m, *st(v).values()] for m, v in mk.items()), key=lambda x: -x[1]),
            "paises": sorted(([c, *st(v).values()] for c, v in pa.items()), key=lambda x: -x[1])[:12],
            "precios": [[lab, sum(1 for p in prices if lo <= p < hi)] for lo, hi, lab in BUCKETS],
            "subastas": sum(1 for i in L if i["a"]), "compra": sum(1 for i in L if not i["a"]),
            "vendedores": sorted(([s, len(v), st(v)["med"]] for s, v in se.items()), key=lambda x: -x[1])[:10], "n_vendedores": len(se),
            "notas": sorted(([lab, *st(v).values()] for lab, v in grp(_nota_label).items()), key=_nota_orden)[:30],
            "casas": sorted(([lab, *st(v).values()] for lab, v in grp(_casa_label).items()), key=lambda x: -x[1])}

CONF = os.path.join(DIR, "config.json"); DIARIO = os.path.join(DIR, "diario.json")
MIN_POR_BUSQUEDA = 5     # what a search takes in the engine (measured 1 November 2026: 5.1 minutes on average)

def conf():
    c = load(CONF, {}) or {}
    c.setdefault("diario", True); c.setdefault("grupos", {})
    return c

def freq(group, kind):
    """Days between two reviews of a collection: 0 off, 1 every day, 2, 3, 7 (a week). kind: "ebay" (the snapshot) or "otros" (the other markets through the engine).
    Only Gold Stars is every day; every other collection (folders, own analyses) is off until the owner turns it on or marks it «Hoy» (3 November 2026: "la foto diaria solo Gold Stars, el resto
    cuando yo lo pida"; before, everything was every day). (An older config saved true/false: True is 1, False is 0.)"""
    try: return max(0, int((conf()["grupos"].get(group) or {}).get(kind, 1 if group == "Gold Stars" else 0)))
    except (TypeError, ValueError): return 1 if group == "Gold Stars" else 0

def activo(group, kind): return freq(group, kind) > 0

def _hoy():
    """What the owner chose for TODAY: {"day", "ebay": {group: True/False}, "otros": {...}}. True = do it today even if it is not due; False = skip it today."""
    h = conf().get("hoy") or {}
    return h if h.get("day") == today() else {}

def debido(group, kind):
    """Is this collection to be reviewed today? What the owner marked for today wins; otherwise its frequency (and the automatic-review switch) decides."""
    ov = (_hoy().get(kind) or {}).get(group)
    if ov is not None: return bool(ov)
    if kind == "otros" and not conf()["diario"]: return False      # the switch stops the all-markets review (engine); the daily eBay photo is its own thing (4 November 2026: stopping the review also stopped the photo)
    f = freq(group, kind)
    if f <= 0: return False
    last = ((conf().get("ultimas") or {}).get(group) or {}).get(kind)
    return last is None or (dt.date.fromisoformat(today()) - dt.date.fromisoformat(last)).days >= f

def set_hoy(group, kind, on):
    if kind not in ("ebay", "otros") or not group: raise ValueError("falta la colección")
    c = conf(); h = c.get("hoy") or {}
    if h.get("day") != today(): h = {"day": today(), "ebay": {}, "otros": {}}
    h.setdefault(kind, {})[group] = bool(on); c["hoy"] = h; save(CONF, c)

def marcar(groups, kind):
    """A collection was reviewed today: its date is saved and a «do it today» mark is used up (a «skip today» stays)."""
    c = conf(); u = c.setdefault("ultimas", {}); h = c.get("hoy") or {}
    for g in groups:
        u.setdefault(g, {})[kind] = today()
        if h.get("day") == today() and (h.get(kind) or {}).get(g) is True: del h[kind][g]
    save(CONF, c)

# ---- the owner's own analyses: a set, a theme or one specific card, each with one or more searches
def analisis_lista(): return conf().get("analisis") or []

def _limpia(s, n): return " ".join(str(s or "").split())[:n]
def _palabras(s): return [w for w in (_norm(x).strip() for x in re.split(r"[,;\n]", str(s or ""))) if w][:8]

APODOS = ("moonbreon", "moon breon", "zard", "pika")
def _sin_apodos(t):
    """Nicknames («moonbreon») are not in most titles and also match merchandise: the card is searched by Pokémon, set, number and language."""
    t = re.sub(r"(?i)\b(?:%s)\b" % "|".join(APODOS), " ", t or "")
    t = re.sub(r"\(\s*,+|,+\s*\)|,\s*,+", lambda m: "(" if m.group(0).startswith("(") else (")" if m.group(0).endswith(")") else ","), t)
    t = re.sub(r"\(\s*\)", " ", t)
    return " ".join(t.split())

def analisis_guardar(nombre, consultas, tipo="carta", incluir="", excluir="", id=None, estado="todos", nota="", idioma="any"):
    nombre = _limpia(_sin_apodos(nombre), 60)
    cons = [q for q in (_limpia(_sin_apodos(x), 120) for x in (consultas if isinstance(consultas, list) else str(consultas or "").split("\n"))) if len(q) >= 2][:12]
    if len(nombre) < 2 or not cons: raise ValueError("Pon un nombre y al menos una búsqueda")
    c = conf(); L = c.setdefault("analisis", [])
    previo = next((a for a in L if a["id"] == id), None) if id else None
    propios = {a["nombre"] for a in L if a is not previo}
    ajenos = {t[2] for t in tracks() if not t[0].startswith("a-")}
    if nombre in propios or nombre in ajenos: raise ValueError("Ya hay una colección o análisis con ese nombre")
    item = {"id": (previo or {}).get("id") or "a" + __import__("hashlib").sha1((nombre + now_iso()).encode()).hexdigest()[:8], "nombre": nombre,
            "tipo": "set" if tipo == "set" else "carta", "consultas": cons, "incluir": _palabras(incluir), "excluir": _palabras(excluir), "estado": estado if estado in ("todos", "raw", "gradeadas", "psa") else "todos", "nota": _limpia(nota, 6),
            "idioma": idioma if idioma in ("any", "en", "ja") else "any", "creado": (previo or {}).get("creado") or today()}
    if previo:
        L[L.index(previo)] = item
        if previo["nombre"] != nombre:   # the switches and dates follow the name
            for k in ("grupos", "ultimas"):
                if previo["nombre"] in (c.get(k) or {}): c[k][nombre] = c[k].pop(previo["nombre"])
    else: L.append(item)
    save(CONF, c); return item

def analisis_borrar(id):
    c = conf(); a = next((x for x in c.get("analisis") or [] if x["id"] == id), None)
    if not a: return False
    c["analisis"] = [x for x in c["analisis"] if x["id"] != id]
    for k in ("grupos", "ultimas"): (c.get(k) or {}).pop(a["nombre"], None)
    save(CONF, c); return True

def set_conf(group=None, ebay=None, otros=None, diario=None):
    c = conf()
    if diario is not None: c["diario"] = bool(diario)
    if group:
        g = c["grupos"].setdefault(group, {})
        if ebay is not None: g["ebay"] = max(0, int(ebay))
        if otros is not None: g["otros"] = max(0, int(otros))
    save(CONF, c); return c

def set_profundo(group):
    """A full sweep of this collection today: its searches go through the engine in «full» depth (every market, GempireCards with ALT / Goldin / Fanatics included)."""
    c = conf(); c.setdefault("profundo", {})[group] = today(); save(CONF, c)

def _cola():
    """The searches of today's all-markets review: Gold Stars (its two collections), each folder's cards and the owner's own analyses, for what is due today."""
    out, grupos = [], set(); prof = lambda g: (conf().get("profundo") or {}).get(g) == today(); D = lambda g: {"depth": "full"} if prof(g) else {}
    if debido("Gold Stars", "otros"): out += [{"kind": "group", "id": "gold_stars", **D("Gold Stars")}, {"kind": "group", "id": "play_promos", **D("Gold Stars")}]; grupos.add("Gold Stars")
    fd = P("app", "folders")
    for fn in sorted(os.listdir(fd)) if os.path.isdir(fd) else []:
        f = load(os.path.join(fd, fn), {}) or {}; lab = f.get("label") or "Carpeta"
        if not debido(lab, "otros"): continue
        out += [{"kind": "text", "query": it["query"], **D(lab)} for it in f.get("items") or [] if it.get("query")]; grupos.add(lab)
    for a in analisis_lista():
        if debido(a["nombre"], "otros"): out += [{"kind": "text", "query": _plano(_linea(q)[1]), **D(a["nombre"])} for q in a["consultas"]]; grupos.add(a["nombre"])
    return out, grupos

def diario_preparar(force=False):
    """Today's list of searches for the all-markets review. Built once a day after 07:00 (or at once when the owner asks); whatever he marks later in the day is
    added to the same list. The server takes them one at a time, only when the engine is idle."""
    d = load(DIARIO, {}) or {}; same = d.get("day") == today()
    if not same and not force and dt.datetime.now(TZ).hour < 7: return d
    extra, grupos = _cola(); marcar(grupos, "otros")
    if same:
        if extra: d["cola"] = (d.get("cola") or []) + extra; d["total"] = d.get("total", 0) + len(extra); save(DIARIO, d)
        return d
    d = {"day": today(), "cola": extra, "total": len(extra), "hechas": 0, "at": now_iso()}
    save(DIARIO, d); return d

def diario_siguiente():
    d = load(DIARIO, {}) or {}
    if not d.get("cola"): return None
    it = d["cola"].pop(0); d["hechas"] = d.get("hechas", 0) + 1; save(DIARIO, d); return it

def grupos_info():
    """For the panel and the folders: every collection (Gold Stars, folders, the owner's analyses) with its number of cards, what is marked for today, its frequency
    and about how long its all-markets review takes."""
    n = {}
    for t in tracks(): n[t[2]] = n.get(t[2], 0) + 1
    ult = conf().get("ultimas") or {}; own = {a["nombre"]: a for a in analisis_lista()}
    def prox(g, kind):
        f = freq(g, kind); last = (ult.get(g) or {}).get(kind)
        if f <= 0: return None
        r = today() if not last else max(today(), (dt.date.fromisoformat(last) + dt.timedelta(days=f)).isoformat())
        if (_hoy().get(kind) or {}).get(g) is False: r = max(r, (dt.date.fromisoformat(today()) + dt.timedelta(days=1)).isoformat())   # skipped today: tomorrow at the earliest
        return r
    out = []
    for g, k in n.items():
        a = own.get(g); u = ult.get(g) or {}
        out.append({"group": g, "cartas": k, "ebay": freq(g, "ebay"), "otros": freq(g, "otros"), "hoy_ebay": debido(g, "ebay"), "hoy_otros": debido(g, "otros"),
                    "hecho_ebay": u.get("ebay") == today(), "hecho_otros": u.get("otros") == today(), "ultima_ebay": u.get("ebay"), "ultima_otros": u.get("otros"),
                    "proxima_ebay": prox(g, "ebay"), "proxima_otros": prox(g, "otros"),
                    "horas": round(((k + (1 if g == "Gold Stars" else 0)) * MIN_POR_BUSQUEDA) / 60, 1),
                    "custom": a and a["id"], "creado": a and a.get("creado"), "tipo": a and a["tipo"], "consultas": a and a["consultas"], "incluir": a and a["incluir"], "excluir": a and a["excluir"], "estado": a and a.get("estado"), "nota": a and a.get("nota"), "idioma": a and a.get("idioma")})
    return out

def config_view(): return {"diario": conf()["diario"], "grupos": grupos_info()}

_oc = {"k": None, "v": None}

def _fuentes():
    """Every market EXCEPT eBay as the app's searches last saw it (Mercari, SNKRDUNK, Magi, Vinted, Gempire: ALT / Goldin / Fanatics..., Cardmarket...).
    {collection: {"upd": newest search date, "cartas": {track key: [listings]}}}. It is not a daily snapshot: each search is as old as its last run (data/app/searches),
    and the page says so; the "Refrescar todos los mercados" button queues them all again in the engine."""
    sd = P("app", "searches"); fd = P("app", "folders")
    files = [os.path.join(sd, f) for f in os.listdir(sd) if f.endswith(".json")] if os.path.isdir(sd) else []
    files += [os.path.join(fd, f) for f in os.listdir(fd) if f.endswith(".json")] if os.path.isdir(fd) else []
    k = (len(files), max((os.path.getmtime(f) for f in files), default=0))
    if _oc["k"] == k: return _oc["v"]
    out, cards = {}, (load(os.path.join(SCREENER, "cards.json"), {}) or {}).get("cards", [])
    gs, upd = {}, ""
    for sid in ("gold_stars", "play_promos"):
        s = load(os.path.join(sd, sid + ".json"), None)
        if not s: continue
        upd = max(upd, s.get("updated") or "")
        for l in s.get("listings") or []: gs.setdefault(l.get("card"), []).append(l)
    out["Gold Stars"] = {"upd": upd, "cartas": {"gs-" + c["key"]: gs.get(c["name_en"], []) for c in cards}}
    for fn in sorted(os.listdir(fd)) if os.path.isdir(fd) else []:
        f = load(os.path.join(fd, fn), {}) or {}
        g = out.setdefault(f.get("label") or "Carpeta", {"upd": "", "cartas": {}})
        for it in f.get("items") or []:
            s = load(os.path.join(sd, it.get("search_id", "x") + ".json"), None) or {}
            g["upd"] = max(g["upd"], s.get("updated") or ""); g["cartas"]["q-" + it.get("search_id", "")[:60]] = s.get("listings") or []
    import app_lib as AL
    for a in analisis_lista():   # the searches the engine made for the owner's analyses (the same name the app gives them)
        g = out.setdefault(a["nombre"], {"upd": "", "cartas": {}})
        for i, q in enumerate(a["consultas"]):
            sr = load(os.path.join(sd, AL.slug(" ".join(_plano(_linea(q)[1]).split())) + ".json"), None) or {}
            key = f"a-{a['id']}-{i}"; tracks()          # fills REQ: the fine filter of this analysis (215/203 or alt art, language...)
            g["upd"] = max(g["upd"], sr.get("updated") or "")
            g["cartas"][key] = [l for l in (sr.get("listings") or []) if key not in REQ or matches(REQ[key], l.get("title"), None)]
    _oc["k"], _oc["v"] = k, out
    return out

def _sitios(listings):
    by, seen = {}, set()
    for l in listings:
        sn = l.get("site_name") or "?"
        if sn == "eBay" or (sn, l.get("id")) in seen: continue
        seen.add((sn, l.get("id"))); by.setdefault(sn, []).append(l)
    rows = []
    for sn, v in by.items():
        p = sorted(x["price_eur"] for x in v if x.get("price_eur") is not None)
        rows.append([sn, len(v), p[0] if p else None, round(statistics.median(p), 2) if p else None])
    return sorted(rows, key=lambda r: -r[1])

def otros(group, key=None):
    g = _fuentes().get(group)
    if not g: return {"upd": None, "sitios": []}
    ls = g["cartas"].get(key, []) if key else [l for v in g["cartas"].values() for l in v]
    return {"upd": g["upd"] or None, "sitios": _sitios(ls)}

def view():
    """Level 1 (collections): the state, the totals and, per collection, its numbers, its week, its price range and where its listings are."""
    u = load(os.path.join(DIR, "ultimo.json"), None); h = load(os.path.join(DIR, "historial.json"), {}) or {}
    cur, prev = snaps(); grupos = []
    if u and cur:
        keys_now = {t[0] for t in tracks()}; u["tracks"] = [r for r in u["tracks"] if r["key"] in keys_now]; u["totals"]["n"] = sum(r["n"] for r in u["tracks"])
        _enrich(u["tracks"], u, h)
        import panorama as PN
        order = list(dict.fromkeys(r["group"] for r in u["tracks"]))
        for g in order:
            rows = [r for r in u["tracks"] if r["group"] == g]; keys = {r["key"] for r in rows}
            items = {}
            for k in keys:
                for iid, it in limpios(cur["tracks"].get(k, {}).get("items", {})).items(): items.setdefault(iid, it)
            b = _breakdown(items); days = {}
            for k in keys:
                for p in (h.get(k) or {}).get("puntos") or []: days[p[0]] = days.get(p[0], 0) + p[1]
            ds = sorted(days.items()); ref_day = (dt.date.fromisoformat(u["date"]) - dt.timedelta(days=7)).isoformat()
            ref = next((v for d, v in ds if ref_day <= d < u["date"]), None)
            have = bool(u["prev_date"])
            grupos.append({"group": g, "cartas": len(rows), "fecha": min((r.get("fecha") or u["date"]) for r in rows), "cada": {1: "día", 2: "2 días", 3: "3 días", 7: "semana"}.get(freq(g, "ebay"), "—"), "n": b["n"], "min": b["min"], "med": b["med"], "p25": b["p25"], "p75": b["p75"],
                           "nuevos": sum(r["nuevos"] or 0 for r in rows) if have else None, "fuera": sum(r["fuera"] or 0 for r in rows) if have else None,
                           "cambios": sum(r["cambios"] or 0 for r in rows) if have else None, "d7_n": (sum(r["n"] for r in rows) - ref) if ref is not None else None,
                           "otros": otros(g)["sitios"][:4], "serie": [v for _, v in ds][-30:], "mercados": {m[0]: m[1] for m in b["por_mercado"]}, "subastas": b["subastas"],
                           "paises": b["paises"][:3], "n_vendedores": b["n_vendedores"], "precios": b["precios"]})
    if grupos:
        mm = PN.menciones_todas([g["group"] for g in grupos], analisis_lista())
        for g in grupos: g["menciones"] = mm.get(g["group"])
    return {"estado": {**(load(os.path.join(DIR, "estado.json"), {}) or {}), "running": en_marcha()}, "ultimo": u, "grupos": grupos,
            "dias": len(h and next(iter(h.values()))["puntos"]), "seguimiento": len([t for t in tracks() if activo(t[2], "ebay")]), "mercados": MARKETS, "limite": MAX_ITEMS,
            "config": config_view(), "diario": {k: v for k, v in (load(DIARIO, {}) or {}).items() if k != "cola"} | {"pendientes": len((load(DIARIO, {}) or {}).get("cola") or [])}}

_img = {"k": None, "by_id": {}, "raw": {}, "any": {}}
def _imagenes():
    """Photos the app already has: every listing of every saved search by eBay item id, and the photo of each Gold Star card (the app checked them against the card's art)."""
    sd = P("app", "searches")
    files = [os.path.join(sd, f) for f in os.listdir(sd) if f.endswith(".json")] if os.path.isdir(sd) else []
    k = (len(files), max((os.path.getmtime(f) for f in files), default=0))
    if _img["k"] != k:
        by_id, raw, anyi = {}, {}, {}
        for f in files:
            s = load(f, None) or {}; base = os.path.basename(f)
            for l in s.get("listings") or []:
                im = l.get("image")
                if not im: continue
                m = re.search(r"/itm/(\\d{9,})", l.get("url") or "")
                if m: by_id.setdefault(m.group(1), im)
                if base in ("gold_stars.json", "play_promos.json") and l.get("card") and not l.get("photo_doubt"):
                    anyi.setdefault(l["card"], im)
                    if not l.get("grader"): raw.setdefault(l["card"], im)
        _img.update(k=k, by_id=by_id, raw=raw, any=anyi)
    return _img

def _foto(key, label, items):
    """The picture of a card: the app's checked photo for a Gold Star; otherwise an ungraded listing priced near the median (a slab photo says less than the card)."""
    I = _imagenes()
    if key.startswith("gs-"):
        im = I["raw"].get(label) or I["any"].get(label)
        if im: return im
    pr = sorted(i["e"] for i in items.values() if i.get("e") is not None)
    med = statistics.median(pr) if pr else 0
    cand = []
    for iid, it in items.items():
        im = it.get("i") or I["by_id"].get(iid)
        if im and it.get("e") is not None: cand.append((bool(it.get("g")) or bool(_grado(it.get("t"))[0]), abs(it["e"] - med), im))
    return min(cand)[2] if cand else None

def detalle(group=None, key=None):
    """Level 2 (a collection: group) or 3 (a card: key): breakdowns, evolution, its cards, the cheapest listings and what changed since the previous snapshot."""
    cur, prev = snaps(); u = load(os.path.join(DIR, "ultimo.json"), None); h = load(os.path.join(DIR, "historial.json"), {}) or {}
    if not cur or not u: return None
    T = {k: t for k, t in cur["tracks"].items() if (k == key if key else t["group"] == group)}
    if not T: return None
    items, src = {}, {}
    n_sosp = 0
    for k, t in T.items():
        malos = sospechosos(t["items"]); n_sosp += len(malos)
        for iid, it in t["items"].items():
            if iid not in malos: items.setdefault(iid, {**it, "id": iid, "k": k, "l": t["label"]})
    b = _breakdown(items)
    P_ = {"tracks": T, "date": cur["date"]}; Q_ = {"tracks": {k: v for k, v in (prev or {}).get("tracks", {}).items() if k in T}} if prev else None
    rows, nuevos, fuera, cambios = diff(P_, Q_)
    cartas = _enrich([r for r in u["tracks"] if r["key"] in T], u, h)
    for r in cartas:
        r["query"] = T[r["key"]]["query"]; its = limpios(T[r["key"]]["items"]); labs = {iid: _nota_label(i) for iid, i in its.items()}
        r["grad_n"] = sum(1 for l in labs.values() if l != "Sin gradear"); r["raw_n"] = len(labs) - r["grad_n"]; r["psa10"] = sum(1 for l in labs.values() if l == "PSA 10")
        med = lambda lab: (lambda p: round(statistics.median(p), 2) if p else None)(sorted(i["e"] for iid, i in its.items() if labs[iid] == lab and i.get("e") is not None))
        r["med_raw"], r["med_psa10"] = med("Sin gradear"), med("PSA 10"); r["foto"] = _foto(r["key"], r["label"], its)
    days = {}
    for k in T:
        for p in (h.get(k) or {}).get("puntos") or []:
            d = days.setdefault(p[0], {"n": 0, "min": [], "med": []}); d["n"] += p[1]
            if p[2] is not None: d["min"].append(p[2])
            if p[3] is not None: d["med"].append(p[3])
    hist = [[d, v["n"], min(v["min"]) if v["min"] else None, round(statistics.median(v["med"]), 2) if v["med"] else None] for d, v in sorted(days.items())]
    cheap = sorted((i for i in items.values() if i["e"] is not None), key=lambda i: i["e"])[:15]
    I = _imagenes()
    anuncios = [{"id": i["id"], "t": i["t"], "e": i["e"], "m": i["m"], "c": i.get("c"), "s": i.get("s"), "a": i.get("a"), "nota": _nota_label(i), "img": i.get("i") or I["by_id"].get(i["id"])}
                for i in sorted((i for i in items.values() if i["e"] is not None), key=lambda i: i["e"])[:160]] if key else []
    foto = _foto(key, next(iter(T.values()))["label"], items) if key else None
    first = next(iter(T.values()))
    return {"group": group or first["group"], "key": key, "label": first["label"] if key else (group or first["group"]), "query": first["query"] if key else None,
            "date": cur["date"], "prev_date": prev and prev["date"], "mercados": MARKETS, "limite": MAX_ITEMS, **b, "cartas": cartas, "historia": hist[-60:],
            "otros": otros(group or first["group"], key), "sospechosos": n_sosp, "anuncios": anuncios, "foto": foto, "menciones": __import__("panorama").menciones_de(group or first["group"], next((a for a in analisis_lista() if a["nombre"] == (group or first["group"])), None)), "baratos": cheap, "nuevos": nuevos[:40], "fuera": fuera[:40], "cambios": cambios[:30],
            "totales": {"nuevos": len(nuevos) if prev else None, "fuera": len(fuera) if prev else None, "cambios": len(cambios) if prev else None}}

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    lim = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else None
    if "--lista" in sys.argv:
        T = tracks()[:lim] if lim else tracks()
        for t in T: print(f"{t[2]:<40.40} | {t[3]}")
        print(f"{len(T)} cartas x {len(MARKETS)} eBay = {len(T) * len(MARKETS)} búsquedas (aprox. {len(T) * len(MARKETS) * 1.3:.0f} llamadas)"); sys.exit(0)
    try:
        estado(running=True, beat=time.time(), started=now_iso(), error=None)
        c, e = snapshot(lim, forzar="--todo" in sys.argv)
        estado(running=False, finished=now_iso(), message="Foto hecha", error=None)
        print(f"Foto {today()}: {c} llamadas, {e} con error")
    except BaseException as ex:
        estado(running=False, finished=now_iso(), message="La foto falló", error=str(ex)[:300]); raise
