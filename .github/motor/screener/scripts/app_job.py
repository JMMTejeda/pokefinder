"""Searches started from the app (ejecutable/app). The server makes the job; Claude runs it with these commands.

  python app_job.py list                 jobs waiting for Claude (or still running), oldest first
  python app_job.py ebay <job>           eBay at once through the eBay API (the server runs this itself for typed searches)
  python app_job.py plan <job> [--q "blaziken power keepers"] [--en "blaziken"] [--ja "バシャーモ"] [--qja "ゲンガー マサキ"]
                         [--poke Gengar]... [--must REGEX]... [--not REGEX]... [--sites mercari,magi,...]
                         (--q / --qja: what is typed on the sites; --en: words every title must contain; --ja: the Japanese name
                         of the Pokémon; --poke: the Pokémon in the search, for the app's Pokémon buttons)
                                         typed search: writes the marketplace pages to read (data/app/jobs/<job>/browser/pages.json);
                                         group search: only marks the job running (Claude then runs the normal screener)
  python app_job.py finish <job>         typed search: reads every page saved for the job, keeps only listings that match exactly and
                                         are for sale, and writes the app's results; group search: see app_export.py <job>
  python app_job.py fail <job> "why"     marks the job failed with a reason the app shows

A typed search is read with the same browser steps as the screener, in the job's own folder: set GS_BROWSER=app/jobs/<job>/browser
for receiver.py, nextbatch.py and batch.py. Matching: every word of the search must be in the title (with the synonyms below and
the Japanese name given with --ja); --must adds required patterns, --not excludes (for example "stamped" must not match a plain holo).
Always left out: accessories (stands, cases, sleeves, stickers, playmats, figures, fan art, proxies...) unless the search asks for
one, and keyword-stuffed titles (another card that lists the searched names, "No Masaki Gengar", or two other tracked Pokémon).
"""
import json, os, re, sys, glob, time
from urllib.parse import quote
from common import P, load, save, SCREENER
import app_lib as A

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(SCREENER)
SYN = {"stamped": r"stamp|stamped|estampad\w*|sello|sellad\w*|tampon\w*|gestempelt|stempel\w*|timbrat\w*|スタンプ",
       "stamp": r"stamp|stamped|estampad\w*|sello|tampon\w*|gestempelt|stempel\w*|timbrat\w*|スタンプ",
       "reverse": r"reverse|inverso|invers\w*|ミラー", "holo": r"holo\w*|ホロ|キラ", "japanese": r"japan\w*|jpn|japon\w*|日本",
       "english": r"english|eng\b|ingl[eé]s|英語", "1st": r"1st|first|1ed|1 ed|primera|初版", "first": r"1st|first|1ed|初版",
       # スター on its own, not inside マスター (Duel Masters), モンスター or ポケットモンスター
       "gold": r"gold\s*star|goldstar|☆|(?<![ァ-ヴ])スター", "star": r"star|☆|(?<![ァ-ヴ])スター|estrella", "psa": r"psa", "promo": r"promo|プロモ"}
