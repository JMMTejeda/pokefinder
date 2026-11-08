"""Precio de referencia de CUALQUIER carta con número de producto de TCGplayer (Fernando, 5 de noviembre de 2026: «si las búsquedas son pocas y extendidas en el tiempo no hay bloqueos,
nos puede ayudar a encontrar por debajo de mercado»). Complementa a ventas.py, que ya lee Collectr y SNKRDUNK para las 27 Gold Star japonesas: esto cubre el resto (inglesas y modernas).
Para cada carta abre DOS fichas públicas con el navegador oculto, sin cuenta y sin aceptar nada:
  - TCGplayer  /product/<id>        precio de mercado (Near Mint), última venta, venta más baja y más alta de 3 meses, total vendido.
  - Collectr   /explore/product/<id> (el mismo número) precio sin gradear y precio de cada nota (PSA, BGS, CGC).
Reglas: una carta cada ~8 s, nunca la misma dos veces en 20 h, y si una página enseña un CAPTCHA o un muro de login se para y no se insiste (nada de saltar antibots).
Guarda data/referencia/<id>.json con la fecha y la fuente de cada cifra. Los precios están en dólares y se guardan también en euros.
Uso: python referencia.py --prueba 5      (las 5 primeras cartas de data/precios/cartas.json)
     python referencia.py --id 590027 [--id ...]      --todas      --forzar"""
import argparse, datetime as dt, re, sys, time
from common import P, load, save, TZ

DIR = P("referencia")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppData Chrome/130.0 Safari/537.36".replace("AppData", "AppleWebKit/537.36 (KHTML, like Gecko)")
REFRESCO_H = 20; PAUSA_S = 8
USD = r"\$\s?([\d,]+(?:\.\d+)?)"
BLOQUEO = re.compile(r"verify yourself|captcha|security measure|are you a human|access denied|unusual traffic", re.I)
C_NOTA = re.compile(r"\b(PSA|BGS|CGC|TAG|SGC|ACE|ARS)\s+(Black Label|Pristine|10|9\.5|9|8\.5|8|7\.5|7)\s*\(\$\s?([\d,]+(?:\.\d+)?)\)")

def ahora(): return dt.datetime.now(TZ)
def num(s): return float(s.replace(",", ""))
def usd_por_eur(): return ((load(P("fx.json"), {}) or {}).get("rates") or {}).get("USD")

HIST_DIR = P("referencia", "historial"); HIST_JS = """async () => {
  const b = [...document.querySelectorAll('button,[role=tab]')].find((x) => x.innerText.trim() === '1Y'); if (!b) return null;
  b.scrollIntoView({block: 'center'}); b.click(); await new Promise((r) => setTimeout(r, 3000));
  const t = [...document.querySelectorAll('table')].find((x) => /Date/.test((x.querySelector('thead') || x).innerText)); if (!t) return null;
  return [...t.querySelectorAll('tr')].slice(1).map((r) => [...r.children].map((c) => c.innerText.trim())); }"""

def _fecha_iso(md, hoy, ref=None):
    m, d = (int(x) for x in md.split("/")); y = hoy.year if ref is None else ref.year
    f = dt.date(y, m, d) if ref is None else None
    if ref is None:
        if f > hoy: f = dt.date(y - 1, m, d)
        return f
    f = dt.date(y, m, d)
    return f if f <= ref else dt.date(y - 1, m, d)

ANUNCIOS_TCG = P("referencia", "anuncios_tcgplayer.jsonl")
LISTADO_JS = """() => [...document.querySelectorAll('.listing-item')].map((e) => (e.innerText || '').replace(/\\s+/g, ' '))"""
CONDICIONES = ("Near Mint", "Lightly Played", "Moderately Played", "Heavily Played", "Damaged")

def leer_anuncios_tcg(pg):
    """Los anuncios que enseña la ficha de TCGplayer (los 10 primeros, ordenados por precio + envío, que es lo que enseña por defecto): precio, envío, estado, unidades, vendedor y su valoración.
    Es la oferta que hay ahora de esa carta (no ventas). Cada uno: {"precio", "envio", "estado", "unidades", "vendedor", "valoracion", "direct"}."""
    out = []
    for t in pg.evaluate(LISTADO_JS) or []:
        p = re.search(r"\$([\d,]+(?:\.\d+)?)\s*USD", t)
        if not p: continue
        env = re.search(r"\+\s*\$([\d,]+(?:\.\d+)?)\s*Shipping", t); cond = next((c for c in CONDICIONES if c in t), None)
        un = re.search(r"\bof\s+(\d+)\b", t); vend = re.search(r"Add to Cart\s+(.+?)\s+(?:Gold Star|Certified|Verified|Wizards|\d{2,3}(?:\.\d)?\s*%)", t); val = re.search(r"(\d{2,3}(?:\.\d)?)\s*%\s*\(([\d,]+\+?)\s*Sales\)", t)
        out.append({"precio": num(p.group(1)), "envio": num(env.group(1)) if env else None, "estado": cond, "unidades": int(un.group(1)) if un else None, "vendedor": (vend.group(1)[:40] if vend else None),
                    "valoracion": float(val.group(1)) if val else None, "direct": "TCGplayer Direct" in t})
    return out

def leer_historial_tcg(pg, pid):
    """El historial de 1 año que enseña la ficha de TCGplayer (pulsando «1Y»): una fila por semana con el precio de mercado y las unidades vendidas. Se apunta en data/referencia/historial/<id>.json.
    Es lo que sale en la página, sin cuenta ni peticiones internas. Devuelve cuántas semanas leyó (0 si la ficha no lo trae)."""
    filas = pg.evaluate(HIST_JS) or []; hoy = ahora().date(); out = []; ref = None
    for fila in reversed(filas):      # de la más reciente a la más antigua: así se deduce el año de cada fecha
        m = re.match(r"(\d{1,2}/\d{1,2}) to (\d{1,2}/\d{1,2})", fila[0]) if fila else None
        p = re.search(r"\$\s?([\d,]+(?:\.\d+)?)", fila[1]) if len(fila) > 1 else None
        if not m or not p: continue
        try:
            fin = _fecha_iso(m.group(2), hoy) if ref is None else _fecha_iso(m.group(2), hoy, ref); ini = _fecha_iso(m.group(1), hoy, fin)
        except ValueError: continue
        v = re.search(r"([\d,]+(?:\.\d+)?)", fila[2]) if len(fila) > 2 else None
        out.append({"desde": ini.isoformat(), "hasta": fin.isoformat(), "precio_usd": num(p.group(1)), "vendidas": int(float(num(v.group(1)))) if v else None}); ref = ini - dt.timedelta(days=1)
    if out:      # tras pulsar «1Y» la ficha enseña también el resumen de 1 año: venta más baja y más alta, total vendido y ventas al día
        t = re.sub(r"\s+", " ", pg.inner_text("body")); s = re.search(r"1 Year Snapshot.*?Low Sale Price: " + USD + r" High Sale Price: " + USD + r" Total Sold: ([\d,]+) Avg\. Daily Sold: ([\d.]+)", t)
        os.makedirs(HIST_DIR, exist_ok=True); save(f"{HIST_DIR}/{pid}.json", {"id": pid, "leido": ahora().isoformat(timespec="minutes"), "semanas": list(reversed(out)),
            "resumen_1a": {"venta_min": num(s.group(1)), "venta_max": num(s.group(2)), "vendidas": int(s.group(3).replace(",", "")), "diarias": float(s.group(4))} if s else None})
    return len(out)

