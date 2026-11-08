"""El Cartero de la Oficina (Jesús, 7 de noviembre de 2026: "el cartero coge toda la información y cuando yo le diga enviar, se la envía a Fernando
Íñiguez, y que será más fácil para él integrarla dentro de su programa").

Dos pasos, los dos a mano desde la Oficina (pulsando al Cartero):
  1. «Preparar paquete»: recoge lo que han producido los agentes (los ficheros de datos que cada proceso declara en oficina_procesos.py, «datos»)
     y lo mete en UN fichero: buzon/<rama>/<AAAA-MM-DD_HHMM>.json.gz. Solo texto (JSON, Markdown, TXT); nada de .secrets/, ni bases binarias
     (parquet, duckdb), ni ficheros de más de 3 MB. De las carpetas y patrones con muchos ficheros solo van los más nuevos.
  2. «Enviar a Fernando»: sube ESE fichero (y nada más) en la rama de este ordenador (git commit -- <fichero>, como compartir.py) a
     origin (el GitHub de Fernando: la acción lo fusiona en main) y, si existe, al remoto «compartido» (el GitHub de Jesús).

Formato del paquete (pensado para que el programa de Fernando lo lea sin conocer el de Jesús):
  {"formato": "pokefinder-buzon/1", "de": "<rama>", "creado": "AAAA-MM-DDTHH:MM", "agentes": {
      "<id del proceso>": {"nombre": "...", "grupo": "...", "archivos": {"data/...json": <contenido JSON ya leído> | "texto", ...}}}}
Para leerlo: json.load(gzip.open(fichero, "rt", encoding="utf-8")). Hay una guía en buzon/LEEME.md.
Estado en data/state/cartero.json (último paquete y último envío)."""
import glob, gzip, json, os, subprocess, time
from common import P, ROOT

TEXTO = (".json", ".md", ".txt", ".csv")
MAX_FICHERO = 3 * 1024 * 1024
MAX_PAQUETE = 4_500_000          # comprimido: sincronizar.ps1 y antes_de_subir.py no dejan subir más de 5 MB
POR_CARPETA = 12                  # de una carpeta o patrón, los N ficheros más nuevos
ESTADO = P("state", "cartero.json")

