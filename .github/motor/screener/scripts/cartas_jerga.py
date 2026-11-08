"""Cartas concretas de un podcast, con la jerga del hobby: qué carta es, de qué set/era y qué dicen de ella, cada dato con su minuto y una cita literal que se comprueba en la transcripción.
  python cartas_jerga.py <transcripcion.json>      -> data/podcasts/cartas/<id>.json  (y lo enseña)
La lee la ficha (tools/analizar_transcripcion.py). Gasta solo texto de Groq (gratis); los episodios ya hechos no se repiten."""
import json, os, re, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import podcasts as PC      # noqa: E402  (_chat, _comprobar, _min: the same Groq client and quote check as the summaries)

DIR = os.path.join(ROOT, "data", "podcasts", "cartas")

# What the hobby calls things (owner, 3 November 2026: «Crystal Lugia es un tipo de carta como Pikachu Gold Star, Bubble Mew, las Shiny de Call of Legends...»). Only what is certain; the model
# gets it as help and must still copy a quote. A nickname that is not here is reported as «apodo sin reconocer» for the owner to explain, never guessed.
JERGA = """- «Crystal X» (Crystal Lugia, Crystal Charizard...): cartas Crystal de las series e-Card, sets Aquapolis y Skyridge. Son un tipo de carta propio, no un set.
- «X Gold Star» / «Gold Star» / «star»: cartas ★ de la era EX (Pikachu Gold Star, Rayquaza Gold Star...). Son un tipo de carta.
- «Shining X» (Shining Charizard, Shining Mewtwo...): Neo Destiny / Neo Revelation. «Shiny» de «Call of Legends»: las holo shiny SL1–SL11 de ese set (HGSS). «Shiny» en otros contextos: Shiny Vault, Hidden Fates, Shining Fates...
- «Bubble Mew» y otras con apodo: el apodo ES el nombre de la carta.
- «Alt Art», «SIR» (special illustration rare), «full art», «trainer gallery», «Radiant», «Shadowless», «1st edition», «Base Set», «Jungle», «Fossil», «Neo», «e-Series»: variantes, ediciones o eras.
- «holo»/«hollow» (Whisper escribe a veces «hollow» por «holo»), «pop 1» (población PSA = 1), «gem rate», «slab», «raw»."""

SIS = ("Eres un experto en cartas Pokémon coleccionables (TCG), con toda la jerga del hobby. Recibes un tramo de la transcripción de un podcast en inglés, con su minuto al principio de cada línea. "
       "Extrae CADA carta concreta de la que hablan (no basta con el nombre del Pokémon: la carta es Pokémon + tipo o apodo + set/era, p. ej. «Crystal Lugia (Aquapolis/Skyridge)», «Pikachu Gold Star (POP Series 5)», "
       "«Lugia V Alt Art (Silver Tempest)»). Whisper puede estropear nombres: escribe el nombre correcto si lo reconoces, pero la cita debe ser literal. Jerga que debes conocer:\n" + JERGA + "\n"
       "Una línea por carta y mención, EXACTAMENTE así:\n"
       "- CARTA: nombre completo | SET: set o era (o ?) | DICEN: qué dicen de ella en español, con precios o tendencia si los hay [m:ss] | «cita literal en inglés, de 6 a 20 palabras»\n"
       "Si dicen un apodo o una carta que no reconoces, ponla igual con el nombre tal como suena y añade al final de DICEN «(apodo sin reconocer)». "
       "No inventes sets, cifras ni cartas que no se nombran. Ignora anuncios. Si no hay ninguna carta, responde solo NADA.")
LINEA = re.compile(r"^-\s*CARTA:\s*(.+?)\s*\|\s*SET:\s*(.+?)\s*\|\s*DICEN:\s*(.+?)\s*\[(\d+:\d{2}(?::\d{2})?)\]\s*\|\s*[«“\"](.+?)[»”\"]\s*$")

def sis():
    """The prompt plus what the knowledge base (expertise.py) has learned and checked: nicknames the owner explained, so the reader grows with use."""
    try: import expertise as EX; extra = EX.jerga_texto()
    except Exception: extra = ""
    return SIS + ("\nLo que ya se ha aprendido y confirmado (úsalo):\n" + extra if extra else "")

def extraer(ruta, log=print):
    d = json.load(open(ruta, encoding="utf-8")); seg = d["segmentos"]
    trozos, cur, n = [], [], 0
    for s, t in seg:
        cur.append(f"[{PC._min(s)}] {t}"); n += len(t) + 10
        if n >= PC.CHUNK: trozos.append("\n".join(cur)); cur, n = [], 0
    if cur: trozos.append("\n".join(cur))
    cartas, descartadas = [], 0
    for i, tr in enumerate(trozos):
        log(f"Cartas: tramo {i + 1} de {len(trozos)}…")
        try: t, _ = PC._chat(sis(), tr)
        except Exception as e: log(f"Tramo {i + 1} sin cartas ({e})"); continue
        for linea in t.splitlines():
            m = LINEA.match(linea.strip())
            if not m: continue
            s_ok = PC._comprobar(m.group(3), m.group(5), m.group(4), seg)
            if s_ok is None: descartadas += 1; continue
            cartas.append({"carta": m.group(1).strip(), "set": m.group(2).strip(), "dicen": m.group(3).strip(), "s": s_ok, "cita": m.group(5).strip(), "sin_reconocer": "sin reconocer" in m.group(3)})
        time.sleep(40)      # the free tier counts tokens per minute: 20 s gave HTTP 429 in 6 of 15 sections (3 November 2026)
    cartas.sort(key=lambda c: c["s"])
    os.makedirs(DIR, exist_ok=True)
    out = {"titulo": d.get("titulo"), "fecha": d.get("fecha"), "descartadas": descartadas, "cartas": cartas}
    with open(os.path.join(DIR, ruta_id(ruta) + ".json"), "w", encoding="utf-8") as f: json.dump(out, f, ensure_ascii=False, indent=1)
    return out

def ruta_id(ruta): return os.path.splitext(os.path.basename(ruta))[0]

def cargar(ruta):
    try:
        with open(os.path.join(DIR, ruta_id(ruta) + ".json"), encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError): return None

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2: sys.exit(__doc__)
    r = extraer(sys.argv[1])
    print(f"{len(r['cartas'])} menciones comprobadas, {r['descartadas']} descartadas")
    for c in r["cartas"]: print(f"[{PC._min(c['s'])}] {c['carta']} · {c['set']} — {c['dicen']}  «{c['cita']}»")
