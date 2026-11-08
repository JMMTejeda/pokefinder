"""Sold prices, to tell a listing that is below its market value (owner, 2 November 2026: "ver si está por debajo de su valor de mercado...
hay que conseguir filtrar por vendidos"). Read ONLY from what the pages show in a hidden browser, never from a site's internal API (owner's
choice, same day).

Sources so far:
  SNKRDUNK  each Japanese card's sales history page (snkrdunk.com/apparels/<id>/sales-histories): every sale with its date, state and price in
            yen. States: A to D (ungraded, A best), PSA10, PSA9, PSA8以下 (8 or less), BGS10 BL/GL, BGS9.5, BGS9以下, ARS10+, ARS10, ARS9,
            ARS8以下, 他鑑定品 (other houses). The product pages of each Gold Star are the ones the app already learnt (data/state/snkr_products.json);
            "再販" in a product's name is the Unlimited print, "1ED" the first edition.
  (next) Collectr's card page, which shows its prices without an account. PSA's Auction Prices Realized is out: since 2 November 2026 it
            puts a Cloudflare check in front of automated browsers, even after the owner signed in himself, and that check is never bypassed.
Market value of a card in one grade (valor): the median of its sales of the last 30 days if there are 3, else of 90 days, else of 180; never
older (owner's rule: "priorizar el último mes, hasta 3 meses, nunca más de 6"). PSA comes first, TAG close behind: a grade is only compared
with sales of the same house and grade.
Files: data/ventas/<card key>.json (only the sales of the last 180 days are kept).
Usage: python ventas.py [--cartas latias,torchic] [--forzar] [--fuente snkrdunk|collectr]   (a card is read at most once every 20 hours unless --forzar)
       python ventas.py --valor latias "PSA 10"                   (prints the market value)
       python ventas.py --sesion psa|collectr                     (a visible window where the owner signs in himself)"""
import argparse, datetime as dt, os, re, statistics, subprocess, sys, time
from common import P, load, save, SCREENER, TZ

