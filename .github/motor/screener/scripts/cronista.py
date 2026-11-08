"""El Cronista (Fernando, 5 de noviembre de 2026: «un redactor con una máquina de escribir, que no pare de escribir todo lo que pasa en la aplicación, todos los commits… para una guía para Jesús y una guía de todo, la app, cómo funciona»).
Escribe, sin gastar tokens ni dinero, tres documentos en data/cronista/ a partir de lo que ya existe:
- diario.md: una entrada por cada commit del repositorio (fecha, título, explicación, áreas tocadas y ficheros), de más antiguo a más nuevo. Los commits automáticos (transcripciones, resúmenes) no entran: solo se cuentan.
- guia_app.md: «cómo funciona la app»: cada módulo de screener/scripts, tools y app con lo primero que dice su propia documentación. Se regenera sola cuando cambia el código.
- novedades.md: lo de los últimos 7 días agrupado por área, listo para pasárselo a Jesús (o para que Claude lo pula y actualice GUIA-COMPLETA-JESUS.md).
El servidor lo llama cada 5 minutos (cronista_loop); estado en data/state/cronista.json: último commit escrito y número de hojas (la Oficina las amontona junto a su mesa).
  python cronista.py            escribe lo que falte ahora        python cronista.py --estado"""
import ast, datetime as dt, glob, os, re, subprocess, sys
from common import P, load, save, ROOT, TZ

DIR = P("cronista"); ESTADO = P("state", "cronista.json")
AUTO = re.compile(r"^(Transcripci[oó]n|Resumen|Merge\b|Foto de eBay)", re.I)      # los commits que hace sola la app (y las fusiones de GitHub)
AREAS = [("Oficina", r"oficina"), ("Precios y tasación", r"referencia|precios|ventas|mercado|caza|busquedas_db|ebay_cuota|collectr|tcgplayer"), ("Sets", r"(^|/)sets\b|sets\.js|sets\.py"),
         ("Podcasts y comunidades", r"podcast|comunidades|yt_canales|transcrib"), ("Dashboard y conocimiento", r"dashboard|expertise"), ("Vídeo y estudio", r"video_html|estudio|reels|plantillas"),
         ("Avisos", r"avisos|avisar|ntfy"), ("Servidor", r"^server\.py$"), ("Guías", r"\.md$"), ("Herramientas", r"^tools/")]

def _git(*a):
    r = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    return r.stdout if r.returncode == 0 else ""

def _f(s):
    """La fecha de un commit (Python 3.10 no entiende la «Z» del final) en la hora de España."""
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(TZ)

def _areas(ficheros):
    out = []
    for nombre, rx in AREAS:
        if any(re.search(rx, f, re.I) for f in ficheros): out.append(nombre)
    return out or ["Otros"]

def commits(desde=None, limite=400):
    """[{"h", "fecha", "titulo", "cuerpo", "ficheros", "auto"}] de más antiguo a más nuevo, los posteriores a `desde`."""
    rango = f"{desde}..HEAD" if desde else "HEAD"
    sal = _git("log", rango, "--reverse", f"-n{limite}", "--name-only", "--format=\x1e%H\x1f%aI\x1f%s\x1f%b\x1f")
    out = []
    for bloque in sal.split("\x1e")[1:]:
        partes = bloque.split("\x1f")
        if len(partes) < 5: continue
        h, fecha, titulo, cuerpo, resto = partes[0], partes[1], partes[2], partes[3], partes[4]
        cuerpo = "\n".join(l for l in cuerpo.splitlines() if not l.startswith("Co-Authored-By")).strip()
        out.append({"h": h, "fecha": fecha, "titulo": titulo.strip(), "cuerpo": cuerpo, "ficheros": [f.strip() for f in resto.splitlines() if f.strip()], "auto": bool(AUTO.match(titulo.strip()))})
    return out

