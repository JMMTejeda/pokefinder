"""«Actualidad» de la Oficina (owner, 3 November 2026: ver rápido los takes más calientes de lo que vamos leyendo: podcasts, comunidades, vídeos, y cómo se mueve el mercado).
Solo LEE lo que ya está guardado y no gasta nada (ni Claude, ni Groq, ni eBay):
  - podcasts:    los puntos de «Lo esencial» de los últimos resúmenes (escritos por Claude, cada uno con su cita comprobada),
  - comunidades: los hilos con más respuestas que se han movido estos días,
  - youtube:     vídeos que más suben, Pokémon y temas de moda (vídeos y comentarios),
  - mercado:     lo que sube y baja en la última foto de eBay (precios de lo pedido, no de lo vendido).
  from actualidad import vista   -> lo que sirve /api/oficina/actualidad"""
import collections, datetime as dt, os, re, time
from common import P, load, TZ

def _hoy(): return dt.datetime.now(TZ).date()
def _int(v):
    try: return int(float(v))
    except (TypeError, ValueError): return 0
def _dias(f):
    try: return (_hoy() - dt.date.fromisoformat(str(f)[:10])).days
    except ValueError: return 999

# ---------------------------------------------------------------- podcasts
_BALA = re.compile(r"^- \*\*(.+?)\*\*\s*(.*)$")
def _quita_cita(t):
    m = re.search(r"\s*\[(\d+:\d+(?::\d+)?)\]\s*[—-]\s*[«\"](.+?)[»\"]\s*$", t)
    return (t[:m.start()].strip(), m.group(1), m.group(2)) if m else (t.strip(), None, None)

def podcasts(max_ep=5, max_pts=4):
    d = P("podcasts", "resumenes"); out = []
    if not os.path.isdir(d): return out
    for f in sorted(os.listdir(d), reverse=True)[:max_ep]:
        if not f.endswith(".md"): continue
        try: txt = open(os.path.join(d, f), encoding="utf-8").read()
        except OSError: continue
        m = re.match(r"#\s*(.+?)\s*\((\d{4}-\d\d-\d\d)\)", txt)
        titulo, fecha = (m.group(1), m.group(2)) if m else (f[:-3], f[:10])
        ep, _, canal = titulo.rpartition("|")
        puntos, dentro = [], False
        for l in txt.splitlines():
            if l.startswith("## "): dentro = l.strip().lower().startswith("## lo esencial"); continue
            b = _BALA.match(l) if dentro else None
            if not b: continue
            resto, minuto, cita = _quita_cita(b.group(2))
            puntos.append({"titulo": b.group(1).rstrip("."), "texto": resto, "minuto": minuto, "cita": cita})
        if puntos: out.append({"episodio": (ep or titulo).strip(), "podcast": canal.strip(), "fecha": fecha, "puntos": puntos[:max_pts], "total": len(puntos), "archivo": f})
    return out

# ---------------------------------------------------------------- comunidades
def comunidades(dias=4, n=10):
    posts = (load(P("comunidades", "posts.json"), {}) or {}).values(); rec = []
    for q in posts:
        if _dias(q.get("u") or q.get("f")) > dias: continue
        rec.append({"fuente": q.get("fuente"), "titulo": q.get("t"), "respuestas": _int(q.get("r")), "vistas": _int(q.get("v")), "likes": _int(q.get("l")), "url": q.get("url"), "cat": q.get("cat") or "",
                    "nuevo": _dias(q.get("f")) <= dias, "ultima": q.get("u")})
    rec.sort(key=lambda x: (-(x["respuestas"] + x["likes"]), -x["vistas"]))
    por = collections.Counter(q["fuente"] for q in rec)
    resumen = None; rd = P("comunidades", "resumenes")
    if os.path.isdir(rd):
        fs = sorted(f for f in os.listdir(rd) if f.endswith(".md"))
        if fs:
            try: resumen = {"fecha": fs[-1][:10], "texto": open(os.path.join(rd, fs[-1]), encoding="utf-8").read()[:1800]}
            except OSError: pass
    nuevos = [q for q in rec if _dias(q["ultima"]) <= dias and q["nuevo"]][:n]      # born this week: the long threads of months pile up replies, these show what is new
    return {"hilos": rec[:n], "nuevos": nuevos, "activos_por_fuente": dict(por), "resumen": resumen, "dias": dias}

