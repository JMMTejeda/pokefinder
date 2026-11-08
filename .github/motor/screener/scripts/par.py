"""El «par»: el ordenador del compañero, conectado por una red privada (Fernando, 5 de noviembre de 2026: «los trabajadores míos y los de Jesús se comuniquen; varias plantas; que lo que busque yo no lo busque él»).
Cada ordenador sigue siendo independiente (sus claves, su cupo de eBay, sus datos). Lo que añade este módulo, todo APAGADO hasta que se configure:
- Un par de endpoints de SOLO LECTURA (/api/par/...) con los que el otro ordenador ve tu plano de la Oficina y trae los precios que has leído. Solo contestan a la red privada (Tailscale o este mismo
  ordenador) y con una contraseña común; nunca a internet ni a la wifi de casa.
- Un cliente que pide lo mismo al otro ordenador: su plano (la «Planta 2» de la Oficina) y sus lecturas de precios, que se guardan como si fueran tuyas.
- El reparto del trabajo: cuando el par está activo y responde, cada carta (del Tasador, de la ronda de caza, del barrido de sets) la hace solo su dueño (compartir.dueno, por mitades); si el otro lleva
  más de TOMA_H horas sin contestar, se hace igual. Con el par apagado, todo es tuyo como hasta ahora.
Configuración: .secrets/par.json {"url": "http://100.x.y.z:8800", "token": "contraseña larga y común"} (python tools/poner_clave.py par) y data/par/config.json {"activo": true}. Probar: python tools/probar_par.py.
Guía: COLABORAR-EN-RED.md. Estado en data/par/estado.json."""
import hmac, ipaddress, json, os, time, urllib.error, urllib.parse, urllib.request
from common import P, load, save, ROOT

CONFIG = P("par", "config.json"); ESTADO = P("par", "estado.json"); SECRETO = os.path.join(ROOT, ".secrets", "par.json")
TOMA_H = 6          # horas sin contestar para que el trabajo del otro lo haga el que lo vea
CGNAT = ipaddress.ip_network("100.64.0.0/10")      # el rango que usa Tailscale

def _json(ruta):
    """Lee un JSON a mano, aunque Notepad o PowerShell le hayan puesto la marca BOM; un fichero roto es «sin configurar», nunca un fallo del servidor."""
    try:
        with open(ruta, encoding="utf-8-sig") as f: d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError): return {}

def secreto(): return _json(SECRETO)
def configurado(): s = secreto(); return bool(str(s.get("url") or "").startswith("http") and len(str(s.get("token") or "")) >= 16)
def activo(): return configurado() and bool(_json(CONFIG).get("activo"))
def estado(**kw):
    e = load(ESTADO, {}) or {}
    if kw: e.update(kw); save(ESTADO, e)
    return e

def yo():
    try: import compartir; return compartir.rama() or "yo"
    except Exception: return "yo"

def otro():
    try: import compartir; return compartir.otro() or "el compañero"
    except Exception: return "el compañero"

def vivo(max_min=15): return time.time() - estado().get("ok_t", 0) < max_min * 60

def mio(clave):
    """¿Me toca a mí esta cosa? Sin par activo, sí. Con par activo, solo si soy su dueño o el otro lleva TOMA_H horas sin contestar."""
    if not activo(): return True
    try:
        import compartir
        if compartir.es_mio(clave): return True
    except Exception: return True
    return time.time() - estado().get("ok_t", 0) > TOMA_H * 3600

# ------------------------------------------------------------------ lado servidor: lo que se le enseña al otro ordenador
def autorizado(handler):
    """True solo si la petición viene de la red privada (o de este mismo ordenador) Y lleva la contraseña común. La comparación es de tiempo constante."""
    if not configurado(): return False
    try: ip = ipaddress.ip_address((handler.client_address[0] or "").split("%")[0])
    except ValueError: return False
    if not (ip.is_loopback or ip in CGNAT): return False
    dado = handler.headers.get("X-PF-Token") or ""
    return hmac.compare_digest(dado.encode("utf-8"), str(secreto().get("token")).encode("utf-8"))

def plano_publico():
    """Mi plano de la Oficina para el otro ordenador, sin lo que no hace falta (los avisos de ntfy y sus nombres de tema)."""
    import oficina_hoy
    p = oficina_hoy.plano(); p = json.loads(json.dumps(p, default=str))
    p["ntfy"] = {"channels": [], "checks": [], "failures": []}; p["dueno"] = yo(); p.pop("par", None)
    return p

