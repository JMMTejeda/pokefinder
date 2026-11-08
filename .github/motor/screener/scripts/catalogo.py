"""El catálogo: UNA ficha por carta y UNA lista de precios con los mismos campos, vengan de la web que vengan (Fernando, 6 de noviembre de 2026: «hay que hacer un estándar, guardar todo lo que hemos
buscado con los mismos campos para no rehacer búsquedas y que todos se comuniquen»). La norma completa está en ESTANDAR-CARTAS.md.

La idea (de Fernando): cada web ya da a cada carta un NÚMERO de identificación (TCGplayer 86658, Collectr 10000595, SNKRDUNK 93276, PokéWallet = el de TCGplayer…). Dos fichas de webs distintas son la
misma carta solo si COINCIDEN LAS DOS COSAS: el número de identificación (o el nombre+número de carta, si no hay id común) Y el nombre. Un número igual con nombre distinto NO se une: se apunta como conflicto.

Ficha (data/catalogo/cartas.json, por clave «pf-<n>»):
  clave, nombre, numero («105/107»), total, set (texto), idioma («en» | «ja»), rareza, imagen, ids {fuente: id}, enlaces [{fuente, id, como: «id+nombre»|«nombre+numero»|«ancla»}], conflictos [...]
Precio (data/catalogo/precios.jsonl, una línea por dato):
  {k, t (ISO), carta (clave), fuente, id, tipo, estado, edicion, valor, moneda, n, ref}
  tipo:   mercado | ultima_venta | venta_min | venta_max | anuncio_min | tendencia | media_1d | media_7d | media_30d | minimo | mediana_ventas | venta
  estado: «sin_gradear» o «PSA 10», «CGC 9.5», «BGS 9»…  (siempre así escrito)       moneda: USD | EUR | JPY
Uso:  python catalogo.py --ingerir   (idempotente)   --stats   --ficha <fuente> <id>   --precios <fuente> <id>
"""
import argparse, glob, hashlib, json, os, re, sys, time, unicodedata
from common import P, ROOT, load, save

DIR = P("catalogo"); CARTAS = P("catalogo", "cartas.json"); PRECIOS = P("catalogo", "precios.jsonl"); ESTADO = P("state", "catalogo.json")
VACIAS = {"the", "of", "de", "la", "el", "and", "y", "a", "pokemon", "card", "carta", "s"}
NOTAS_ETIQUETA = {"psa10": "PSA 10", "psa9": "PSA 9", "psa8": "PSA 8", "psa7": "PSA 7", "cgc10": "CGC 10", "cgc9_5": "CGC 9.5", "cgc9": "CGC 9", "bgs10": "BGS 10", "bgs9_5": "BGS 9.5", "bgs9": "BGS 9", "tag10": "TAG 10", "ace10": "ACE 10"}

# ---------------------------------------------------------------------------------------------------------------------- normalizar
def _norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower() if not re.search(r"[☆★]", str(s or "")) else unicodedata.normalize("NFKD", str(s).replace("☆", " star ").replace("★", " star ")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9/]+", " ", s)).strip()

def numero_de(texto):
    """«Charizard 004/102 · Base Set» → («4», «102»); «Entei 062/L-P» → («062/l-p», None); sin número → (None, None)."""
    t = str(texto or "")
    m = re.search(r"(?<![\d/])(\d{1,3})\s*/\s*(\d{1,3})(?![\d/])", t)
    if m: return str(int(m.group(1))), str(int(m.group(2)))
    m = re.search(r"\b(\d{1,3}/[A-Za-z][\w-]*)\b", t)
    return (m.group(1).lower(), None) if m else (None, None)

def base_nombre(nombre):
    """El nombre de la carta sin set, rareza ni número: “Flareon 010/110 · Legendary Collection Holo Rare” → «flareon»."""
    t = str(nombre or "").split(" · ")[0]; t = re.sub(r"\([^)]*\)", " ", t); t = re.sub(r"\d{1,3}\s*/\s*[\w-]+", " ", t)
    return _norm(t)

def _toks(n): return {w for w in base_nombre(n).split() if w not in VACIAS and len(w) > 0}

def parece(a, b):
    """¿Son la misma carta? Nombres parecidos (≥ 60 % de las palabras del más corto) Y, si los dos traen número de carta, el mismo."""
    ta, tb = _toks(a["nombre"]), _toks(b["nombre"])
    if not ta or not tb or len(ta & tb) / min(len(ta), len(tb)) < 0.6: return False
    na, nb = a.get("numero") or numero_de(a["nombre"])[0], b.get("numero") or numero_de(b["nombre"])[0]
    na, nb = (numero_de(str(na))[0] or str(na or "").lower() or None), (numero_de(str(nb))[0] or str(nb or "").lower() or None)
    return not (na and nb and na != nb)