DIR = P("ventas")
ESTADO = P("state", "ventas.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
VENTANAS = (30, 90, 180)
MIN_VENTAS = 3        # sales a window needs to give the value (the 180-day window gives it with fewer, marked by its count)
MIN_MARCAR = 2        # sales needed before a listing is called below market
UMBRAL = 0.8          # a listing at 80 % of the market value or less is "below market"
REFRESCO_H = 20
PERFIL = P("ventas", "navegador")   # this module's own browser profile: the owner's PSA / Collectr sign-in lives here (data/ is never uploaded)
SESION = {"psa": "https://www.psacard.com/auctionprices", "collectr": "https://app.getcollectr.com/"}

def ahora(): return dt.datetime.now(TZ)

def sesion(sitio):
    """Opens a VISIBLE browser with PERFIL so the owner signs in himself (Claude never types a password); closing the window keeps the sign-in."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(PERFIL, headless=False, locale="en-US", viewport=None)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page(); pg.goto(SESION[sitio])
        print(f"Inicia sesión en {sitio} en la ventana que se ha abierto y ciérrala cuando termines.")
        try: pg.wait_for_event("close", timeout=0)
        except Exception: pass
        ctx.close()

_c = {}
def cartas():
    """{key: card} of screener/cards.json, cached until the file changes."""
    f = os.path.join(SCREENER, "cards.json"); k = os.path.getmtime(f)
    if _c.get("k") != k: _c.update(k=k, v={c["key"]: c for c in (load(f, {}) or {}).get("cards", [])})
    return _c["v"]

def jpy_por_eur(): return ((load(P("fx.json"), {}) or {}).get("rates") or {}).get("JPY")

def nota_snkr(estado):
    """A SNKRDUNK state in the app's words: "PSA10" -> "PSA 10", "PSA8以下" -> "PSA ≤8", "BGS10 BL" -> "BGS 10 Black Label", "A" -> "Sin gradear"."""
    s = estado.strip()
    if re.fullmatch(r"[AB]", s): return "Sin gradear"
    if re.fullmatch(r"[CD]", s): return "Sin gradear (C-D)"   # played copies sell far below a near mint one: they are not the reference of an A / B card
    if s == "他鑑定品": return "Otra casa"
    m = re.fullmatch(r"(PSA|BGS|ARS|CGC|TAG)\s*(\d+(?:\.\d)?)\s*(以下|\+|BL|GL)?", s)
    if not m: return s
    h, n, x = m.groups()
    return f"{h} ≤{n}" if x == "以下" else f"{h} {n}" + {"+": "+", "BL": " Black Label", "GL": " Gold Label"}.get(x or "", "")

def edicion(titulo):
    if re.search(r"再販|resale|unlimited", titulo or "", re.I): return "Unlimited"
    if re.search(r"1ED|1st|初版", titulo or "", re.I): return "1st Edition"
    return None

# a section header is one line ("状態PSA10の売買履歴"); the tables' own column header "状態" (state) must not end the section
SECCION = re.compile(r"状態([^\n]+?)の売買履歴(.*?)(?=状態[^\n]+?の売買履歴|商品情報|$)", re.S)
FILA = re.compile(r"(\d{4})/(\d{2})/(\d{2})\s+(\S+)\s+([\d,]+)")

def leer_snkr(pg, pid, fx):
    """(page title, [sale]) of one SNKRDUNK product, from its sales history page as the browser shows it."""
    # the tables fill in unevenly (one read gave 1 sale of a product that had 6): wait for the page to settle and go down it to the end first
    pg.goto(f"https://snkrdunk.com/apparels/{pid}/sales-histories", timeout=60000, wait_until="domcontentloaded")
    pg.wait_for_selector("text=売買履歴", timeout=30000)
    try: pg.wait_for_load_state("networkidle", timeout=20000)
    except Exception: pass
    for _ in range(8):
        pg.mouse.wheel(0, 2500); pg.wait_for_timeout(400)
    pg.wait_for_timeout(1500)
    out = []
    for est, cuerpo in SECCION.findall(pg.inner_text("body")):
        for y, mo, d, lab, precio in FILA.findall(cuerpo):
            jpy = int(precio.replace(",", ""))
            out.append({"f": "snkrdunk", "prod": pid, "fecha": f"{y}-{mo}-{d}", "estado": lab, "nota": nota_snkr(lab), "jpy": jpy,
                        "eur": round(jpy / fx, 2) if fx else None})
    return pg.title(), out

def snkr_carta(pg, pids, fx):
    """(products, sales of the last 180 days) of one card on SNKRDUNK, or None when every page failed."""
    ventas, productos = [], []
    for pid in pids:
        try: titulo, vs = leer_snkr(pg, pid, fx)
        except Exception as e:
            print(f"  SNKRDUNK {pid}: {type(e).__name__} {str(e)[:120]}"); continue
        ed = edicion(titulo)
        for v in vs: v["edicion"] = ed
        productos.append({"f": "snkrdunk", "id": pid, "titulo": titulo, "edicion": ed, "ventas": len(vs)}); ventas += vs
        time.sleep(2)
    if not productos: return None
    if sum(p_["edicion"] == "1st Edition" for p_ in productos) == 1:   # "セレビィ☆ ◇ :1ED [...]" and "セレビィ☆ ◇ [...]": the unmarked one is the Unlimited
        for p_ in productos:
            if not p_["edicion"]: p_["edicion"] = "Unlimited"
        for v in ventas:
            if not v["edicion"]: v["edicion"] = "Unlimited"
    corte = (ahora().date() - dt.timedelta(days=VENTANAS[-1])).isoformat()
    return productos, sorted((v for v in ventas if v["fecha"] >= corte), key=lambda v: v["fecha"], reverse=True)

# Collectr: the search page's result boxes ("Torchic Gold Star (JP) Rocket Gang Strikes Back Ultra Rare • 020/084 Unlimited Holofoil $4,437.50")
# and each card page ("... 020/084 $4,437.50 ... PSA 10 ($...) PSA 9 ($...) CGC 10 ($...)"). Prices in dollars, kept in euros.
COLLECTR = "https://app.getcollectr.com/"
C_PRECIO = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)")
C_NOTA = re.compile(r"\b(PSA|BGS|CGC|TAG|SGC|ACE|ARS)\s+(10|9\.5|9|8\.5|8|7\.5|7)\s*\(\$\s?([\d,]+(?:\.\d+)?)\)")
MARCAR_JS = """(num) => { let i = 0; const out = [];
  const ok = (t) => /\\(JP\\)/.test(t) && t.includes(num) && /\\$/.test(t);
  for (const e of document.querySelectorAll('div, a, li')) {
    const t = (e.innerText || '').replace(/\\s+/g, ' ');
    if (t.length > 260 || !ok(t) || [...e.children].some((ch) => ok((ch.innerText || '').replace(/\\s+/g, ' ')))) continue;   // the smallest box holding one result
    e.setAttribute('data-pf', i++); out.push(t); }
  return out; }"""

