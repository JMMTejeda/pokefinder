"""Mercado, phase 5 (owner, 2 November 2026: "que lo de mercados ya tenga todo lo necesario"): what ties the eBay analyses, YouTube and the communities together.
- menciones_*(): for each collection / analysis, what is said about it in YouTube (titles and tags), in the comments and in the communities (topics, posts, Bluesky), last 30 and 90 days.
- panorama(): the market as a whole: the hottest themes (30th anniversary, vintage, modern, correction...), sets and Pokémon that rise or cool, with a written summary.
- barrido(): the «full sweep» of one thing: eBay snapshot + the other markets (engine) + YouTube and communities, and progreso() to follow it.
Everything is read from files the other modules already keep (data/contenido, data/comunidades, data/mercado); nothing here asks any site for anything except through barrido()."""
import datetime as dt, os, re
from common import P, load, save, ROOT, TZ
import contenido as CT
import comunidades as CM

def today(): return dt.datetime.now(TZ).date().isoformat()

_cache = {}
def _mt(*paths):
    out = []
    for p in paths:
        try: out.append(os.path.getmtime(p))
        except OSError: out.append(0)
    return tuple(out)

def _datos():
    """(videos, comments, posts, sources), cached until the files change."""
    fv, fc, fp = os.path.join(CT.DIR, "videos.json"), os.path.join(CT.DIR, "comentarios.json"), os.path.join(CM.DIR, "posts.json")
    k = _mt(fv, fc, fp)
    if _cache.get("k") != k:
        _cache["k"] = k; _cache["v"] = (load(fv, {}) or {}, load(fc, {}) or {}, load(fp, {}) or {})
        for v in _cache["v"][0].values(): v["_n"] = CT._norm(v["t"] + " " + v.get("tags", ""))
        for it in _cache["v"][2].values():     # entities of each community item, once per change of the file (the dictionary is large)
            txt = it["t"] + " " + it["x"][:500]; it["_s"], it["_p"] = CT.entidades(txt); it["_n"] = CT._norm(txt)
        _cache.pop("m", None)
    return _cache["v"]

def _detectores(group, a):
    """What an item must name to count as «about this»: [(Pokémon set, set names, nickname regex)]; an item matches if ANY of them does. Approximate and said so."""
    if group == "Gold Stars": return [(set(), {"Gold Star"}, None)]
    out = []
    if a:   # an analysis of the owner's: its searches without the eBay syntax
        for line in a["consultas"]:
            q = re.sub(r"-?\([^)]*\)|(?:^|\s)-\S+", " ", line.split("::")[-1])
            sets, poke = CT.entidades(q); poke = set(poke)
            if not poke and not sets: continue
            alias = []      # never by nickname (owner, 2 November 2026)
            out.append((poke, set(sets), re.compile("|".join(r"(?<![a-z0-9])" + re.escape(x) + r"(?![a-z0-9])" for x in alias)) if alias else None))
        return out
    sets, poke = CT.entidades(group)       # a folder: the set in its name, else its Pokémon
    return [(set(), set(sets), None)] if sets else ([(set(poke), set(), None)] if poke else [])

def _coincide(dets, sets, poke, texto_n):
    for p, s, alias in dets:
        if p and s:
            if (p & set(poke)) and (s & set(sets)): return True
        elif p:
            if p & set(poke): return True
        elif s:
            if s & set(sets): return True
        if alias and alias.search(texto_n): return True
    return False

def menciones_de(grupo, a=None):
    """Mentions of one collection / analysis. None when nothing can be told from its name."""
    dets = _detectores(grupo, a)
    if not dets: return None
    V, C, Pp = _datos(); hoy = dt.date.fromisoformat(today()); age = lambda s: (hoy - dt.date.fromisoformat(s)).days
    pk = set().union(*[d[0] for d in dets]) if any(d[0] and d[1] for d in dets) else set()     # the Pokémon alone, for a broader reading when the exact one is rare
    r = {"amplio": ", ".join(sorted(pk)) or None, "amplio_videos30": 0, "amplio_comunidades30": 0, "videos30": 0, "videos90": 0, "comentarios30": 0, "comunidades30": 0, "comunidades90": 0, "ultima": None, "bear": 0, "bull": 0, "top_video": None, "top_post": None, "aprox": a is None}
    ultima = ""
    for vid, v in V.items():
        a_ = age(v["f"])
        if pk and a_ <= 30 and pk & set(v["poke"]): r["amplio_videos30"] += 1
        if a_ > 90 or not _coincide(dets, v["sets"], v["poke"], v["_n"]): continue
        r["videos90"] += 1; ultima = max(ultima, v["f"])
        if a_ <= 30:
            r["videos30"] += 1; _, bear, bull = CT.temas_mercado(v["t"] + " " + v.get("tags", "")); r["bear"] += bear; r["bull"] += bull
            if not r["top_video"] or v["v"] > r["top_video"]["v"]: r["top_video"] = {"id": vid, "t": v["t"], "v": v["v"], "canal": v["canal"], "f": v["f"]}
            for it in (C.get(vid) or {}).get("items", []):
                if _coincide(dets, it["s"], it["p"], CT._norm(it["x"])): r["comentarios30"] += 1
    for it in Pp.values():
        if pk and age(it["u"]) <= 30 and pk & set(it["_p"]): r["amplio_comunidades30"] += 1
        if age(it["u"]) > 90: continue
        if not _coincide(dets, it["_s"], it["_p"], it["_n"]): continue
        r["comunidades90"] += 1; ultima = max(ultima, it["u"])
        if age(it["u"]) <= 30:
            r["comunidades30"] += 1; _, bear, bull = CT.temas_mercado(it["t"] + " " + it["x"][:500]); r["bear"] += bear; r["bull"] += bull
            peso = it["r"] * 30 + it["v"] / 20 + it["l"]
            if not r["top_post"] or peso > r["top_post"]["peso"]: r["top_post"] = {"url": it["url"], "t": it["t"][:110], "fuente": it["fuente"], "u": it["u"], "peso": peso}
    r["ultima"] = ultima or None
    return r

