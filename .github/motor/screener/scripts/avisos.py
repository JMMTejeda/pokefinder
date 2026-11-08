"""Phone notices (ntfy, tools/avisar.py) about what the app does, so the owner does not have to open it (owner, 3 November 2026).
- A search finishes, stops or fails: one notice with its listings, the listings below market value and the progress it reached.
- Below-market listings (ventas.marcar, the green label) of a finished search: one notice each (at most MAX_CHOLLOS), tapping it opens the listing. Each listing once.
- A daily summary at SUMMARY_HOUR: the eBay snapshot numbers, the bargains of the day and what failed.
The server calls revisar() every minute. The first time it runs it only notes what already exists, so old results never flood the phone.
State: data/state/avisos.json. Notices carry no keys or personal data: only card names, prices and the listing's own link."""
import datetime as dt, glob, os, re, sys
from common import P, load, save, TZ

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tools")
ESTADO = P("state", "avisos.json")
MAX_CHOLLOS = 5
SUMMARY_HOUR = 10

def _avisar(*a, **k):
    if TOOLS not in sys.path: sys.path.insert(0, TOOLS)
    from avisar import avisar
    return avisar(*a, **k)

def _chollos(search_id):
    """Below-market listings of a saved search, best discount first."""
    import ventas
    s = load(P("app", "searches", search_id + ".json"), None)
    if not s: return []
    ventas.marcar(s)
    # only the ones whose value rests on real sales that agree with each other (Collectr's lone figure is shown in the Chollos tab, but does not make the phone ring)
    bajo = [l for l in s.get("listings") or [] if (l.get("mercado") or {}).get("bajo") and (l["mercado"].get("confianza") in ("media", "alta"))]
    return sorted(bajo, key=lambda l: l["mercado"]["pct"])

# ---- «Posible chollo»: for searches with no sales to compare with (a modern or English card), the reference is the MEDIAN OF WHAT SELLERS ASK, which is not a market value.
# Fernando, 4 November 2026: «automatizado que revise la búsqueda, filtre y encuentre chollos»; «las quiero en inglés o japonés». So the notice is its own, softer one («comprueba la carta y la foto»):
MIN_COMPARABLES = 12      # asking prices of the same card and grade needed before a median means anything
BAJO_DESDE, BAJO_HASTA = 0.40, 0.65   # below 40 % of the median is almost always another card mislabelled (a 14 € «alt art» that is the plain full art); sellers ask high, so a median of asks is inflated and above 65 % is just a normal price
SIN_GRADO = re.compile(r"\b(?:raw|potenti\w*|candidate|contender|possible|ready\s*for|to\s*be\s*graded|ungraded)\b", re.I)    # «RAW, PSA 10 potentieel» and «PSA 10 Contender» are not PSA 10s

def _apto(l):
    """English or Japanese, or not stated by a seller who is not in a country / marketplace where English is not what is usually written (Vinted titles are in the seller's language:
    «Tempesta Argentata» is Italian even though it says nothing of it)."""
    import idioma
    g = idioma.lang_of(l)
    if g in ("en", "ja"): return True
    if g == "unk": return not (idioma.EU_LOCAL.search(str(l.get("site_name") or l.get("site") or "")) or idioma.OTHER_COUNTRY.search(str(l.get("country") or "")))
    return False
MIN_EUR = 40
MAX_POSIBLES = 3

def _req(query):
    """The words before the card number (Pokémon name, 'ex', 'V'...) and the number itself: «Lugia V 186/195 Silver Tempest» -> words [lugia, v], number 186/195. The set name is left out on purpose:
    many honest titles say only «Lugia V Alt Art 186/195»."""
    import mercado
    toks = (query or "").lower().split(); words, nums = [], []
    for t in toks:
        if re.search(r"\d", t): nums.append(t); break
        if t not in mercado.STOP: words.append(t)
    return {"words": words, "nums": nums}