def _collectr_buscar(pg, c):
    pg.goto(COLLECTR, timeout=60000, wait_until="domcontentloaded"); pg.wait_for_timeout(2500)
    box = pg.locator("input").first; box.fill(f"{c['pokemon']} Gold Star"); box.press("Enter"); pg.wait_for_timeout(5000)
    return pg.evaluate(MARCAR_JS, c["number"])

def collectr_carta(pg, c, usd):
    """{"leido", "productos": [{"id", "titulo", "edicion", "sin_gradear", "notas": {"PSA 10": €...}}]} of a Japanese Gold Star on Collectr, or None.
    Only the results that say "(JP)" and the card's own number count (Collectr also has the English print, a different card)."""
    eur = lambda s: round(float(s.replace(",", "")) / usd, 2)
    try: res = _collectr_buscar(pg, c)
    except Exception as e:
        print(f"  Collectr {c['key']}: {type(e).__name__} {str(e)[:120]}"); return None
    productos = []
    for i, titulo in enumerate(res[:3]):
        try:
            if i: _collectr_buscar(pg, c)
            pg.locator(f'[data-pf="{i}"]').first.click(timeout=10000); pg.wait_for_url(re.compile(r"/explore/product/\d+"), timeout=20000); pg.wait_for_timeout(4000)
            t = re.sub(r"\s+", " ", pg.inner_text("body")); m = C_PRECIO.search(titulo)      # the ungraded price of THIS edition is the one in its result box
            productos.append({"f": "collectr", "id": re.search(r"/explore/product/(\d+)", pg.url).group(1), "titulo": titulo, "edicion": edicion(titulo),
                              "sin_gradear": eur(m.group(1)) if m and float(m.group(1).replace(",", "")) > 0 else None,
                              "notas": {f"{h} {n}": eur(v) for h, n, v in C_NOTA.findall(t)}})
            time.sleep(1.5)
        except Exception as e:
            print(f"  Collectr {c['key']} #{i}: {type(e).__name__} {str(e)[:120]}")
    # 1st edition and Unlimited may share one card page, which shows the grades of only one of them: those grades are kept apart, without edition
    for pid in {p_["id"] for p_ in productos if sum(q["id"] == p_["id"] for q in productos) > 1}:
        notas = next(p_["notas"] for p_ in productos if p_["id"] == pid)
        for p_ in productos:
            if p_["id"] == pid: p_["notas"] = {}
        productos.append({"f": "collectr", "id": pid, "titulo": "notas de la ficha, sin separar edición", "edicion": None, "sin_gradear": None, "notas": notas, "compartida": True})
    return {"leido": ahora().isoformat(timespec="minutes"), "productos": productos} if productos else None

def usd_por_eur(): return ((load(P("fx.json"), {}) or {}).get("rates") or {}).get("USD")