def menciones_todas(grupos, analisis):
    import json
    _datos(); k = (tuple(grupos), json.dumps(analisis, sort_keys=True))
    if _cache.get("m", (None,))[0] != k:
        own = {a["nombre"]: a for a in analisis}; _cache["m"] = (k, {g: menciones_de(g, own.get(g)) for g in grupos})
    return _cache["m"][1]

# ---- the market as a whole
def _veredicto(serie):
    n14 = sum(serie[-2:]); n8 = sum(serie[-8:]); rec, prev = n14 / 14, max(0, n8 - n14) / 46
    if n14 >= 2 and rec > 1.5 * prev: return "subiendo"
    if n14 == 0 and n8 > 0: return "enfriando"
    return "antiguo" if n14 == 0 else "estable"

def _fusion(a, b):
    ag = {}
    for src, lista in (("yt", a), ("cm", b)):
        for x in lista:
            y = ag.setdefault(x["e"], {"e": x["e"], "n": 0, "antes": 0, "fuentes": 0, "yt": 0, "cm": 0, "serie": [0] * 26, "hace": 9999, "ej": None})
            y["n"] += x["n"]; y["antes"] += x["antes"]; y["fuentes"] += x["canales"]; y[src] += x["n"]; y["hace"] = min(y["hace"], x["hace"])
            y["serie"] = [p + q for p, q in zip(y["serie"], x["serie"])]
            if x.get("ej") and (not y["ej"] or x["ej"].get("v", 0) >= y["ej"].get("v", 0)): y["ej"] = x["ej"]
    for y in ag.values(): y["estado"] = _veredicto(y["serie"])
    return sorted(ag.values(), key=lambda y: (-y["fuentes"], -y["n"]))

def _tend(n, antes):
    if antes == 0: return "nuevo" if n >= 3 else "="
    r = n / antes
    return "sube" if r >= 1.3 else ("baja" if r <= 0.77 else "=")