def leer_tcgplayer(pg, pid):
    """{"mercado", "ultima_venta", "venta_min", "venta_max", "vendidas", "diarias", "anuncios_desde", "vendedores"} (dólares) o None si no se pudo leer."""
    pg.goto(f"https://www.tcgplayer.com/product/{pid}?Language=English", timeout=60000, wait_until="domcontentloaded"); pg.wait_for_timeout(5000)
    t = re.sub(r"\s+", " ", pg.inner_text("body"))
    if BLOQUEO.search(t[:600]): raise PermissionError("TCGplayer pide verificación: se para")
    g = lambda pat: (re.search(pat, t) or [None, None])[1]
    mercado = g(r"Market Price " + USD)
    if not mercado or num(mercado) == 0: return None      # sin ventas recientes (carta poco movida): no hay precio de mercado, no se inventa
    low, high = re.search(r"Low Sale Price: " + USD + r" High Sale Price: " + USD, t).groups() if re.search(r"Low Sale Price: " + USD + r" High Sale Price: " + USD, t) else (None, None)
    res = {"mercado": num(mercado), "ultima_venta": num(g(r"Most Recent Sale " + USD)) if g(r"Most Recent Sale " + USD) else None,
            "venta_min": num(low) if low else None, "venta_max": num(high) if high else None,
            "vendidas": int(g(r"Total Sold: ([\d,]+)").replace(",", "")) if g(r"Total Sold: ([\d,]+)") else None,
            "diarias": float(g(r"Avg\. Daily Sold: ([\d.]+)")) if g(r"Avg\. Daily Sold: ([\d.]+)") else None,
            "anuncios_desde": num(g(r"As low as " + USD)) if g(r"As low as " + USD) else None, "vendedores": int(g(r"Current Sellers: (\d+)")) if g(r"Current Sellers: (\d+)") else None}
    try: res["anuncios"] = leer_anuncios_tcg(pg)      # la oferta de ahora (los 10 más baratos con envío): se apunta aparte en anuncios_tcgplayer.jsonl
    except Exception as ex: print("  anuncios:", type(ex).__name__, str(ex)[:80])
    try:      # el historial de 1 año (semana a semana) se renueva como mucho una vez por semana: no cambia más deprisa y cuesta un clic y 3 s por carta
        h = load(f"{HIST_DIR}/{pid}.json", {}) or {}
        if not h.get("leido") or "resumen_1a" not in h or (ahora() - dt.datetime.fromisoformat(h["leido"])).days >= 7: res["semanas"] = leer_historial_tcg(pg, pid)
    except Exception as ex: print("  historial:", type(ex).__name__, str(ex)[:80])
    return res

def leer_collectr(pg, pid):
    """{"sin_gradear", "notas": {"PSA 10": dólares…}} o None."""
    pg.goto(f"https://app.getcollectr.com/explore/product/{pid}", timeout=60000, wait_until="domcontentloaded"); pg.wait_for_timeout(5000)
    t = re.sub(r"\s+", " ", pg.inner_text("body"))
    if BLOQUEO.search(t[:600]): raise PermissionError("Collectr pide verificación: se para")
    cab = t.split("Login for Watchlist")[0] if "Login for Watchlist" in t else ""
    precios = re.findall(USD, cab); sin = num(precios[-3]) if len(precios) >= 3 else (num(precios[0]) if precios and "Price Coming Soon" not in t else None)
    notas = {f"{h} {n}": num(v) for h, n, v in C_NOTA.findall(t)}
    return {"sin_gradear": sin, "notas": notas} if (sin or notas) else None

def _monotona(notas):
    """PSA 10 ≥ PSA 9 ≥ PSA 8: si no se cumple, esa cifra viene de una sola venta rara y no se usa."""
    r = [notas.get(f"PSA {n}") for n in (10, 9, 8)]; r = [x for x in r if x]; return all(a >= b for a, b in zip(r, r[1:]))

# ---- Registro: qué cartas (fuera de las Gold Star de cards.json) tienen referencia y con qué número de producto se leen.
# {"clave", "nombre", "patrones": [palabras que salen en el título], "numero": "006/016", "id": "611208" (Collectr = TCGplayer en las inglesas),
#  "edicion_sin_gradear": "Unlimited" | "1st Edition" | None (de qué edición es el precio sin gradear de la ficha), "edicion_notas": ídem para PSA/BGS/CGC}
# Las ediciones se anotan a mano tras mirar la ficha: Collectr enseña un precio por edición y no se adivina cuál es el que sale por defecto.
REG = P("referencia", "registro.json")
_reg_c = {"k": None, "v": [], "idx": {}, "otros": [], "t": 0.0}
def registro():
    """El registro de cartas con precio de referencia. Se lee del disco solo cuando el fichero cambia (antes, en cada llamada; y se llamaba una vez por anuncio); y se mira si cambió como mucho cada 2 s."""
    if _reg_c["k"] is not None and time.time() - _reg_c["t"] < 2: return _reg_c["v"]
    try: k = os.path.getmtime(REG)
    except OSError: return load(REG, []) or []
    _reg_c["t"] = time.time()
    if _reg_c["k"] != k:
        v = load(REG, []) or []; idx, otros = {}, []
        for pos, e in enumerate(v):
            a, _, b = str(e.get("numero") or "").partition("/")
            if a.isdigit() and b.isdigit(): idx.setdefault((int(a), int(b)), []).append((pos, e))
            else: otros.append((pos, e))
        _reg_c.update(k=k, v=v, idx=idx, otros=otros)
    return _reg_c["v"]