def _posibles(search_id, ver=False):
    """Possible bargains of a finished text search, best first: same card (title names it AND its number), English / Japanese / not stated (never another language), a buy-it-now you can buy,
    not an auction, a photo not in doubt, and between 40 % and 75 % of the median asked for the same grader+grade (at least 12 comparable asks)."""
    import statistics, mercado, idioma
    s = load(P("app", "searches", search_id + ".json"), None)
    if not s or s.get("kind") != "text" or not s.get("query"): return []
    req = _req(s["query"])
    if not req["words"] or not req["nums"]: return []
    base = []
    for l in s.get("listings") or []:
        if l.get("sale") != "buy" or not l.get("price_eur") or l.get("ships_to_spain") is False: continue
        if not _apto(l): continue
        if not mercado.matches(req, l.get("title") or "", bool(l.get("grader"))): continue
        if l.get("grader") and SIN_GRADO.search(l.get("title") or ""): continue
        base.append(l)
    grupos = {}
    for l in base: grupos.setdefault((l.get("grader") or "RAW", str(l.get("grade") or "")), []).append(l)
    out = []
    for (casa, nota), L in grupos.items():
        if len(L) < MIN_COMPARABLES: continue
        med = statistics.median(x["price_eur"] for x in L)
        for l in L:
            r = l["price_eur"] / med
            if BAJO_DESDE <= r <= BAJO_HASTA and l["price_eur"] >= MIN_EUR and not l.get("photo_doubt"):
                out.append({**l, "_med": med, "_n": len(L), "_pct": round(r * 100), "_grupo": casa if casa == "RAW" else f"{casa} {nota}".strip(), "_clave": f"{l.get('site')}:{l.get('id')}"})
    return sorted(out, key=lambda l: l["_pct"])

def _txt_posible(l):
    return (f"{(l.get('title') or '')[:80]} · {l['price_eur']:.0f} € ({l['_pct']} % de la mediana de lo que piden, {l['_med']:.0f} € en {l['_n']} anuncios {l['_grupo']}; {l.get('site_name') or l.get('site')}). "
            "Es precio pedido, no vendido: comprueba que es la carta y la foto.")

def _txt(l):
    m = l["mercado"]
    return f"{l.get('card') or l.get('title')} {l.get('grader') or ''} {l.get('grade') or ''}: {l['price_eur']:.0f} € ({m['pct']} % frente a {m['valor']:.0f} € de mercado, {l.get('site_name') or l.get('site')})".replace("  ", " ")

def _jobs():
    return [j for j in (load(f, {}) or {} for f in glob.glob(P("app", "jobs", "*.json"))) if j.get("id")]

# ---- «Bajo la referencia» (Fernando, 5 nov: «monta ya el aviso de chollos; que no deje de buscar»): los anuncios por debajo del precio de TCGplayer o Collectr que lee el Tasador (referencia.py).
# Es un precio de ficha, no ventas una a una: aviso suave, solo a este móvil, y cada anuncio una sola vez. Sirve tanto al terminar una búsqueda como en el repaso periódico (vigilar), porque el precio
# puede llegar DESPUÉS de la búsqueda (el Tasador lee de continuo).
MAX_REF = 3

def _por_referencia(search_id):
    import ventas
    s = load(P("app", "searches", search_id + ".json"), None)
    if not s: return []
    ventas.marcar(s)
    bajo = [l for l in s.get("listings") or [] if (l.get("mercado") or {}).get("bajo") and (l["mercado"].get("leido")) and l.get("ships_to_spain") is not False]
    return sorted(bajo, key=lambda l: l["mercado"]["pct"])

def _txt_ref(l):
    m = l["mercado"]; f = (m.get("fuentes") or ["referencia"])[0]
    return (f"{(l.get('title') or '')[:70]} · {l['price_eur']:.0f} € ({abs(m['pct'])} % por debajo de {m['valor']:.0f} € de referencia {f}{' ' + m['edicion'] if m.get('edicion') else ''}; {l.get('site_name') or l.get('site')}). "
            + (f"Máx. para ganar {m['margen_pct']} %: {m['max_pagar']:.0f} € (beneficio ~{m['beneficio']:.0f} €). " if m.get("max_pagar") is not None else "")
            + "Es el precio de una ficha, no ventas: comprueba carta, estado y foto.")

