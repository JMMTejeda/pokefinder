"""Base de conocimiento del TCG de Pokémon («expertise»): lo que se va aprendiendo de los podcasts, de la web y de las API, con su fuente.
  python expertise.py sembrar                       -> sets (nombre, serie/era, fecha, nº de cartas) desde pokemontcg.io
  python expertise.py añadir <tema> <sujeto> <dato> <fuente> [ref] [cita]
  python expertise.py jerga <apodo> <significado> <fuente> [ref]
  python expertise.py buscar <texto>                -> hechos, jerga y sets que lo mencionan
  python expertise.py resumen                       -> cuántos datos hay y de qué tipo
  python expertise.py afirmaciones <archivo.json>   -> carga afirmaciones CON FECHA (lo que se dijo y cuándo; caducan según su clase)
  python expertise.py cronologia <tema> [--vigentes] -> líneas fechadas de un tema, con su edad y estado
  python expertise.py revisar <id> <cumplida|parcial|fallida|superada|no_verificable> <evidencia con fecha>
Cada dato lleva fuente (transcripcion | web | api | dueño) y referencia (episodio+minuto, o enlace). Lo que viene de la web o de un podcast entra como «por comprobar»
hasta que alguien lo confirma: un podcast da opiniones y la web se equivoca. Archivo: data/expertise/expertise.duckdb (no se sube)."""
import json, os, sys, time, urllib.parse, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
DB = os.path.join(ROOT, "data", "expertise", "expertise.duckdb")
TEMAS = ("carta", "set", "rareza", "probabilidad", "mercado", "inversion", "comparativa", "pokemon", "arte", "jerga", "evento", "otro")

def con():
    import duckdb
    os.makedirs(os.path.dirname(DB), exist_ok=True); c = duckdb.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS hechos (tema VARCHAR, sujeto VARCHAR, dato VARCHAR, fuente VARCHAR, ref VARCHAR, cita VARCHAR, confianza VARCHAR, anotado VARCHAR)")
    c.execute("ALTER TABLE hechos ADD COLUMN IF NOT EXISTS razon VARCHAR")      # why it is (not) believed: sample, bias, who sells what, whether another source agrees
    c.execute("CREATE TABLE IF NOT EXISTS jerga (apodo VARCHAR, significado VARCHAR, fuente VARCHAR, ref VARCHAR, confianza VARCHAR, anotado VARCHAR)")
    c.execute("CREATE TABLE IF NOT EXISTS sets (id VARCHAR, nombre VARCHAR, serie VARCHAR, fecha VARCHAR, cartas INTEGER, total INTEGER, codigo VARCHAR)")
    return c

def ahora(): return time.strftime("%Y-%m-%d")

CONFIANZA = ("verificado", "corroborado", "por comprobar", "dudoso")
# verificado = API oficial / dato del dueño / aritmética · corroborado = dos fuentes independientes sin interés comercial coinciden · por comprobar = una fuente · dudoso = contradicha, promocional o sin base.
# (owner, 3 November 2026: «la gente subirá posts por subir y cosas que luego no son del todo verdad»: nothing from a post, a blog or a podcast is «verificado» just for being written down.)

def añadir(tema, sujeto, dato, fuente, ref="", cita="", confianza=None, razon=""):
    """One fact, with WHY it is believed or not (razon). The same subject+fact from the same source is not stored twice."""
    if tema not in TEMAS: tema = "otro"
    confianza = confianza if confianza in CONFIANZA else ("verificado" if fuente in ("api", "dueño") else "por comprobar")
    c = con()
    if c.execute("SELECT 1 FROM hechos WHERE sujeto=? AND dato=? AND ref=?", [sujeto, dato, ref]).fetchone(): return False
    c.execute("INSERT INTO hechos (tema, sujeto, dato, fuente, ref, cita, confianza, anotado, razon) VALUES (?,?,?,?,?,?,?,?,?)", [tema, sujeto, dato, fuente, ref, cita, confianza, ahora(), razon]); return True

def contrastar(sujeto):
    """All the facts about a subject with their confidence, reason and source, most trusted first: this is how to see contradictions before using a number."""
    orden = {k: i for i, k in enumerate(CONFIANZA)}
    f = con().execute("SELECT confianza, dato, razon, fuente, ref FROM hechos WHERE lower(sujeto) LIKE ?", [f"%{sujeto.lower()}%"]).fetchall()
    return sorted(f, key=lambda r: orden.get(r[0], 9))

def jerga_añadir(apodo, significado, fuente, ref="", confianza=None):
    confianza = confianza or ("verificado" if fuente in ("api", "dueño") else "por comprobar")
    c = con()
    c.execute("DELETE FROM jerga WHERE lower(apodo)=lower(?) AND fuente=?", [apodo, fuente])
    c.execute("INSERT INTO jerga VALUES (?,?,?,?,?,?)", [apodo, significado, fuente, ref, confianza, ahora()])