def registrar(clave, nombre, patrones, numero, pid, edicion_sin_gradear=None, edicion_notas=None):
    r = [x for x in registro() if x["clave"] != clave]
    r.append({"clave": clave, "nombre": nombre, "patrones": [p.lower() for p in patrones], "numero": numero, "id": str(pid), "edicion_sin_gradear": edicion_sin_gradear, "edicion_notas": edicion_notas})
    import os; os.makedirs(DIR, exist_ok=True); save(REG, r); return r[-1]

def entrada_de(l):
    """La entrada del registro a la que pertenece un anuncio: su número y una de sus palabras en el título. Un lote con otro número de la misma serie («006/016 008/016») no cuenta."""
    t = f"{l.get('title') or ''} {l.get('number') or ''}".lower()
    registro()      # (deja al día el índice por número)
    cand = list(_reg_c["otros"])      # las de número raro («062/L-P»): pocas, se miran todas
    for x, y in set(re.findall(r"(?<!\d)0*(\d{1,3})\s*/\s*0*(\d{1,3})(?!\d)", t)): cand += _reg_c["idx"].get((int(x), int(y)), [])      # las de número normal: solo las que dicen ese número (antes: todo el registro por cada anuncio)
    for _, e in sorted(cand, key=lambda z: z[0]):
        a, _, b = e["numero"].partition("/")
        if not (a.isdigit() and b.isdigit()):
            if e["numero"].lower() not in t: continue
        elif not re.search(rf"(?<!\d)0*{int(a)}\s*/\s*0*{int(b)}(?!\d)", t): continue      # «4/102» y «004/102» son el mismo número
        if not any(p in t for p in e["patrones"]): continue
        if b.isdigit() and any(int(n) != int(a) for n in re.findall(rf"(?<!\d)(\d{{1,3}})\s*/\s*0*{int(b)}(?!\d)", t)): continue      # un lote con otros números de la misma serie no cuenta
        return e
    return None

VIEJOS = set(SETS_ANTIGUOS_INICIALES) if "SETS_ANTIGUOS_INICIALES" in globals() else set()
def registrar_auto(e):
    """Cada carta que el servicio lee queda en el registro para que la búsqueda (rápida o exhaustiva) la compare. Se saca el nombre y el número de su nombre («Charizard 004/102 · Base Set Holo Rare»);
    en los sets antiguos la edición (1ª o Unlimited) no se sabe sin mirar la ficha a mano: se marca «?» y esos anuncios se enseñan con su referencia, pero sin la etiqueta de bajo mercado."""
    m = re.match(r"^(?P<n>.+?)\s+(?P<num>\d{1,3}/\d{1,3})\b", e["nombre"])
    if not m: return
    nombre = re.sub(r"\s*\(\d+\)\s*$", "", m["n"]).strip().lower()
    if len(nombre) < 3 or not (e.get("tcg") or e.get("collectr")): return
    vieja = e.get("set") in VIEJOS or e["clave"].startswith("d-") and e.get("set") in VIEJOS
    r = [x for x in registro() if x["clave"] != "auto-" + e["clave"]]
    r.append({"clave": "auto-" + e["clave"], "nombre": e["nombre"], "patrones": list(dict.fromkeys([nombre, nombre.replace("-", " ")])), "numero": m["num"], "id": str(e.get("tcg") or e.get("collectr")), "edicion_sin_gradear": "?" if vieja else None, "edicion_notas": "?" if vieja else None})
    save(REG, r)

_datos_c = {}
def datos(e):
    """La ficha de precios de una carta; se vuelve a leer solo si su fichero cambió (antes, un acceso al disco por anuncio)."""
    f = f"{DIR}/{e['id']}.json"
    try: k = os.path.getmtime(f)
    except OSError: return {}
    c = _datos_c.get(f)
    if not c or c[0] != k: c = _datos_c[f] = (k, load(f, {}) or {})
    return c[1]

def actualizar(ids, forzar=False):
    from playwright.sync_api import sync_playwright
    usd = usd_por_eur(); hecho = 0
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True); pg = b.new_context(locale="en-US", user_agent=UA, viewport={"width": 1400, "height": 2200}).new_page()
        for pid, nombre in ids:
            f = f"{DIR}/{pid}.json"; viejo = load(f, {}) or {}
            if not forzar and viejo.get("leido") and ahora() - dt.datetime.fromisoformat(viejo["leido"]) < dt.timedelta(hours=REFRESCO_H): continue
            try:
                tcg = leer_tcgplayer(pg, pid); time.sleep(PAUSA_S / 2); col = leer_collectr(pg, pid)
            except PermissionError as e:
                print(f"PARADO en {pid}: {e}"); break
            except Exception as e:
                print(f"  {pid} {nombre}: {type(e).__name__} {str(e)[:100]}"); time.sleep(PAUSA_S); continue
            r = {"id": pid, "nombre": nombre, "leido": ahora().isoformat(timespec="minutes"), "tcgplayer": tcg, "collectr": col, "usd_por_eur": usd}
            if col: col["notas_fiables"] = _monotona(col["notas"])
            if usd:
                for k in ("mercado", "ultima_venta", "venta_min", "venta_max", "anuncios_desde"):
                    if tcg and tcg.get(k): tcg[k + "_eur"] = round(tcg[k] / usd, 2)
            save(f, r); hecho += 1
            print(f"{nombre}: TCGplayer {tcg and tcg['mercado']} $ ({tcg and tcg['vendidas']} vendidas) · Collectr {col and col['sin_gradear']} $, notas {col and col['notas']}")
            time.sleep(PAUSA_S)
        b.close()
    return hecho

def cartas_conocidas():
    return [(str(c["tcg_id"]), c["nombre"]) for c in (load(P("precios", "cartas.json"), {}) or {}).get("cartas", []) if c.get("tcg_id")]

# ======================================================================== SERVICIO: la base de precios que se va llenando sola
# (Fernando, 5 de noviembre de 2026: «tenemos que tener una base de datos de precios; sin que nos bloqueen, pero sin parar, porque cuanto más tengamos mejor»).
# Un proceso aparte (server.py lo vigila y lo relanza) que lee UNA carta cada 40-90 s, con tope diario, y apunta cada lectura en data/referencia/lecturas.jsonl (una línea por fuente,
# con fecha y hora: ahí queda el historial de precios; DuckDB lo lee tal cual con read_json_auto). Nunca la misma carta dos veces en REFRESCO_H horas. Si una página pide verificación
# (CAPTCHA, muro de login) se para BLOQUEO_H horas y no se insiste: nada de saltar antibots. Orden: grails (los que va diciendo Fernando) > Gold Star > el resto de cartas seguidas.
import json, os, random, subprocess, urllib.parse
ESTADO = P("state", "referencia.json"); LECTURAS = P("referencia", "lecturas.jsonl"); GRAILS = P("referencia", "grails.json"); IDS = P("referencia", "ids.json")
LIMITE_DIA = 3000; PAUSA = (40, 90); BLOQUEO_MIN = 20      # Fernando (5 nov): «todas las que pueda»: con 40-90 s por carta salen unas 1.300 al día; el tope es solo una red de seguridad
MARCAR_JS = """(debe) => { let i = 0; const out = [];
  const ok = (t) => debe.every((d) => t.toLowerCase().includes(d));
  for (const e of document.querySelectorAll('div, a, li, button')) {
    const t = (e.innerText || '').replace(/\\s+/g, ' ');
    if (t.length > 220 || !ok(t) || [...e.children].some((ch) => ok((ch.innerText || '').replace(/\\s+/g, ' ')))) continue;
    e.setAttribute('data-pf', i++); out.push(t); }
  return out; }"""