def _avisar_refs(e, search_id, nombre=""):
    """Manda los nuevos de esa búsqueda (hasta MAX_REF) y apunta cada uno; devuelve cuántos mandó."""
    refs = e.setdefault("refs", []); hoy = e.setdefault("refs_hoy", []); fecha = dt.datetime.now(TZ).date().isoformat()
    e["refs_hoy"] = hoy = [x for x in hoy if x.get("d") == fecha]
    nuevos = [c for c in _por_referencia(search_id) if f"{c.get('site')}:{c.get('id')}" not in refs]; n = 0
    for c in nuevos[:MAX_REF]:
        if _avisar(_txt_ref(c), "Bajo la referencia", click=c.get("url")):
            refs.append(f"{c.get('site')}:{c.get('id')}"); n += 1; hoy.append({"d": fecha, "t": dt.datetime.now(TZ).strftime("%H:%M"), "txt": _txt_ref(c)[:140]})
    if len(nuevos) > MAX_REF: refs.extend(f"{c.get('site')}:{c.get('id')}" for c in nuevos[MAX_REF:]); _avisar(f"y {len(nuevos) - MAX_REF} más bajo la referencia en {nombre or search_id}: míralos en la pestaña Chollos", "Bajo la referencia")
    e["refs"] = refs[-4000:]; return n

def vigilar():
    """El repaso periódico (el servidor lo llama cada 10 minutos): mira todas las búsquedas guardadas por si el Tasador ha leído un precio nuevo que deje a algún anuncio por debajo."""
    e = load(ESTADO, {}) or {}
    if "inicio" not in e: return
    if not e.get("refs_base"):      # la primera vez solo se anota lo que ya hay (como hace revisar): el móvil no se llena con lo viejo
        refs = e.setdefault("refs", [])
        for f in glob.glob(P("app", "searches", "*.json")):
            try: refs.extend(f"{c.get('site')}:{c.get('id')}" for c in _por_referencia(os.path.basename(f)[:-5]))
            except Exception as ex: print("vigilar (base):", type(ex).__name__, ex)
        e["refs"] = sorted(set(refs))[-4000:]; e["refs_base"] = True; save(ESTADO, e); return
    for f in glob.glob(P("app", "searches", "*.json")):
        try: _avisar_refs(e, os.path.basename(f)[:-5])
        except Exception as ex: print("vigilar:", type(ex).__name__, ex)
    e["vigilado"] = dt.datetime.now(TZ).isoformat(timespec="minutes"); save(ESTADO, e)