def panorama(dias=30):
    dias = dias if dias in (7, 30, 90) else 30
    yt, cm = CT.view("todos", dias), CM.view(dias)
    T = {}
    for src, lista in (("yt", yt["temas"]), ("cm", cm["temas"])):
        for x in lista:
            t = T.setdefault(x["e"], {"e": x["e"], "yt": 0, "cm": 0, "antes": 0, "bear": 0, "bull": 0, "fuentes": 0, "com": 0})
            t[src] += x["n"]; t["antes"] += x["antes"]; t["bear"] += x["bear"]; t["bull"] += x["bull"]; t["fuentes"] += x["fuentes"]
    for x in (yt.get("comentarios") or {}).get("temas", []):
        if x["e"] in T: T[x["e"]]["com"] = x["n"]; T[x["e"]]["bear"] += x["bear"]; T[x["e"]]["bull"] += x["bull"]
    temas = sorted(({**t, "total": t["yt"] + t["cm"], "tendencia": _tend(t["yt"] + t["cm"], t["antes"])} for t in T.values()), key=lambda t: -t["total"])
    sets, pokes = _fusion(yt["sets"], cm["sets"]), _fusion(yt["pokemon"], cm["pokemon"])
    def tema(clave):
        return next((t for t in temas if clave in t["e"].lower()), None)
    R = []
    if temas:
        top = temas[:3]; R.append("Lo que más se habla ahora (%s): %s." % ({7: "última semana", 30: "último mes", 90: "últimos 3 meses"}[dias], ", ".join(f"{t['e'].split(' ', 1)[-1].lower()} ({t['total']})" for t in top)))
        suben = [t for t in temas if t["tendencia"] in ("sube", "nuevo") and t["total"] >= 5][:3]; bajan = [t for t in temas if t["tendencia"] == "baja" and t["antes"] >= 5][:3]
        if suben: R.append("Suben frente al periodo anterior: " + ", ".join(f"{t['e'].split(' ', 1)[-1].lower()} ({t['antes']} → {t['total']})" for t in suben) + ".")
        if bajan: R.append("Se enfrían: " + ", ".join(f"{t['e'].split(' ', 1)[-1].lower()} ({t['antes']} → {t['total']})" for t in bajan) + ".")
        for clave, nombre in (("vintage", "Vintage"), ("30 aniversario", "30 aniversario"), ("moderno", "Moderno"), ("corrección", "Corrección")):
            t = tema(clave)
            if t and t["total"]: R.append(f"{nombre}: {t['total']} menciones (antes {t['antes']}), tono {t['bear']} de caída frente a {t['bull']} de subida.")
    if sets: R.append("Sets que más suenan: " + ", ".join(f"{s['e']} ({s['estado']})" for s in sets[:4]) + ".")
    if pokes: R.append("Pokémon que más suenan: " + ", ".join(f"{s['e']} ({s['estado']})" for s in pokes[:4]) + ".")
    enf = [s["e"] for s in sets + pokes if s["estado"] == "enfriando"][:4]
    if enf: R.append("Se están enfriando: " + ", ".join(enf) + ".")
    # what is ready and what is not
    import mercado as M
    mv = M.view(); u = mv.get("ultimo"); ce, cc = load(os.path.join(CT.DIR, "estado.json"), {}) or {}, load(os.path.join(CM.DIR, "estado.json"), {}) or {}
    dias_h = mv.get("dias", 0)
    try: NPC = len(__import__("podcasts").listar()["episodios"])
    except Exception: NPC = 0
    listo = [
        {"n": "YouTube", "ok": bool(ce.get("fecha")), "t": f"{yt['videos']:,} vídeos de {len([c for c in yt['canales'] if c['activo']])} canales; última lectura {ce.get('fecha', '—')}".replace(",", ".")},
        {"n": "Comunidades", "ok": bool(cc.get("fecha")), "t": f"{cm['n_total']:,} elementos de {len([f for f in cm['fuentes'] if f['activo']])} fuentes; última lectura {cc.get('fecha', '—')}".replace(",", ".")},
        {"n": "Foto de eBay", "ok": bool(u), "t": f"{u['date'] if u else '—'} · {dias_h} día{'s' if dias_h != 1 else ''} de historial" + ("" if dias_h >= 2 else " (las tendencias de precio y los nuevos/desaparecidos empiezan con la 2ª foto)")},
        {"n": "Bluesky", "ok": cm.get("bluesky_creds", False), "t": "conectado" if cm.get("bluesky_creds") else "falta rellenar .secrets/bluesky.json"},
        {"n": "Podcasts", "ok": bool(NPC), "t": f"{NPC} episodio{'s' if NPC != 1 else ''} transcrito{'s' if NPC != 1 else ''} (pestaña Podcasts)" if NPC else "ninguno transcrito todavía (tools/transcribir_podcast.py)"},
        {"n": "PSA (población y notas)", "ok": False, "t": "sin acceso: PSA aún no ha aprobado tu cuenta de la API"},
        {"n": "pokemontcg.io (sets y precios)", "ok": False, "t": "su API da errores del lado del servidor; se reintentará"},
    ]
    colecciones = [{"group": g["group"], "n": g["n"], "med": g["med"], "p25": g["p25"], "p75": g["p75"], "d7_n": g["d7_n"], "nuevos": g["nuevos"], "fuera": g["fuera"], "menciones": g.get("menciones")} for g in mv.get("grupos", [])]
    return {"dias": dias, "resumen": R, "temas": temas, "sets": sets[:16], "pokemon": pokes[:16], "listo": listo, "colecciones": colecciones, "hoy": today(),
            "fuentes_yt": len([c for c in yt["canales"] if c["activo"]]), "fuentes_cm": len([f for f in cm["fuentes"] if f["activo"]]), "elementos": yt["videos"] + cm["n_total"]}

# ---- the full sweep of one thing
def barrido(grupo, extra=True):
    import mercado as M
    if grupo not in {g["group"] for g in M.grupos_info()}: raise ValueError("No existe esa colección o análisis")
    M.set_hoy(grupo, "ebay", True); M.set_hoy(grupo, "otros", True); M.set_profundo(grupo)   # a full sweep reads every market
    r = {"ebay": False, "otros": 0, "youtube": False, "comunidades": False}
    if not M.en_marcha(): M.lanzar(); r["ebay"] = True
    d = M.diario_preparar(force=True); r["otros"] = len(d.get("cola") or [])
    if extra:
        if not CT.en_marcha(): CT.lanzar(); r["youtube"] = True
        if not CM.en_marcha(): CM.lanzar(); r["comunidades"] = True
    return r

def progreso():
    import mercado as M
    e, d = load(os.path.join(M.DIR, "estado.json"), {}) or {}, load(M.DIARIO, {}) or {}
    ce, cc = load(os.path.join(CT.DIR, "estado.json"), {}) or {}, load(os.path.join(CM.DIR, "estado.json"), {}) or {}
    return {"ebay": {"running": M.en_marcha(), "message": e.get("message")}, "otros": {"hechas": d.get("hechas", 0), "total": d.get("total", 0), "pendientes": len(d.get("cola") or [])},
            "youtube": {"running": CT.en_marcha(), "message": ce.get("message")}, "comunidades": {"running": CM.en_marcha(), "message": cc.get("message")}}