def referencias_desde(desde=0.0, limite=300):
    """Las fichas de precios (data/referencia/<id>.json) y sus entradas de registro que han cambiado desde `desde` (hora Unix), de la más antigua a la más reciente."""
    import glob
    reg = {x["id"]: x for x in (load(P("referencia", "registro.json"), []) or [])}
    fich = sorted(((os.path.getmtime(f), f) for f in glob.glob(P("referencia", "[0-9]*.json"))), key=lambda x: x[0]); out = []
    for t, f in fich:
        if t <= desde: continue
        pid = os.path.basename(f)[:-5]; d = load(f, None)
        if not d: continue
        h = load(P("referencia", "historial", pid + ".json"), None)
        out.append({"id": pid, "t": t, "ficha": d, "registro": reg.get(pid), "historial": h})
        if len(out) >= limite: break
    return {"de": yo(), "hasta": out[-1]["t"] if out else desde, "cartas": out}

# ------------------------------------------------------------------ lado cliente: pedirle cosas al otro ordenador
def pedir(ruta, params=None, timeout=8):
    """GET al otro ordenador con la contraseña. Devuelve el JSON o lanza ConnectionError con la causa (sin enseñar nunca la contraseña)."""
    s = secreto(); url = str(s.get("url")).rstrip("/") + ruta + (("?" + urllib.parse.urlencode(params)) if params else "")
    req = urllib.request.Request(url, headers={"X-PF-Token": str(s.get("token")), "User-Agent": "PokeFinder-par/1.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: d = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        estado(error=f"HTTP {e.code}", error_t=time.time()); raise ConnectionError(f"el otro ordenador contestó {e.code}" + (" (contraseña distinta o fuera de la red privada)" if e.code in (401, 403) else ""))
    except Exception as e:
        estado(error=type(e).__name__, error_t=time.time()); raise ConnectionError(f"no se llega al otro ordenador ({type(e).__name__})")
    estado(ok_t=time.time(), error=None); return d

_cache = {"t": 0, "plano": None}
def plano_del_par(max_s=15):
    """El plano de la Oficina del otro ordenador (la «Planta 2»). Con el par apagado, o si no contesta, lanza ConnectionError."""
    if not activo(): raise ConnectionError("el par está apagado")
    if _cache["plano"] is None or time.time() - _cache["t"] > max_s: _cache.update(plano=pedir("/api/par/plano", timeout=10), t=time.time())
    return _cache["plano"]

def traer_referencias(limite_rondas=6):
    """Trae las fichas de precios que el otro ha leído desde la última vez y las guarda como tuyas (solo si son más nuevas que las que ya tienes). Devuelve cuántas guardó."""
    if not activo(): return 0
    e = estado(); cursor = float(e.get("cursor", 0)); n = 0
    for _ in range(limite_rondas):
        d = pedir("/api/par/referencias", {"desde": cursor, "limite": 300}, timeout=30); cs = d.get("cartas") or []
        if not cs: break
        reg = load(P("referencia", "registro.json"), []) or []; ids = {x["id"] for x in reg}
        for c in cs:
            pid = str(c["id"]); f = P("referencia", pid + ".json"); mio_ = load(f, None)
            if not mio_ or str(c["ficha"].get("leido") or "") > str(mio_.get("leido") or ""):
                c["ficha"]["de"] = d.get("de"); save(f, c["ficha"]); n += 1
            if c.get("historial") and not load(P("referencia", "historial", pid + ".json"), None): os.makedirs(P("referencia", "historial"), exist_ok=True); save(P("referencia", "historial", pid + ".json"), c["historial"])
            if c.get("registro") and pid not in ids: reg.append(c["registro"]); ids.add(pid)
        save(P("referencia", "registro.json"), reg); cursor = float(d.get("hasta") or cursor); estado(cursor=cursor)
        if len(cs) < 300: break
    estado(traidas=estado().get("traidas", 0) + n, ultima_traida=time.strftime("%Y-%m-%d %H:%M")); return n

def resumen():
    """Lo que la página necesita saber del par: si hay, si está activo, si contesta y cómo se llama."""
    e = estado()
    return {"configurado": configurado(), "activo": activo(), "vivo": vivo(), "nombre": otro().capitalize(), "yo": yo().capitalize(), "error": e.get("error"), "traidas": e.get("traidas", 0), "ultima_traida": e.get("ultima_traida")}

def tick():
    """Lo que el servidor hace cada 10 minutos con el par activo: comprobar que contesta y traer sus precios. Nunca lanza."""
    if not activo(): return
    try: pedir("/api/par/ping", timeout=8); traer_referencias()
    except ConnectionError as e: print("par:", e)
    except Exception as e: print("par:", type(e).__name__, e)