def revisar():
    e = load(ESTADO, {}) or {}
    jobs = _jobs(); fin = ("done", "error", "cancelled")
    if "inicio" not in e:   # first run: remember what exists, send nothing
        e = {"inicio": dt.datetime.now(TZ).isoformat(timespec="minutes"), "jobs": {j["id"]: j["status"] for j in jobs if j.get("status") in fin}, "chollos": [], "resumen": ""}
        for f in glob.glob(P("app", "searches", "*.json")):
            e["chollos"] += [c["id"] for c in _chollos(os.path.basename(f)[:-5])]
        save(ESTADO, e); return
    hechos = e.setdefault("jobs", {}); vistos = set(e.setdefault("chollos", []))
    ini = e.setdefault("iniciados", [])      # Fernando, 6 nov: «también cuando termine una búsqueda avise, o en curso tu búsqueda»: las búsquedas COMPLETAS (las tuyas y las de la campaña) avisan al empezar y al terminar
    for j in jobs:
        if j.get("status") in ("running", "claimed") and j.get("depth") == "full" and j["id"] not in ini:
            ini.append(j["id"]); _avisar(f"En curso: {j.get('label') or j['id']} (búsqueda completa, tarda unos minutos)", "Búsqueda en curso")
    e["iniciados"] = ini[-300:]
    for j in jobs:
        if j.get("status") not in fin or hechos.get(j["id"]) == j["status"]: continue
        hechos[j["id"]] = j["status"]; nombre = j.get("label") or j["id"]
        if j["status"] == "done":
            s = load(P("app", "searches", str(j.get("search_id")) + ".json"), {}) or {}
            nuevos = [c for c in _chollos(str(j.get("search_id"))) if c["id"] not in vistos]
            try: import caza; auto = caza.es_auto(j["id"])      # las búsquedas de la ronda automática no avisan de que han terminado (serían decenas al día): solo avisan de los chollos
            except Exception: auto = False
            if not auto or j.get("depth") == "full": _avisar(f"{nombre}: {len(s.get('listings') or [])} anuncios" + (f", {len(nuevos)} bajo mercado" if nuevos else ""), "Búsqueda terminada")
            try: _avisar_refs(e, str(j.get("search_id")), nombre)
            except Exception as ex: print("avisos referencia:", ex)
            try: import busquedas_db; busquedas_db.archivar(str(j.get("search_id")))      # cada búsqueda terminada queda en la base de datos de búsquedas
            except Exception as ex: print("archivar búsqueda:", ex)
            for c in nuevos[:MAX_CHOLLOS]:
                if _avisar(_txt(c), "Bajo mercado", urgente=True, click=c.get("url"), equipo=True): vistos.add(c["id"])   # also to the topic shared with the other owner
            if len(nuevos) > MAX_CHOLLOS: _avisar(f"y {len(nuevos) - MAX_CHOLLOS} más bajo mercado en {nombre}: míralos en la app", "Bajo mercado"); vistos.update(c["id"] for c in nuevos)
            try:      # the softer notice: below the median of what is asked (searches with no sales to compare with); each listing once, to this phone only
                pos = e.setdefault("posibles", []); nuevos_p = [c for c in _posibles(str(j.get("search_id"))) if c["_clave"] not in pos]
                for c in nuevos_p[:MAX_POSIBLES]:
                    if _avisar(_txt_posible(c), "Posible chollo", click=c.get("url")): pos.append(c["_clave"])
                if len(nuevos_p) > MAX_POSIBLES: _avisar(f"y {len(nuevos_p) - MAX_POSIBLES} posibles chollos más en {nombre}: míralos en la app", "Posible chollo"); pos.extend(c["_clave"] for c in nuevos_p[MAX_POSIBLES:])
                e["posibles"] = pos[-3000:]
            except Exception as ex: print("avisos posibles:", ex)
        elif j["status"] == "error": _avisar(f"{nombre} falló: {str(j.get('message') or '')[:100]}", "Búsqueda fallida", urgente=True, canal="salud")
        else: _avisar(f"{nombre} se paró al {j.get('progress', 0)} %", "Búsqueda parada")
    e["chollos"] = sorted(vistos)
    ahora = dt.datetime.now(TZ)
    if ahora.hour >= SUMMARY_HOUR and e.get("resumen") != ahora.date().isoformat():
        e["resumen"] = ahora.date().isoformat(); _avisar(resumen(), "Resumen de PokéFinder")
    save(ESTADO, e)

if __name__ == "__main__" and "--posibles" in sys.argv:      # python avisos.py --posibles <id de búsqueda>: enseña lo que avisaría, sin mandar nada
    sys.stdout.reconfigure(encoding="utf-8")
    for c in _posibles(sys.argv[sys.argv.index("--posibles") + 1]): print(_txt_posible(c), "|", c.get("url"))

def resumen():
    hoy = dt.datetime.now(TZ).date().isoformat()
    u = load(P("mercado", "ultimo.json"), {}) or {}; t = u.get("totals") or {}
    lineas = []
    if u.get("date") == hoy: lineas.append(f"eBay: {t.get('n')} anuncios; nuevos {t.get('nuevos')}, fuera {t.get('fuera')}, cambios de precio {t.get('cambios')}")
    else: lineas.append(f"eBay: sin foto de hoy (última {u.get('date') or 'ninguna'})")
    if TOOLS not in sys.path: sys.path.insert(0, TOOLS)
    import subprocess
    mal = subprocess.run([sys.executable, os.path.join(TOOLS, "comprobar_salud.py"), "--aviso"], capture_output=True, text=True, encoding="utf-8", timeout=60).stdout.strip()
    lineas.append(mal.replace("PokéFinder: ", "", 1) if mal else "Todo en orden: servidor, lecturas y disco.")
    return "\n".join(lineas)