SITES = {
    "mercari":  ("ja", "https://jp.mercari.com/search?keyword={q}&status=on_sale&sort=created_time&order=desc"),
    "rakuma":   ("ja", "https://fril.jp/s?query={q}&order=desc&sort=created_at&transaction=selling"),
    "buyee":    ("ja", "https://buyee.jp/item/search/query/{q}?translationType=98"),
    "magi":     ("ja", "https://magi.camp/items/search?forms_search_items%5Bkeyword%5D={q}"),
    "cardrush": ("ja", "https://www.cardrush-pokemon.jp/product-list?keyword={q}"),
    "snkrdunk": ("ja", "https://snkrdunk.com/search?keywords={q}"),
    "hareruya2": ("ja", "https://www.hareruya2.com/search?q={q}"),
    "gempire":  ("en", "https://www.gempirecards.com/listings?q={q}"),
    "wallapop": ("en", "https://es.wallapop.com/search?keywords={q}&order_by=newest"),
    "vinted":   ("en", "https://www.vinted.es/catalog?search_text={q}&order=newest_first"),
    "rakuten":  ("ja", "https://search.rakuten.co.jp/search/mall/{q}/"),   # Rakuten Ichiba (motor.py, 28 October 2026)
    # full search only (1 November 2026): Mandarake (ships to Spain itself; stores in Ikebukuro, Nakano, Akihabara...), Yuyu-tei and
    # Card Labo (Japanese card shops, through a proxy), and Elite Fourum's buy and sell section (collectors' sale threads)
    "mandarake": ("ja", "https://order.mandarake.co.jp/order/listPage/list?keyword={q}"),
    "yuyutei":  ("ja", "https://yuyu-tei.jp/sell/poc/s/search?search_word={q}"),
    "clabo":    ("ja", "https://www.c-labo-online.jp/product-list?keyword={q}"),
    "elitefourum": ("en", "https://www.elitefourum.com/search?q={q}%20%23buy-section%20order%3Alatest"),
    # more markets (1 November 2026): Yahoo! Auctions through Jauce (a proxy that ships to Spain), and card shops whose search answers
    # in plain data (Shopify): Cherry Collectables and Monster Mart (Australia), Pokemon Plug (US), Japan TCG (Japan)
    "jauce":    ("ja", "https://www.jauce.com/search/{q}"),
    "cherry":   ("en", "https://www.cherrycollectables.com.au/search/suggest.json?q={q}&resources%5Btype%5D=product&resources%5Blimit%5D=10"),
    "monstermart": ("en", "https://www.monstermart.com.au/search/suggest.json?q={q}&resources%5Btype%5D=product&resources%5Blimit%5D=10"),
    "pokemonplug": ("en", "https://pokemonplug.com/search/suggest.json?q={q}&resources%5Btype%5D=product&resources%5Blimit%5D=10"),
    "japantcg": ("en", "https://japantcg.com/search/suggest.json?q={q}&resources%5Btype%5D=product&resources%5Blimit%5D=10"),
    "ebay":     ("en", "https://www.ebay.es/sch/i.html?_nkw={q}&_ipg=240"),   # only without eBay API keys
}
ACCESSORY = re.compile(r"\bstands?\b|\bdisplay\b|\bextended\s*art(?:work)?\b(?!.*\bholo)|\bfor\s+(?:graded\s+)?(?:slabs?|psa|cards?)\b"
    r"|\b(?:card|slab|display|magnetic|acrylic)\s+(?:case|holder)\b|\bh[uü]lle\b|\bfunda\b|\bsleeves?\b|\bstickers?\b|\bskin\b"
    r"|\bvinyl\b|\bplay\s*mat\b|\bplaymat\b|\btapete\b|figur(?:e|en|ine|a|as|ita)?s?\b|\bkey\s*(?:ring|chain)\b|\bkeyring\b|\bllavero\b|\bplush\b"
    r"|\bpeluche\b|\bposter\b|\bart\s*print\b|\bfan\s*art\b|\bcustom\b|\bproxy\b|\borica\b|\br[eé]plica\b|\breproduction\b"
    r"|\bdeko\b|\bmetal\s+card\b|スリーブ|ケース|ローダー|プレイマット|ステッカー|フィギュア|オリカ|ぬいぐるみ|キーホルダー", re.I)
LOTWORD = re.compile(r"\blot\b|\blote\b|\bbundle\b|まとめ|セット", re.I)
HAS_KEYS = os.path.exists(os.path.join(ROOT, ".secrets", "ebay_api.json"))
RD = os.path.join(SCREENER, "browser", "readers")
def part(n): return open(os.path.join(RD, n + ".js"), encoding="utf-8").read().strip()

def job(jid):
    j = load(A.job_path(jid))
    if not j: sys.exit(f"no job {jid}")
    return j

def put(j, **kw):
    j.update(kw); save(A.job_path(j["id"]), j)

def bdir(j): return os.path.join(P(), j["browser_dir"])

def args(flag):
    out, a = [], sys.argv
    for i, x in enumerate(a):
        if x == flag and i + 1 < len(a): out.append(a[i + 1])
    return out

def known_names(text):
    """Japanese and other names of the tracked Pokémon named in the search (blaziken is not tracked: Claude gives --ja)."""
    names = []
    for c in A.CARDS:
        if A.POKEMON[c["pokemon"]].search(text): names += c["names"]
    return list(dict.fromkeys(names))

