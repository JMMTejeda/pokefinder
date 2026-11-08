"""Foto diaria de precios de las cartas que sigue Fernando, con TODAS las API de precios que tienen plan gratis (owner, 4 November 2026: "todos los días mínimo las 27 Gold Stars, las de Call of Legends,
el Campaign Set y las promos... tírale, usa todas las APIs"). Cada fuente aporta lo que sabe hacer y se guardan SEPARADAS (nunca se mezclan en una sola cifra):
- PokemonPriceTracker (ppt): ventas de eBay por nota (PSA 10/9/8/7, CGC, BGS, TAG, ACE): nº de ventas, mediana, media, mínimo, máximo y fecha de la última. Es lo que SE VENDIÓ. Cuesta 2 créditos por carta y el plan gratis da 100 al día.
- PokéWallet (pokewallet): TCGplayer (USD) y Cardmarket (EUR: tendencia, media 1/7/30 días) de la carta sin gradear. 100 peticiones por hora, 1.000 al día.
- TCGAPI.dev (tcgapi): mercado, mediana y nº de anuncios de TCGplayer, y de las Gold Stars en inglés también ventas agregadas (sales_volume, avg_sales_price). Y la versión japonesa (game=pokemon-japan). 100 peticiones al día.
- PokéSats: queda fuera del diario (la vista previa gratis son 50 consultas en total y pide otros identificadores de carta): solo para la población PSA, a mano.
Los precios de TCGplayer/Cardmarket son lo que PIDEN y lo medio vendido en esas tiendas, no el valor de una graduada; el valor de una graduada sale de las ventas de eBay (ppt).

    python precios_graduadas.py --candidatos     busca en PokéWallet qué carta es cada una (data/precios/candidatos.json y notas/precios-candidatos.md); sigue donde lo dejó si se acaba el cupo por hora
    python precios_graduadas.py --foto           la foto de hoy con todas las fuentes que tengan clave (se para sola al quedar poco cupo y continúa en la siguiente vuelta)
    python precios_graduadas.py --foto --solo ppt   solo una fuente (ppt, pokewallet, tcgapi)
    python precios_graduadas.py --estado

data/precios/cartas.json: las cartas con su identificador (se rellena solo con la primera candidata; para cambiar una a mano: pon "fijo": true). data/precios/excluir.json: las que Fernando no quiere.
Claves en .secrets/ (las pone él con tools/poner_clave.py): pokemonpricetracker, pokewallet, tcgapi."""
import datetime as dt, json, os, re, subprocess, sys, time, urllib.parse, urllib.request, urllib.error
from common import P, ROOT, TZ, load, save
import compartir as CP      # el reparto con el compañero (compartir.dueno / ajenos_de / publicar_item)

CARTAS = P("precios", "cartas.json"); CAND = P("precios", "candidatos.json"); HIST = P("precios", "historial.json"); ESTADO = P("precios", "estado.json"); EXCL = P("precios", "excluir.json")
NOTAS = os.path.join(ROOT, "notas", "precios-candidatos.md")
NOTAS_QUE_SE_GUARDAN = ("psa10", "psa9", "psa8", "psa7", "cgc10", "cgc9_5", "cgc9", "bgs10", "bgs9_5", "bgs9", "tag10", "ace10")
RESERVA = 6                     # no se gasta si quedan menos créditos de PokemonPriceTracker (para no dejar a 0 sus pruebas)
JP_SETS = ("Clash of the Blue Sky", "Rocket Gang Strikes Back", "Golden Sky, Silvery Ocean", "Mirage Forest", "Holon Research Tower", "Miracle Crystal", "Gift Box Mew - Lucario")
EXCLUIR_POR_DEFECTO = ["gs-espeon-play", "gs-umbreon-play"]      # Fernando, 4 de noviembre: "quita Umbreon y Espeon Gold Star japonesas" (las promos PLAY)
FUENTES = ("ppt", "pokewallet", "tcgapi")


HORA_REPARTO = 14      # pasada esta hora, las cartas del compañero que siguen sin datos las pide uno mismo (por si el otro tiene el ordenador apagado)

def ahora(): return dt.datetime.now(TZ)