# Los grails con los que se empieza. «debe»: palabras que tiene que decir el resultado de Collectr (nombre, set, rareza o «(jp)»); los ids se guardan en ids.json al resolverse.
GRAILS_INICIALES = [
    {"clave": "g-pikachu-ex-ssp", "nombre": "Pikachu ex 238/191 Surging Sparks", "idioma": "en", "tcg": "590027"},
    {"clave": "g-umbreon-vmax-evs", "nombre": "Umbreon VMAX 215/203 Evolving Skies", "idioma": "en", "tcg": "246723"},
    {"clave": "g-umbreon-vmax-jp", "nombre": "Umbreon VMAX alt art (JP) Eevee Heroes", "idioma": "ja", "collectr": "10000595"},
    {"clave": "g-charizard-pfl", "nombre": "Mega Charizard X ex Phantasmal Flames", "idioma": "en", "busqueda": "Mega Charizard X ex Phantasmal Flames", "debe": ["mega charizard x ex", "phantasmal flames", "special illustration rare"]},
    {"clave": "g-lugia-v-sit", "nombre": "Lugia V Silver Tempest alt art", "idioma": "en", "busqueda": "Lugia V Silver Tempest", "debe": ["lugia v", "silver tempest", "186/195"]},
] + [{"clave": f"g-{n.lower()}-ex-pre", "nombre": f"{n} ex Prismatic Evolutions (Special Illustration Rare)", "idioma": "en", "busqueda": f"{n} ex Prismatic Evolutions",
      "debe": [f"{n.lower()} ex", "prismatic evolutions", "special illustration rare"]} for n in ("Umbreon", "Espeon", "Sylveon", "Vaporeon", "Jolteon", "Flareon", "Leafeon", "Glaceon")]

# ---- Barrido de sets antiguos (Fernando, 5 nov: «que se vaya moviendo por todos los sets antiguos, sobre todo las más caras»): la página de búsqueda de un set en TCGplayer enseña 24 cartas
# por página con su número de producto y su precio de mercado; así se descubren las cartas sin buscar una a una. Solo entran en la cola las de MIN_PRECIO dólares o más, las más caras primero.
SETS_ANTIGUOS = P("referencia", "sets_antiguos.json"); DESCUBIERTAS = P("referencia", "descubiertas.json"); MIN_PRECIO = 20
SETS_ANTIGUOS_INICIALES = ["base-set", "jungle", "fossil", "base-set-2", "team-rocket", "gym-heroes", "gym-challenge", "neo-genesis", "neo-discovery", "neo-revelation", "neo-destiny", "legendary-collection",
    "expedition-base-set", "aquapolis", "skyridge", "ex-ruby-and-sapphire", "ex-sandstorm", "ex-dragon", "ex-team-magma-vs-team-aqua", "ex-hidden-legends", "ex-firered-leafgreen", "ex-team-rocket-returns",
    "ex-deoxys", "ex-emerald", "ex-unseen-forces", "ex-delta-species", "ex-legend-maker", "ex-holon-phantoms", "ex-crystal-guardians", "ex-dragon-frontiers", "ex-power-keepers",
    "wizards-black-star-promos", "nintendo-black-star-promos", "call-of-legends", "hs-unleashed", "hs-undaunted", "hs-triumphant"]
FILA_SET = re.compile(r"^(?P<cab>.*?), #(?P<num>\S+) (?P<nombre>.*?) (?:\d+ listings? from|Out of stock|No listings)")
LISTA_JS = """() => [...document.querySelectorAll('a[href*="/product/"]')].map((a) => ({href: a.getAttribute('href'), txt: (a.innerText || '').replace(/\\s+/g, ' ')}))"""

def descubrir_set(pg, slug):
    """Recorre las páginas de un set en TCGplayer y apunta sus cartas en descubiertas.json. Devuelve cuántas cartas leyó (0: el set no existe con ese nombre)."""
    desc = load(DESCUBIERTAS, {}) or {}; pagina, total, leidas = 1, None, 0
    while True:
        estado(beat=time.time())      # descubrir un set tarda varios minutos: sin latir aquí, el servidor creía muerto el servicio y lanzaba otro igual (dos navegadores con el mismo perfil)
        pg.goto(f"https://www.tcgplayer.com/search/pokemon/{slug}?productLineName=pokemon&setName={slug}&view=grid&ProductTypeName=Cards&page={pagina}", timeout=60000, wait_until="domcontentloaded"); pg.wait_for_timeout(5500)
        t = re.sub(r"\s+", " ", pg.inner_text("body"))
        if BLOQUEO.search(t[:600]): raise PermissionError("TCGplayer pide verificación: se para")
        if total is None:
            m = re.search(r"([\d,]+) results?", t); total = int(m.group(1).replace(",", "")) if m else 0
            if not total: return 0
        for f in pg.evaluate(LISTA_JS):
            pid = re.search(r"/product/(\d+)/", f["href"]); m = FILA_SET.match(f["txt"])
            if not pid or not m: continue
            p = re.search(r"Market Price:\s*\$([\d,]+(?:\.\d+)?)", f["txt"])
            desc[pid.group(1)] = {"clave": "d-" + pid.group(1), "nombre": f"{m['nombre']} {m['num']} · {m['cab']}", "tcg": pid.group(1), "idioma": "en", "set": slug, "precio": num(p.group(1)) if p else None, "visto": ahora().date().isoformat()}
            leidas += 1
        save(DESCUBIERTAS, desc)
        if pagina * 24 >= total or pagina >= 40: return leidas
        pagina += 1; time.sleep(random.uniform(6, 12))

def siguiente_set():
    s = load(SETS_ANTIGUOS, None)
    if s is None: s = [{"slug": x, "estado": "pendiente"} for x in SETS_ANTIGUOS_INICIALES]; save(SETS_ANTIGUOS, s)
    try: import par; mio = par.mio
    except Exception: mio = lambda k: True
    return next((x for x in s if x.get("estado") == "pendiente" and mio("set:" + x["slug"])), None)