def actualizar(keys=None, forzar=False, fuentes=("snkrdunk", "collectr")):
    """Reads the sales (SNKRDUNK) and reference prices (Collectr) of the Gold Stars (or of keys) into data/ventas/<key>.json.
    A source whose pages all fail keeps what it had."""
    C = cartas(); prods = load(P("state", "snkr_products.json"), {}) or {}; jpy, usd = jpy_por_eur(), usd_por_eur()
    todo = [k for k in (keys or C) if k in C]
    hoy = ahora().date().isoformat(); save(ESTADO, {"running": True, "beat": time.time(), "dia": hoy})
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pj = b.new_context(locale="ja-JP", user_agent=UA).new_page()
        pc = b.new_context(locale="en-US", user_agent=UA, viewport={"width": 1400, "height": 2600}).new_page()
        for k in todo:
            save(ESTADO, {"running": True, "beat": time.time(), "dia": hoy, "carta": k})
            f = os.path.join(DIR, k + ".json"); old = load(f, {}) or {}
            if not forzar and old.get("leido") and ahora() - dt.datetime.fromisoformat(old["leido"]) < dt.timedelta(hours=REFRESCO_H): continue
            new = {**old, "card": k, "nombre": C[k]["name_en"]}
            if "snkrdunk" in fuentes and prods.get(k) and jpy:
                r = snkr_carta(pj, prods[k], jpy)
                if r: new["productos"], new["ventas"] = r
            if "collectr" in fuentes and usd:
                r = collectr_carta(pc, C[k], usd)
                if r: new["collectr"] = r
            if new == {**old, "card": k, "nombre": C[k]["name_en"]}: continue
            new["leido"] = ahora().isoformat(timespec="minutes"); save(f, new)
            cr = (new.get("collectr") or {}).get("productos") or []
            print(f"{C[k]['name_en']}: {len(new.get('ventas') or [])} ventas en 180 días en SNKRDUNK; Collectr: "
                  + ("; ".join(f"{p_['edicion'] or '?'} {p_['sin_gradear']} € sin gradear, {len(p_['notas'])} notas" for p_ in cr) or "—"))
        b.close()
    save(ESTADO, {"running": False, "dia": hoy, "fin": ahora().isoformat(timespec="minutes")})

def toca():
    """Once a day (server.py asks every 5 minutes): no reading running and today's not done yet."""
    s = load(ESTADO, {}) or {}
    if s.get("running") and time.time() - s.get("beat", 0) < 600: return False
    return s.get("dia") != ahora().date().isoformat()

