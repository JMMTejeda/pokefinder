"""El Arquitecto: mira el sistema ENTERO y apunta cómo se hablan sus piezas (Fernando, 6 nov 2026: «que no se me olvide cómo se comunicaban estas dos cosas o queden cosas sin comunicar»).
Sin tokens ni dinero: lee el código y los ficheros de estado. Escribe en data/arquitecto/:
  mapa.md    quién escribe y quién lee cada fichero de datos, y qué módulo usa a cuál (el plano de cómo se coordinan los trabajadores)
  huecos.md  lo que no cuadra: datos que se escriben y nadie lee, datos que se leen y nadie escribe, piezas que no se hablan, servicios parados o con cola, cupos que se pierden
  mapa.json  lo mismo para las máquinas (Oficina, otros trabajadores)
Uso: python arquitecto.py   (el servidor lo repasa cada pocas horas)"""
import ast, glob, json, os, re, sys, time, datetime as dt
from common import P, ROOT, load, save, TZ

DIR = P("arquitecto"); SCR = os.path.dirname(os.path.abspath(__file__))
IGNORAR = {"common", "__init__", "arquitecto"}
LEE = re.compile(r"\b(load|_json|_j|json\.load|read_text|glob\.glob|open)\(")
ESCRIBE = re.compile(r"\b(save|json\.dump|write_text|\.write)\(|open\([^)]*,\s*[\"'](?:w|a|wb|ab)[\"']")

def _p_literal(call):
    """P("a","b","c.json") → «a/b/c.json» (solo si todos los argumentos son texto fijo)."""
    try:
        if isinstance(call.func, ast.Name) and call.func.id == "P" and call.args and all(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in call.args):
            return "/".join(a.value for a in call.args)
    except Exception: pass
    return None

def analizar(ruta):
    """Un módulo: los ficheros de datos que lee y escribe, y los módulos del proyecto que importa."""
    src = open(ruta, encoding="utf-8-sig", errors="replace").read(); mod = os.path.basename(ruta)[:-3]
    try: arbol = ast.parse(src)
    except SyntaxError: return None
    vars_ = {}      # NOMBRE = P("state", "x.json")
    for n in ast.walk(arbol):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                tup = n.value.elts if isinstance(n.value, ast.Tuple) else [n.value]; ts = t.elts if isinstance(t, ast.Tuple) else [t]
                for tt, vv in zip(ts, tup):
                    if isinstance(tt, ast.Name) and isinstance(vv, ast.Call) and _p_literal(vv): vars_[tt.id] = _p_literal(vv)
    lee, escribe = set(), set(); lineas = src.splitlines()
    for i, ln in enumerate(lineas):
        if ln.lstrip().startswith("#"): continue
        usados = set(re.findall(r'P\(\s*((?:"[^"]+"\s*,?\s*)+)\)', ln)); rutas = ["/".join(re.findall(r'"([^"]+)"', u)) for u in usados]
        rutas += [m for m in re.findall(r'["\']data/([\w./-]+\.(?:jsonl?|md|txt))["\']', ln)]      # rutas escritas como texto: O._j("data/state/x.json")
        rutas += [p for v, p in vars_.items() if re.search(rf"\b{re.escape(v)}\b", ln) and not re.match(rf"\s*{re.escape(v)}\s*=", ln.strip())]
        if not rutas: continue
        w, r = bool(ESCRIBE.search(ln)), bool(LEE.search(ln))
        for p in rutas:
            if w: escribe.add(p)
            if r or not w: lee.add(p)
    imp = set()
    for n in ast.walk(arbol):
        if isinstance(n, ast.Import): imp |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module: imp.add(n.module.split(".")[0])
    return {"mod": mod, "lee": sorted(lee), "escribe": sorted(escribe), "importa": sorted(imp)}

def mapa():
    mods = {}
    for f in sorted(glob.glob(os.path.join(SCR, "*.py"))) + [os.path.join(ROOT, "server.py")]:
        m = os.path.basename(f)[:-3]
        if m in IGNORAR: continue
        a = analizar(f)
        if a: mods[m] = a
    nombres = set(mods)
    for a in mods.values(): a["importa"] = sorted(x for x in a["importa"] if x in nombres and x != a["mod"])
    datos = {}
    for m, a in mods.items():
        for p in a["escribe"]: datos.setdefault(p, {"escribe": [], "lee": []})["escribe"].append(m)
        for p in a["lee"]: datos.setdefault(p, {"escribe": [], "lee": []})["lee"].append(m)
    return mods, datos

def _vivo(ruta, max_h):
    try: return (time.time() - os.path.getmtime(ruta)) / 3600 < max_h
    except OSError: return False