# ---------------------------------------------------------------- YouTube
def youtube(dias=7, n=6):
    vids = load(P("contenido", "videos.json"), {}) or {}; rec = []
    for vid, v in vids.items():
        if _dias(v.get("f")) > dias: continue
        h = v.get("hist") or {}; ks = sorted(h)
        sube = (_int(h[ks[-1]]) - _int(h[ks[-2]])) if len(ks) >= 2 else 0
        rec.append({"id": vid, "canal": v.get("canal"), "titulo": v.get("t"), "fecha": v.get("f"), "vistas": _int(v.get("v")), "likes": _int(v.get("l")), "comentarios": _int(v.get("k")), "sube": sube,
                    "poke": v.get("poke") or [], "temas": v.get("temas") or [], "url": f"https://www.youtube.com/watch?v={vid}"})
    pk, tm = collections.Counter(), collections.Counter()
    for v in rec:
        pk.update(v["poke"]); tm.update(v["temas"])
    for c in (load(P("contenido", "comentarios.json"), {}) or {}).values():
        if _dias(c.get("at")) > dias: continue
        for it in c.get("items") or []: pk.update(it.get("p") or [])
    return {"suben": sorted(rec, key=lambda x: -x["sube"])[:n], "vistos": sorted(rec, key=lambda x: -x["vistas"])[:n],
            "pokemon": pk.most_common(10), "temas": tm.most_common(8), "videos": len(rec), "dias": dias}

# ---------------------------------------------------------------- mercado (la foto de eBay)
def mercado(n=6):
    u = load(P("mercado", "ultimo.json"), {}) or {}
    if not u: return {}
    ch = u.get("cambios") or []
    fila = lambda c: {"titulo": c.get("t"), "carta": c.get("l"), "eur": c.get("e"), "antes": c.get("antes"), "pct": c.get("pct"), "imagen": c.get("i"), "url": f"https://www.ebay.com/itm/{c.get('id')}" if c.get("id") else None}
    bajan = sorted((c for c in ch if (c.get("pct") or 0) < 0), key=lambda c: c["pct"])[:n]
    suben = sorted((c for c in ch if (c.get("pct") or 0) > 0), key=lambda c: -c["pct"])[:n]
    h = load(P("mercado", "historial.json"), {}) or {}; med = []
    for k, t in h.items():
        pts = [p for p in t.get("puntos") or [] if len(p) >= 4 and p[3]]
        if len(pts) >= 2 and pts[-2][3]:
            med.append({"carta": t.get("label") or k, "grupo": t.get("group"), "antes": pts[-2][3], "ahora": pts[-1][3], "pct": round((pts[-1][3] / pts[-2][3] - 1) * 100, 1), "n": pts[-1][1]})
    med.sort(key=lambda x: x["pct"])
    mov = sorted(u.get("tracks") or [], key=lambda t: -((t.get("nuevos") or 0) + (t.get("fuera") or 0)))
    return {"fecha": u.get("date"), "anterior": u.get("prev_date"), "totales": u.get("totals"),
            "bajan": [fila(c) for c in bajan], "suben": [fila(c) for c in suben],
            "mediana_baja": med[:n], "mediana_sube": [m for m in reversed(med) if m["pct"] > 0][:n],
            "movimiento": [{"carta": t.get("label"), "grupo": t.get("group"), "n": t.get("n"), "nuevos": t.get("nuevos"), "fuera": t.get("fuera"), "med": t.get("med")} for t in mov[:n]],
            "aviso": "Son precios PEDIDOS en eBay, no ventas reales."}

_cache = [0, None]
def vista():
    """Everything together, kept 2 minutes: the panel does not need to read the big files every time it asks."""
    if time.time() - _cache[0] < 120 and _cache[1]: return _cache[1]
    out = {"hecho": dt.datetime.now(TZ).isoformat(timespec="seconds")}
    for k, fn in (("podcasts", podcasts), ("comunidades", comunidades), ("youtube", youtube), ("mercado", mercado)):
        try: out[k] = fn()
        except Exception as e: out[k] = {"_error": f"{type(e).__name__}: {str(e)[:100]}"}
    _cache[:] = [time.time(), out]
    return out

if __name__ == "__main__":
    import json; v = vista(); print(json.dumps({k: (v[k] if not isinstance(v[k], (list, dict)) else (len(v[k]) if isinstance(v[k], list) else list(v[k])[:8])) for k in v}, ensure_ascii=False))
    print(json.dumps(v["podcasts"][:1], ensure_ascii=False)[:600]); print(json.dumps(v["comunidades"]["hilos"][:2], ensure_ascii=False)[:400]); print(json.dumps(v["youtube"]["pokemon"], ensure_ascii=False)); print(json.dumps(v["mercado"].get("bajan", [])[:1], ensure_ascii=False)[:400])