def jerga_texto(max_lineas=60):
    """What the card reader gets as help: the learned nickname meanings (not the ones still unchecked from the web, those would mislead it)."""
    try: filas = con().execute("SELECT apodo, significado FROM jerga WHERE confianza='verificado' ORDER BY apodo LIMIT ?", [max_lineas]).fetchall()
    except Exception: return ""
    return "\n".join(f"- «{a}»: {s}" for a, s in filas)

def sembrar():
    """Every set of pokemontcg.io (name, series = era, release date, printed and total cards). Public data, one request."""
    d = json.load(urllib.request.urlopen(urllib.request.Request("https://api.pokemontcg.io/v2/sets?pageSize=250&orderBy=releaseDate", headers={"user-agent": "PokeFinder"}), timeout=60))
    c = con(); c.execute("DELETE FROM sets")
    for s in d.get("data", []): c.execute("INSERT INTO sets VALUES (?,?,?,?,?,?,?)", [s["id"], s["name"], s.get("series"), s.get("releaseDate"), s.get("printedTotal"), s.get("total"), s.get("ptcgoCode")])
    return len(d.get("data", []))

def buscar(texto):
    c = con(); t = f"%{texto.lower()}%"
    return {"hechos": c.execute("SELECT tema, sujeto, dato, fuente, ref, confianza || ' · ' || coalesce(razon, '') FROM hechos WHERE lower(sujeto||' '||dato) LIKE ?", [t]).fetchall(),
            "jerga": c.execute("SELECT apodo, significado, fuente, confianza FROM jerga WHERE lower(apodo||' '||significado) LIKE ?", [t]).fetchall(),
            "sets": c.execute("SELECT nombre, serie, fecha, cartas FROM sets WHERE lower(nombre||' '||serie) LIKE ? ORDER BY fecha", [t]).fetchall()}

# ---------------------------------------------------------------- dated claims: what each source SAID, WHEN, and what happened later
# (owner, 4 November 2026: «para este tipo de cosas es muy importante la fecha... una nota interesante a día de hoy pero que se escribió hace unos meses, no me vale para nada»).
# `fecha` is the day it was SAID (the episode's date), never the day it was transcribed. Every claim expires by its CLASS, so an old price never reads as today's:
CLASES = {"precio": 14, "observacion": 14, "tendencia": 45, "lectura": 21, "prediccion": 90, "hecho": 120, "estructural": 365}   # days it can still be shown as «vigente»
VENTANA = 90            # older than this many days: «archivo» (kept to judge how well sources predicted, never shown as current)
MERCADO = ("vintage", "moderno", "gold_stars", "japones_ingles", "ventas_dudosas", "institucional", "riesgos", "grading", "mercado_general")
POSTURAS = ("sube", "baja", "neutral", "")
VERIF = ("pendiente", "cumplida", "parcial", "fallida", "superada", "no_verificable")
AFIR = os.path.join(ROOT, "data", "expertise", "afirmaciones.json")      # a plain copy the app reads, so the web server never waits on the database file

def _tabla(c):
    c.execute("CREATE TABLE IF NOT EXISTS afirmaciones (id VARCHAR, fecha VARCHAR, fuente VARCHAR, episodio VARCHAR, ref VARCHAR, tema VARCHAR, sujeto VARCHAR, postura VARCHAR, texto VARCHAR, "
              "cita VARCHAR, tipo VARCHAR, clase VARCHAR, vigencia_dias INTEGER, fecha_dato VARCHAR, confianza VARCHAR, verificacion VARCHAR, evidencia VARCHAR, revisada VARCHAR, anotado VARCHAR)")

def _fecha_ok(f):
    import datetime as dt
    try: d = dt.date.fromisoformat(str(f)[:10])
    except ValueError: return False
    return d <= dt.date.today()

def estado_de(fecha, vigencia, hoy=None):
    """(edad en días, 'vigente' | 'caduca pronto' | 'caducada' | 'archivo'): the label that decides how a claim may be shown."""
    import datetime as dt
    hoy = hoy or dt.date.today(); edad = (hoy - dt.date.fromisoformat(str(fecha)[:10])).days
    if edad > VENTANA: return edad, "archivo"
    if edad > vigencia: return edad, "caducada"
    return edad, "caduca pronto" if edad > 0.75 * vigencia else "vigente"