def marcar_set(slug, estado_, n=0):
    s = load(SETS_ANTIGUOS, []) or []
    for x in s:
        if x["slug"] == slug: x.update(estado=estado_, cartas=n, fecha=ahora().date().isoformat())
    save(SETS_ANTIGUOS, s)

PEDIDOS = P("referencia", "pedidos.json")
PALABRAS_VACIAS = {"de", "del", "la", "el", "los", "las", "y", "and", "the", "of", "carta", "card", "pokemon", "pokémon", "japanese", "japonesa", "english", "inglés", "ingles", "unlimited", "1st", "edition"}

def encolar(query):
    """Una búsqueda que acaba de pedir Fernando: el Tasador pasa a ella antes que a nada (la prioridad son las búsquedas). Si ya tiene el precio de esa carta de hace menos de 36 h, lo reutiliza y no vuelve a leer.
    Devuelve «ya_lo_tenia» o «encolada»."""
    q = re.sub(r"\s+", " ", query or "").strip()
    if len(q) < 3: return None
    e = entrada_de({"title": q})
    if e:
        try:
            if (ahora() - dt.datetime.fromisoformat(datos(e)["leido"])).total_seconds() < 36 * 3600: return "ya_lo_tenia"
        except Exception: pass
    m = re.search(r"\d{1,3}/\d{1,3}", q); antes = (q[:m.start()] if m else q).lower().split()
    nombre = " ".join(w for w in antes if w not in PALABRAS_VACIAS)[:40].strip()
    debe = [nombre] + ([m.group(0)] if m else [])
    clave = "q-" + re.sub(r"[^a-z0-9]+", "-", q.lower())[:60].strip("-"); p = load(PEDIDOS, []) or []
    if any(x["clave"] == clave for x in p): return "encolada"
    p.append({"clave": clave, "nombre": q, "idioma": "en", "busqueda": q, "debe": [d for d in debe if d], "t": ahora().isoformat(timespec="minutes")})
    os.makedirs(DIR, exist_ok=True); save(PEDIDOS, p[-60:]); return "encolada"

def _quitar_pedido(clave):
    p = load(PEDIDOS, []) or []
    if any(x["clave"] == clave for x in p): save(PEDIDOS, [x for x in p if x["clave"] != clave])

def estado(**kw):
    s = load(ESTADO, {}) or {}
    if kw: s.update(kw); save(ESTADO, s)
    return s

def _ids(): return load(IDS, {}) or {}

def objetivos():
    """La cola completa, en orden de prioridad: [{"clave", "nombre", "idioma", "tcg", "collectr", "busqueda", "debe", "prio"}]."""
    os.makedirs(DIR, exist_ok=True)
    if not os.path.exists(GRAILS): save(GRAILS, GRAILS_INICIALES)
    out, vistos, ids = [], set(), _ids()
    def add(e, prio):
        e = {**e, **{k: v for k, v in (ids.get(e["clave"]) or {}).items() if v}, "prio": prio}; k = e.get("tcg") or e.get("collectr") or e["clave"]
        if k in vistos: return
        vistos.add(k); out.append(e)
    for g in load(PEDIDOS, []) or []: add(g, -1)      # lo que se acaba de pedir en una búsqueda: va antes que todo
    for g in load(GRAILS, []) or []: add(g, 0)
    try:
        import ventas
        for key, c in ventas.cartas().items():
            ps = ((load(os.path.join(ventas.DIR, key + ".json"), {}) or {}).get("collectr") or {}).get("productos") or []
            if ps: add({"clave": "gs-" + key, "nombre": c["name_en"] + " (JP, Gold Star)", "idioma": "ja", "collectr": ps[0]["id"]}, 1)
    except Exception as ex: print("objetivos Gold Star:", ex)
    for c in (load(P("precios", "cartas.json"), {}) or {}).get("cartas", []):
        if c.get("tcg_id"): add({"clave": "p-" + c["clave"], "nombre": c["nombre"], "idioma": "ja" if "japonesa" in c["nombre"] or c.get("idioma") == "japanese" else "en", "tcg": str(c["tcg_id"]), "numero": c.get("numero"), "base": c.get("base"), "set": c.get("set")}, 2)
    for d in sorted((load(DESCUBIERTAS, {}) or {}).values(), key=lambda x: -(x.get("precio") or 0)):      # las cartas descubiertas en los sets antiguos, las más caras primero
        if (d.get("precio") or 0) >= MIN_PRECIO or d.get("forzar"): add(d, 3)      # «forzar»: sets de una campaña de búsqueda (Double Crisis entero), aunque la carta sea barata
    return out

def _hace_h(e):
    f = load(f"{DIR}/{e.get('tcg') or e.get('collectr')}.json", {}) if (e.get("tcg") or e.get("collectr")) else {}
    try: return (ahora() - dt.datetime.fromisoformat(f["leido"])).total_seconds() / 3600
    except Exception: return 9999

def siguiente():
    """La primera carta de la cola (por prioridad, luego la menos reciente) a la que le toca lectura, o None si todas están al día."""
    try: import par; mio = par.mio
    except Exception: mio = lambda k: True      # con el par apagado (o sin par.py) todo es mío; con él activo, cada carta la hace solo su dueño (y lo pedido en una búsqueda, siempre yo)
    c = [e for e in objetivos() if _hace_h(e) >= REFRESCO_H and not ((_ids().get(e["clave"]) or {}).get("fallos", 0) >= 3) and (e["prio"] < 0 or mio(e["clave"]))]
    c.sort(key=lambda e: (e["prio"], -(e.get("precio") or 0) if e["prio"] == 3 else 0, -_hace_h(e))); return c[0] if c else None

def resolver(pg, e):
    """El número de producto de Collectr de una carta: busca su nombre, se queda con el resultado que dice todas las palabras de «debe» y lo abre. None si no está."""
    pg.goto("https://app.getcollectr.com/", timeout=60000, wait_until="domcontentloaded"); pg.wait_for_timeout(3000)
    box = pg.locator("input[type=search]").first; box.fill(e["busqueda"]); box.press("Enter"); pg.wait_for_timeout(4500)
    if BLOQUEO.search(re.sub(r"\s+", " ", pg.inner_text("body"))[:600]): raise PermissionError("Collectr pide verificación")
    res = pg.evaluate(MARCAR_JS, [d.lower() for d in e.get("debe") or []])
    if not res: return None
    pg.locator('[data-pf="0"]').first.click(timeout=10000); pg.wait_for_url(re.compile(r"/explore/product/\d+"), timeout=20000)
    return re.search(r"/explore/product/(\d+)", pg.url).group(1)