def matcher(spec):
    """Every search word must be in the title (with synonyms), plus the --must patterns; none of the --not patterns."""
    words = [w for w in re.split(r"\s+", spec["en"].lower()) if w and w not in ("pokemon", "pokémon", "card", "carta", "tcg")]
    if spec.get("goldstar"): words = [w for w in words if w not in ("gold", "star", "goldstar")]   # goldstar_rule checks the star
    alts = {w: [x.lower() for x in spec.get("alias", {}).get(w, [])] for w in words}
    req = []
    for w in words:
        if re.fullmatch(r"#?\d+/\d+", w):
            a, b = w.lstrip("#").split("/"); pat = rf"(?<!\d)0*{int(a)}\s*/\s*0*{int(b)}(?!\d)"
        else:
            pat = SYN.get(w, A.name_re(w))
        names = alts.get(w) or []
        req.append(re.compile("|".join([pat] + [A.name_re(n) for n in names]), re.I))
    req += [re.compile(m, re.I) for m in spec.get("must", [])]
    bad = [re.compile(m, re.I) for m in spec.get("not", [])]
    if not ACCESSORY.search(spec["en"] + " " + spec.get("q", "")): bad.append(ACCESSORY)
    named = [w for w in words if not re.fullmatch(r"#?\d+/\d+", w) and w not in SYN]
    if named: bad.append(re.compile(r"\b(?:no|not|non)\b(?!\.?\s*\d)[^|/]{0,30}?(?<![A-Za-z])(?:" + "|".join(map(re.escape, named)) + r")(?![A-Za-z])", re.I))
    mine = set(spec.get("poke") or [])
    def stuffed(t):   # another card's title padded with famous names: two or more other tracked Pokémon and no lot word
        return len([p for p in A.pokemon_in(t) if p not in mine]) >= 2 and not LOTWORD.search(t)
    gold = goldstar_rule(spec) if spec.get("goldstar") else (lambda t: True)
    return lambda t: all(r.search(t or "") for r in req) and not any(r.search(t or "") for r in bad) and not stuffed(t or "") and gold(t or "")

# a typed "<Pokémon> gold star" (owner, 28 October 2026: "Umbreon gold star" brought the 25th Anniversary reprint, a Pikachu Gold
# Star lot naming Umbreon and an "Umbreon Gold Star Electric Card"): the rules goldstar.py uses for the collection, for any Gold Star
GS_STAR = r"(?:gold\s*-?\s*star|goldstar|ゴールドスター|estrella\s*dorada|[eé]toile\s*d'?or|goldstern|stella\s*d'?oro|☆|(?<![ァ-ヴー])スター(?![ァ-ヴー])|\bstar\b)"
GS_FAKE = re.compile(r"proxy|fan\s*-?\s*made|hecha? por fan|custom|orica|オリカ|レプリカ|replica|r[eé]plica|複製|コピー|\bcopy\b|\bfake\b|\bfals[oa]\b|unofficial|"
                     r"no oficial|非公式|metal\s*card|gold\s*metal|electric\s*card|\belectric\b(?!\s*type)|sticker|シール|poster|figure|フィギュア|plush|"
                     r"pl[üu]sch|puppe|kuscheltier|peluche|all\s*star\s*m|all\s*star\s*collection|ぬいぐるみ|"
                     r"peluche|\bpin\b|keychain|キーホルダー|llavero|mascot|マスコット|all\s*star\s*collection|30th\s*celebration|復刻|メザスタ|mezz?ast\w*|mezzasuta|"
                     r"gaole|ガオーレ|fan\s*art|pixel\s*art|perler|database|pok[eé]mon\s*attacks?|pokescam|booster|sealed|未開封|ブースター|"
                     r"[ée]tui|coque|\bcase\s+(?:for|para|pour)|(?:display|storage|magnetic|acrylic)\s+case|card\s+holder|vitrina|"
                     r"chin[eo]s[ea]?|cinese|中文|簡体|繁体|gran\w*\s*fiesta|grande\s*festa|"
                     # desk mats, stickers and key rings in the languages eBay's sites write titles in (owner, 28 October 2026)
                     r"mouse\s*-?\s*pad|desk\s*mat|alfombrilla|tappetino|mauspad|tapis\s*de\s*souris|naklejka|pegatina|aufkleber|autocollant|"
                     r"adesivo|schl[üu]sselanh[äa]nger|portachiavi|porte[\s-]*cl[ée]s|brelok|datenbank", re.I)   # not "pack": "Pop Series 5 Pack" names the set