def lanzar():
    here = os.path.dirname(os.path.abspath(__file__))
    log = open(P("state", "ventas.log"), "a", encoding="utf-8")
    subprocess.Popen([sys.executable, os.path.join(here, "ventas.py")], cwd=here, env={**os.environ, "PYTHONIOENCODING": "utf-8"}, stdin=subprocess.DEVNULL,
                     stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

_v = {}
def _datos(key):
    f = os.path.join(DIR, key + ".json")
    try: k = os.path.getmtime(f)
    except OSError: return {}
    if _v.get(key, (None,))[0] != k: _v[key] = (k, load(f, {}) or {})
    return _v[key][1]

ALIAS = {"PSA ≤8": "PSA 8", "BGS ≤9": "BGS 9", "ARS ≤8": "ARS 8"}   # a "≤8" listing is a PSA 8 (nota_anuncio): Collectr's own PSA 8 price fits it

def _creible(notas, lab):
    """Collectr sometimes shows a grade far out of line (2.28 M$ for the English PSA 10 Torchic, 26 times its PSA 9): a grade worth over 15 times
    the next one down is ignored (a vintage PSA 10 is often 5 to 10 times the PSA 9)."""
    h, n = lab.split(); n = float(n)
    def _num(x):      # «CGC 9.5» → 9.5; «CGC Pristine» o cualquier nota sin número → None (esto hizo caer las búsquedas con «Failed to fetch», 6 nov)
        p = x.split()
        try: return float(p[1]) if len(p) > 1 and p[0] == h else None
        except ValueError: return None
    abajo = sorted((_num(x), v) for x, v in notas.items() if _num(x) is not None and _num(x) < n)
    return not abajo or notas[lab] <= 15 * abajo[-1][1]

def _ediciones(key):
    """The editions the card exists in: cards.json says it ("1st Edition and Unlimited"), else the products SNKRDUNK and Collectr show for it."""
    if "1st Edition and Unlimited" in str(cartas().get(key, {}).get("editions") or ""): return {"1st Edition", "Unlimited"}
    d = _datos(key)
    return {p.get("edicion") for p in (d.get("productos") or []) + ((d.get("collectr") or {}).get("productos") or []) if p.get("edicion")}

def referencia(key, nota, ed=None):
    """Collectr's price of the card in that grade (its own figure, not single sales): {"eur", "n": 0, "fuentes": ["collectr"], "referencia": True} or None."""
    vals, eds, amb = [], set(), False
    dos = len(_ediciones(key)) > 1     # a Collectr page that does not say its edition, for a card printed in both, may be either
    for p in ((_datos(key).get("collectr") or {}).get("productos") or []):
        if ed and p.get("edicion") and p["edicion"] != ed: continue
        if nota == "Sin gradear": v = p.get("sin_gradear")
        else:
            lab = ALIAS.get(nota, nota); v = p["notas"].get(lab)
            if v and not _creible(p["notas"], lab): v = None
        if v: vals.append(v); eds.add(p.get("edicion")); amb = amb or bool(p.get("compartida")) or (dos and not p.get("edicion"))
    return {"eur": round(statistics.median(vals), 2), "n": 0, "dias": None, "fuentes": ["collectr"], "referencia": True,
            "ediciones": sorted(e for e in eds if e), "ambigua": amb} if vals else None

# --- ventas de eBay y Fanatics por nota de PokemonPriceTracker (precios_graduadas.py, 4 de noviembre de 2026): solo para anuncios en INGLÉS, porque son las cartas inglesas;
# los japoneses siguen con SNKRDUNK y Collectr. En dólares; se pasan a euros con el cambio de data/fx.json.
PPT_NOTAS = {"PSA 10": "psa10", "PSA 9": "psa9", "PSA ≤8": "psa8", "BGS 10": "bgs10", "BGS 9.5": "bgs9_5", "BGS ≤9": "bgs9", "CGC 10": "cgc10", "CGC 9.5": "cgc9_5", "CGC 9": "cgc9", "TAG 10": "tag10"}
PPT_FUENTE = "eBay y Fanatics (PokemonPriceTracker)"
_pp = {}
def _precios():
    """The newest data/precios/AAAA-MM-DD.json, cached until it changes."""
    try: fs = sorted(f for f in os.listdir(P("precios")) if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", f))
    except OSError: return {}
    if not fs: return {}
    f = P("precios", fs[-1]); k = (fs[-1], os.path.getmtime(f))
    if _pp.get("k") != k: _pp.update(k=k, v=load(f, {}) or {})
    return _pp["v"]

def valor_ppt(key, nota, hoy=None):
    """Value in euros of an ENGLISH Gold Star in one grade from its sold prices on eBay and Fanatics: the median of the window, never the «smart» price unless it rests on 120 days or less.
    Needs MIN_VENTAS sales; the confidence follows the number of sales, how old the last one is and how far apart the sales are (a PSA 7 above a PSA 8 means few and scattered)."""
    n = PPT_NOTAS.get(nota)
    if not n: return None
    hoy = hoy or ahora().date()
    c = (_precios().get("cartas") or {}).get("gs-" + (key[:-5] + "-play" if key.endswith("_play") else key)); g = ((c or {}).get("ppt") or {}).get("notas", {}).get(n)
    usd = usd_por_eur()
    if not g or not usd or (g.get("ventas") or 0) < MIN_VENTAS or not g.get("mediana"): return None
    ppt = c["ppt"]; precio = g["mediana"]
    if g.get("smart") and g.get("smart_conf") in ("high", "medium") and (g.get("smart_dias") or 9999) <= 120: precio = g["smart"]
    try: antig = (hoy - dt.date.fromisoformat(str(g["ultima"])[:10])).days
    except (TypeError, ValueError): antig = 999
    try: ventana = (dt.date.fromisoformat(str(ppt["hasta"])[:10]) - dt.date.fromisoformat(str(ppt["desde"])[:10])).days
    except (TypeError, ValueError): ventana = 999
    spread = ((g.get("max") or 0) - (g.get("min") or 0)) / g["mediana"]
    conf = "alta" if g["ventas"] >= 10 and antig <= 30 and spread <= 1.0 else "media" if g["ventas"] >= 5 and antig <= 90 and spread <= 2.0 else "baja"
    return {"eur": round(precio / usd, 2), "n": g["ventas"], "dias": min(ventana, 180), "fuentes": [PPT_FUENTE], "disp": round(spread, 2), "confianza": conf, "ultima": str(g["ultima"])[:10], "ediciones": []}

def valor(key, nota, ed=None, hoy=None, idioma=None):
    """Market value in euros of one card in one grade: the real sales first {"eur", "n", "dias", "fuentes"}; without sales of that grade in 180 days,
    Collectr's price (referencia); else None. ed: "1st Edition" / "Unlimited" when known. idioma "en": an English listing is set against the English sales (eBay, PokemonPriceTracker) when there are."""
    hoy = hoy or ahora().date()
    if idioma == "en":
        r = valor_ppt(key, nota, hoy)
        if r: return r
    # sales saved before C / D were kept apart still say "Sin gradear": the state letter decides
    nota_de = lambda v: "Sin gradear (C-D)" if v.get("estado") in ("C", "D") else v["nota"]
    vs = [v for v in _datos(key).get("ventas") or [] if nota_de(v) == nota and v.get("eur") and (not ed or not v.get("edicion") or v["edicion"] == ed)]
    for dias in VENTANAS:
        desde = (hoy - dt.timedelta(days=dias)).isoformat(); w = [v for v in vs if v["fecha"] >= desde]
        if len(w) >= MIN_VENTAS or (dias == VENTANAS[-1] and w):
            med = statistics.median(v["eur"] for v in w)
            disp = round(statistics.median(abs(v["eur"] - med) for v in w) / med, 2) if len(w) >= 4 and med else None   # how spread the sales are (MAD / median)
            confianza = "alta" if len(w) >= 5 and disp is not None and disp <= 0.25 and dias <= 90 else "media" if len(w) >= MIN_VENTAS and (disp is None or disp <= 0.35) else "baja"
            return {"eur": round(med, 2), "n": len(w), "dias": dias, "fuentes": sorted({v["f"] for v in w}), "disp": disp, "confianza": confianza,
                    "ultima": w[0]["fecha"] if w else None, "ediciones": sorted({v["edicion"] for v in w if v.get("edicion")})}
    r = referencia(key, nota, ed)
    return {**r, "confianza": "baja", "disp": None} if r else None   # Collectr's figure is one price, not sales: never more than low confidence

# an ungraded card the seller calls played or damaged is not set against the sales (most are near mint): "Heavily Played", "[MP]", "傷あり"
JUGADA = re.compile(r"heavily\s*played|moderately\s*played|lightly\s*played|\bplayed\b|\[(?:hp|mp|lp|dmg)\]|\b(?:hp|mp|lp)\b(?!\s*\d)|damaged?|\bdmg\b|crease|\bpoor\b|"
                    r"傷あり|キズあり|ジャンク|折れ|難あり|プレイ用", re.I)

def nota_anuncio(l):
    """The grade of a search listing in the words of the sales, or None when it cannot be compared fairly: a "≤8" sale mixes lower grades, so
    only a PSA 8 (BGS 9, ARS 8) is set against them; an ungraded card in condition C or D is not set against the ungraded sales."""
    g = l.get("grader"); txt = str(l.get("grade") or "")
    if not g: return None if re.search(r"Condition [CD]\b", txt) or JUGADA.search(l.get("title") or "") else "Sin gradear"
    m = re.search(r"(\d+(?:\.\d)?)", txt)
    if not m: return None
    n = float(m.group(1))
    if g == "PSA": return {10: "PSA 10", 9: "PSA 9", 8: "PSA ≤8"}.get(n)
    if g in ("BGS", "Beckett"): return {9.5: "BGS 9.5", 9: "BGS ≤9"}.get(n)
    if g == "ARS": return {10: "ARS 10", 9: "ARS 9", 8: "ARS ≤8"}.get(n)
    if g in ("CGC", "TAG", "SGC"): return f"{g} {n:g}"      # no SNKRDUNK state of their own: Collectr's price of that exact grade
    return None

def _idioma(l):
    try:
        import idioma; return idioma.lang_of(l)
    except Exception: return None

def marcar(s):
    """Adds to each listing of a search whose card and grade have sales: l["mercado"] = {"valor", "n", "dias", "nota", "pct", "bajo", "fuentes"}
    (pct: how far its price is from the market value; bajo: at UMBRAL of it or less, with MIN_MARCAR sales)."""
    por_nombre = {c["name_en"]: k for k, c in cartas().items()}
    # what the other listings of the same card and grade ask (buy now): a real bargain is also below them, else the reference is the odd one
    # (14 Mewtwo ☆ under Collectr's figure means Collectr's figure is high, not 14 bargains)
    piden = {}
    for l in s.get("listings") or []:
        k = por_nombre.get(l.get("card")); nota = nota_anuncio(l) if k else None
        if nota and l.get("price_eur") and l.get("sale") != "auction": piden.setdefault((k, nota), []).append(l["price_eur"])
    piden = {x: statistics.median(v) for x, v in piden.items() if len(v) >= 3}
    for l in s.get("listings") or []:
        l.pop("mercado", None)
        k = por_nombre.get(l.get("card")); nota = nota_anuncio(l) if k else None
        if not nota or l.get("price_eur") is None: continue
        v = valor(k, nota, l.get("edition") if l.get("edition") in ("1st Edition", "Unlimited") else None, idioma=_idioma(l))
        if not v or not v["eur"]: continue
        pct = round(100 * (l["price_eur"] / v["eur"] - 1)); subasta = l.get("sale") == "auction"   # an auction's price is today's bid, not what it will fetch
        ref = bool(v.get("referencia"))
        # a Japanese Unlimited is worth more than the 1st edition (fewer PSA copies; owner, 2 November 2026): a listing that does not say its
        # edition, set against both, is never called below market
        mezcla = False if v.get("fuentes") == [PPT_FUENTE] else (l.get("edition") not in ("1st Edition", "Unlimited") and len(_ediciones(k)) > 1) or bool(v.get("ambigua"))
        dudosa = v.get("confianza") == "baja" and not ref    # sales that disagree with each other (or too few): the value is not trusted to call a bargain
        l["mercado"] = {"valor": v["eur"], "n": v["n"], "dias": v["dias"], "nota": nota, "pct": pct, "fuentes": v["fuentes"], "subasta": subasta, "referencia": ref,
                        "confianza": v.get("confianza"), "disp": v.get("disp"),
                        "mezcla": mezcla, "bajo": not subasta and not mezcla and not dudosa and (ref or v["n"] >= MIN_MARCAR) and l["price_eur"] <= UMBRAL * v["eur"]
                                                  and l["price_eur"] <= 0.9 * piden.get((k, nota), l["price_eur"] / 0.9)}
    _marcar_generico(s)
    for l in s.get("listings") or []:      # en cada anuncio con valor de mercado: cuánto ganarías y hasta cuánto pagar
        m = l.get("mercado")
        if m and m.get("valor") and l.get("price_eur") is not None: m.update(ganancia(m["valor"], l["price_eur"]))
    return s

COMISION, ENVIO_VENTA_EUR, MARGEN_BUSCADO = 0.13, 4.0, 0.10      # SUPUESTOS (Fernando, 7 nov: «el precio máximo para ganar un 10 %»): comisión de venta de eBay ~13 %, ~4 € de envío al vender y el 10 % que se quiere ganar. Se cambian en data/mercado/beneficio.json
def ganancia(valor, precio):
    """Si lo vendes al valor de mercado: reventa neta (valor − comisión − envío), beneficio contra lo que pagas y el PRECIO MÁXIMO que puedes pagar para ganar aún el margen buscado."""
    aj = load(P("mercado", "beneficio.json"), {}) or {}
    com, env, mar = float(aj.get("comision", COMISION)), float(aj.get("envio_eur", ENVIO_VENTA_EUR)), float(aj.get("margen", MARGEN_BUSCADO))
    neto = valor * (1 - com) - env
    return {"neto": round(neto, 2), "max_pagar": round(max(neto / (1 + mar), 0), 2), "beneficio": round(neto - precio, 2), "beneficio_pct": round(100 * (neto / precio - 1)) if precio else None, "margen_pct": round(mar * 100)}

def _marcar_generico(s):
    """Las demás cartas (no Gold Star): las que están en referencia.registro() se comparan con el precio de TCGplayer (sin gradear) o de Collectr (cada nota), leídos por referencia.py
    (Fernando, 5 de noviembre de 2026: la búsqueda rápida y la exhaustiva tienen que mirar también estos precios). Solo con la edición que la ficha enseña: un anuncio de otra edición
    no se compara. Nunca más que confianza «baja» (es un precio de mercado de una ficha, no ventas propias), y no se llama «bajo mercado» si los demás anuncios de esa carta piden menos."""
    try: import referencia as R
    except Exception: return
    reg = R.registro()
    if not reg: return
    usd = usd_por_eur()
    if not usd: return
    L = [l for l in s.get("listings") or [] if l.get("mercado") is None and l.get("price_eur") is not None]
    hallados = []
    for l in L:
        e = R.entrada_de(l); nota = nota_anuncio(l) if e else None
        if e and nota: hallados.append((l, e, nota))
    piden = {}
    for l, e, nota in hallados:
        if l.get("sale") != "auction": piden.setdefault((e["clave"], nota), []).append(l["price_eur"])
    piden = {x: statistics.median(v) for x, v in piden.items() if len(v) >= 3}
    for l, e, nota in hallados:
        d = R.datos(e); tcg, col = d.get("tcgplayer") or {}, d.get("collectr") or {}; ed = l.get("edition") if l.get("edition") in ("1st Edition", "Unlimited") else None
        if nota == "Sin gradear":
            eur, fuente, n, ed_ref = None, None, 0, e.get("edicion_sin_gradear")
            if tcg.get("mercado"): eur, fuente, n = tcg["mercado"] / usd, "TCGplayer", tcg.get("vendidas") or 0
            elif col.get("sin_gradear"): eur, fuente = col["sin_gradear"] / usd, "Collectr"
        else:
            lab = ALIAS.get(nota, nota); v = (col.get("notas") or {}).get(lab); ed_ref = e.get("edicion_notas"); fuente, n = "Collectr", 0
            eur = v / usd if v and col.get("notas_fiables", True) and _creible(col["notas"], lab) else None
        if not eur: continue
        mezcla = bool(ed_ref and (ed is None or ed != ed_ref))      # el precio es de una edición y el anuncio es de otra o no la dice
        pct = round(100 * (l["price_eur"] / eur - 1)); subasta = l.get("sale") == "auction"
        l["mercado"] = {"valor": round(eur, 2), "n": n, "dias": None, "nota": nota, "pct": pct, "fuentes": [fuente], "subasta": subasta, "referencia": True, "confianza": "baja", "disp": None,
                        "mezcla": mezcla, "edicion": ed_ref, "leido": d.get("leido"),
                        "bajo": not subasta and not mezcla and l["price_eur"] <= UMBRAL * eur and l["price_eur"] <= 0.9 * piden.get((e["clave"], nota), l["price_eur"] / 0.9)}

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    a = argparse.ArgumentParser(); a.add_argument("--cartas"); a.add_argument("--forzar", action="store_true"); a.add_argument("--valor", nargs=2)
    a.add_argument("--sesion", choices=sorted(SESION)); a.add_argument("--fuente", choices=["snkrdunk", "collectr"])
    o = a.parse_args()
    if o.sesion: sesion(o.sesion)
    elif o.valor: print(valor(*o.valor))
    else:
        actualizar([k.strip() for k in o.cartas.split(",")] if o.cartas else None, o.forzar, (o.fuente,) if o.fuente else ("snkrdunk", "collectr"))
        try: import oficina; oficina.registrar("ventas", "Lectura de ventas terminada")
        except Exception: pass