def _git(*a, timeout=120):
    return subprocess.run(["git", "-C", ROOT, *a], capture_output=True, text=True, encoding="utf-8", timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

def rama():
    try: return _git("config", "pokefinder.rama").stdout.strip() or "sin-rama"
    except Exception: return "sin-rama"

def estado():
    try:
        with open(ESTADO, encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError): return {}

def _guardar_estado(**k):
    s = estado(); s.update(k); os.makedirs(os.path.dirname(ESTADO), exist_ok=True)
    with open(ESTADO, "w", encoding="utf-8") as f: json.dump(s, f, ensure_ascii=False, indent=1)

def _ficheros(patron):
    """Lo que hay detrás de un «datos» de oficina_procesos: un fichero, una carpeta (acaba en /) o un patrón con *. AAAA-MM-DD = el más nuevo."""
    patron = patron.replace("AAAA-MM-DD", "*")
    if not (patron.startswith("data/") or patron.startswith("compartido/")) or ".secrets" in patron: return []
    if patron.startswith("data/app/jobs"): return []      # trabajos a medias del motor: no son un resultado
    ruta = os.path.join(ROOT, patron)
    if patron.endswith("/"): fs = [os.path.join(dp, f) for dp, _, fn in os.walk(ruta) for f in fn]
    elif "*" in patron: fs = glob.glob(ruta)
    else: fs = [ruta] if os.path.isfile(ruta) else []
    fs = [f for f in fs if f.lower().endswith(TEXTO) and os.path.getsize(f) <= MAX_FICHERO]
    return sorted(fs, key=os.path.getmtime, reverse=True)[:POR_CARPETA]

def _busqueda_terminada(v):
    """De las búsquedas solo va el FINAL: terminada («done»), con resultados y hecha aquí (no las que vinieron de Fernando: import_source)."""
    return isinstance(v, dict) and v.get("status") == "done" and not v.get("import_source") and bool(v.get("listings"))

import re, unicodedata

def _clave(t):
    """Para comparar búsquedas de los dos: sin tildes, en minúsculas y solo letras y números («Charizard Gold Star» = «charizard-gold-star»)."""
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", t)

def _lo_que_ya_tiene_fernando(yo):
    """Lo que Fernando ya tiene, mirado en su GitHub (origin/main y origin/<yo>, sin tocar la carpeta): sus búsquedas compartidas (busquedas/*.json que no subió este
    ordenador) y los anuncios que ya le mandó este Cartero en paquetes anteriores (buzon/<yo>/). Devuelve ({clave de búsqueda: fichero}, {id de anuncio}, {url})."""
    busq, ids, urls = {}, set(), set()
    try: _git("fetch", "-q", "origin", timeout=180)
    except Exception: pass
    yo_nombre = _git("config", "user.name").stdout.strip()
    for ref in ("origin/main", f"origin/{yo}"):
        if _git("rev-parse", "--verify", "-q", ref).returncode: continue
        for path in _git("ls-tree", "-r", "--name-only", ref, "--", "busquedas/", f"buzon/{yo}/").stdout.split():
            if path.startswith("busquedas/") and path.endswith(".json"):
                if yo_nombre and _git("log", "-1", "--format=%an", ref, "--", path).stdout.strip() == yo_nombre: continue      # la subí yo: no es de Fernando
                try: d = json.loads(_git("show", f"{ref}:{path}").stdout)
                except Exception: continue
                for k in (d.get("id"), d.get("query"), d.get("label"), d.get("group")):
                    if _clave(k): busq.setdefault(_clave(k), path)
                for l in d.get("listings") or []:
                    if l.get("id"): ids.add(l["id"])
                    if l.get("url"): urls.add(l["url"])
            elif path.endswith(".json.gz"):
                try:
                    raw = subprocess.run(["git", "-C", ROOT, "show", f"{ref}:{path}"], capture_output=True, timeout=120).stdout
                    d = json.loads(gzip.decompress(raw).decode("utf-8"))
                except Exception: continue
                for b in d.get("busquedas") or []:
                    for l in b.get("anuncios_nuevos") or []:
                        if l.get("id"): ids.add(l["id"])
                        if l.get("url"): urls.add(l["url"])
    return busq, ids, urls

def _cruzar(busquedas, yo):
    """Cada búsqueda terminada de aquí, frente a lo que Fernando ya tiene: «nueva» o «repetida» (la misma carta o colección que ya buscó él),
    y sus anuncios separados en nuevos para él y los que ya tiene (de esa u otra búsqueda, o mandados antes por el Cartero)."""
    suyas, ids, urls = _lo_que_ya_tiene_fernando(yo)
    out = []
    for rel, d in busquedas:
        coincide = next((suyas[_clave(k)] for k in (d.get("id"), d.get("query"), d.get("label"), d.get("group")) if _clave(k) in suyas), None)
        nuevos, ya = [], []
        for l in d.get("listings") or []:
            (ya if (l.get("id") in ids or l.get("url") in urls) else nuevos).append(l)
        out.append({"id": d.get("id"), "label": d.get("label"), "query": d.get("query"), "kind": d.get("kind"), "group": d.get("group"),
                    "terminada": d.get("updated") or d.get("created"), "fichero": rel,
                    "estado": "repetida" if coincide else "nueva", "coincide_con": coincide,
                    "anuncios_total": len(d.get("listings") or []), "anuncios_nuevos": nuevos, "anuncios_que_ya_tiene": [l.get("id") for l in ya]})
    return out

def preparar():
    import oficina_procesos as R
    agentes, total, n, vistos, busquedas = {}, 0, 0, set(), []
    for p in R.PROCESOS:
        arch = {}
        for patron in p.get("datos") or []:
            for f in _ficheros(patron):
                rel = os.path.relpath(f, ROOT).replace("\\", "/")
                if rel in arch or rel in vistos: continue
                try:
                    with open(f, encoding="utf-8") as fh: txt = fh.read()
                except (OSError, UnicodeDecodeError): continue
                if total + len(txt) > MAX_PAQUETE * 6: break           # el JSON se comprime ~6 veces: así no se pasa de 5 MB
                try: v = json.loads(txt) if rel.endswith(".json") else txt
                except ValueError: v = txt
                vistos.add(rel)
                if rel.startswith("data/app/searches/"):      # las búsquedas van aparte, cruzadas con lo de Fernando
                    if _busqueda_terminada(v): busquedas.append((rel, v)); n += 1
                    continue
                arch[rel] = v; total += len(txt); n += 1
        if arch: agentes[p["id"]] = {"nombre": p["nombre"], "grupo": p.get("grupo"), "archivos": arch}
    r = rama(); creado = time.strftime("%Y-%m-%dT%H:%M")
    cruce = _cruzar(busquedas, r)
    preguntas = []      # los informes del jefe (pestaña ❓ Preguntas): orden, desglose, respuesta, cifras, tablas y gráficas
    carpeta_j = P("jefe", "tareas")
    if os.path.isdir(carpeta_j):
        for fn in sorted(os.listdir(carpeta_j)):
            try:
                with open(os.path.join(carpeta_j, fn), encoding="utf-8") as fh: t = json.load(fh)
            except (OSError, ValueError): continue
            if t.get("resultado"): preguntas.append(t)
    resumen = {"busquedas": len(cruce), "nuevas": sum(b["estado"] == "nueva" for b in cruce), "repetidas": sum(b["estado"] == "repetida" for b in cruce),
               "anuncios_nuevos": sum(len(b["anuncios_nuevos"]) for b in cruce), "anuncios_que_ya_tiene": sum(len(b["anuncios_que_ya_tiene"]) for b in cruce),
               "agentes": len(agentes), "ficheros": n, "preguntas": len(preguntas)}
    if not cruce and not agentes and not preguntas: return {"ok": False, "mensaje": "No hay nada terminado que enviar todavía"}
    carpeta = os.path.join(ROOT, "buzon", r); os.makedirs(carpeta, exist_ok=True)
    nombre = time.strftime("%Y-%m-%d_%H%M") + ".json.gz"; destino = os.path.join(carpeta, nombre)
    datos = gzip.compress(json.dumps({"formato": "pokefinder-buzon/3", "de": r, "creado": creado, "resumen": resumen, "busquedas": cruce, "preguntas": preguntas, "agentes": agentes},
                                     ensure_ascii=False).encode("utf-8"))
    tam = len(datos)      # medido en memoria: en una carpeta de Google Drive el tamaño del fichero recién escrito puede salir 0 un momento
    if tam > 5 * 1024 * 1024: return {"ok": False, "mensaje": f"El paquete salía de {tam // 1048576} MB (máximo 5): no se ha guardado"}
    with open(destino, "wb") as f: f.write(datos)
    rel = f"buzon/{r}/{nombre}"
    _guardar_estado(paquete=rel, creado=creado, ficheros=n, agentes=len(agentes), kb=tam // 1024, enviado=False, resumen=resumen)
    return {"ok": True, "paquete": rel, "ficheros": n, "agentes": len(agentes), "kb": tam // 1024, "resumen": resumen,
            "mensaje": (f"Paquete listo ({tam // 1024} KB): {resumen['busquedas']} búsquedas terminadas — {resumen['nuevas']} nuevas para Fernando y {resumen['repetidas']} que él ya tenía; "
                        f"{resumen['anuncios_nuevos']} anuncios nuevos para él ({resumen['anuncios_que_ya_tiene']} ya los tiene), {len(preguntas)} informes de Preguntas y {len(agentes)} agentes con sus datos.")}

def _commit_solo(rel, base, mensaje):
    """Un commit que es «base» + los ficheros rel (uno o una lista), y nada más (índice aparte: no toca la carpeta ni la rama de trabajo). Devuelve su id o None."""
    import tempfile
    idx = os.path.join(tempfile.gettempdir(), f"cartero-index-{os.getpid()}")
    env = {**os.environ, "GIT_INDEX_FILE": idx}
    run = lambda *a, entrada=None: subprocess.run(["git", "-C", ROOT, *a], capture_output=True, text=True, encoding="utf-8", env=env, input=entrada, timeout=120,
                                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        if run("read-tree", base).returncode: return None
        for fr in ([rel] if isinstance(rel, str) else rel):
            blob = run("hash-object", "-w", "--", fr).stdout.strip()
            if not blob or run("update-index", "--add", "--cacheinfo", f"100644,{blob},{fr}").returncode: return None
        arbol = run("write-tree").stdout.strip()
        c = run("commit-tree", arbol, "-p", base, "-F", "-", entrada=mensaje)
        return c.stdout.strip() if c.returncode == 0 and c.stdout.strip() else None
    finally:
        try: os.remove(idx)
        except OSError: pass

def enviar(adjuntos=None):
    """A Fernando (origin) le llega UN commit encima de su rama <rama> con SOLO el paquete: ni código ni nada más de esta carpeta.
    A tu GitHub (compartido), además, se guarda en tu rama de trabajo como un commit normal."""
    s = estado(); rel = s.get("paquete")
    if not rel or not os.path.exists(os.path.join(ROOT, rel)): return {"ok": False, "mensaje": "No hay paquete: pulsa antes «Preparar paquete»"}
    if s.get("enviado"): return {"ok": True, "mensaje": "Este paquete ya se envió"}
    r = rama()
    if r == "sin-rama": return {"ok": False, "mensaje": "Falta decir la rama de este ordenador (git config pokefinder.rama jesus)"}
    adjuntos = [a for a in (adjuntos or []) if os.path.isfile(os.path.join(ROOT, a)) and a.lower().endswith(".md")]      # solo documentos, nunca código
    mensaje = f"Cartero: paquete de {r} ({s.get('creado')})\n\nSolo datos de los agentes: {rel}." + (f" Con: {', '.join(adjuntos)}." if adjuntos else "") + " Formato en buzon/LEEME.md."
    salida, ok = [], False
    remotos = _git("remote").stdout.split()
    if "origin" in remotos:
        f = _git("fetch", "-q", "origin", timeout=180)
        base = next((b for b in (f"origin/{r}", "origin/main") if _git("rev-parse", "--verify", "-q", b).returncode == 0), None)
        sha = _commit_solo([rel] + adjuntos, base, mensaje) if base and f.returncode == 0 else None
        if sha:
            p = _git("push", "-q", "origin", f"{sha}:refs/heads/{r}", timeout=300)
            ok = p.returncode == 0; salida.append(("✓" if ok else "✗") + " Fernando")
        else: salida.append("✗ Fernando (no se pudo preparar el envío)")
    if "compartido" in remotos and _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == r:
        _git("add", "-f", "--", rel, *adjuntos); _git("commit", "-q", "-m", mensaje, "--", rel, *adjuntos)
        p = _git("push", "-q", "compartido", r, timeout=300); salida.append(("✓" if p.returncode == 0 else "✗") + " tu GitHub")
    if ok:
        _guardar_estado(enviado=True, enviado_cuando=time.strftime("%Y-%m-%d %H:%M"))
        try:
            import sys; sys.path.insert(0, os.path.join(ROOT, "tools")); from avisar import avisar
            avisar(f"Paquete del cartero enviado: {rel}", "PokeFinder: paquete para Fernando", equipo=True)
        except Exception: pass
    return {"ok": ok, "mensaje": ("Enviado: " if ok else "No se pudo enviar: ") + ", ".join(salida) + f" ({rel})"}