def huecos(mods, datos):
    H = []; solos = {}
    for p, d in sorted(datos.items()):
        esc, lee = set(d["escribe"]), set(d["lee"])
        if re.search(r"[*\[\]]", p) or p.startswith("state/") and not esc: continue      # patrones con comodín: no son un fichero concreto
        if p.startswith("state/"): continue      # el estado propio de cada pieza lo lee su Oficina o ella misma: no es un hueco
        if p.endswith(".json") or p.endswith(".jsonl") or p.endswith(".md"):
            if esc and not lee: H.append(("Se escribe y no lo lee nadie", f"`data/{p}` lo escribe {', '.join(sorted(esc))} y ningún módulo lo lee: ¿es solo para mirarlo a mano o falta quien lo use?"))
            elif esc and not (lee - esc): solos.setdefault(", ".join(sorted(esc)), []).append(p)
            if lee and not esc and not os.path.exists(os.path.join(ROOT, "data", *p.split("/"))): H.append(("Se lee y nadie lo escribe", f"`data/{p}` lo lee {', '.join(sorted(lee))} y no existe ni lo escribe nadie."))
    if solos: H.append(("Datos que solo usa quien los escribe", "Es lo normal para el estado propio de una pieza; es un hueco si otra pieza debería aprovecharlos (p. ej. el catálogo estándar, que aún no consume nadie más). " + " · ".join(f"**{m}**: " + ", ".join(f"`{x}`" for x in ps) for m, ps in sorted(solos.items()))))
    sin_hablar = sorted(m for m, a in mods.items() if not a["importa"] and not any(m in b["importa"] for b in mods.values()) and m != "server")
    if sin_hablar: H.append(("Piezas aisladas", "Ningún módulo las usa ni usan a otro (¿herramientas sueltas o código muerto?): " + ", ".join(sin_hablar)))
    try:
        import referencia as RF
        r = load(P("state", "referencia.json"), {}) or {}
        if not RF.viva(): H.append(("Servicio parado", "El servicio del Tasador no late (lo relanza el servidor en ≤ 5 min; si sigue así, mirar `data/state/referencia.log`)."))
        if r.get("cola", 0) > 300: H.append(("Cola larga", f"El Tasador tiene {r['cola']} cartas en cola: a 40-90 s por carta son unas {r['cola'] * 65 / 3600:.0f} h. PokéWallet y el catálogo la reparten, pero conviene priorizar."))
    except Exception as ex: H.append(("Comprobación", f"No pude mirar el Tasador: {type(ex).__name__}"))
    pw = load(P("state", "pokewallet.json"), {}) or {}
    if pw.get("dia") == time.strftime("%Y-%m-%d") and pw.get("hoy", 0) < 100 and dt.datetime.now(TZ).hour >= 12: H.append(("Cupo que se pierde", f"PokéWallet lleva solo {pw.get('hoy')} peticiones hoy de 950 y ya son más de las 12: el hilo va lento o sin cartas que pedirle."))
    try:
        import ebay_cuota as Q; v = Q.vista(); h = dt.datetime.now(TZ).hour
        if v["quedan"] > 1500 and h >= 6 and h < 9: H.append(("Cupo que se pierde", f"Quedan {v['quedan']} llamadas de eBay y se renuevan a las 09:00: lo que no se gaste se pierde."))
    except Exception: pass
    ci = load(P("state", "catalogo.json"), {}) or {}
    if not ci or not _vivo(P("state", "catalogo.json"), 2): H.append(("Catálogo", "El catálogo estándar no se ha actualizado en las últimas 2 horas (lo hace el servicio del Tasador cada 15 min)."))
    if ci.get("conflictos"): H.append(("Catálogo", f"{ci['conflictos']} fichas con el mismo id y otro nombre: revisar `data/catalogo/cartas.json` (campo `conflictos`)."))
    H.append(("Pendiente de comunicar", "Entre los dos ordenadores solo viajan los precios del Tasador (par.py, apagado). Aún no se comparten: el catálogo estándar, las búsquedas ya hechas (`data/busquedas/`) ni el cupo de eBay."))
    return H

def escribir():
    mods, datos = mapa(); H = huecos(mods, datos); os.makedirs(DIR, exist_ok=True); ahora = dt.datetime.now(TZ).strftime("%d/%m/%Y %H:%M")
    L = [f"# Mapa del sistema · {ahora}", "", f"{len(mods)} módulos y {len(datos)} ficheros de datos. Generado por el Arquitecto leyendo el código (no hay que mantenerlo a mano).", "", "## Quién escribe y quién lee cada dato", "", "| Dato (`data/…`) | Lo escribe | Lo leen |", "|---|---|---|"]
    for p, d in sorted(datos.items()):
        if d["escribe"] or len(d["lee"]) > 1: L.append(f"| `{p}` | {', '.join(sorted(set(d['escribe']))) or '—'} | {', '.join(sorted(set(d['lee']) - set(d['escribe']))) or '—'} |")
    L += ["", "## Quién usa a quién (importaciones)", ""] + [f"- **{m}** → {', '.join(a['importa'])}" for m, a in sorted(mods.items()) if a["importa"]]
    open(os.path.join(DIR, "mapa.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    G = [f"# Huecos y mejoras · {ahora}", ""] + ([f"- **{t}.** {x}" for t, x in H] or ["Nada que señalar."])
    open(os.path.join(DIR, "huecos.md"), "w", encoding="utf-8").write("\n".join(G) + "\n")
    save(os.path.join(DIR, "mapa.json"), {"t": ahora, "modulos": mods, "datos": datos, "huecos": [{"tipo": t, "texto": x} for t, x in H]})
    e = load(P("state", "arquitecto.json"), {}) or {}; e.update(ultima=ahora, modulos=len(mods), datos=len(datos), huecos=len(H), beat=time.time()); save(P("state", "arquitecto.json"), e); return e

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8"); e = escribir(); print(e)
    print(open(os.path.join(DIR, "huecos.md"), encoding="utf-8").read())