def _apuntar(e, tcg, col):
    t = ahora().isoformat(timespec="seconds"); os.makedirs(DIR, exist_ok=True)
    if tcg and tcg.get("anuncios"):
        with open(ANUNCIOS_TCG, "a", encoding="utf-8") as fa: fa.write(json.dumps({"t": t, "clave": e["clave"], "nombre": e["nombre"], "id": e.get("tcg"), "anuncios": tcg["anuncios"]}, ensure_ascii=False) + "\n")
    if tcg: tcg = {k: v for k, v in tcg.items() if k != "anuncios"}      # en la lectura principal no se repiten (ya están en su fichero)
    with open(LECTURAS, "a", encoding="utf-8") as f:
        if tcg: f.write(json.dumps({"t": t, "clave": e["clave"], "nombre": e["nombre"], "idioma": e["idioma"], "fuente": "tcgplayer", "id": e.get("tcg"), "estado": "NM", **tcg}, ensure_ascii=False) + "\n")
        if col: f.write(json.dumps({"t": t, "clave": e["clave"], "nombre": e["nombre"], "idioma": e["idioma"], "fuente": "collectr", "id": e.get("collectr") or e.get("tcg"), **col}, ensure_ascii=False) + "\n")

def leer_carta(pg, e):
    """Lee la carta (resolviendo antes su número si falta) y la apunta. Devuelve (tcg, col)."""
    ids = _ids(); ficha = ids.setdefault(e["clave"], {})
    if not (e.get("tcg") or e.get("collectr")):
        pid = resolver(pg, e)
        if not pid: ficha["fallos"] = ficha.get("fallos", 0) + 1; save(IDS, ids); raise LookupError("no está en Collectr: " + e["nombre"])
        e["collectr"] = ficha["collectr"] = pid
        if e["idioma"] == "en" and int(pid) < 10_000_000: e["tcg"] = ficha["tcg"] = pid      # en las inglesas el número de Collectr es el de TCGplayer: se lee también su ficha (ventas y rango)
        save(IDS, ids)
    tcg = col = None; cid = e.get("collectr") or e.get("tcg")
    if e.get("tcg"):
        try: tcg = leer_tcgplayer(pg, e["tcg"]); time.sleep(PAUSA_S / 2)
        except PermissionError: raise
        except Exception as ex: print(f"  TCGplayer {e['clave']}: {type(ex).__name__}")
    try: col = leer_collectr(pg, cid)
    except PermissionError: raise
    except Exception as ex: print(f"  Collectr {e['clave']}: {type(ex).__name__}")
    if not (tcg or col): ficha["fallos"] = ficha.get("fallos", 0) + 1; save(IDS, ids); raise LookupError("sin datos: " + e["nombre"])
    usd = usd_por_eur(); r = {"id": cid, "nombre": e["nombre"], "leido": ahora().isoformat(timespec="minutes"), "tcgplayer": tcg, "collectr": col, "usd_por_eur": usd}
    if col: col["notas_fiables"] = _monotona(col["notas"])
    if usd and tcg:
        for k in ("mercado", "ultima_venta", "venta_min", "venta_max", "anuncios_desde"):
            if tcg.get(k): tcg[k + "_eur"] = round(tcg[k] / usd, 2)
    save(f"{DIR}/{e.get('tcg') or cid}.json", r); _apuntar(e, tcg, col); ficha["fallos"] = 0; save(IDS, ids)
    try: registrar_auto(e)
    except Exception as ex: print("registro:", type(ex).__name__, ex)
    if e["clave"].startswith("q-"): _quitar_pedido(e["clave"])
    return tcg, col

def lecturas_hoy():
    """Cartas leídas hoy (cada una deja una o dos líneas en lecturas.jsonl, una por fuente: se cuentan las claves distintas)."""
    claves = set(); hoy = ahora().date().isoformat()
    try:
        for ln in open(LECTURAS, encoding="utf-8"):
            if ln[7:17] == hoy and '"fuente": "pokewallet"' not in ln: claves.add(json.loads(ln).get("clave"))      # PokéWallet va aparte (su propio tope): no cuenta para el del navegador
    except OSError: pass
    return len(claves)

def lecturas_de_hoy(n=8):
    """Las últimas cartas leídas hoy para el panel de la Oficina: [{"time", "what", "res"}]."""
    out = {}; hoy = ahora().date().isoformat()
    try:
        for ln in open(LECTURAS, encoding="utf-8"):
            if ln[7:17] != hoy or '"fuente": "pokewallet"' in ln: continue
            d = json.loads(ln); o = out.setdefault(d["clave"], {"time": d["t"][11:16], "what": d["nombre"][:70], "res": ""})
            if d["fuente"] == "tcgplayer" and d.get("mercado"): o["res"] = f"TCGplayer {d['mercado']:,.0f} $" + (f" · {d['vendidas']} vendidas" if d.get("vendidas") else "") + (" · " + o["res"] if o["res"] else "")
            if d["fuente"] == "collectr": o["res"] = (o["res"] + " · " if o["res"] else "") + (f"Collectr {d['sin_gradear']:,.0f} $" if d.get("sin_gradear") else f"Collectr {len(d.get('notas') or {})} notas")
    except OSError: pass
    return sorted(out.values(), key=lambda x: x["time"])[-n:]


def viva(): return time.time() - (load(ESTADO, {}) or {}).get("beat", 0) < 120      # el servicio late cada 20 s aunque duerma

