"""Lo que lee eBay una vez, no lo lee el otro (owner, 3 November 2026: "con que uno haga la foto de mercado y estados no lo tiene que hacer el otro... el primero que lo haga, que se suba solo").
Fernando and Jesús see the same public eBay listings and the same seller-declared card condition, but each spends his own 5,000 calls a day. The FIRST one to read something publishes it in the repository
(compartido/ebay/<day>-<branch>.json.gz: the day's snapshot; compartido/estados/<day>-<branch>.json.gz: the card conditions read that day) and the other one imports it instead of asking eBay.
- Reading: «git fetch origin main» and «git show origin/main:<file>»: nothing is merged, the working folder is not touched.
- Publishing: ONLY that file is committed (git commit -- <file>) and pushed from the owner's own branch (the GitHub Action merges it into main); whatever else is being edited is never included.
- One file per person and day, so two people publishing at once never collide in git. Nothing here ever raises: a failure is written to data/state/compartir.log and the computer just asks eBay itself.
Needs `git config pokefinder.rama <fernando|jesus>` (tools/sincronizar.ps1 sets it). The photo is only imported if its query is the same one this computer would ask (same card, same words)."""
import gzip, json, os, re, subprocess, sys, threading, time
from common import P, ROOT

SUB = {"foto": "ebay", "estados": "estados"}

def _log(t):
    try:
        os.makedirs(P("state"), exist_ok=True)
        with open(P("state", "compartir.log"), "a", encoding="utf-8") as f: f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {t}\n")
    except OSError: pass