def afirmar(fecha, fuente, tema, texto, clase, episodio="", ref="", sujeto="", postura="", cita="", tipo="opinion", fecha_dato="", confianza=None, vigencia_dias=None, verificacion="pendiente", evidencia=""):
    """One dated claim. It is REFUSED without a real past date, and a price/observation must say which day its figure is from (fecha_dato, the episode's day if the speaker gave no other)."""
    import hashlib
    if not _fecha_ok(fecha): raise ValueError("Falta la fecha en que se dijo (AAAA-MM-DD, no futura): sin fecha no vale")
    if clase not in CLASES: raise ValueError("clase: " + "|".join(CLASES))
    tema = tema if tema in MERCADO else "mercado_general"; postura = postura if postura in POSTURAS else ""
    confianza = confianza if confianza in CONFIANZA else ("verificado" if fuente in ("dueño", "api") else "por comprobar")
    i = hashlib.md5(f"{fecha}|{episodio}|{ref}|{texto}".encode()).hexdigest()[:10]
    c = con(); _tabla(c)
    if c.execute("SELECT 1 FROM afirmaciones WHERE id=?", [i]).fetchone(): return i, False
    c.execute("INSERT INTO afirmaciones VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [i, str(fecha)[:10], fuente, episodio, ref, tema, sujeto, postura, texto, cita, tipo, clase, vigencia_dias or CLASES[clase],
                                                                                          str(fecha_dato or fecha)[:10], confianza, verificacion if verificacion in VERIF else "pendiente", evidencia, "", ahora()])
    _exportar(c); return i, True

def revisar(id, verificacion, evidencia):
    """What happened afterwards, with its own date: cumplida | parcial | fallida | superada | no_verificable | pendiente. This is how the sources' record is built."""
    if verificacion not in VERIF: raise ValueError("verificación: " + "|".join(VERIF))
    c = con(); _tabla(c); c.execute("UPDATE afirmaciones SET verificacion=?, evidencia=?, revisada=? WHERE id=?", [verificacion, evidencia, ahora(), id]); _exportar(c)

def _exportar(c=None):
    c = c or con(); _tabla(c)
    cols = [r[0] for r in c.execute("DESCRIBE afirmaciones").fetchall()]
    filas = [dict(zip(cols, r)) for r in c.execute("SELECT * FROM afirmaciones ORDER BY fecha, tema").fetchall()]
    os.makedirs(os.path.dirname(AFIR), exist_ok=True)
    with open(AFIR, "w", encoding="utf-8") as f: json.dump(filas, f, ensure_ascii=False, indent=1)

def importar_afirmaciones(ruta):
    """Many claims from a JSON file (a list of objects with afirmar's fields); returns (added, already there)."""
    nuevas = ya = 0
    for x in json.load(open(ruta, encoding="utf-8")):
        r = x.pop("revision", None); i, n = afirmar(**x)
        if n and r: revisar(i, r["verificacion"], r["evidencia"])
        nuevas += n; ya += (not n)
    return nuevas, ya

def cronologia(tema, solo_vigentes=False):
    """Dated lines of a topic, oldest first, each with its age and state: how a claim ages is visible at a glance."""
    c = con(); _tabla(c); out = []
    for r in c.execute("SELECT fecha, fuente, episodio, ref, postura, texto, clase, vigencia_dias, verificacion, id FROM afirmaciones WHERE tema=? ORDER BY fecha", [tema]).fetchall():
        edad, est = estado_de(r[0], r[7])
        if solo_vigentes and est in ("caducada", "archivo"): continue
        out.append((r[0], f"hace {edad} d", est, r[1], r[4] or "·", r[5], r[8], r[9]))
    return out

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8"); a = sys.argv[1:]
    if not a: sys.exit(__doc__)
    if a[0] == "afirmaciones" and len(a) >= 2: print("nuevas: %d · ya estaban: %d" % importar_afirmaciones(a[1])); sys.exit(0)
    if a[0] == "cronologia" and len(a) >= 2:
        for r in cronologia(a[1], "--vigentes" in a): print(" | ".join(str(x) for x in r))
        sys.exit(0)
    if a[0] == "revisar" and len(a) >= 4: revisar(a[1], a[2], " ".join(a[3:])); print("revisada"); sys.exit(0)
    if a[0] == "sembrar": print(sembrar(), "sets")
    elif a[0] == "añadir" and len(a) >= 5: print("añadido" if añadir(a[1], a[2], a[3], a[4], *(a[5:7])) else "ya estaba")
    elif a[0] == "jerga" and len(a) >= 4: jerga_añadir(a[1], a[2], a[3], *(a[4:5])); print("guardado")
    elif a[0] == "buscar" and len(a) >= 2:
        for k, v in buscar(" ".join(a[1:])).items():
            print(f"## {k} ({len(v)})")
            for r in v[:30]: print("  ", " | ".join(str(x) for x in r))
    elif a[0] == "resumen":
        c = con(); print("hechos por tema:", c.execute("SELECT tema, count(*) FROM hechos GROUP BY 1 ORDER BY 2 DESC").fetchall())
        print("jerga:", c.execute("SELECT count(*) FROM jerga").fetchone()[0], "· sets:", c.execute("SELECT count(*) FROM sets").fetchone()[0])
    else: sys.exit(__doc__)