def lanzar():
    here = os.path.dirname(os.path.abspath(__file__)); os.makedirs(P("state"), exist_ok=True)
    subprocess.Popen([sys.executable, os.path.join(here, "referencia.py"), "--servicio"], cwd=here, env={**os.environ, "PYTHONIOENCODING": "utf-8"}, stdin=subprocess.DEVNULL,
                     stdout=open(P("state", "referencia.log"), "a", encoding="utf-8"), stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

PERFIL = P("referencia", "navegador")      # el perfil del navegador del servicio: lo que se verifica a mano (CAPTCHA) queda guardado y el servicio sigue con ello

def dormir(seg):
    """Duerme en trozos de 20 s latiendo, para que la Oficina vea que el servicio sigue vivo (y para reaccionar enseguida a «parar» o «desbloquear»)."""
    fin = time.time() + seg
    while time.time() < fin:
        estado(beat=time.time()); time.sleep(min(20, max(0, fin - time.time())))
        s = estado()
        if s.get("parar") or s.get("desbloquear"): return

def _abrir(p, visible=False):
    ctx = p.chromium.launch_persistent_context(PERFIL, headless=not visible, locale="en-US", user_agent=UA, viewport={"width": 1400, "height": 2200} if not visible else None)
    return ctx, (ctx.pages[0] if ctx.pages else ctx.new_page())

def desbloquear(p, ctx, url):
    """Abre una ventana VISIBLE en la página que pidió verificación para que Fernando la haga a mano (nunca se resuelve sola). Espera hasta 10 min a que la página deje de pedirla o se cierre la ventana;
    después vuelve al navegador oculto con lo verificado guardado. Devuelve el contexto oculto nuevo."""
    ctx.close(); estado(desbloqueando=True, desbloquear=False)
    vis, pv = _abrir(p, visible=True)
    try:
        pv.goto(url, timeout=60000, wait_until="domcontentloaded"); fin = time.time() + 600
        while time.time() < fin and vis.pages:
            estado(beat=time.time()); time.sleep(3)
            try:
                if not BLOQUEO.search(re.sub(r"\s+", " ", pv.inner_text("body"))[:600]): break
            except Exception: break
    except Exception as ex: print("desbloquear:", type(ex).__name__)
    finally:
        try: vis.close()
        except Exception: pass
    estado(desbloqueando=False, bloqueo=None, pausa_hasta=None, motivo=None)
    return _abrir(p)

# ---- Carril de PokéWallet (Fernando, 6 nov: «enchúfalo al Tasador y que la use también»): una API con 1.000 peticiones al día (100 por hora) que da el precio SIN GRADEAR de TCGplayer (USD, por edición)
# y el de Cardmarket (EUR: tendencia, medias 1/7/30 días, mínimo). Corre en un hilo del mismo servicio, a su ritmo, sin tocar el navegador ni las cuotas de eBay/TCGAPI/PPT. Solo cartas con número de TCGplayer.
PW_DIR = P("referencia", "pokewallet"); PW_ESTADO = P("state", "pokewallet.json"); PW_PAUSA = 40; PW_DIA = 950; PW_RESERVA = 10; PW_REPETIR_H = 24; PW_FALLO_H = 168

def _pw_estado(**kw):
    e = load(PW_ESTADO, {}) or {}
    if kw: e.update(kw); save(PW_ESTADO, e)
    return e

def pokewallet_una(e, k, http):
    """Pide a PokéWallet la carta `e` (nombre «Charizard 004/102 · …») y se queda con el resultado cuyo número de producto de TCGplayer es el suyo. Devuelve (ficha|None, restan_hora|None, http_estado)."""
    m = None      # (sin esto, las Gold Stars con numero+base daban «UnboundLocalError» más abajo y el carril de PokéWallet se paraba)
    if e.get("numero") and e.get("base"): q = f"{e['numero']} {str(e['base']).replace(' - ', ' ')}"      # las cartas de precios/cartas.json (Gold Stars, promos…): «105/107 Latias Star» (10 de 10 aciertos en la prueba)
    else:
        m = re.match(r"^(?P<n>.+?)\s+(?P<num>\d{1,3}/\d{1,3})\b", e["nombre"])
        q = f"{m['num']} {m['n']}" if m else re.sub(r"\s*\([^)]*\)", "", e["nombre"]).strip()      # sin número (los grails «Espeon ex Prismatic Evolutions»): por el nombre, y se empareja por el número de producto
    est, cab, d = http("https://api.pokewallet.io/search?" + urllib.parse.urlencode({"q": q, "limit": 8 if m else 25}), {"X-API-Key": k})
    try: restan = int(cab.get("x-ratelimit-remaining-hour"))
    except (TypeError, ValueError): restan = None
    if est != 200 or not isinstance(d, dict): return None, restan, est
    for r in d.get("results") or []:
        tp, cm = r.get("tcgplayer") or {}, r.get("cardmarket") or {}; mm = re.search(r"/product/(\d+)", str(tp.get("url") or ""))
        if mm and mm.group(1) == str(e.get("tcg")):
            return {"tcgplayer_usd": {p.get("sub_type_name"): p.get("market_price") for p in tp.get("prices") or [] if p.get("market_price")},
                    "cardmarket_eur": {p.get("variant_type"): {a: p.get(a) for a in ("trend", "avg1", "avg7", "avg30", "low")} for p in cm.get("prices") or []}}, restan, est
    return None, restan, est

def pokewallet_loop():
    """Hilo del servicio: una carta cada PW_PAUSA s (≈90 por hora, bajo el límite de 100), con tope diario PW_DIA y dejando PW_RESERVA peticiones por hora para el resto de la app."""
    try: import precios_graduadas as PG; k = PG._clave("pokewallet"); http = PG._http
    except Exception as ex: print("pokewallet: sin módulo", ex); return
    if not k: print("pokewallet: sin clave (python tools/poner_clave.py pokewallet)"); return
    try: import par; mio = par.mio
    except Exception: mio = lambda c: True
    os.makedirs(PW_DIR, exist_ok=True)
    while True:
        try:
            hoy = ahora().date().isoformat(); st = _pw_estado()
            if st.get("dia") != hoy: st = _pw_estado(dia=hoy, hoy=0)
            if st.get("hoy", 0) >= PW_DIA: _pw_estado(motivo="tope del día"); time.sleep(1800); continue
            if time.time() < st.get("pausa_hasta", 0): time.sleep(60); continue
            vistas = st.get("vistas") or {}; ahora_t = time.time(); cola = []
            for e in objetivos():
                if not e.get("tcg") or not (e["prio"] < 0 or mio(e["clave"])): continue
                v = vistas.get(str(e["tcg"]))
                if v and ahora_t - v["t"] < (PW_REPETIR_H if v["ok"] else PW_FALLO_H) * 3600: continue
                cola.append(e)
            if not cola: _pw_estado(motivo="todo al día", cola=0); time.sleep(1800); continue
            cola.sort(key=lambda e: (e["prio"], -(e.get("precio") or 0)))
            e = cola[0]; _pw_estado(cola=len(cola), motivo=None, actual=e["nombre"])
            ficha, restan, est = pokewallet_una(e, k, http)
            if est == 429: _pw_estado(pausa_hasta=time.time() + 15 * 60, motivo="límite por hora: espera 15 min"); continue
            if est == 0: vistas[str(e["tcg"])] = {"t": ahora_t, "ok": False}      # nombre sin número: no se puede buscar
            elif est != 200: _pw_estado(pausa_hasta=time.time() + 5 * 60, motivo=f"PokéWallet contestó {est}"); continue
            else:
                vistas[str(e["tcg"])] = {"t": ahora_t, "ok": bool(ficha)}
                if ficha:
                    t = ahora().isoformat(timespec="seconds"); usd = usd_por_eur()
                    save(f"{PW_DIR}/{e['tcg']}.json", {"id": str(e["tcg"]), "nombre": e["nombre"], "leido": t, "usd_por_eur": usd, **ficha})
                    with open(LECTURAS, "a", encoding="utf-8") as f: f.write(json.dumps({"t": t, "clave": e["clave"], "nombre": e["nombre"], "idioma": e["idioma"], "fuente": "pokewallet", "id": str(e["tcg"]), **ficha}, ensure_ascii=False) + "\n")
            _pw_estado(vistas=vistas, hoy=_pw_estado().get("hoy", 0) + 1, restan_hora=restan, ultima=e["nombre"], ultima_t=ahora().isoformat(timespec="minutes"), actual=None)
            if restan is not None and restan < PW_RESERVA: _pw_estado(pausa_hasta=time.time() + 10 * 60, motivo="límite por hora casi agotado")
        except Exception as ex: print("pokewallet:", type(ex).__name__, str(ex)[:120]); time.sleep(120)
        time.sleep(PW_PAUSA)

def servicio():
    """Bucle sin fin: una carta cada 40-90 s mientras haya cartas que tocan y no se haya llegado al tope del día. Si una web pide verificación se para (BLOQUEO_MIN minutos como mucho, o hasta que
    Fernando la verifique desde la Oficina: «Lanzar ahora» en la ficha del Tasador abre una ventana) y la Oficina enseña qué web es y desde cuándo."""
    from playwright.sync_api import sync_playwright
    viejo = estado().get("pid")      # un solo servicio a la vez: dos con el mismo perfil de navegador se pisan la caché (y el antivirus lo ve como un intento de borrarla)
    if viejo and viejo != os.getpid():
        try:
            if str(viejo) in subprocess.run(["tasklist", "/FI", f"PID eq {viejo}", "/NH"], capture_output=True, text=True, timeout=15).stdout and not estado().get("parar"): print(f"ya hay un servicio vivo (pid {viejo}): este se cierra"); return
        except Exception: pass
    estado(pid=os.getpid(), beat=time.time(), arranque=ahora().isoformat(timespec="minutes"), parar=False, desbloquear=False, desbloqueando=False)
    import threading; threading.Thread(target=pokewallet_loop, daemon=True).start()
    def catalogo_loop():      # cada 15 minutos pasa lo leído al estándar (catalogo.py, ESTANDAR-CARTAS.md); idempotente
        while True:
            try: import catalogo; catalogo.ingerir()
            except Exception as ex: print("catálogo:", type(ex).__name__, str(ex)[:120])
            time.sleep(900)
    threading.Thread(target=catalogo_loop, daemon=True).start()
    with sync_playwright() as p:
        ctx, pg = _abrir(p); hechas = 0
        while True:
            s = estado(beat=time.time(), actual=None)
            try:
                if s.get("parar"): print("parado desde la Oficina"); estado(parar=False, pid=None, beat=0); ctx.close(); return
                if s.get("desbloquear") and s.get("bloqueo"): ctx, pg = desbloquear(p, ctx, s["bloqueo"].get("url") or "https://www.tcgplayer.com/"); continue
                s["desbloquear"] and estado(desbloquear=False)
                if s.get("pausa_hasta") and time.time() < s["pausa_hasta"]: dormir(60); continue
                if s.get("bloqueo"): estado(bloqueo=None, pausa_hasta=None, motivo="reintento tras la pausa")
                if lecturas_hoy() >= LIMITE_DIA: estado(motivo="tope del día"); dormir(1800); continue
                e = siguiente(); ss = siguiente_set()
                if ss and (not e or hechas % 25 == 24):      # descubrir las cartas de un set antiguo (hasta 40 páginas) cuando no hay nada que tasar y, de vez en cuando, entre cartas
                    estado(actual="Descubriendo las cartas del set " + ss["slug"], beat=time.time()); hechas += 1
                    try: n = descubrir_set(pg, ss["slug"]); marcar_set(ss["slug"], "hecho" if n else "sin_resultados", n); print(f"{ahora():%H:%M} set {ss['slug']}: {n} cartas descubiertas")
                    except PermissionError: raise
                    except Exception as ex: print("set", ss["slug"], type(ex).__name__, str(ex)[:100]); marcar_set(ss["slug"], "error")
                    estado(actual=None, beat=time.time()); dormir(random.uniform(*PAUSA)); continue
                if not e: estado(motivo="todo al día", cola=0); dormir(1800); continue
                estado(actual=e["nombre"], motivo=None, cola=sum(1 for x in objetivos() if _hace_h(x) >= REFRESCO_H), beat=time.time())
                tcg, col = leer_carta(pg, e); hechas += 1
                estado(ultima=e["nombre"], ultima_t=ahora().isoformat(timespec="minutes"), actual=None, beat=time.time())
                print(f"{ahora():%H:%M} {e['nombre']}: TCGplayer {tcg and tcg.get('mercado')} · Collectr {col and col.get('sin_gradear')}")
                if hechas % 80 == 0: ctx.close(); ctx, pg = _abrir(p)
            except PermissionError as ex:
                web = "TCGplayer" if "tcgplayer" in pg.url else "Collectr" if "collectr" in pg.url else str(ex)
                estado(bloqueo={"web": web, "url": pg.url, "desde": ahora().isoformat(timespec="minutes")}, pausa_hasta=time.time() + BLOQUEO_MIN * 60, motivo=f"{web} pidió verificación", actual=None); print("BLOQUEO:", ex)
            except LookupError as ex: print(" ", ex)
            except Exception as ex: print("error:", type(ex).__name__, str(ex)[:120]); dormir(60)
            dormir(random.uniform(*PAUSA))
if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--prueba", type=int); ap.add_argument("--id", action="append"); ap.add_argument("--todas", action="store_true"); ap.add_argument("--forzar", action="store_true")
    ap.add_argument("--servicio", action="store_true"); ap.add_argument("--cola", action="store_true")
    a = ap.parse_args(); sys.stdout.reconfigure(encoding="utf-8")
    if a.servicio: servicio(); sys.exit(0)
    if a.cola:
        for e in objetivos(): print(e["prio"], e["clave"], "|", e["nombre"], "|", e.get("tcg") or e.get("collectr") or "(por resolver)", f"| hace {_hace_h(e):.0f} h")
        sys.exit(0)
    conocidas = cartas_conocidas()
    ids = [(i, dict(conocidas).get(i, i)) for i in a.id] if a.id else conocidas[:a.prueba] if a.prueba else conocidas if a.todas else []
    if not ids: sys.exit(__doc__)
    print(actualizar(ids, a.forzar), "cartas leídas")