# modern cards and rarity marks (not "EX": the Gold Stars are EX-era cards, "EX Holon Phantoms"; a modern Pokémon-ex is caught by the
# name right before it, below)
GS_MODERN = re.compile(r"(?<![a-z])(gx|vmax|vstar|sar|chr|csr|rr|ur|hr|mega|30th)(?![a-z])|マスターボール|モンスターボール|テラスタル|legend|レジェンド|star\s*rare|shiny\s*rare|shiny\s*(?:star\s*v|v\s*star)|シャイニースターv|\basc\b|"   # LEGEND ☆ and Star Rare are not Gold Stars
                       r"(?<![a-z])(sv|sm)\d+[a-z]?(?![a-z])|(?<![a-z])s\d{1,2}[a-z](?![a-z])|\d{2,3}\s*/\s*(?:sm|sv|s|xy|bw|dp)-?p\b", re.I)
_OTHERS = None

def other_pokemon(mine):
    """Every other Pokémon's name (English and Japanese), to see whose star a title's "Gold Star" is."""
    global _OTHERS
    if _OTHERS is None:
        _OTHERS = load(os.path.join(SCREENER, "pokemon_names.json"), {}).get("pokemon", [])
    en = sorted({p["en"] for p in _OTHERS if p["en"] not in mine and len(p["en"]) > 2}, key=len, reverse=True)
    ja = sorted({p["ja"] for p in _OTHERS if p["en"] not in mine}, key=len, reverse=True)
    return ("(?:(?<![a-z])(?:" + "|".join(re.escape(x) for x in en) + ")(?![a-z])|(?<![ァ-ヴー])(?:" + "|".join(re.escape(x) for x in ja) + ")(?![ァ-ヴー]))")

def goldstar_rule(spec):
    poke = spec.get("poke") or []
    names = sorted({n for p in poke for n in [p] + spec.get("alias", {}).get(p.lower(), []) if n}, key=len, reverse=True)
    if not names: return lambda t: not GS_FAKE.search(t) and not GS_MODERN.search(t)
    nm = "(?:" + "|".join(re.escape(n) for n in names) + ")"
    named = re.compile(rf"(?<![a-z]){nm}(?![a-z])", re.I)
    star = re.compile(GS_STAR, re.I)
    # its own number stands for the star (「シャワーズ 022/PLAY」, "Alakazam 033/075"), for the cards the collection tracks
    nums = [n for c in A.CARDS if c["pokemon"] in poke for n in [c["number"]] + c.get("numbers", [])]
    own = re.compile("|".join(re.escape(n) for n in nums), re.I) if nums else None
    # the star belongs to another Pokémon when that one is written right before it and ours is not ("MP Pikachu Gold Star 001/002 …
    # Eevee Umbreon 141/SM-P"); "Gift Box Mew" is the box the Pikachu ☆ and Mewtwo ☆ came in, not a Mew
    others = other_pokemon(set(poke))
    # ours right before the star, maybe in a list of Gold Stars sold together ("Pikachu Mewtwo Gold Star", "Pikachu☆ … Mewtwo")
    mine_star = re.compile(rf"(?<![a-z]){nm}(?![a-z])(?:[\s,&+/・、]+{others}){{0,3}}[\s\-:・()（）]{{0,3}}(?:holo\s*)?{GS_STAR}", re.I)
    other_star = re.compile(others + rf"[\s\-:・()（）]{{0,3}}(?:holo\s*)?{GS_STAR}", re.I)
    # a modern Pokémon-ex, -GX, V: "ブラッキーex", "Umbreon V"
    modern_name = re.compile(rf"(?<![a-z]){nm}\s*(?:ex|gx|v|vmax|vstar)(?![a-z])", re.I)
    def ok(t):
        # "Black Star Promo" is Pokémon's promo series, not a Gold Star; "EX Deoxys", "Gift Box Mew" are set and box names
        u = re.sub(r"bl[a-z]{0,2}ck\s*star|ブラックスター|shining\s*star|シャイニースター|star\s*wars|starter|スターター", " ", t, flags=re.I)
        u = re.sub(r"\bex\s+(?:deoxys|team\s*rocket|unseen|delta|dragon|holon|legend|crystal|power|emerald|hidden|firered|ruby|sandstorm)"
                   r"|gift\s*b(?:o)?x\s*mew|ギフトボックス\s*ミュウ", " ", u, flags=re.I)
        if not named.search(u) or GS_FAKE.search(u) or GS_MODERN.search(u) or modern_name.search(u): return False
        if not (star.search(u) or (own and own.search(u))): return False
        return not (other_star.search(u) and not mine_star.search(u))
    return ok

