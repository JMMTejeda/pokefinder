"""«Dashboard» (owner, 4 November 2026: conclusiones de verdad, no listas; los takes más importantes de cada podcast, eligiendo qué decir y qué no).
Las conclusiones las escribe Claude en data/conclusiones/semana.json (esquema en tools/tarea_resumen_podcasts.md) y este módulo solo las lee y le suma lo que se puede contar sin gastar nada:
episodios analizados y quién escribió cada resumen, cuántas conclusiones y takes hay, y las cifras vivas del mercado y de YouTube.
  from dashboard import vista    -> lo que sirve /api/dashboard"""
import datetime as dt, os, re, time
from common import P, load
import actualidad

def _episodios():
    d = P("podcasts", "resumenes"); n = {"claude": 0, "groq": 0}
    if not os.path.isdir(d): return n
    for f in os.listdir(d):
        if not f.endswith(".md"): continue
        try: txt = open(os.path.join(d, f), encoding="utf-8").read()
        except OSError: continue
        n["claude" if re.search(r"escrito por Claude", txt) else "groq"] += 1
    return n

TEMAS = [("vintage", "🕰", "Vintage"), ("moderno", "🆕", "Moderno"), ("gold_stars", "⭐", "Gold Stars"), ("japones_ingles", "🇯🇵", "Japonés frente a inglés"), ("ventas_dudosas", "🕵️", "Ventas dudosas"),
         ("institucional", "🏦", "Dinero institucional"), ("riesgos", "🛡", "Riesgos: robos y seguros"), ("grading", "🔖", "Grading"), ("mercado_general", "🌐", "Mercado en general")]

def canales(todas):
    """Per source (channel/podcast): everything it has said, newest first, with how often it held up, plus Claude's written balance of it if there is one
    (data/conclusiones/canales.json: {"<fuente>": {"texto": "...", "escrito": "AAAA-MM-DD", "autor": "Claude"}}; steps in tools/tarea_resumen_podcasts.md).
    A verdict (cumplida/fallida…) exists only after someone compared the claim with real prices or sales: 'pendiente' means nobody has checked it yet."""
    esc = load(P("conclusiones", "canales.json"), {}) or {}
    por = {}
    for r in todas: por.setdefault(r["fuente"], []).append(r)
    out = []
    for f, L in por.items():
        L = sorted(L, key=lambda r: r["fecha"], reverse=True)
        v = {k: sum(1 for r in L if r["verificacion"] == k) for k in ("pendiente", "cumplida", "parcial", "fallida", "superada", "no_verificable")}
        temas = {}
        for r in L: temas[r["tema"]] = temas.get(r["tema"], 0) + 1
        out.append({"fuente": f, "total": len(L), "desde": L[-1]["fecha"], "hasta": L[0]["fecha"], "verif": v, "temas": sorted(temas.items(), key=lambda x: -x[1]),
                    "episodios": len({r.get("episodio") for r in L if r.get("episodio")}), "balance": esc.get(f), "items": L})
    return sorted(out, key=lambda c: (-c["total"], c["fuente"]))

def cronologia():
    """The dated claims by topic (expertise.py afirmar): each with its age and whether it still counts as current, plus Fernando's own observations and Claude's reading of the topic,
    and the track record of each source (how often what they said held up). Owner, 4 November 2026: the date is what makes a note worth anything."""
    import expertise as X
    filas = load(P("expertise", "afirmaciones.json"), []) or []
    por = {}
    for r in filas:
        try: edad, est = X.estado_de(r["fecha"], r["vigencia_dias"])
        except (KeyError, ValueError): continue
        r = {**r, "edad": edad, "estado": est, "caduca_en": r["vigencia_dias"] - edad}
        por.setdefault(r["tema"], []).append(r)
    temas = []; reg = {}
    for k, ico, titulo in TEMAS:
        L = sorted(por.get(k, []), key=lambda r: r["fecha"])
        items = [r for r in L if r["tipo"] not in ("observacion", "lectura")]
        obs = [r for r in L if r["tipo"] == "observacion"]
        lec = [r for r in L if r["tipo"] == "lectura"]
        cnt = {e: sum(1 for r in items if r["estado"] == e) for e in ("vigente", "caduca pronto", "caducada", "archivo")}
        temas.append({"id": k, "icono": ico, "titulo": titulo, "items": items, "observaciones": obs, "lectura": lec[-1] if lec else None, "contadores": cnt, "total": len(items)})
        for r in items:
            if r["clase"] in ("tendencia", "prediccion") and r["verificacion"] != "pendiente":
                g = reg.setdefault(r["fuente"], {"fuente": r["fuente"], "revisadas": 0, "cumplida": 0, "parcial": 0, "fallida": 0, "superada": 0, "no_verificable": 0})
                g["revisadas"] += 1; g[r["verificacion"]] = g.get(r["verificacion"], 0) + 1
    todas = [r for L in por.values() for r in L if r["tipo"] not in ("observacion", "lectura")]
    return {"temas": temas, "canales": canales(todas), "hoy": dt.date.today().isoformat(), "ventana": X.VENTANA,
            "contadores": {"afirmaciones": len(todas), "vigentes": sum(1 for r in todas if r["estado"] in ("vigente", "caduca pronto")), "caducadas": sum(1 for r in todas if r["estado"] == "caducada"),
                           "archivo": sum(1 for r in todas if r["estado"] == "archivo"), "revisadas": sum(1 for r in todas if r["verificacion"] != "pendiente"), "pendientes": sum(1 for r in todas if r["verificacion"] == "pendiente")},
            "registro": sorted(reg.values(), key=lambda g: -g["revisadas"])}

def vista():
    s = load(P("conclusiones", "semana.json"), None)
    if not s: return {"vacio": True}
    ep = _episodios(); cs = s.get("conclusiones") or []; ps = s.get("podcasts") or []
    takes = sum(len(p.get("takes") or []) for p in ps)
    citas = sum(1 for p in ps for t in p.get("takes") or [] if t.get("cita")) + sum(1 for c in cs for f in c.get("fuentes") or [] if f.get("cita"))
    tipos = {}
    for c in cs: tipos[c.get("tipo")] = tipos.get(c.get("tipo"), 0) + 1
    a = actualidad.vista()
    try: edad_c = (dt.date.today() - dt.date.fromisoformat(str(s.get("actualizado"))[:10])).days
    except ValueError: edad_c = None
    try: cr = cronologia()
    except Exception as e: cr = {"_error": f"{type(e).__name__}: {str(e)[:100]}"}
    return {"vacio": False, "cronologia": cr, "edad_conclusiones": edad_c, "desfasadas": edad_c is None or edad_c > 14, "actualizado": s.get("actualizado"), "autor": s.get("autor"), "criterio": s.get("criterio"), "conclusiones": cs, "habla_vs_datos": s.get("habla_vs_datos") or [], "podcasts": ps,
            "contadores": {"episodios": ep["claude"] + ep["groq"], "con_claude": ep["claude"], "con_groq": ep["groq"], "conclusiones": len(cs), "takes": takes, "citas": citas, "tipos": tipos,
                           "pendientes": ep["groq"]},
            "mercado": {k: (a.get("mercado") or {}).get(k) for k in ("fecha", "anterior", "totales", "aviso")},
            "pokemon": ((a.get("youtube") or {}).get("pokemon") or [])[:8]}

if __name__ == "__main__":
    import json; v = vista(); print(json.dumps({k: v[k] for k in v if k in ("vacio", "actualizado", "contadores", "mercado", "pokemon")}, ensure_ascii=False))