# ---------------------------------------------------------------------------------------------------------------------- el catálogo en memoria
class Catalogo:
    def __init__(s):
        s.c = load(CARTAS, {}) or {}; s.idx = {}; s.por_valor = {}; s.n = max([int(k[3:]) for k in s.c if k.startswith("pf-") and k[3:].isdigit()] or [0])
        for k, f in s.c.items():
            for fu, i in (f.get("ids") or {}).items(): s._indexar(k, fu, i)
        s.cambiado = False
    def _indexar(s, clave, fuente, id_):
        s.idx[(fuente, str(id_))] = clave; s.por_valor.setdefault(str(id_), set()).add(clave)

    def registrar(s, fuente, id_, nombre, numero=None, set_=None, idioma=None, imagen=None, rareza=None):
        """Devuelve la clave de la carta de esa web y número. La une a otra ficha solo si coincide el id Y el nombre (o, sin id común, nombre Y número de carta Y idioma)."""
        id_ = str(id_); nombre = str(nombre or "").strip()
        if (fuente, id_) in s.idx:
            f = s.c[s.idx[(fuente, id_)]]; s._completar(f, nombre, numero, set_, idioma, imagen, rareza); return f["clave"]
        num, tot = numero_de(numero) if numero else numero_de(nombre)
        nueva = {"nombre": nombre, "numero": (f"{num}/{tot}" if tot else num), "total": tot, "set": set_, "idioma": idioma, "rareza": rareza, "imagen": imagen}
        destino, como = None, None
        for k in sorted(s.por_valor.get(id_, ())):      # 1) mismo número de identificación en OTRA web: se une si además el nombre coincide
            f = s.c[k]
            if fuente in f["ids"]: continue
            if parece(f, nueva): destino, como = k, "id+nombre"; break
            f.setdefault("conflictos", []).append({"fuente": fuente, "id": id_, "nombre": nombre[:60], "motivo": "mismo id, otro nombre"}); s.cambiado = True
        if not destino and num and idioma:      # 2) sin id común: mismo idioma, mismo número de carta y nombre
            for k, f in s.c.items():
                if fuente in f["ids"] or f.get("idioma") != idioma or not f.get("numero") or f["numero"] != nueva["numero"]: continue
                if (set_ and f.get("set") and _norm(set_) != _norm(f["set"])): continue
                if parece(f, nueva): destino, como = k, "nombre+numero"; break
        if destino:
            f = s.c[destino]; f["ids"][fuente] = id_; f.setdefault("enlaces", []).append({"fuente": fuente, "id": id_, "como": como}); s._completar(f, nombre, numero, set_, idioma, imagen, rareza)
        else:
            s.n += 1; destino = f"pf-{s.n}"; s.c[destino] = {"clave": destino, **nueva, "ids": {fuente: id_}, "enlaces": [{"fuente": fuente, "id": id_, "como": "ancla"}]}
        s._indexar(destino, fuente, id_); s.cambiado = True; return destino

    def _completar(s, f, nombre, numero, set_, idioma, imagen, rareza):
        num, tot = numero_de(numero) if numero else numero_de(nombre)
        for campo, v in (("numero", (f"{num}/{tot}" if tot else num)), ("total", tot), ("set", set_), ("idioma", idioma), ("imagen", imagen), ("rareza", rareza)):
            if v and not f.get(campo): f[campo] = v; s.cambiado = True
    def guardar(s):
        if s.cambiado: os.makedirs(DIR, exist_ok=True); save(CARTAS, s.c); s.cambiado = False

# ---------------------------------------------------------------------------------------------------------------------- precios
class Precios:
    def __init__(s): s.vistos = None; s.f = None; s.nuevos = 0
    def _abrir(s):
        if s.vistos is None:
            s.vistos = set(); os.makedirs(DIR, exist_ok=True)
            try:
                for ln in open(PRECIOS, encoding="utf-8"):
                    m = re.search(r'"k": "([0-9a-f]+)"', ln)
                    if m: s.vistos.add(m.group(1))
            except OSError: pass
            s.f = open(PRECIOS, "a", encoding="utf-8")
    def dato(s, carta, t, fuente, id_, tipo, valor, moneda, estado="sin_gradear", edicion=None, n=None, ref=None):
        if valor is None or isinstance(valor, bool) or not isinstance(valor, (int, float)): return
        k = hashlib.sha1("|".join(map(str, (carta, t, fuente, id_, tipo, estado, edicion, moneda))).encode()).hexdigest()[:16]
        s._abrir()
        if k in s.vistos: return
        s.vistos.add(k); s.nuevos += 1
        s.f.write(json.dumps({"k": k, "t": t, "carta": carta, "fuente": fuente, "id": str(id_), "tipo": tipo, "estado": estado, "edicion": edicion, "valor": valor, "moneda": moneda, "n": n, "ref": ref}, ensure_ascii=False) + "\n")
    def cerrar(s):
        if s.f: s.f.close(); s.f = None