def importar_precios(snap, dia):
    """Mete en la foto de hoy lo que el compañero ya ha pedido (compartido/precios/<día>-<quién>.json.gz): sus cartas llegan sin gastar créditos tuyos. Devuelve cuántos datos entraron. Nunca lanza."""
    n = 0
    try:
        for nombre, (path, quien) in CP.ajenos_de("precios", 120).items():
            if nombre != dia: continue
            for k, v in ((CP.leer(path) or {}).get("cartas") or {}).items():
                e = snap["cartas"].setdefault(k, {a: v.get(a) for a in ("nombre", "grupo", "tcg_id", "set", "numero", "idioma", "imagen")})
                for f in FUENTES:
                    if v.get(f) is not None and e.get(f) is None: e[f] = v[f]; e.setdefault("de", {})[f] = quien; n += 1
    except Exception as ex: print("importar precios:", ex)
    return n

def publicar_precios(snap, dia):
    """Sube SOLO lo que pidió este ordenador (lo importado no se vuelve a subir). Devuelve cuántos datos subió."""
    mias = {}
    for k, v in snap["cartas"].items():
        d = {f: v[f] for f in FUENTES if v.get(f) is not None and f not in (v.get("de") or {})}
        if d: mias[k] = {**{a: v.get(a) for a in ("nombre", "grupo", "tcg_id", "set", "numero", "idioma", "imagen")}, **d}
    n = sum(len([f for f in FUENTES if f in v]) for v in mias.values())
    if n: CP.publicar_item("precios", dia, {"date": dia, "cartas": mias}, "Precios " + dia)
    return n
def _clave(nombre):
    try:
        with open(os.path.join(ROOT, ".secrets", nombre + ".json"), encoding="utf-8") as f: v = str(json.load(f).get("api_key") or "").strip()
        return "" if (not v or v.startswith(("PEGA", "TU_"))) else v
    except (OSError, ValueError): return ""


