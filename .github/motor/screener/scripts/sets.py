"""Espacio «Sets» (Fernando, 5 de noviembre de 2026: «un espacio de sets y poder ver todas las cartas de un set y poder buscar por todas las cartas que hay»).
Todos los sets y todas sus cartas (nombre, número, imagen oficial) en inglés y en japonés, desde TCGdex (API pública y abierta, la misma que ya usa carta.py).
pokemontcg.io se probó primero y devolvía errores 500/502 en la lista de sets, así que no se depende de él.
Se baja una vez (~440 peticiones, un par de minutos, en segundo plano, reanuda donde se quedó) y se guarda en data/sets/<idioma>/. Después todo se lee del disco.
  from sets import lista, cartas, buscar, estado, lanzar      -> lo que sirve /api/sets...
Las imágenes se piden a assets.tcgdex.net desde el navegador (no se guardan). TCGdex no da la rareza en el listado: se busca por nombre, número, set y serie.
Los precios NO están aquí: salen de ventas reales (ventas.py), nunca de este catálogo."""
import json, os, threading, time, urllib.parse, urllib.request
from common import P, load, save

DIR = P("sets"); IDIOMAS = ("en", "ja"); API = "https://api.tcgdex.net/v2"
UA = {"user-agent": "PokeFinder/1.0 (personal collection catalog)"}
_lock = threading.Lock(); _cache = {}

def _get(url, intentos=4):
    for i in range(intentos):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60))
        except Exception:
            if i == intentos - 1: raise
            time.sleep(2 * (i + 1))

def _idioma(i): return i if i in IDIOMAS else "en"
def _dir(i): return os.path.join(DIR, _idioma(i))

def estado(**kw):
    p = os.path.join(DIR, "estado.json"); s = load(p, {}) or {}
    if kw: os.makedirs(DIR, exist_ok=True); s.update(kw); save(p, s)
    return s

def lista(idioma="en"):
    """Sets por fecha (nuevos primero), con si sus cartas ya están descargadas."""
    s = load(os.path.join(_dir(idioma), "sets.json"), []) or []
    for x in s: x["bajadas"] = os.path.exists(os.path.join(_dir(idioma), "cartas", x["id"] + ".json"))
    return sorted(s, key=lambda x: x.get("fecha") or "", reverse=True)

def _todas(idioma):
    """Todas las cartas descargadas de un idioma, en memoria (se refresca si cambia el disco)."""
    i = _idioma(idioma); cd = os.path.join(_dir(i), "cartas")
    with _lock:
        mt = os.path.getmtime(cd) if os.path.isdir(cd) else 0
        if _cache.get(i, (None, None))[0] != mt:
            out = []; sets = {x["id"]: x for x in (load(os.path.join(_dir(i), "sets.json"), []) or [])}
            for f in (os.listdir(cd) if os.path.isdir(cd) else []):
                if not f.endswith(".json"): continue
                sid = f[:-5]; s = sets.get(sid, {})
                for c in load(os.path.join(cd, f), []) or []: out.append({**c, "set": sid, "set_nombre": s.get("nombre", sid), "serie": s.get("serie"), "fecha": s.get("fecha")})
            _cache[i] = (mt, out)
        return _cache[i][1]

def _num(n):
    d = "".join(ch for ch in str(n) if ch.isdigit()); return (int(d) if d else 9999, str(n))

def buscar(q="", set_id="", idioma="en", limite=120, desde=0):
    """Busca por nombre, número, set o serie; todas las palabras tienen que aparecer. Devuelve (total, [cartas]); dentro de un set, por número."""
    w = [x for x in (q or "").lower().split() if x]; out = []
    for c in _todas(idioma):
        if set_id and c["set"] != set_id: continue
        h = f"{c['nombre']} {c['numero']} {c['set_nombre']} {c['set']} {c.get('serie') or ''}".lower()
        if all(x in h for x in w): out.append(c)
    out.sort(key=lambda c: _num(c["numero"])) if set_id else out.sort(key=lambda c: ((c.get("fecha") or ""), c["set"], _num(c["numero"])), reverse=True)
    return len(out), out[desde:desde + limite]

def _guardar_set(i, sid):
    d = _get(f"{API}/{i}/sets/{urllib.parse.quote(sid, safe='')}"); serie = (d.get("serie") or {}).get("name"); logo = d.get("logo"); simbolo = d.get("symbol")
    cs = []
    for c in d.get("cards") or []:
        im = c.get("image"); cs.append({"id": c["id"], "nombre": c.get("name") or "", "numero": str(c.get("localId") or ""), "rareza": None, "tipos": [], "artista": None,
                                       "img": f"{im}/low.png" if im else None, "img_grande": f"{im}/high.png" if im else None})
    cd = os.path.join(_dir(i), "cartas"); os.makedirs(cd, exist_ok=True); save(os.path.join(cd, sid + ".json"), cs)
    return {"id": sid, "nombre": d.get("name") or sid, "serie": serie, "fecha": d.get("releaseDate") or "", "cartas": (d.get("cardCount") or {}).get("official"), "total": (d.get("cardCount") or {}).get("total"),
            "codigo": (d.get("abbreviation") or {}).get("official"), "logo": f"{logo}.png" if logo else None, "simbolo": f"{simbolo}.png" if simbolo else None}

def _bajar(forzar=False):
    try:
        estado(corriendo=True, error=None, inicio=time.strftime("%Y-%m-%d %H:%M"), hechos=0, total=0, actual=None)
        listas = {i: _get(f"{API}/{i}/sets") for i in IDIOMAS}; estado(total=sum(len(v) for v in listas.values())); hechos = 0
        for i in IDIOMAS:
            os.makedirs(_dir(i), exist_ok=True); fichas = {x["id"]: x for x in (load(os.path.join(_dir(i), "sets.json"), []) or [])}
            for s in listas[i]:
                sid = s["id"]; hechos += 1
                if not forzar and sid in fichas and os.path.exists(os.path.join(_dir(i), "cartas", sid + ".json")): estado(hechos=hechos); continue
                try: fichas[sid] = _guardar_set(i, sid)
                except Exception as e: estado(ultimo_fallo=f"{i}/{sid}: {type(e).__name__}")
                estado(hechos=hechos, actual=f"{fichas.get(sid, {}).get('nombre', sid)} ({i})")
                if hechos % 10 == 0: save(os.path.join(_dir(i), "sets.json"), list(fichas.values()))
                time.sleep(0.15)
            save(os.path.join(_dir(i), "sets.json"), list(fichas.values()))
        estado(corriendo=False, fin=time.strftime("%Y-%m-%d %H:%M"), actual=None)
    except Exception as e: estado(corriendo=False, error=f"{type(e).__name__}: {str(e)[:120]}")

def lanzar(forzar=False):
    """Empieza la descarga en segundo plano si no está ya en marcha."""
    p = os.path.join(DIR, "estado.json")
    if estado().get("corriendo") and os.path.exists(p) and time.time() - os.path.getmtime(p) < 300: return False
    threading.Thread(target=_bajar, args=(forzar,), daemon=True).start(); return True

if __name__ == "__main__":
    import sys
    if "--bajar" in sys.argv: _bajar("--forzar" in sys.argv); print(estado())
    else: print(estado(), {i: (len(lista(i)), len(_todas(i))) for i in IDIOMAS})