def _entrada(c):
    d = _f(c["fecha"]); a = _areas(c["ficheros"])
    txt = f"### {d:%d/%m/%Y %H:%M} · {c['titulo']}\n"
    if c["cuerpo"]: txt += c["cuerpo"] + "\n"
    return txt + f"*Áreas:* {', '.join(a)} · *{len(c['ficheros'])} fichero{'s' if len(c['ficheros']) != 1 else ''}:* " + ", ".join(f"`{f}`" for f in c["ficheros"][:8]) + (" …" if len(c["ficheros"]) > 8 else "") + f" · `{c['h'][:7]}`\n\n"

def _doc_py(ruta):
    try: t = ast.parse(open(ruta, encoding="utf-8").read()); d = ast.get_docstring(t)
    except Exception: return None
    if not d: return None
    d = re.sub(r"\s+", " ", d.strip()); return (d[:300] + "…") if len(d) > 300 else d

def _doc_js(ruta):
    try: m = re.match(r"\s*/\*+\s*(.*?)\*/", open(ruta, encoding="utf-8").read(), re.S)
    except OSError: return None
    return re.sub(r"\s+", " ", m.group(1)).strip()[:300] if m else None

def guia_app():
    """data/cronista/guia_app.md: un índice de la app hecho con la documentación de cada fichero. Devuelve cuántos módulos documentó."""
    sec = [("Servidor", [os.path.join(ROOT, "server.py")], _doc_py), ("Motores y lectores (screener/scripts)", sorted(glob.glob(os.path.join(ROOT, "screener", "scripts", "*.py"))), _doc_py),
           ("Herramientas (tools)", sorted(glob.glob(os.path.join(ROOT, "tools", "*.py"))), _doc_py), ("Pantallas (app)", sorted(glob.glob(os.path.join(ROOT, "app", "*.js"))), _doc_js)]
    out = [f"# Cómo funciona PokéFinder (guía generada por el Cronista el {dt.datetime.now(TZ):%d/%m/%Y %H:%M})\n\nCada fila es un fichero con lo primero que dice su propia documentación. Para ampliar, abre el fichero.\n"]; n = 0
    for titulo, ficheros, f in sec:
        filas = [(os.path.relpath(r, ROOT).replace("\\", "/"), f(r)) for r in ficheros]; filas = [(a, b) for a, b in filas if b]
        if not filas: continue
        out.append(f"\n## {titulo}\n\n| Fichero | Qué hace |\n|---|---|")
        for a, b in filas: out.append(f"| `{a}` | {b.replace('|', '/')} |"); n += 1
    os.makedirs(DIR, exist_ok=True); open(os.path.join(DIR, "guia_app.md"), "w", encoding="utf-8").write("\n".join(out) + "\n"); return n

def novedades(todos, dias=7):
    """data/cronista/novedades.md: lo de los últimos `dias` días por área (sin los commits automáticos)."""
    corte = dt.datetime.now(TZ) - dt.timedelta(days=dias); por = {}
    for c in todos:
        if c["auto"] or _f(c["fecha"]) < corte: continue
        for a in _areas(c["ficheros"]): por.setdefault(a, []).append(c)
    out = [f"# Novedades de los últimos {dias} días (para Jesús)\n\nEscrito por el Cronista el {dt.datetime.now(TZ):%d/%m/%Y %H:%M}. Para ponerlo al día en tu ordenador: `powershell -File tools\\sincronizar.ps1` y reinicia el buscador.\n"]
    for a, cs in sorted(por.items(), key=lambda x: -len(x[1])):
        out.append(f"\n## {a}\n")
        for c in cs: out.append(f"- **{_f(c['fecha']):%d/%m}** {c['titulo']}" + (f"\n  {c['cuerpo'][:400]}" if c["cuerpo"] else ""))
    os.makedirs(DIR, exist_ok=True); open(os.path.join(DIR, "novedades.md"), "w", encoding="utf-8").write("\n".join(out) + "\n"); return sum(len(v) for v in por.values())