def spec_of(j):
    s = j.get("spec") or {}
    s.setdefault("en", j.get("query") or ""); s.setdefault("ja", ""); s.setdefault("must", []); s.setdefault("not", [])
    # the Japanese name counts as the English word it translates (bare names only: "バシャーモ" for "blaziken")
    if s["ja"] and "alias" not in s:
        first = next((w for w in s["en"].lower().split() if w not in SYN and not re.fullmatch(r"#?\d+/\d+", w)), None)
        if first: s["alias"] = {first: s["ja"].split()}
    if not s.get("poke"):   # until Claude names them (--poke): the tracked Pokémon written in the search
        s["poke"] = [p for p in A.POKEMON if A.POKEMON[p].search(s["en"])]
    for n in known_names(s["en"]):   # tracked Pokémon: their own Japanese and French names
        first = next((w for w in s["en"].lower().split() if A.POKEMON.get(w.title()) and A.POKEMON[w.title()].search(n)), None)
        if first: s.setdefault("alias", {}).setdefault(first, []).append(n)
    return s

def cmd_list():
    out = []
    jd = P("app", "jobs")
    for f in sorted(glob.glob(os.path.join(jd, "*.json")), key=os.path.getmtime):
        try:
            j = load(f)
        except (OSError, ValueError):
            continue
        if j and j.get("status") in ("queued", "waiting_claude", "claimed", "running", "ebay"): out.append(j)
    if not out: print("No hay búsquedas pendientes en el buscador."); return
    for j in out:
        print(f"{j['id']}  [{j['kind']}] {j['label']}  status={j['status']}  created={j['created']}")

def cmd_ebay(jid):
    j = job(jid); put(j, status="ebay", progress=6, message="Buscando en eBay (API)…")
    pre = A.preset_of(j.get("query"))   # a search with its own rules (app_lib.PRESETS)
    if pre: put(j, spec=dict(pre["spec"]))
    elif not j.get("spec") and j.get("query"):   # the engine's reading of the search from the start, so eBay's first results are exact too
        from motor import plan_spec
        put(j, spec=plan_spec(j["query"]))
    try:
        from ebay_api import token, search, row, MARKETS
        from concurrent.futures import ThreadPoolExecutor
        spec = spec_of(j)
        qs = (pre["q_en"] + pre["q_ja"]) if pre else [spec["en"]] + ([spec["ja"]] if spec["ja"] else []) + list(spec.get("extra_q") or [])
        tok = token()
        with ThreadPoolExecutor(6) as ex:
            # eBay allows 5,000 searches a day, shared with the phone page's own searches (cloud/engine.js, same plan): one page of
            # 200 per eBay site, two on the three biggest
            res = list(ex.map(lambda qm: search(qm[0], qm[1], tok, 400 if qm[1] in ("EBAY_US", "EBAY_GB", "EBAY_DE") else 200),
                              [(q, m) for q in qs for m in MARKETS]))
        rows, n = {}, 0
        for items, err in res:
            n += len(items)
            for it in items:
                r = row(it); rows.setdefault(r["id"], r)
        d = bdir(j); os.makedirs(os.path.join(d, "pages"), exist_ok=True)
        pages = [p for p in load(os.path.join(d, "pages.json"), []) if not p.get("api")]
        pages.insert(0, {"i": 0, "site": "ebay", "api": True, "label": "eBay API", "url": "https://api.ebay.com", "viewport": "tall"})
        for i, p in enumerate(pages): p["i"] = i
        save(os.path.join(d, "pages.json"), pages)
        save(os.path.join(d, "pages", "000.json"), {"site": "api.ebay.com", "blocked": False, "n": n, "rows": list(rows.values())})
        listings = build(j, spec)
        j = job(jid); n_e = sum(l['site'] == 'ebay' for l in listings)
        if j["status"] == "ebay":
            put(j, status="waiting_claude", progress=15, message=f"eBay listo: {n_e} anuncios. Ahora el resto de mercados…")
        else:
            put(j, progress=max(j.get("progress", 0), 15), message=f"eBay listo: {n_e} anuncios. Buscando en el resto de mercados…")
    except Exception as e:   # no keys, no network: Claude does everything
        put(j, status="waiting_claude", progress=8, message=f"eBay API no disponible ({type(e).__name__}); se busca en el resto de mercados.")