# ---------------------------------------------------------------------------------------------------------------------- lo que ya tenemos, traducido al estándar
def _lecturas(cat, pr, est):
    """data/referencia/lecturas.jsonl (TCGplayer, Collectr, PokéWallet), desde donde se quedó la última vez."""
    ruta = P("referencia", "lecturas.jsonl"); off = int(est.get("lecturas_off", 0))
    if not os.path.exists(ruta): return
    with open(ruta, "rb") as f:
        f.seek(off)
        while True:
            pos = f.tell(); ln = f.readline()
            if not ln: break
            if not ln.endswith(b"\n"): f.seek(pos); break      # una línea a medio escribir: se lee la próxima vez
            try: d = json.loads(ln.decode("utf-8"))
            except ValueError: continue
            fu, i, t, idi = d.get("fuente"), str(d.get("id") or ""), d.get("t"), d.get("idioma")
            if not (fu and i and t): continue
            c = cat.registrar(fu, i, d.get("nombre"), idioma=idi)
            if fu == "tcgplayer":
                for tipo, campo, moneda in (("mercado", "mercado", "USD"), ("ultima_venta", "ultima_venta", "USD"), ("venta_min", "venta_min", "USD"), ("venta_max", "venta_max", "USD"), ("anuncio_min", "anuncios_desde", "USD"),
                                             ("mercado", "mercado_eur", "EUR"), ("ultima_venta", "ultima_venta_eur", "EUR"), ("anuncio_min", "anuncios_desde_eur", "EUR")):
                    pr.dato(c, t, fu, i, tipo, d.get(campo), moneda, n=d.get("vendidas") if tipo in ("mercado", "ultima_venta") else None, ref=d.get("estado"))
            elif fu == "collectr":
                pr.dato(c, t, fu, i, "mercado", d.get("sin_gradear"), "USD")
                for nota, v in (d.get("notas") or {}).items(): pr.dato(c, t, fu, i, "mercado", v, "USD", estado=nota, ref="fiable" if d.get("notas_fiables") else "dudosa")
            elif fu == "pokewallet":
                for ed, v in (d.get("tcgplayer_usd") or {}).items(): pr.dato(c, t, fu, i, "mercado", v, "USD", edicion=ed)
                for var, dd in (d.get("cardmarket_eur") or {}).items():
                    for tipo, campo in (("tendencia", "trend"), ("media_1d", "avg1"), ("media_7d", "avg7"), ("media_30d", "avg30"), ("minimo", "low")):
                        if (dd or {}).get(campo): pr.dato(c, t, "cardmarket", i, tipo, dd.get(campo), "EUR", edicion=var)      # lo que PokéWallet trae de Cardmarket es de Cardmarket
        est["lecturas_off"] = f.tell()

def _descubiertas(cat):
    """Las cartas que el Tasador descubrió en TCGplayer: ficha con id, nombre, número y set."""
    for d in (load(P("referencia", "descubiertas.json"), {}) or {}).values():
        cat.registrar("tcgplayer", d["tcg"], d["nombre"], set_=d.get("set"), idioma=d.get("idioma") or "en")

def _cartas_precios(cat):
    """data/precios/cartas.json: las Gold Stars, promos y modernas con id de TCGplayer, set, número e imagen."""
    for c in (load(P("precios", "cartas.json"), {}) or {}).get("cartas", []):
        if c.get("tcg_id"): cat.registrar("tcgplayer", c["tcg_id"], c.get("base") or c["nombre"], numero=c.get("numero"), set_=c.get("set"), idioma="ja" if c.get("idioma") == "japanese" else "en", imagen=c.get("imagen"))

def _historial(cat, pr):
    """data/precios/historial.json (la foto diaria: PPT, TCGAPI y Cardmarket por PokéWallet) → precios por día."""
    cl = {("p-" if False else "") + c["clave"]: c for c in (load(P("precios", "cartas.json"), {}) or {}).get("cartas", []) if c.get("tcg_id")}
    for clave, dias in (load(P("precios", "historial.json"), {}) or {}).items():
        c = cl.get(clave)
        if not c: continue
        i = str(c["tcg_id"]); pf = cat.registrar("tcgplayer", i, c.get("base") or c["nombre"], numero=c.get("numero"), set_=c.get("set"), idioma="ja" if c.get("idioma") == "japanese" else "en")
        for dia, r in dias.items():
            t = dia + "T12:00:00+01:00"
            pr.dato(pf, t, "ppt", i, "mercado", r.get("raw_usd"), "USD")
            for kk, etq in NOTAS_ETIQUETA.items():
                v = r.get(kk)
                if isinstance(v, list) and len(v) == 2: pr.dato(pf, t, "ppt", i, "mediana_ventas", v[1], "USD", estado=etq, n=v[0], ref="ventas de eBay")
            tc = r.get("tcgapi")
            if isinstance(tc, list) and tc: pr.dato(pf, t, "tcgapi", i, "mercado", tc[0], "USD", n=tc[1] if len(tc) > 1 else None)
            for var, dd in (r.get("cm") or {}).items():
                for tipo, campo in (("tendencia", "trend"), ("media_1d", "avg1"), ("media_7d", "avg7"), ("media_30d", "avg30"), ("minimo", "low")):
                    if (dd or {}).get(campo): pr.dato(pf, t, "cardmarket", i, tipo, dd.get(campo), "EUR", edicion=var)