def _git(*a, timeout=90, entrada=None):
    return subprocess.run(["git", "-C", ROOT, *a], capture_output=True, timeout=timeout, input=entrada, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

_rama_c = {"t": 0.0, "v": ""}
def rama():
    """La rama de este ordenador (git config pokefinder.rama). Se guarda 60 s: la Oficina la pedía 7 veces por cada plano, cada una lanzando un proceso de git (unos 0,4 s en total)."""
    if time.time() - _rama_c["t"] < 60: return _rama_c["v"]
    try: v = _git("config", "pokefinder.rama").stdout.decode().strip()
    except Exception: v = ""
    _rama_c.update(t=time.time(), v=v); return v

def disponible(): return bool(rama()) and os.path.isdir(os.path.join(ROOT, ".git"))

_solo_c = {"t": 0.0, "v": False}
def solo_cartero():
    """git config pokefinder.fernando solo-cartero (Jesús, 7 nov 2026: "no des ningún output a Fernando de ningún tipo que no sea el final de una búsqueda"):
    este ordenador NO publica nada en el GitHub del otro (ni foto, ni estados, ni lotes) y no reparte el trabajo a medias: lo hace todo él. Lo único que sale
    hacia el otro es el paquete del Cartero (cartero.py), cuando se pulsa «Enviar». Sí sigue LEYENDO lo que el otro haya subido."""
    if time.time() - _solo_c["t"] < 60: return _solo_c["v"]
    try: v = _git("config", "pokefinder.fernando").stdout.decode().strip() == "solo-cartero"
    except Exception: v = False
    _solo_c.update(t=time.time(), v=v); return v

def _traer():
    """Brings origin/main up to date (a fetch only). False when it cannot be reached."""
    try:
        r = _git("fetch", "--quiet", "origin", "main", timeout=60)
        if r.returncode: _log("fetch falló: " + r.stderr.decode(errors="replace")[:150]); return False
        return True
    except Exception as e: _log(f"fetch falló: {type(e).__name__}"); return False

def _ajenos(sub, dia):
    """[(file path in origin/main, who)] published by the OTHER people for that day."""
    yo = rama()
    try: l = _git("ls-tree", "-r", "--name-only", "origin/main", "--", f"compartido/{sub}/").stdout.decode().split()
    except Exception: return []
    out = []
    for p in l:
        m = re.match(rf"compartido/{sub}/{re.escape(dia)}-([\w.-]+)\.json\.gz$", p)
        if m and m.group(1) != yo: out.append((p, m.group(1)))
    return out

def _leer(path):
    r = _git("show", f"origin/main:{path}");
    if r.returncode: return None
    try: return json.loads(gzip.decompress(r.stdout).decode("utf-8"))
    except (OSError, ValueError): return None

def foto_ajena(dia):
    """The snapshot another person published for that day ({"quien", "snap"}), or None. Several: the one with most listings."""
    if not disponible() or not _traer(): return None
    mejor = None
    for p, quien in _ajenos("ebay", dia):
        s = _leer(p)
        if s and s.get("tracks"):
            n = sum(len(t.get("items") or {}) for t in s["tracks"].values())
            if not mejor or n > mejor[0]: mejor = (n, {"quien": quien, "snap": s})
    return mejor and mejor[1]

def estados_ajenos(dia_desde=None):
    """{item id: condition} published by the others (every day: a listing read last week is still read), only what origin/main has. Never raises."""
    if not disponible() or not _traer(): return {}
    yo = rama(); out = {}
    try: l = _git("ls-tree", "-r", "--name-only", "origin/main", "--", "compartido/estados/").stdout.decode().split()
    except Exception: return {}
    for p in sorted(l):
        m = re.match(r"compartido/estados/\d{4}-\d{2}-\d{2}-([\w.-]+)\.json\.gz$", p)
        if not m or m.group(1) == yo: continue
        d = _leer(p)
        if isinstance(d, dict): out.update(d)
    return out

LOTE = P("state", "aviso_lote.json"); LOTE_MIN = 120; LOTE_MAX = 15
def lote_anadir(clave, titulo):
    """Fernando, 6 nov: «que no me lleguen cada 5 minutos». Las transcripciones no avisan una a una: se apuntan y salen juntas (lote_vaciar) cuando la más antigua lleva LOTE_MIN minutos o hay LOTE_MAX."""
    from common import load, save
    d = load(LOTE, {}) or {}; d.setdefault(clave, []).append({"t": time.time(), "x": re.sub(r"\s+", " ", str(titulo)).strip()[:80]}); save(LOTE, d)

def lote_vaciar(forzar=False):
    """Manda los lotes que toca. 'equipo' va al tema del equipo (con la firma del dueño), 'tema' a tu tema. Nunca lanza."""
    try:
        from common import load, save
        sys.path.insert(0, os.path.join(ROOT, "tools")); from avisar import avisar
        d = load(LOTE, {}) or {}
        for clave, xs in list(d.items()):
            if not xs or not (forzar or len(xs) >= LOTE_MAX or time.time() - xs[0]["t"] >= LOTE_MIN * 60): continue
            tit = [x["x"] for x in xs]; cuerpo = "; ".join(tit[:5]) + (f" … y {len(tit) - 5} más" if len(tit) > 5 else "")
            ok = avisar(f"Transcritas {len(tit)} desde las {time.strftime('%H:%M', time.localtime(xs[0]['t']))}: {cuerpo}. " + ("No hace falta repetirlas: se importan solas." if clave == "equipo" else "Míralas en Mercado → Podcasts."),
                        "PokéFinder · reparto" if clave == "equipo" else "Podcasts transcritos", equipo=(clave == "equipo"))
            if ok: d[clave] = []
        save(LOTE, d)
    except Exception as e: _log(f"lote de avisos falló: {type(e).__name__}")

def avisar_equipo(texto):
    """A notice to the team topic, signed with the owner's name (tools/avisar.py): «who did what today», so the other one does not repeat it (owner, 3 November 2026). Never raises."""
    if str(texto).startswith("Transcrito y subido"):      # las transcripciones van en lote (una cada 5 minutos llenaban el móvil)
        try: lote_anadir("equipo", re.sub(r"^Transcrito y subido\s*(\([^)]*\))?:?\s*", "", str(texto)).split(". No hace falta")[0]); return
        except Exception as e: _log(f"lote falló: {type(e).__name__}")
    try:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        from avisar import avisar
        avisar(texto, "PokéFinder · reparto", equipo=True)
    except Exception as e: _log(f"aviso de equipo falló: {type(e).__name__}")

def _publicar(sub, dia, datos, texto, aviso="", esperar=True):
    """Writes compartido/<sub>/<day>-<branch>.json.gz and pushes only it, from the owner's branch. Never raises. It WAITS by default: the callers are the short-lived processes of the photo and the
    conditions, and a background (daemon) thread dies with its process before the push (4 November 2026: today's photo was never shared because mercado.py ended first)."""
    def hacer():
        try:
            if not disponible(): return
            if solo_cartero(): _log(f"no se publica {sub}/{dia}: en este ordenador solo envía el Cartero"); return
            yo = rama(); ahora = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.decode().strip()
            if ahora != yo: _log(f"no se publica: la rama actual es {ahora} y no {yo}"); return
            rel = f"compartido/{sub}/{dia}-{yo}.json.gz"; ruta = os.path.join(ROOT, *rel.split("/"))
            os.makedirs(os.path.dirname(ruta), exist_ok=True)
            with open(ruta, "wb") as f: f.write(gzip.compress(json.dumps(datos, ensure_ascii=False, separators=(",", ":")).encode("utf-8")))
            _git("add", "--", rel)
            c = _git("-c", f"user.name=PokeFinder ({yo})", "-c", f"user.email={yo}@pokefinder.local", "commit", "-q", "-m", f"{texto} ({yo})", "--", rel)
            if c.returncode: _log("commit falló: " + (c.stdout + c.stderr).decode(errors="replace")[:200]); return
            p = _git("push", "-q", "origin", "HEAD", timeout=120)
            _log(f"publicado {rel}" if not p.returncode else "push falló: " + p.stderr.decode(errors="replace")[:200])
            if not p.returncode and aviso: avisar_equipo(aviso)
        except Exception as e: _log(f"publicar falló: {type(e).__name__}: {str(e)[:100]}")
    if esperar: hacer()
    else: threading.Thread(target=hacer, daemon=True).start()

def publicar_foto(snap, claves):
    """snap: the snapshot just taken; claves: the tracks THIS computer asked eBay for (not the imported ones)."""
    tr = {k: v for k, v in (snap.get("tracks") or {}).items() if k in claves and v.get("items")}
    if tr:
        n = sum(len(v["items"]) for v in tr.values())
        _publicar("ebay", snap["date"], {**{k: v for k, v in snap.items() if k != "tracks"}, "tracks": tr}, f"Foto de eBay {snap['date']}",
                  f"Foto de eBay de {snap['date']} hecha y subida: {len(tr)} cartas, {n} anuncios. No hace falta repetirla: se importa sola.")

def publicar_estados(dia, nuevos):
    """nuevos: {item id: condition} read today by this computer."""
    if nuevos: _publicar("estados", dia, nuevos, f"Estados de cartas leidos {dia}", f"Estados de cartas leídos y subidos ({len(nuevos)} anuncios de eBay): no hace falta volver a pedirlos.")


# ---------------------------------------------------------------- reparto del trabajo entre los dos (owner, 4 November 2026: "cómo gestionaremos Jesús y yo que no se transcriba dos veces, fotos a distintas horas...")
# Tres reglas, sin servidor ni cola: (1) cada cosa tiene un DUEÑO que sale de su identificador, igual en los dos ordenadores sin hablar entre ellos (la mitad para cada uno: cada uno gasta sus propios
# límites de Groq y de las API de precios, así que entre los dos se hace el doble); (2) lo que uno termina lo sube a git (compartido/<qué>/<nombre>-<quién>.json.gz) y el otro lo IMPORTA en vez de repetirlo;
# (3) lo que es del otro y no ha llegado pasado un tiempo, lo hace el que lo vea (por si el otro tiene el ordenador apagado). Sin rama configurada (git config pokefinder.rama) no hay reparto: todo es de uno.
import hashlib

def otro():
    if solo_cartero(): return ""      # sin reparto: este ordenador lo hace todo (no publica su mitad)
    yo = rama(); return {"fernando": "jesus", "jesus": "fernando"}.get(yo, "")

def dueno(clave):
    """«fernando» o «jesus»: el dueño de una cosa por el MD5 de su clave (estable entre ordenadores). Vacío si no hay reparto (rama sin configurar o compañero desconocido)."""
    o = otro()
    if not o: return ""
    return sorted([rama(), o])[int(hashlib.md5(str(clave).encode("utf-8")).hexdigest(), 16) % 2]

def es_mio(clave):
    d = dueno(clave); return not d or d == rama()

_fetch = {"t": 0}
def ajenos_de(sub, cada=300):
    """{nombre: (ruta en origin/main, quién)} de lo que el OTRO ha subido a compartido/<sub>/ (de cualquier día). El fetch se repite como mucho cada 5 minutos. Nunca lanza."""
    if not disponible(): return {}
    if time.time() - _fetch["t"] > cada:
        if not _traer(): return {}
        _fetch["t"] = time.time()
    yo = rama(); out = {}
    try: l = _git("ls-tree", "-r", "--name-only", "origin/main", "--", f"compartido/{sub}/").stdout.decode().split()
    except Exception: return {}
    for p in l:
        m = re.match(rf"compartido/{re.escape(sub)}/(.+)-([a-z0-9_.]+)\.json\.gz$", p)
        if m and m.group(2) != yo: out[m.group(1)] = (p, m.group(2))
    return out

def leer(path): return _leer(path)

def publicar_item(sub, nombre, datos, texto, aviso=""):
    """Sube compartido/<sub>/<nombre>-<yo>.json.gz (solo ese fichero, desde tu rama) y, si hay aviso, lo manda al tema de equipo. Nunca lanza."""
    _publicar(sub, nombre, datos, texto, aviso)


def publicar_lote(items, texto, aviso=""):
    """items: [(sub, nombre, datos)]. Escribe todos los compartido/<sub>/<nombre>-<yo>.json.gz y los sube en UN solo commit y UN push (para subir de golpe lo que ya tenías). Devuelve cuántos subió. Nunca lanza."""
    try:
        if not disponible() or not items: return 0
        if solo_cartero(): _log("no se publica el lote: en este ordenador solo envía el Cartero"); return 0
        yo = rama(); ahora = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.decode().strip()
        if ahora != yo: _log(f"no se publica: la rama actual es {ahora} y no {yo}"); return 0
        rels = []
        for sub, nombre, datos in items:
            rel = f"compartido/{sub}/{nombre}-{yo}.json.gz"; ruta = os.path.join(ROOT, *rel.split("/")); os.makedirs(os.path.dirname(ruta), exist_ok=True)
            with open(ruta, "wb") as f: f.write(gzip.compress(json.dumps(datos, ensure_ascii=False, separators=(",", ":")).encode("utf-8")))
            rels.append(rel)
        _git("add", "--", *rels)
        c = _git("-c", f"user.name=PokeFinder ({yo})", "-c", f"user.email={yo}@pokefinder.local", "commit", "-q", "-m", f"{texto} ({yo})", "--", *rels)
        if c.returncode: _log("commit del lote falló: " + (c.stdout + c.stderr).decode(errors="replace")[:200]); return 0
        p = _git("push", "-q", "origin", "HEAD", timeout=180)
        _log(f"publicado lote de {len(rels)}" if not p.returncode else "push del lote falló: " + p.stderr.decode(errors="replace")[:200])
        if not p.returncode and aviso: avisar_equipo(aviso)
        return 0 if p.returncode else len(rels)
    except Exception as e: _log(f"publicar lote falló: {type(e).__name__}: {str(e)[:100]}"); return 0