def cmd_plan(jid):
    j = job(jid)
    if j["kind"] == "group":
        put(j, status="running", progress=10, started=A.now_iso(), message="Buscando en todos los mercados…"); return
    spec = spec_of(j)
    pre = A.preset_of(j.get("query"))   # a search with its own rules: its words, filters and the wordings typed on each site
    if pre: spec = spec_of({**j, "spec": dict(pre["spec"])})
    if args("--en"): spec["en"] = args("--en")[0]
    if args("--ja"): spec["ja"] = args("--ja")[0]; spec.pop("alias", None); spec = spec_of({**j, "spec": spec})
    spec["must"] = list(dict.fromkeys(spec["must"] + args("--must"))); spec["not"] = list(dict.fromkeys(spec["not"] + args("--not")))
    if args("--poke"): spec["poke"] = [x.strip().title() for a in args("--poke") for x in a.split(",") if x.strip()]
    if args("--qja"): spec["qja"] = args("--qja")[0]
    nxt = os.path.join(bdir(j), "next_page.txt")
    if os.path.exists(nxt): os.remove(nxt)
    sites = (args("--sites") or [",".join(s for s in SITES if s != "ebay")])[0].split(",")
    if not HAS_KEYS and "ebay" not in sites: sites.append("ebay")   # no API: eBay in the browser
    first = spec["en"].lower().split()[0]
    keep = "|".join(re.escape(x) for x in [first] + spec.get("alias", {}).get(first, []) + spec.get("poke", []) if x)
    d = bdir(j); os.makedirs(os.path.join(d, "pages"), exist_ok=True)
    pages = [p for p in load(os.path.join(d, "pages.json"), []) if p.get("api")]
    if "mandarake" in sites:   # Mandarake's search needs one visit to its shop first (a cookie); the engine keeps cookies
        pages.append({"site": "mandarake", "label": "Mandarake: entrada a la tienda", "card_key": None, "url": "https://order.mandarake.co.jp/order/",
                      "js": "(async()=>JSON.stringify({blocked:false,n:0,rows:[]}))()", "viewport": "tall"})
    q_en = (args("--q") or [spec["en"]])[0]   # what is typed on each site; the matching uses spec en/must/not
    if not pre: spec["q"] = q_en
    for site in sites:
        lang, tpl = SITES[site]
        q_ja = spec.get("qja") or spec["ja"]
        q_jas = pre["q_ja"] if pre else ([q_ja] if q_ja else [])
        q_ens = pre["q_en"] if pre else [q_en]
        for q in (q_jas if lang == "ja" else []) + (q_ens if lang == "en" or (site in ("mercari", "magi") and not pre) else []):
            url = tpl.format(q=quote(q).replace("%20", "+") if site in ("gempire", "rakuten") else quote(q))
            js = part("_prelude") + "\n" + part(site) + "\nconst KEEP=" + json.dumps(keep, ensure_ascii=False) + ",STAR=\"\";" + part("_tail")
            pages.append({"site": site, "label": f"{site}: {q}", "card_key": None, "url": url, "js": js,
                          "viewport": "normal" if site == "gempire" else "tall"})
    for i, p in enumerate(pages): p["i"] = i
    save(os.path.join(d, "pages.json"), pages)
    put(j, status="running", spec=spec, started=A.now_iso(), progress=max(j.get("progress", 0), 15),
        message="Buscando en los mercados…")
    print(f"{len(pages)} pages for job {jid} (eBay API page included: {any(p.get('api') for p in pages)}). "
          f"Read them with GS_BROWSER={j['browser_dir']}")