def _http(url, headers, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "PokeFinder/1.0", "Accept": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: est, cab, cuerpo = r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e: est, cab, cuerpo = e.code, dict(e.headers or {}), e.read()
    except Exception as e: return 0, {}, {"_error": f"{type(e).__name__}: {str(e)[:80]}"}
    cab = {a.lower(): b for a, b in cab.items()}
    try: d = json.loads(cuerpo.decode("utf-8", "replace"))
    except ValueError: d = {"_error": "respuesta que no es JSON"}
    try: _apuntar_uso(url, est, cab, d)
    except Exception: pass      # llevar la cuenta nunca puede romper una lectura
    return est, cab, d

# ---- El gasto de las API, día a día (Fernando, 5 nov: «¿cómo llevamos el gasto de APIs? el fotógrafo no ha gastado nada»): antes el cupo solo vivía en memoria durante una vuelta y nadie veía cuánto se había gastado
# ni por qué se paraba. Ahora cada petición se apunta (cuántas por fuente y día, qué quedaba y cuándo se reinicia) y una fuente que ya dijo «hasta mañana» no se vuelve a preguntar hasta entonces.
USO = P("state", "api_precios.json")
FUENTE_DE = (("pokemonpricetracker", "ppt"), ("pokewallet", "pokewallet"), ("tcgapi", "tcgapi"))

def _apuntar_uso(url, est, cab, d):
    f = next((n for h, n in FUENTE_DE if h in url), None)
    if not f: return
    u = load(USO, {}) or {}; hoy = dt.datetime.now(TZ).date().isoformat(); dia = u.setdefault("dias", {}).setdefault(hoy, {}); dia[f] = dia.get(f, 0) + 1
    u["dias"] = {k: v for k, v in sorted(u["dias"].items())[-14:]}
    fu = u.setdefault("fuentes", {}).setdefault(f, {})
    restan = cab.get("x-ratelimit-daily-remaining") or cab.get("x-ratelimit-remaining-day") or cab.get("x-ratelimit-remaining")
    try: fu["restan"] = int(restan)
    except (TypeError, ValueError): pass
    try: fu["limite"] = int(cab.get("x-ratelimit-limit") or cab.get("x-ratelimit-limit-day") or fu.get("limite") or 0) or None
    except (TypeError, ValueError): pass
    fu["visto"] = dt.datetime.now(TZ).isoformat(timespec="minutes"); fu["estado"] = est
    if est == 429:      # hasta cuándo no se pregunta más: lo que dice la propia API (medianoche UTC) o, si no lo dice, dentro de 1 h
        reset = (d.get("resetsAt") if isinstance(d, dict) else None) or cab.get("x-ratelimit-reset")
        try: hasta = dt.datetime.fromisoformat(str(reset).replace("Z", "+00:00")).timestamp()
        except Exception: hasta = time.time() + 3600
        fu["hasta"] = hasta; fu["motivo"] = (d.get("error") if isinstance(d, dict) and isinstance(d.get("error"), str) else (d.get("error") or {}).get("message") if isinstance(d, dict) else None) or "límite alcanzado"
    elif est == 200: fu.pop("hasta", None)
    save(USO, u)


def excluidas():
    v = load(EXCL, None)
    if v is None: save(EXCL, EXCLUIR_POR_DEFECTO); v = EXCLUIR_POR_DEFECTO
    return set(v)


# ------------------------------------------------------------------------------------------------------------- 1) qué cartas son
EXTRAS = [      # las cartas modernas que Fernando busca (alt art): donde las API tienen cientos de ventas. Se identifican con TCGAPI.dev (devuelve el número exacto) y van las primeras
    ("mod-pikachu-ex-238", "Pikachu ex 238/191 · Surging Sparks", "Pikachu ex 238/191", "238/191"),
    ("mod-lugia-v-186", "Lugia V 186/195 · Silver Tempest", "Lugia V 186/195", "186/195"),
    ("mod-mega-charizard-x-ex-125", "Mega Charizard X ex 125/094 · Phantasmal Flames", "Mega Charizard X ex 125/094", "125/094"),
    ("mod-umbreon-vmax-215", "Umbreon VMAX 215/203 · Evolving Skies", "Umbreon VMAX 215/203", "215/203"),
]

def cartas_base():
    """22 Gold Stars + 5 promos PLAY de las evoluciones de Eevee (menos las que Fernando quita) y las de «Call of Legends / Campaign Set / Promos» (sus búsquedas guardadas)."""
    gs = load(os.path.join(ROOT, "data", "app", "searches", "gold_stars.json"), {}).get("pokemon") or []
    cl = load(os.path.join(ROOT, "data", "app", "searches", "q-call-of-legends-2026-11-02-de-fernandoiniguez.json"), {}).get("pokemon") or []
    out = [{"clave": f"gs-{n.lower()}", "nombre": f"{n} ☆", "grupo": "Gold Stars", "busca": f"{n} Star", "filtro": "star"} for n in gs if isinstance(n, str)]
    out += [{"clave": f"gs-{n.lower()}-play", "nombre": f"{n} ☆ (PLAY Promo)", "grupo": "Gold Stars", "busca": f"{n} Star", "filtro": "play"} for n in ("Espeon", "Umbreon", "Vaporeon", "Jolteon", "Flareon")]
    for t in cl:
        if not isinstance(t, str) or re.search(r"[぀-ヿ]", t): continue      # las líneas en japonés repiten HGSS19-21
        out.append({"clave": "cl-" + re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-"), "nombre": t, "grupo": "Call of Legends / Campaign / Promos", "busca": t.replace(" call of legends", ""), "filtro": ""})
    out = [{"clave": k, "nombre": n, "grupo": "Modernas (alt art)", "busca": q, "filtro": "mod", "numero": num} for k, n, q, num in EXTRAS] + out
    ex = excluidas()
    return [c for c in out if c["clave"] not in ex]


def candidatos():
    k = _clave("pokewallet")
    if not k: print("Falta .secrets/pokewallet.json (python tools/poner_clave.py pokewallet)"); return 1
    res = []; previas = {x["clave"]: x for x in (load(CAND, {}) or {}).get("cartas", []) if x.get("candidatas") and x.get("v") == 2}      # lo ya encontrado no se vuelve a pedir: PokéWallet da 100 peticiones por HORA
    parar = False
    for c in cartas_base():
        if c["clave"] in previas: res.append({**previas[c["clave"]], **{a: c[a] for a in ("nombre", "grupo", "busca", "filtro")}}); continue
        if parar: res.append({**c, "estado": 0, "candidatas": [], "v": 2}); continue
        if c["filtro"] == "mod":      # las modernas se identifican con TCGAPI.dev por su número exacto (no gasta el cupo por hora de PokéWallet)
            kt = _clave("tcgapi"); cand = []
            est, cab, d = _http("https://api.tcgapi.dev/v1/search?" + urllib.parse.urlencode({"q": re.sub(r"\s*\d+/\d+\s*$", "", c["busca"]), "game": "pokemon", "per_page": 50}), {"X-API-Key": kt}) if kt else (0, {}, {})      # solo busca por nombre (con el número no devuelve nada) y se queda con el número exacto
            for it in (d.get("data") or []) if est == 200 else []:
                if str(it.get("number") or "").lower() == c["numero"].lower() and it.get("tcgplayer_id") and "sealed" not in str(it.get("product_type") or "").lower():
                    cand.append({"nombre": it.get("name"), "set": it.get("set_name"), "numero": it.get("number"), "tcg_id": it.get("tcgplayer_id"), "raw_usd": it.get("market_price"), "imagen": it.get("image_url")})
            res.append({**c, "estado": est, "candidatas": cand[:4], "v": 2}); time.sleep(0.5); continue
        est, cab, d = _http("https://api.pokewallet.io/search?" + urllib.parse.urlencode({"q": c["busca"], "limit": 25}), {"X-API-Key": k})
        if est == 429 or int(cab.get("x-ratelimit-remaining-hour") or 99) < 3: parar = True; print("Límite por hora de PokéWallet: paro; continúa en la siguiente vuelta.")
        if est == 429: res.append({**c, "estado": 429, "candidatas": [], "v": 2}); continue
        cand = []
        for r in (d.get("results") or []) if est == 200 else []:
            ci, tp = r.get("card_info") or {}, r.get("tcgplayer") or {}; nombre = str(ci.get("name") or ""); sett = str(ci.get("set_name") or "")
            if c["filtro"] == "star" and not ((re.search(r"\bstar\b", nombre.lower()) or "☆" in nombre) and not re.search(r"vstar|prism", nombre.lower())): continue      # «Mewtwo VSTAR» y las «Prism Star» no son Gold Stars
            if c["filtro"] == "play" and "play" not in sett.lower(): continue
            m = re.search(r"/product/(\d+)", str(tp.get("url") or ""))
            cand.append({"nombre": nombre, "set": sett, "numero": ci.get("card_number"), "tcg_id": int(m.group(1)) if m else None, "raw_usd": next((p.get("market_price") for p in (tp.get("prices") or []) if p.get("market_price")), None)})
        res.append({**c, "estado": est, "candidatas": cand[:6], "v": 2}); time.sleep(0.7)
    save(CAND, {"fecha": ahora().isoformat(timespec="minutes"), "cartas": res})
    md = ["# Cartas candidatas para la foto diaria de precios", "", f"Hecho con `precios_graduadas.py --candidatos` ({ahora().date().isoformat()}). Se aplica sola la primera candidata (y, en las Gold Stars, también la primera japonesa). Para cambiar una: edita `data/precios/cartas.json` y pon `\"fijo\": true`.", ""]
    for g in dict.fromkeys(c["grupo"] for c in res):
        md += [f"## {g}", "", "| Carta que buscas | Primera candidata | Otras |", "|---|---|---|"]
        for c in (x for x in res if x["grupo"] == g):
            f = lambda x: f"{x['nombre']} · {x['set']} · {x['numero']} · id {x['tcg_id']}" + (f" · {x['raw_usd']} $" if x["raw_usd"] else "")
            md.append(f"| {c['nombre']} | {f(c['candidatas'][0]) if c['candidatas'] else '**sin candidata**'} | {' ; '.join(f(x) for x in c['candidatas'][1:4])} |")
        md.append("")
    os.makedirs(os.path.dirname(NOTAS), exist_ok=True)
    with open(NOTAS, "w", encoding="utf-8") as fh: fh.write("\n".join(md))
    print(f"{len(res)} cartas, {sum(1 for c in res if c['candidatas'])} con alguna candidata → {os.path.relpath(NOTAS, ROOT)}"); return 0


def _es_jp(c): return any(j.lower() in str(c.get("set") or "").lower() for j in JP_SETS)


def confirmar_auto():
    """Pasa de data/precios/candidatos.json a data/precios/cartas.json: la primera candidata inglesa y, en las Gold Stars, también la primera japonesa (clave «…-jp»). Lo marcado «fijo» no se toca."""
    actual = {c["clave"]: c for c in (load(CARTAS, {}) or {}).get("cartas", [])}; ex = excluidas(); nuevas = {}
    for c in (load(CAND, {}) or {}).get("cartas", []):
        if c["clave"] in ex: continue
        cand = [x for x in c.get("candidatas") or [] if x.get("tcg_id")]
        en = next((x for x in cand if not _es_jp(x)), None); jp = next((x for x in cand if _es_jp(x)), None) if c.get("filtro") == "star" else None
        for sufijo, x, idioma in (("", en, "english"), ("-jp", jp, "japanese")):
            if not x: continue
            clave = c["clave"] + sufijo
            if actual.get(clave, {}).get("fijo"): nuevas[clave] = actual[clave]; continue
            nuevas[clave] = {"clave": clave, "nombre": c["nombre"] + (" (japonesa)" if sufijo else ""), "grupo": c["grupo"], "tcg_id": x["tcg_id"], "set": x["set"], "numero": x["numero"], "base": x["nombre"], "idioma": idioma, "imagen": x.get("imagen") or f"https://product-images.tcgplayer.com/fit-in/400x400/{x['tcg_id']}.jpg",      # la foto de la carta: la CDN de TCGplayer la sirve por su identificador, sin gastar peticiones
                             
                             "cada": 1 if (c["grupo"] in ("Gold Stars", "Modernas (alt art)") or sufijo) else 2}      # las Gold Stars cada día; las demás un día sí y otro no (los 100 créditos diarios no dan para todas)
    for clave, c in actual.items():
        if c.get("fijo") and clave not in nuevas and clave.split("-jp")[0] not in ex: nuevas[clave] = c
    save(CARTAS, {"actualizado": ahora().isoformat(timespec="minutes"), "cartas": list(nuevas.values())})
    return len(nuevas)


# ------------------------------------------------------------------------------------------------------------- 2) las fuentes (una función por API; devuelven el dato de UNA carta o None)
def _ppt_resumen(c):
    eb = (c.get("ebay") or {}); sg = eb.get("salesByGrade") or {}; out = {}
    for g in NOTAS_QUE_SE_GUARDAN:
        v = sg.get(g)
        if isinstance(v, dict) and v.get("count"):
            sm = v.get("smartMarketPrice") or {}      # su estimación «inteligente»: con pocas ventas tira de ventas de hace años (daysUsed 1549 en una carta con 16), así que se guarda aparte y no se usa sin mirar daysUsed
            out[g] = {k: v.get(a) for k, a in (("ventas", "count"), ("mediana", "medianPrice"), ("media", "averagePrice"), ("min", "minPrice"), ("max", "maxPrice"), ("ultima", "lastSaleDate"), ("m7", "marketPrice7Day"), ("tendencia", "marketTrend"), ("vol7", "dailyVolume7Day"))}
            out[g].update({"smart": sm.get("price"), "smart_conf": sm.get("confidence"), "smart_dias": sm.get("daysUsed"), "fuentes": v.get("salesBySource")})
    return {"raw_usd": (c.get("prices") or {}).get("market"), "desde": eb.get("dateRangeStart"), "hasta": eb.get("dateRangeEnd"), "notas": out, "imagen": c.get("imageCdnUrl400") or c.get("imageCdnUrl") or c.get("imageUrl")}


class Cupo:
    """Lo que queda de cada API, leído de sus cabeceras; cuando se acaba, esa fuente se salta el resto de la vuelta."""
    def __init__(s):
        s.restan = {}; s.parada = set(); s.reserva = RESERVA
        for f, v in ((load(USO, {}) or {}).get("fuentes") or {}).items():      # lo que ya dijo «hasta mañana» no se vuelve a preguntar
            if v.get("hasta") and v["hasta"] > time.time(): s.parada.add(f)
    def _fin(s, f): return f in s.parada


def fuente_ppt(c, cupo, k):
    if c.get("idioma") == "japanese" or cupo._fin("ppt"): return None      # las graduadas japonesas no las da ninguna API gratis (ver notas/probar-apis)
    if cupo.restan.get("ppt") is not None and cupo.restan["ppt"] < cupo.reserva: cupo.parada.add("ppt"); return None
    est, cab, d = _http("https://www.pokemonpricetracker.com/api/v2/cards?" + urllib.parse.urlencode({"tcgPlayerId": c["tcg_id"], "includeEbay": "true", "limit": 1}), {"Authorization": "Bearer " + k})
    try: cupo.restan["ppt"] = int(cab.get("x-ratelimit-daily-remaining"))
    except (TypeError, ValueError): pass
    if est == 429: cupo.parada.add("ppt"); return None
    datos = d.get("data") if est == 200 and isinstance(d, dict) else None
    datos = [datos] if isinstance(datos, dict) else (datos or [])      # con tcgPlayerId la API devuelve UNA carta (dict), no una lista: así se perdieron 29 créditos el 4 de noviembre
    time.sleep(1.1)      # 60 llamadas por minuto
    return _ppt_resumen(datos[0]) if datos else None


def fuente_pokewallet(c, cupo, k):
    if cupo._fin("pokewallet"): return None
    est, cab, d = _http("https://api.pokewallet.io/search?" + urllib.parse.urlencode({"q": f"{c['numero']} {str(c['base']).replace(' - ', ' ')}", "limit": 6}), {"X-API-Key": k})
    try: cupo.restan["pokewallet"] = int(cab.get("x-ratelimit-remaining-hour"))
    except (TypeError, ValueError): pass
    if est == 429 or (cupo.restan.get("pokewallet") is not None and cupo.restan["pokewallet"] < 3): cupo.parada.add("pokewallet")
    if est != 200: return None
    for r in d.get("results") or []:
        tp, cm = r.get("tcgplayer") or {}, r.get("cardmarket") or {}; m = re.search(r"/product/(\d+)", str(tp.get("url") or ""))
        if m and int(m.group(1)) == int(c["tcg_id"]):
            return {"tcgplayer_usd": {p.get("sub_type_name"): p.get("market_price") for p in tp.get("prices") or []}, "cardmarket_eur": {p.get("variant_type"): {a: p.get(a) for a in ("trend", "avg1", "avg7", "avg30", "low")} for p in cm.get("prices") or []}}
    time.sleep(0.7); return None


def fuente_tcgapi(c, cupo, k):
    if cupo._fin("tcgapi"): return None
    jp = c.get("idioma") == "japanese"
    est, cab, d = _http("https://api.tcgapi.dev/v1/search?" + urllib.parse.urlencode({"q": str(c["base"]).replace(" - ", " ")[:60], "game": "pokemon-japan" if jp else "pokemon"}), {"X-API-Key": k})
    try: cupo.restan["tcgapi"] = int(cab.get("x-ratelimit-remaining"))
    except (TypeError, ValueError): pass
    if est == 429 or (cupo.restan.get("tcgapi") is not None and cupo.restan["tcgapi"] < 3): cupo.parada.add("tcgapi")
    if est != 200: return None
    num = str(c.get("numero") or "").lower()
    it = next((x for x in d.get("data") or [] if (not jp and x.get("tcgplayer_id") == c["tcg_id"]) or (jp and num and str(x.get("number") or "").lower() == num)), None)
    if not it: return None
    out = {a: it.get(a) for a in ("market_price", "median_price", "low_price", "total_listings", "lowest_with_shipping")}; out["imagen"] = it.get("image_url")
    if not jp and c["grupo"] == "Gold Stars" and not cupo._fin("tcgapi"):      # las ventas agregadas (una petición más) solo de las Gold Stars inglesas: caben en las 100 del día
        e2, cb2, d2 = _http(f"https://api.tcgapi.dev/v1/cards/{it['id']}/prices", {"X-API-Key": k})
        for x in (d2.get("data") or []) if e2 == 200 and isinstance(d2, dict) else []:
            out.update({a: x.get(a) for a in ("sales_volume", "avg_sales_price", "sales_as_of", "price_change_7d", "price_change_30d")}); break
    time.sleep(0.5); return out


def foto(solo=None, claves=None, reserva=None):
    ks = {"ppt": _clave("pokemonpricetracker"), "pokewallet": _clave("pokewallet"), "tcgapi": _clave("tcgapi")}
    fuentes = [f for f in FUENTES if ks[f] and (not solo or f == solo)]
    if not fuentes: print("No hay ninguna clave de precios en .secrets/ (python tools/poner_clave.py)."); return 1
    if not (load(CARTAS, {}) or {}).get("cartas") or ahora().minute % 5 == 0: pass
    if ks["pokewallet"]: candidatos()      # completa las que falten con lo que dé el cupo por hora
    confirmar_auto(); lista = (load(CARTAS, {}) or {}).get("cartas") or []
    if not lista: print("Todavía no hay cartas identificadas."); return 1
    hoy = ahora().date(); dia = hoy.toordinal(); ruta = P("precios", f"{hoy.isoformat()}.json")
    snap = load(ruta, None) or {"date": hoy.isoformat(), "cartas": {}}; cupo = Cupo(); hechas = {f: 0 for f in fuentes}; fallos = []
    toca = [(i, c) for i, c in enumerate(lista) if (c["clave"] in claves) if claves] if claves else [(i, c) for i, c in enumerate(lista) if int(c.get("cada") or 1) == 1 or (dia + i) % int(c["cada"]) == 0]
    cupo.reserva = RESERVA if reserva is None else reserva
    previo = load(ESTADO, {}) or {}; importados = importar_precios(snap, hoy.isoformat())
    save(ESTADO, {"running": True, "beat": time.time(), "dia": hoy.isoformat(), "total": len(toca), "done": 0, "message": "Pidiendo precios…"})
    for n, (i, c) in enumerate(toca):
        e = snap["cartas"].setdefault(c["clave"], {"nombre": c["nombre"], "grupo": c["grupo"], "tcg_id": c["tcg_id"], "set": c.get("set"), "numero": c.get("numero"), "idioma": c.get("idioma"), "imagen": c.get("imagen")})
        e["imagen"] = c.get("imagen") or e.get("imagen")
        for f in fuentes:
            if e.get(f) is not None: continue      # lo de hoy ya pedido no se vuelve a pedir si la vuelta se repite
            if not CP.es_mio(c["clave"]) and ahora().hour < HORA_REPARTO: continue      # es del compañero: lo suyo llega por git; si a las 14:00 no ha llegado, se pide
            try: v = {"ppt": fuente_ppt, "pokewallet": fuente_pokewallet, "tcgapi": fuente_tcgapi}[f](c, cupo, ks[f])
            except Exception as ex: v = None; fallos.append(f"{c['nombre']} ({f}): {type(ex).__name__}")
            if v is not None: e[f] = v; hechas[f] += 1
        save(ESTADO, {"running": True, "beat": time.time(), "dia": hoy.isoformat(), "total": len(toca), "done": n + 1, "message": f"{n + 1}/{len(toca)} cartas"})
        if len(cupo.parada) == len(fuentes): break
    save(ruta, snap)
    pub_n, pub_t = previo.get("publicado_n", 0), previo.get("publicado_t", 0)      # se sube lo nuevo como mucho una vez por hora (cada subida es un commit)
    propios = sum(1 for v in snap["cartas"].values() for f in FUENTES if v.get(f) is not None and f not in (v.get("de") or {}))
    if propios > pub_n and time.time() - pub_t > 3600:
        if publicar_precios(snap, hoy.isoformat()): pub_n, pub_t = propios, time.time()
    h = load(HIST, {}) or {}
    for clave, v in snap["cartas"].items():
        reg = {}
        if v.get("ppt"): reg.update({"raw_usd": v["ppt"].get("raw_usd"), **{g: [n.get("ventas"), n.get("mediana")] for g, n in (v["ppt"].get("notas") or {}).items()}})      # lo importado del compañero puede venir incompleto: nada de índices directos
        if v.get("pokewallet"): reg["cm"] = v["pokewallet"].get("cardmarket_eur")
        if v.get("tcgapi"): reg["tcgapi"] = [v["tcgapi"].get("market_price"), v["tcgapi"].get("sales_volume")]
        if reg: h.setdefault(clave, {})[hoy.isoformat()] = reg
    save(HIST, h)
    completas = sum(1 for c in toca if all(snap["cartas"].get(c[1]["clave"], {}).get(f) is not None or (f == "ppt" and c[1].get("idioma") == "japanese") for f in fuentes))
    # el mensaje cuenta lo que hay HOY en la foto (no solo lo de esta vuelta: «ppt 0, pokewallet 0» después de una vuelta sin cupo parecía que no había nada; Fernando, 5 nov: «no veo resultados de su trabajo»)
    hoy_n = {f: sum(1 for v in snap["cartas"].values() if v.get(f) is not None) for f in fuentes}; con_precio = sum(1 for v in snap["cartas"].values() if any(v.get(f) is not None for f in fuentes))
    NOMBRE_F = {"ppt": "ventas por nota (PokemonPriceTracker)", "pokewallet": "TCGplayer y Cardmarket (PokéWallet)", "tcgapi": "TCGAPI"}
    msg = f"Hoy hay precio de {con_precio} de {len(snap['cartas'])} cartas: " + ", ".join(f"{NOMBRE_F.get(f, f)} {hoy_n[f]}" for f in fuentes) + (f" · esta vuelta, {sum(hechas.values())} lecturas nuevas" if sum(hechas.values()) else " · esta vuelta, nada nuevo") + (f" · sin cupo hasta mañana: {', '.join(sorted(cupo.parada))}" if cupo.parada else "") + (f" · créditos de ppt que quedan: {cupo.restan['ppt']}" if cupo.restan.get("ppt") is not None else "")
    save(ESTADO, {"running": False, "dia": hoy.isoformat() if completas >= len(toca) else None, "intento": ahora().isoformat(timespec="minutes"), "fin": ahora().isoformat(timespec="minutes"), "message": msg + (f" · importados del compañero: {importados}" if importados else ""), "total": len(toca), "done": completas, "publicado_n": pub_n, "publicado_t": pub_t,
                  "error": ("; ".join(fallos[:3]) or None)})      # «dia» solo se marca cuando todo está hecho: mientras falte algo, el servidor lo reintenta en la siguiente vuelta
    print(msg); [print("  -", f) for f in fallos[:8]]
    try:
        import oficina; oficina.registrar("precios_graduadas", msg, ok=not fallos)
    except Exception: pass
    return 0


# ------------------------------------------------------------------------------------------------------------- 3) lo que usa el servidor
def toca():
    """El servidor lo pregunta cada 5 minutos. Los 100 créditos de ppt se renuevan a las 01:00 (hora de Madrid): antes no se pide. Si faltan cartas, reintenta cada 20 minutos."""
    s = load(ESTADO, {}) or {}
    if ahora().hour < 1 or not (_clave("pokemonpricetracker") or _clave("pokewallet") or _clave("tcgapi")): return False
    if s.get("running") and time.time() - s.get("beat", 0) < 600: return False
    if s.get("dia") == ahora().date().isoformat(): return False
    try: ult = dt.datetime.fromisoformat(s["intento"]) if s.get("intento") else None
    except ValueError: ult = None
    return not ult or (ahora() - ult).total_seconds() > 1200 or ult.date() != ahora().date()


def lanzar():
    here = os.path.dirname(os.path.abspath(__file__)); os.makedirs(P("state"), exist_ok=True)
    log = open(P("state", "precios.log"), "a", encoding="utf-8")
    subprocess.Popen([sys.executable, os.path.join(here, "precios_graduadas.py"), "--foto"], cwd=here, env={**os.environ, "PYTHONIOENCODING": "utf-8"}, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def vista():
    """Para /api/precios: la última foto y la cuenta de cartas por fuente."""
    fs = sorted(f for f in os.listdir(P("precios")) if re.match(r"\d{4}-\d{2}-\d{2}\.json$", f)) if os.path.isdir(P("precios")) else []
    snap = load(P("precios", fs[-1]), {}) if fs else {}
    imgs = {c["clave"]: c.get("imagen") for c in (load(CARTAS, {}) or {}).get("cartas", [])}
    for k, v in (snap.get("cartas") or {}).items(): v.setdefault("imagen", imgs.get(k))
    return {"fecha": snap.get("date"), "cartas": snap.get("cartas") or {}, "confirmadas": len((load(CARTAS, {}) or {}).get("cartas") or []), "estado": load(ESTADO, {}) or {}}


def estado():
    lista = (load(CARTAS, {}) or {}).get("cartas") or []; ult = sorted(f for f in os.listdir(P("precios")) if re.match(r"\d{4}-\d{2}-\d{2}\.json$", f)) if os.path.isdir(P("precios")) else []
    print(f"{len(lista)} cartas identificadas · última foto: {ult[-1][:-5] if ult else 'ninguna'} · excluidas: {sorted(excluidas())}"); print((load(ESTADO, {}) or {}).get("message") or ""); return 0


if __name__ == "__main__":
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    a = sys.argv[1:]
    if "--candidatos" in a: sys.exit(candidatos())
    if "--foto" in a: sys.exit(foto(a[a.index("--solo") + 1] if "--solo" in a else None, a[a.index("--cartas") + 1].split(",") if "--cartas" in a else None, int(a[a.index("--reserva") + 1]) if "--reserva" in a else None))
    sys.exit(estado())