def _ventas(cat, pr):
    """data/ventas/<carta>.json: ventas reales de SNKRDUNK (japonesas) con fecha, estado y precio."""
    for f in glob.glob(P("ventas", "*.json")):
        d = load(f, {}) or {}
        if not isinstance(d, dict) or not d.get("ventas"): continue
        for p in d.get("productos") or []:
            num = numero_de(p.get("titulo"))[0]; nm = d.get("nombre") or ""; tot = numero_de(p.get("titulo"))[1]
            numtxt = f"{num}/{tot}" if num and tot else None
            c = cat.registrar(p.get("f") or "snkrdunk", p["id"], nm, numero=numtxt, idioma="ja")
            for v in d["ventas"]:
                if str(v.get("prod")) != str(p["id"]): continue
                est = v.get("nota") or v.get("estado") or "sin_gradear"
                if est and re.match(r"^[A-D]$", str(v.get("estado") or "")): est = "sin_gradear"
                pr.dato(c, v.get("fecha", "")[:10] + "T00:00:00+09:00", v.get("f") or "snkrdunk", p["id"], "venta", v.get("jpy"), "JPY", estado=est, edicion=v.get("edicion"), ref=v.get("estado"))
                pr.dato(c, v.get("fecha", "")[:10] + "T00:00:00+09:00", v.get("f") or "snkrdunk", p["id"], "venta", v.get("eur"), "EUR", estado=est, edicion=v.get("edicion"), ref=v.get("estado"))

def ingerir():
    """Pasa todo lo que hay al estándar. Se puede repetir las veces que haga falta: no duplica."""
    est = load(ESTADO, {}) or {}; cat = Catalogo(); pr = Precios(); antes = len(cat.c)
    try:
        _descubiertas(cat); _cartas_precios(cat); _lecturas(cat, pr, est); _historial(cat, pr); _ventas(cat, pr)
    finally:
        pr.cerrar(); cat.guardar()
    est.update(ultima=time.strftime("%Y-%m-%dT%H:%M:%S"), cartas=len(cat.c), cartas_nuevas=len(cat.c) - antes, precios_nuevos=pr.nuevos, conflictos=sum(len(f.get("conflictos") or []) for f in cat.c.values()),
               enlazadas=sum(1 for f in cat.c.values() if len(f["ids"]) > 1)); save(ESTADO, est); return est

# ---------------------------------------------------------------------------------------------------------------------- consultas
def ficha(fuente, id_):
    cat = Catalogo(); k = cat.idx.get((fuente, str(id_))); return cat.c.get(k) if k else None

def precios(fuente=None, id_=None, clave=None, tipo=None):
    """Los precios de una carta (por su clave pf-N, o por fuente+id), del más reciente al más antiguo."""
    if not clave:
        f = ficha(fuente, id_); clave = f and f["clave"]
    if not clave: return []
    out = []
    try:
        for ln in open(PRECIOS, encoding="utf-8"):
            if f'"carta": "{clave}"' in ln:
                d = json.loads(ln)
                if not tipo or d["tipo"] == tipo: out.append(d)
    except OSError: pass
    return sorted(out, key=lambda d: d["t"], reverse=True)

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8"); ap = argparse.ArgumentParser(); ap.add_argument("--ingerir", action="store_true"); ap.add_argument("--stats", action="store_true")
    ap.add_argument("--ficha", nargs=2); ap.add_argument("--precios", nargs=2); a = ap.parse_args()
    if a.ingerir: print(json.dumps(ingerir(), ensure_ascii=False, indent=1))
    if a.stats: print(json.dumps(load(ESTADO, {}), ensure_ascii=False, indent=1))
    if a.ficha: print(json.dumps(ficha(*a.ficha), ensure_ascii=False, indent=1))
    if a.precios:
        for d in precios(*a.precios)[:30]: print(d["t"][:16], d["fuente"], d["tipo"], d["estado"], d.get("edicion") or "", d["valor"], d["moneda"], d.get("n") or "")