def en_curso():
    """Lo que se está haciendo y aún no tiene commit (Fernando, 6 nov: «que vaya pensando y anotando todo»): data/cronista/en_curso.md, que se reescribe entero cada vez (no se acumula), con los ficheros
    tocados por áreas y las líneas cambiadas, más las notas a mano de data/cronista/notas.md (lo que se decidió y por qué, que un commit no cuenta)."""
    try: st = _git("status", "--porcelain")
    except Exception: return 0
    fs = []
    for ln in str(st).splitlines():
        p = ln[3:].strip().strip('"')
        if p and not p.startswith(("data/", ".secrets/", "notas/")) and not p.endswith((".pyc", ".log")): fs.append(p)
    try: stat = {m.group(3): (m.group(1), m.group(2)) for m in re.finditer(r"^(\S+)\t(\S+)\t(.+)$", str(_git("diff", "HEAD", "--numstat")), re.M)}
    except Exception: stat = {}
    nota = ""
    try: nota = open(os.path.join(DIR, "notas.md"), encoding="utf-8").read().strip()
    except OSError: pass
    L = [f"# En curso (sin commit) · actualizado {dt.datetime.now(TZ):%d/%m/%Y %H:%M}", ""]
    if nota: L += ["## Notas del día (lo que se ha decidido y por qué)", "", nota, ""]
    if fs:
        L += [f"## Ficheros tocados sin commit ({len(fs)})", ""]
        for area in dict.fromkeys(a for f in fs for a in (_areas([f]) or ["Otros"])):
            L.append(f"**{area}**: " + ", ".join(f"`{f}`" + (f" (+{stat[f][0]} −{stat[f][1]})" if f in stat else " (nuevo)") for f in fs if area in (_areas([f]) or ["Otros"])))
    else: L.append("Nada sin commit.")
    os.makedirs(DIR, exist_ok=True); open(os.path.join(DIR, "en_curso.md"), "w", encoding="utf-8").write("\n".join(L) + "\n"); return len(fs)

def escribir():
    """Escribe lo que falte: las entradas de los commits nuevos y, si cambió código, la guía de la app. Devuelve el estado."""
    e = load(ESTADO, {}) or {}; ultimo = e.get("ultimo")
    cs = commits(ultimo if ultimo and _git("cat-file", "-t", ultimo).strip() == "commit" else None); nuevos = [c for c in cs if not c["auto"]]; auto = len(cs) - len(nuevos)
    os.makedirs(DIR, exist_ok=True); ruta = os.path.join(DIR, "diario.md")
    if not os.path.exists(ruta): open(ruta, "w", encoding="utf-8").write("# Diario de PokéFinder (lo que va pasando en la app, commit a commit)\n\nEscrito por el Cronista. Los commits automáticos (transcripciones y resúmenes) no entran: solo se cuentan.\n\n")
    if nuevos:
        with open(ruta, "a", encoding="utf-8") as f:
            for c in nuevos: f.write(_entrada(c))
    if cs: e["ultimo"] = cs[-1]["h"]
    e["entradas"] = e.get("entradas", 0) + len(nuevos); e["automaticos"] = e.get("automaticos", 0) + auto
    cambio_codigo = any(re.search(r"\.(py|js)$", f) for c in nuevos for f in c["ficheros"])
    if cambio_codigo or not os.path.exists(os.path.join(DIR, "guia_app.md")): e["modulos"] = guia_app()
    if nuevos or not os.path.exists(os.path.join(DIR, "novedades.md")): e["novedades"] = novedades(commits(None, 400))
    e["hojas"] = e.get("entradas", 0) + (e.get("modulos", 0) // 6) + (1 if os.path.exists(os.path.join(DIR, "novedades.md")) else 0)      # lo que se amontona junto a su mesa
    if nuevos: e["ultima"] = nuevos[-1]["titulo"][:90]; e["ultima_t"] = dt.datetime.now(TZ).isoformat(timespec="minutes")
    try: e["en_curso"] = en_curso()
    except Exception as ex: print("cronista en_curso:", ex)
    e["beat"] = dt.datetime.now(TZ).timestamp(); save(ESTADO, e); return e

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    e = load(ESTADO, {}) or {} if "--estado" in sys.argv else escribir()
    print({k: e.get(k) for k in ("entradas", "automaticos", "modulos", "hojas", "ultima", "ultima_t")})