def build(j, spec):
    """Every saved page of the job -> matching listings for sale -> the app search. Returns the listings."""
    d = bdir(j); ok = matcher(spec)
    pages = load(os.path.join(d, "pages.json"), [])
    poke = spec.get("poke") or []
    al = spec.get("alias", {})
    ali = {p: [p] + al.get(p.lower(), []) + (al.get(spec["en"].lower().split()[0], []) if len(poke) == 1 else []) for p in poke}
    found, per_site, read_sites, matched = {}, {}, set(), set()
    gone = set(load(P("app", "images", "gone.json"), []))
    gone |= {k for k, v in load(P("app", "photo_review.json"), {}).items() if not v.get("ok")}   # revisar_fotos.py
    gone |= {k for k, v in load(P("app", "photo_auto.json"), {}).items() if v.get("verdict") == "other"}   # motor.py: the photo's label says reprint
    for p in pages:
        res = load(os.path.join(d, "pages", f"{p['i']:03d}.json"))
        if not res or res.get("blocked"): continue
        read_sites.add(p["site"])
        for r in res.get("rows", []):
            if r.get("status") not in (None, "on sale"): continue
            if not ok(r.get("title")): continue
            matched.add(p["site"])
            l = A.from_page_row(p["site"], r)
            if l["id"] in gone: continue   # app_images.py found it cannot be bought
            l["pokemon"] = [x for x in poke if any(re.search(A.name_re(n), r.get("title") or "", re.I) for n in ali[x])] +                            [x for x in l["pokemon"] if x not in poke]
            if l["id"] in found and found[l["id"]]["site"] == "ebay" and l["site"] == "ebay" and found[l["id"]]["price_eur"]: continue
            found[l["id"]] = l
    listings = sorted(found.values(), key=lambda l: (l["price_eur"] is None, l["price_eur"] or 0))
    for l in listings: per_site[l["site_name"]] = per_site.get(l["site_name"], 0) + 1
    old = load(A.search_path(j["search_id"]), {})
    seen = {l["id"]: l for l in old.get("listings", [])}
    for l in listings:
        if l["id"] in seen: l["status"] = "Seen before"; l["first_seen"] = seen[l["id"]].get("first_seen", l["first_seen"])
    every = {"ebay"} | set(SITES)
    sitename = lambda s: A.SITE_NAME.get(s, s)
    no_sites = [sitename(s) for s in sorted(read_sites - matched)]
    not_read = [sitename(s) for s in sorted(every - read_sites)]
    A.save_search({"id": j["search_id"], "kind": "text", "group": None, "query": j["query"], "label": j["label"],
                   "status": "searching" if j.get("status") != "done" else "done", "job": j["id"], "updated": A.now_iso(),
                   "spec": {k: spec.get(k) for k in ("en", "ja", "qja", "q", "poke", "must", "not", "goldstar", "lang", "card")}, "pokemon": poke if len(poke) > 1 else [],
                   "listings": listings,
                   "no_results": {"cards": [], "sites": no_sites, "not_read": not_read}, "per_site": per_site})
    return listings

def cmd_finish(jid):
    j = job(jid)
    if j["kind"] == "group": sys.exit("group job: run `python app_export.py " + jid + "` after goldstar.py")
    spec = spec_of(j); put(j, status="done", progress=100, finished=A.now_iso(), message="Búsqueda terminada")
    listings = build(job(jid), spec)
    s = load(A.search_path(j["search_id"])); s["status"] = "done"; A.save_search(s)
    print(f"{j['label']}: {len(listings)} listings for sale match exactly.")

if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "list"
    if c == "list": cmd_list()
    elif c == "ebay": cmd_ebay(sys.argv[2])
    elif c == "plan": cmd_plan(sys.argv[2])
    elif c == "finish": cmd_finish(sys.argv[2])
    elif c == "fail":
        j = job(sys.argv[2]); put(j, status="error", message=" ".join(sys.argv[3:]) or "Error")
        s = load(A.search_path(j["search_id"]))
        if s: s["status"] = "done" if s.get("listings") else "error"; A.save_search(s)
    else: print(__doc__)
