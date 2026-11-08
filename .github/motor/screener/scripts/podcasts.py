"""Mercado > Podcasts: the transcribed podcast episodes with their summary, their data and the text.
Reads data/transcripciones/ (made by tools/transcribir_podcast.py on this computer) and notas/transcripciones/ (the ones shared in the repository), and for each episode:
the summary written in notas/podcast-*-AAAA-MM-DD.md (if there is one), the data sheet (sets and Pokémon with the minute they appear, market themes and tone, money figures with their minute;
tools/analizar_transcripcion.py) and the transcript with a search. If the episode is also a video of a followed YouTube channel, its minutes link to that video at that second."""
import datetime as dt, glob, json, os, re, subprocess, sys, time, unicodedata, urllib.error, urllib.parse, urllib.request
from common import P, load, save, ROOT
sys.path.insert(0, os.path.join(ROOT, "tools"))
import analizar_transcripcion as AT         # noqa: E402
import compartir as CP                      # noqa: E402  (el reparto con el compañero: de quién es cada episodio y lo que sube y baja de git)
import transcribir_podcast as TP            # noqa: E402

DIRS = [os.path.join(ROOT, "data", "transcripciones"), os.path.join(ROOT, "notas", "transcripciones")]
NOTAS = os.path.join(ROOT, "notas")
_cache = {}

def _norm(s): return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)).lower()
def _slug(s): return re.sub(r"[^a-z0-9]+", "-", _norm(s)).strip("-")

_epi = {"k": None, "t": 0.0, "v": None}

def _episodios():
    """{id: {"ruta", "d"}} from both folders; the same episode in both (same date and title) counts once, the local one first.
    Rápido (Fernando, 6 nov: «al pasar de pestaña va lento»): se llamaba 177 veces por cada lista y cada vez recorría las dos carpetas (31.000 consultas al disco); ahora la lista se guarda mientras las carpetas no cambien (hasta 20 s)."""
    try: k = tuple((os.path.getmtime(c), len(os.listdir(c))) for c in DIRS if os.path.isdir(c))
    except OSError: k = None
    if k is not None and _epi["k"] == k and _epi["v"] is not None and time.time() - _epi["t"] < 20: return _epi["v"]
    v = _episodios_sin_cache(); _epi.update(k=k, t=time.time(), v=v); return v

def _episodios_sin_cache():
    out = {}
    for carpeta in DIRS:
        for f in sorted(glob.glob(os.path.join(carpeta, "*.json"))):
            if os.path.basename(f).startswith("_"): continue
            k = (f, os.path.getmtime(f))
            if _cache.get(f, (None,))[0] != k:
                try: _cache[f] = (k, json.load(open(f, encoding="utf-8")))
                except ValueError: continue
            d = _cache[f][1]
            if not d.get("segmentos"): continue
            eid = d.get("fecha", "") + "-" + _slug(d.get("titulo", ""))[:40]
            out.setdefault(eid, {"id": eid, "ruta": f, "d": d, "fuente": "data" if carpeta == DIRS[0] else "notas"})
    return out

RES_DIR = P("podcasts", "resumenes")          # summaries the app wrote by itself (Groq), one per episode; notas/podcast-*-<date>.md (Claude's) win over them

_notas_c = {"k": None, "v": []}
def _notas_de(fecha):
    """Las notas a mano notas/podcast-*-<fecha>.md, con la lista de la carpeta guardada mientras no cambie (antes: un glob por episodio)."""
    try: k = os.path.getmtime(NOTAS)
    except OSError: return []
    if _notas_c["k"] != k: _notas_c.update(k=k, v=sorted(f for f in glob.glob(os.path.join(NOTAS, "podcast-*.md"))))
    return [f for f in _notas_c["v"] if re.fullmatch(rf"podcast-.*-{re.escape(fecha)}\.md", os.path.basename(f))]

def _resumen(fecha, eid=None, ep=None):
    ep = ep or (_episodios().get(eid) if eid else None)
    youtube = bool(ep and ep["d"].get("fuente") == "youtube-subtitulos")      # las notas a mano se casan con el episodio por la FECHA: un vídeo de YouTube del mismo día no puede enseñar la nota de otro podcast (5 de noviembre de 2026: Red & Blue salía «con resumen» con la nota de Card Lounge)
    for f in ([] if youtube else _notas_de(fecha)):
        return open(f, encoding="utf-8").read()
    f = os.path.join(RES_DIR, (eid or "") + ".md")
    return open(f, encoding="utf-8").read() if eid and os.path.exists(f) else None

def _esencial(txt):
    """(the «## Lo esencial» section of a summary, the summary without it): the page shows the short one first, on top, and the long one folded (owner, 2 November 2026:
    "no me entero de los takes más importantes")."""
    if not txt: return None, txt
    m = re.search(r"^## Lo esencial[ \t]*\n(.*?)(?=^## |\Z)", txt, re.S | re.M)
    return (m.group(1).strip(), txt.replace(m.group(0), "")) if m else (None, txt)

_yt_c = {"k": None, "idx": {}}
def _yt(titulo):
    """The YouTube video of this episode among the followed channels (same title up to the first «|» or the cut of YouTube's list).
    El índice título→vídeo se construye una vez por cambio del fichero (antes se leía y se normalizaba toda la lista de vídeos por cada episodio)."""
    f = P("contenido", "videos.json")
    try: k = os.path.getmtime(f)
    except OSError: return None
    if _yt_c["k"] != k:
        V = load(f, {}) or {}; idx = {}
        for vid, v in V.items():
            if v.get("s", 0) > 1500: idx.setdefault(_slug(v["t"].split("|")[0])[:38], vid)
        _yt_c.update(k=k, idx=idx)
    t = _slug(titulo.split("|")[0])[:38]
    return _yt_c["idx"].get(t) if len(t) >= 12 else None

def _ficha(ep):
    k = (ep["ruta"], os.path.getmtime(ep["ruta"]))
    if _cache.get("f" + ep["id"], (None,))[0] != k: _cache["f" + ep["id"]] = (k, AT.analizar(ep["ruta"]))
    return _cache["f" + ep["id"]][1]

def _palabras(ep):
    """Número de palabras de la transcripción, guardado por episodio mientras su fichero no cambie."""
    k = (ep["ruta"], id(ep["d"]))
    c = _cache.get("w" + ep["id"])
    if not c or c[0] != k: c = _cache["w" + ep["id"]] = (k, sum(len(t.split()) for _, t in ep["d"]["segmentos"]))
    return c[1]

def listar():
    out = []; nombres = {f["url"]: f["nombre"] for f in feeds()}      # de dónde viene cada uno: el nombre del podcast o del canal de YouTube
    for ep in sorted(_episodios().values(), key=lambda e: e["d"].get("fecha", ""), reverse=True):
        d = ep["d"]; _, sets, poke, primera, minutos, temas, bear, bull, cifras, n_ad = _ficha(ep)
        out.append({"id": ep["id"], "tipo": "video" if d.get("fuente") == "youtube-subtitulos" else "podcast", "origen": d.get("podcast") or nombres.get(d.get("feed") or "") or "Podcast", "titulo": d["titulo"], "fecha": d.get("fecha"), "duracion_s": d.get("duracion_s"), "palabras": _palabras(ep), "fuente": ep["fuente"],
                    "sets": sets.most_common(6), "poke": poke.most_common(6), "temas": temas.most_common(8), "bear": bear, "bull": bull, "n_cifras": len(cifras), "tiene_resumen": bool(_resumen(d.get("fecha", ""), ep["id"], ep)), "yt": d.get("yt") or _yt(d["titulo"]), "imagen": d.get("imagen")})
    return {"episodios": out}

def episodio(eid):
    ep = _episodios().get(eid)
    if not ep: return None
    d = ep["d"]; _, sets, poke, primera, minutos, temas, bear, bull, cifras, n_ad = _ficha(ep)
    fila = lambda cont: [{"e": e, "n": n, "primera": primera[e], "minutos": sorted(minutos[e])[:14]} for e, n in cont.most_common(14)]
    esencial, resto = _esencial(_resumen(d.get("fecha", ""), eid))
    return {"id": eid, "titulo": d["titulo"], "fecha": d.get("fecha"), "duracion_s": d.get("duracion_s"), "fuente": ep["fuente"], "pedido": pedidos().get(eid), "yt": d.get("yt") or _yt(d["titulo"]), "imagen": d.get("imagen"), "esencial": esencial, "resumen": resto,
            "sets": fila(sets), "poke": fila(poke), "temas": temas.most_common(), "bear": bear, "bull": bull, "cifras": [[s, c, ctx] for s, c, ctx in cifras], "anuncios": n_ad,
            "segmentos": d["segmentos"]}

# ---------------------------------------------------------------- transcribe a link from the page (owner, 2 November 2026: "poner el enlace y darle a transcribir, sin gastar Claude")
# Only routes made for downloading: a podcast's public feed (RSS), an Apple Podcasts page (its feed comes from Apple's public lookup), a direct audio link, or a YouTube link
# of an episode that is ALSO in a podcast feed we know (matched by title; the audio comes from the feed). The audio of YouTube itself is never downloaded (its terms forbid it).
STATE = P("state", "podcast_job.json"); ARGS = P("state", "podcast_args.json"); FEEDS = P("podcasts", "feeds.json")
SEED_FEEDS = [{"nombre": "Card Lounge", "url": "https://anchor.fm/s/100638494/podcast/rss"}]

def _http(url, timeout=30):
    r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 PokeFinder personal"}), timeout=timeout)
    return r.read(3_000_000).decode("utf-8", "replace")

def feeds(): return load(FEEDS, None) or list(SEED_FEEDS)

def _recordar(url, nombre):
    L = feeds()
    if not any(f["url"] == url for f in L): L.append({"nombre": nombre or urllib.parse.urlparse(url).netloc, "url": url}); save(FEEDS, L)

def _hecho(titulo, fecha):
    """Is this episode already transcribed? (the same name the transcriber gives its file)"""
    slug = re.sub(r"[^a-z0-9]+", "-", TP.norm(titulo))[:60].strip("-") + "-" + (fecha or "")
    return any(os.path.exists(os.path.join(c, slug + ".json")) for c in DIRS)

def _lista_feed(url):
    nombre, eps = TP.feed(url, True); _recordar(url, nombre)
    return {"tipo": "feed", "podcast": nombre, "feed": url, "episodios": [dict(e, hecho=_hecho(e["titulo"], e["fecha"])) for e in eps[:40]]}

def _mismo(a, b):
    ka = lambda t: set(w for w in re.findall(r"[a-z0-9]+", _norm(t.split("|")[0])) if len(w) > 2)
    x, y = ka(a), ka(b)
    return bool(x and y) and len(x & y) / len(x | y) >= 0.8

def _de_youtube(vid, url):
    try: titulo = json.loads(_http("https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(url, safe="")))["title"]
    except Exception: raise ValueError("No he podido leer ese vídeo de YouTube: comprueba el enlace.")
    for f in feeds():
        try: nombre, eps = TP.feed(f["url"], True)
        except Exception: continue
        for e in eps:
            if _mismo(titulo, e["titulo"]): return {"tipo": "youtube", "podcast": nombre or f["nombre"], "feed": f["url"], "yt": vid, "episodios": [dict(e, yt=vid, hecho=_hecho(e["titulo"], e["fecha"]))]}
    raise ValueError(f"«{titulo[:80]}» no está en ningún podcast que conozca. Esta app no baja el audio de YouTube (sus condiciones lo prohíben). "
                     "Si es de un podcast, pega el enlace de su feed RSS o de Apple Podcasts y la próxima vez lo reconoceré por el título.")

def resolver(url):
    """What can be transcribed from a pasted link: {"tipo", "podcast"?, "feed"?, "yt"?, "episodios": [{titulo, fecha, audio, duracion_s, hecho}]}. ValueError says why not."""
    u = (url or "").strip()
    if not re.match(r"https?://", u): raise ValueError("Pega un enlace que empiece por http")
    yt = re.search(r"(?:youtube\.com/(?:watch\?(?:[^#]*&)?v=|shorts/|live/)|youtu\.be/)([\w-]{11})", u)
    if yt: return _de_youtube(yt.group(1), u)
    ap = re.search(r"podcasts\.apple\.com/.*?/id(\d+)", u)
    if ap:
        try: u = json.loads(_http(f"https://itunes.apple.com/lookup?id={ap.group(1)}&entity=podcast"))["results"][0]["feedUrl"]
        except Exception: raise ValueError("No he encontrado el feed de ese podcast en Apple Podcasts.")
    if re.search(r"\.(?:mp3|m4a|aac|wav|ogg)(?:\?|$)", u, re.I):
        nombre = urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(u).path))
        return {"tipo": "audio", "episodios": [{"titulo": nombre, "fecha": dt.date.today().isoformat(), "audio": u, "duracion_s": 0, "hecho": False}]}
    try: return _lista_feed(u)
    except Exception: pass
    try: pagina = _http(u)
    except Exception: raise ValueError("No he podido abrir ese enlace.")
    m = re.search(r'<link[^>]+type="application/(?:rss|atom)\+xml"[^>]*href="([^"]+)"', pagina, re.I) or re.search(r'<link[^>]+href="([^"]+)"[^>]*type="application/(?:rss|atom)\+xml"', pagina, re.I)
    if m:
        try: return _lista_feed(urllib.parse.urljoin(u, m.group(1)))
        except Exception: pass
    raise ValueError("Ese enlace no es un podcast que pueda leer. Prueba con su feed RSS, su página de Apple Podcasts o un enlace directo a un MP3.")

def estado():
    s = load(STATE, {}) or {}
    if s.get("running") and time.time() - s.get("beat", 0) > 1800: s = {**s, "running": False, "ok": False, "error": "La transcripción se quedó parada."}
    return s

def iniciar(ep, idioma="en", feed_url=""):
    """Starts the transcription of one episode in the background (python podcasts.py --transcribir) and returns the state."""
    if estado().get("running"): raise ValueError("Ya hay una transcripción en marcha: " + str(estado().get("titulo", ""))[:80])
    if not re.match(r"https?://", str(ep.get("audio") or "")): raise ValueError("Ese episodio no tiene un enlace de audio válido.")
    ep = {k: ep.get(k) for k in ("titulo", "fecha", "audio", "duracion_s", "yt", "imagen")}; ep["titulo"] = str(ep.get("titulo") or "Episodio")[:200]
    os.makedirs(P("state"), exist_ok=True)
    save(ARGS, {"ep": ep, "idioma": idioma if idioma in ("en", "es", "ja", "fr", "de") else "en", "feed": feed_url})
    save(STATE, {"running": True, "beat": time.time(), "titulo": ep["titulo"], "started": dt.datetime.now().isoformat(timespec="minutes"), "log": ["Empezando…"], "ok": None, "error": None})
    log = open(P("state", "podcasts.log"), "a", encoding="utf-8"); here = os.path.dirname(os.path.abspath(__file__))
    subprocess.Popen([sys.executable, os.path.join(here, "podcasts.py"), "--transcribir"], cwd=here, env={**os.environ, "PYTHONIOENCODING": "utf-8"}, stdin=subprocess.DEVNULL,
                     stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return estado()

# ---- the automatic «Lo esencial» (Groq's free text models, only when the owner transcribes from the page; the quality is below a Claude summary and the page says so)
CHUNK = 7000        # characters of transcript per request: Groq's free tier takes about 7,000 input tokens a minute per model

def _chat(sistema, usuario):
    tok = (load(os.path.join(ROOT, ".secrets", "groq.json"), {}) or {}).get("token")
    if not tok: raise RuntimeError("sin clave de Groq")
    err = ""
    for modelo in ("openai/gpt-oss-120b", "openai/gpt-oss-20b"):
        for intento in range(3):
            try:
                body = json.dumps({"model": modelo, "temperature": 0.2, "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]}).encode()
                r = json.load(urllib.request.urlopen(urllib.request.Request("https://api.groq.com/openai/v1/chat/completions", data=body,
                              headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json", "User-Agent": "PokeFinder personal"}), timeout=180))
                t = (r["choices"][0]["message"].get("content") or "").strip()
                if t: return t, modelo
            except urllib.error.HTTPError as e:
                err = f"{modelo}: HTTP {e.code}"
                if e.code == 429: time.sleep(25 * (intento + 1)); continue
                break
            except Exception as e: err = f"{modelo}: {type(e).__name__}"; break
    raise RuntimeError(err or "Groq no respondió")

def _min(s): return f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{int(s % 60):02d}" if s >= 3600 else f"{int(s // 60)}:{int(s % 60):02d}"

def _pal(s): return re.findall(r"[a-z0-9']+", _norm(s))
def _seg_de(m): p = [int(x) for x in m.split(":")]; return p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else p[0] * 60 + p[1]

def _comprobar(texto, cita, minuto, seg):
    """The second (in the transcript) where the quote really is, or None: at least 85 % of the quote's words must be in three consecutive segments near the minute the model gave
    (90 s before to 150 s after); a take with figures needs figures in its quote. This is what stops invented points."""
    q = [w for w in _pal(cita) if len(w) > 2]
    if len(q) < 4: return None
    ref = _seg_de(minuto); mejor = (0.0, None)
    for i, (s, _) in enumerate(seg):
        if not ref - 90 <= s <= ref + 150: continue
        win = set(_pal(" ".join(t for _, t in seg[i:i + 3]))); r = sum(1 for w in q if w in win) / len(q)
        if r > mejor[0]: mejor = (r, s)
    if mejor[0] < 0.85: return None
    if re.search(r"\d", texto) and not re.search(r"\d|million|billion|thousand|hundred|grand|\bk\b|dollar|percent|bucks", cita, re.I): return None
    return mejor[1]

# ---- summaries written by Claude, with as few tokens as possible: sin_resumen lists what is missing, material gives the transcript without ads or filler, guardar checks every quote
SPONSOR = re.compile(r"sponsor|eau de toilette|volkswagen|yves saint|consign|collector app|use code|link in the description|brief message|dancing with myself|polo, now|celsius|promo code|subscribe|follow us", re.I)

def _resumen_de(e):
    """'claude' | 'groq' | None for an episode: who wrote its summary."""
    t = _resumen(e["d"].get("fecha", ""), e["id"]) if e["fuente"] == "notas" else (open(os.path.join(RES_DIR, e["id"] + ".md"), encoding="utf-8").read() if os.path.exists(os.path.join(RES_DIR, e["id"] + ".md")) else None)
    if not t: return None
    return "claude" if ("escrito por Claude" in t or e["fuente"] == "notas") else "groq"

RESUMEN_DIAS = 30      # hasta qué antigüedad resume Claude SOLO (podcasts y vídeos): Fernando, 7 nov 2026: «resumen solo de hasta un mes; hay que dedicarse a sacar conocimiento, no a resumir sin fin». Lo más viejo se transcribe (gratis) y se puede pedir a mano desde la página
RESUMEN_YT_DIAS = RESUMEN_DIAS      # (nombre antiguo, por si algo lo usa)
PEDIDOS = P("podcasts", "pedidos_resumen.json")      # {id del episodio: {"t": cuándo}}: los resúmenes que Fernando pide con el botón de la página de cada episodio

def pedidos(): return load(PEDIDOS, {}) or {}

def pedir_resumen(eid):
    """El botón «Pedir resumen a Claude» de la página del episodio: lo apunta; la tarea de Claude (cada hora, a y 30) lo hace la primera, aunque sea antiguo o del compañero. El resumen lo escribe Claude, no Groq."""
    ep = _episodios().get(eid)
    if not ep: raise ValueError("No encuentro ese episodio.")
    if _resumen_de(ep) == "claude": return {"estado": "hecho"}
    p = pedidos(); p.setdefault(eid, {"t": dt.datetime.now().isoformat(timespec="minutes")}); save(PEDIDOS, p)
    try: import oficina; oficina.registrar("t_resumen_podcasts", "Resumen pedido desde la app: " + str(ep["d"].get("titulo", ""))[:80], evento="manual")
    except Exception: pass
    return {"estado": "pedido", "t": p[eid]["t"]}

def cancelar_pedido(eid):
    p = pedidos(); p.pop(eid, None); save(PEDIDOS, p); return {"estado": "cancelado"}

ESPERA_AJENO_H, ESPERA_RESUMEN_H = 6, 12      # horas que se espera a que el otro haga lo suyo antes de hacerlo uno (por si tiene el ordenador apagado)
VISTOS = P("podcasts", "cola_vistos.json"); _imp = {"t": 0}

def _clave_ep(fecha, titulo): return f"{fecha}|{_slug(titulo)}"

def _de_otro_aun(fecha, titulo, dias=None, gratis=False):
    """Es un episodio del compañero (el reparto es por su clave) y todavía no ha pasado el tiempo de espera desde que lo vi por primera vez. Lo nuevo (2 días o menos) espera solo 1 hora y, si no gasta
    cupo (los vídeos de YouTube), no espera: «así si salen nuevos los tenemos al momento» (Fernando, 5 de noviembre de 2026)."""
    k = _clave_ep(fecha, titulo)
    if CP.es_mio(k): return False
    if gratis and dias is not None and dias <= 2: return False
    v = load(VISTOS, {}) or {}
    if k not in v: v[k] = time.time(); save(VISTOS, v)
    return time.time() - v[k] < (1 if dias is not None and dias <= 2 else ESPERA_AJENO_H) * 3600

def importar_compartido(cada=600):
    """Baja de git las transcripciones y los resúmenes que subió el otro y aún no tienes. Devuelve (transcripciones, resúmenes) nuevos. Nunca lanza."""
    if time.time() - _imp["t"] < cada: return 0, 0
    _imp["t"] = time.time(); nt = nr = 0
    try:
        for eid, (path, quien) in CP.ajenos_de("transcripciones").items():
            if not re.fullmatch(r"[a-z0-9-]+", eid): continue
            j = CP.leer(path); d = (j or {}).get("datos")
            if not d or not d.get("segmentos"): continue
            archivo = os.path.basename(str(j.get("archivo") or eid + ".json")); destino = os.path.join(DIRS[0], archivo)
            if os.path.exists(destino) or _hecho_ep(d.get("feed") or "", d.get("titulo", ""), d.get("fecha", "")): continue
            os.makedirs(DIRS[0], exist_ok=True); json.dump(d, open(destino, "w", encoding="utf-8"), ensure_ascii=False); nt += 1
            try: import oficina; oficina.registrar("podcast_cola", "Importada de " + quien + ": " + str(d.get("titulo", ""))[:80], evento="manual")
            except Exception: pass
        for eid, (path, quien) in CP.ajenos_de("resumenes").items():
            if not re.fullmatch(r"[a-z0-9-]+", eid): continue
            destino = os.path.join(RES_DIR, eid + ".md"); j = CP.leer(path); md = (j or {}).get("md")
            if not md or "escrito por Claude" not in md: continue
            if os.path.exists(destino) and "escrito por Claude" in open(destino, encoding="utf-8").read(): continue
            os.makedirs(RES_DIR, exist_ok=True); open(destino, "w", encoding="utf-8").write(md); nr += 1
            try: import oficina; oficina.registrar("t_resumen_podcasts", "Resumen importado de " + quien + ": " + eid[:60], evento="manual")
            except Exception: pass
    except Exception as ex: print("importar compartido:", ex)
    if nt or nr: _idx.update(k=None); _pend.update(t=0)
    return nt, nr

def sin_resumen():
    """Episodes still without a summary by Claude: [(id, route, duration min, 'nada'|'groq')], newest first. Los del compañero esperan 12 h a que los resuma él (reparto de compartir.dueno)."""
    importar_compartido(); out = []; hoy = dt.date.today(); ped = pedidos(); primeros = []
    for e in sorted(_episodios().values(), key=lambda e: e["d"].get("fecha", ""), reverse=True):
        if e["id"] in ped and _resumen_de(e) != "claude": primeros.append((ped[e["id"]]["t"], (e["id"], e["ruta"], int((e["d"].get("duracion_s") or 0) // 60), "pedido"))); continue      # pedido desde la app: va el primero, sea antiguo o del compañero
        try: viejo = (hoy - dt.date.fromisoformat(e["d"].get("fecha", ""))).days > RESUMEN_DIAS
        except ValueError: viejo = False
        if viejo: continue      # lo de hace más de RESUMEN_DIAS días (podcasts y vídeos) se transcribe (gratis) pero no se resume solo: gastaría tokens de Claude en material que ya es «archivo» (si se pide desde la página, entra por «pedido»)
        w = _resumen_de(e)
        if w != "claude" and (CP.es_mio(_clave_ep(e["d"].get("fecha", ""), e["d"].get("titulo", ""))) or time.time() - os.path.getmtime(e["ruta"]) > ESPERA_RESUMEN_H * 3600): out.append((e["id"], e["ruta"], int((e["d"].get("duracion_s") or 0) // 60), w or "nada"))
    return [x[1] for x in sorted(primeros)] + out

def material(ruta):
    """The transcript in the fewest tokens: lines of about 30 s with their minute, without sponsor reads or fragments with no content. What Claude reads to write the summary."""
    seg = json.load(open(ruta, encoding="utf-8"))["segmentos"]; out, cur, t0 = [], [], 0
    ad = set()
    for i, (_, t) in enumerate(seg):
        if SPONSOR.search(t): ad.update(range(max(0, i - 1), min(len(seg), i + 5)))
    for i, (s, t) in enumerate(seg):
        if i in ad or len(t.split()) < 3: continue
        if not cur: t0 = s
        cur.append(t.strip())
        if s - t0 >= 30: out.append(f"[{_min(t0)}] {' '.join(cur)}"); cur = []
    if cur: out.append(f"[{_min(t0)}] {' '.join(cur)}")
    return "\n".join(out)

BALA = re.compile(r"^-\s*(\*\*.+?\*\*.*?)\s*\[(\d+:\d{2}(?::\d{2})?)\]\s*[—-]\s*[«“\"](.+?)[»”\"]\s*$")

def guardar(ruta, borrador):
    """Checks the quote of every bullet of «## Lo esencial» in the draft (a .md Claude wrote), puts the real minute and drops what is not in the transcript; writes the summary of the episode.
    Returns (bullets kept, bullets dropped, [what was dropped])."""
    d = json.load(open(ruta, encoding="utf-8")); seg = d["segmentos"]; eid = d.get("fecha", "") + "-" + _slug(d.get("titulo", ""))[:40]
    md = open(borrador, encoding="utf-8").read(); m = re.search(r"^## Lo esencial[ \t]*\n(.*?)(?=^## |^_Resumen|\Z)", md, re.S | re.M)
    if not m: raise ValueError("el borrador no tiene «## Lo esencial»")
    ok, mal, lineas = 0, [], []
    for l in m.group(1).splitlines():
        if not l.strip(): continue
        b = BALA.match(l.strip())
        s = _comprobar(b.group(1), b.group(3), b.group(2), seg) if b else None
        if s is None: mal.append(l.strip()[:90]); continue
        lineas.append(f"- {b.group(1).strip()} [{_min(s)}] — «{b.group(3).strip()}»"); ok += 1
    if not ok: raise ValueError("ningún punto tiene su cita en la transcripción")
    nuevo = md[:m.start(1)] + "\n".join(lineas) + "\n\n" + md[m.end(1):]
    if "escrito por Claude" not in nuevo: nuevo = nuevo.rstrip() + "\n\n_Resumen escrito por Claude a partir de " + ("los subtítulos automáticos de YouTube (pueden fallar nombres y cifras)" if d.get("fuente") == "youtube-subtitulos" else "la transcripción de Groq (Whisper)") + ". Cada punto lleva una cita literal comprobada en el texto y el minuto real; los datos son lo que dicen ellos, no hechos verificados._\n"
    os.makedirs(RES_DIR, exist_ok=True); open(os.path.join(RES_DIR, eid + ".md"), "w", encoding="utf-8").write(nuevo)
    try: p = pedidos(); (p.pop(eid, None) is not None) and save(PEDIDOS, p)      # si lo había pedido Fernando, queda cumplido
    except Exception: pass
    try: CP.publicar_item("resumenes", eid, {"id": eid, "md": nuevo}, "Resumen " + eid, "Resumen de Claude subido: " + str(d.get("titulo", ""))[:80] + ". No hace falta repetirlo: se importa solo.")
    except Exception as ex: print("compartir resumen:", ex)
    return ok, len(mal), mal

def _correr():
    a = load(ARGS, {}) or {}
    def log(t):
        s = load(STATE, {}) or {}; s["log"] = (s.get("log") or [])[-40:] + [t]; s["beat"] = time.time(); save(STATE, s)
    try:
        slug, n = TP.transcribir(a["ep"], a.get("feed", ""), a.get("idioma", "en"), log)
        ruta = os.path.join(DIRS[0], slug + ".json")
        try: import historial; historial.exportar_transcripcion(ruta)      # Parquet copy for SQL questions across episodes (historial.py); never raises
        except Exception: pass
        # No summary here: Groq only transcribes (owner, 3 November 2026: "Groq se limite solo a transcribir"). The summary is written by Claude (daily task, see sin_resumen / material / guardar).
        d = json.load(open(ruta, encoding="utf-8")); s = load(STATE, {}) or {}
        save(STATE, {**s, "running": False, "ok": True, "id": d.get("fecha", "") + "-" + _slug(d.get("titulo", ""))[:40], "fin": dt.datetime.now().isoformat(timespec="minutes")})
        try: import oficina; oficina.registrar("podcast_cola", "Transcrito: " + str(d.get("titulo", ""))[:100])
        except Exception: pass
        try: CP.publicar_item("transcripciones", d.get("fecha", "") + "-" + _slug(d.get("titulo", ""))[:40], {"archivo": os.path.basename(ruta), "datos": d}, "Transcripción " + str(d.get("titulo", ""))[:60], "Transcrito y subido: " + str(d.get("titulo", ""))[:80] + ". No hace falta repetirlo: se importa solo.")
        except Exception as ex: print("compartir transcripción:", ex)
    except BaseException as e:
        s = load(STATE, {}) or {}; save(STATE, {**s, "running": False, "ok": False, "error": str(e)[:300]})
        try: import oficina; oficina.registrar("podcast_cola", "Falló: " + str(e)[:120], ok=False)
        except Exception: pass
        raise

# ---------------------------------------------------------------- the automatic queue (owner, 3 November 2026: "tareas que cada hora vayan transcribiendo...
# actuales, último mes, últimos 3 meses, y lo que ya decían previo a eso para saber si acertaban"). Every feed the app knows is read; the episodes not yet transcribed go in this
# order: the last 30 days, then 31-90 days, then older (the newest first in each, the podcasts taking turns). One episode at a time, inside Groq's limits for audio.
COLA = P("podcasts", "cola.json"); COLA_ESTADO = P("state", "podcast_cola.json")
ASH, ASD, MARGEN = 7200, 28800, 0.9     # Groq's speech limits in audio seconds per hour / per day (console.groq.com/docs/rate-limits; the account's own figures: console.groq.com/settings/limits)
CUBOS = ["actuales (último mes)", "últimos 3 meses", "anteriores"]
_pend = {"t": 0, "v": []}

def cola_conf():
    c = load(COLA, {}) or {}; c.setdefault("activa", True); c.setdefault("excluidos", []); return c

_idx = {"k": None, "v": set()}
def _ya_transcritos():
    """{(feed, date)} and {(date, title words)} read from the transcripts' own metadata: an episode transcribed by hand under another file name (card-lounge-ep93-...) still counts as done."""
    ks = tuple((f, os.path.getmtime(f)) for d in DIRS for f in sorted(glob.glob(os.path.join(d, "*.json"))))
    if _idx["k"] != ks:
        v = set()
        for f, _ in ks:
            try: j = json.load(open(f, encoding="utf-8"))
            except (OSError, ValueError): continue
            if j.get("fecha"): v.add((j.get("feed") or "", j["fecha"], _slug(j.get("titulo", ""))))
        _idx.update(k=ks, v=v)
    return _idx["v"]

def _hecho_ep(feed, titulo, fecha):
    """Already transcribed: its own file name, or a transcript of the same podcast and date, or one of that date with a title that matches."""
    if _hecho(titulo, fecha): return True
    for f, d, t in _ya_transcritos():
        if d != fecha: continue
        if f and f == feed: return True
        if not f and t and (t == _slug(titulo) or _mismo(titulo, t.replace("-", " "))): return True
    return False

def pendientes(fuerza=False):
    """[{titulo, fecha, audio, duracion_s, feed, podcast, dias, cubo}] of every episode of the known feeds not yet transcribed (cached 30 minutes: it reads each feed)."""
    if not fuerza and time.time() - _pend["t"] < 900: return _pend["v"]
    out, hoy = [], dt.date.today()
    for f in feeds():
        if f["url"] in cola_conf()["excluidos"]: continue
        try: nombre, eps = TP.feed(f["url"], True)
        except Exception: continue
        for e in eps:
            if not e.get("audio") or _hecho_ep(f["url"], e["titulo"], e["fecha"]): continue
            try: dias = (hoy - dt.date.fromisoformat(e["fecha"])).days
            except (TypeError, ValueError): dias = 9999
            out.append({**e, "feed": f["url"], "podcast": nombre or f["nombre"], "dias": dias, "cubo": 0 if dias <= 30 else 1 if dias <= 90 else 2, "idioma": f.get("idioma", "en")})
    try:      # los canales de YouTube (yt_canales.py): mismo formato, con «tipo»: «youtube»; la cola los ordena por fecha junto a los podcasts
        import yt_canales as YT
        out += YT.pendientes_yt({e["d"].get("yt") for e in _episodios().values() if e["d"].get("yt")})
    except Exception as ex: print("youtube:", ex)
    _pend.update(t=time.time(), v=out); return out

def ordenar(eps):
    """Strictly by date, the newest first, whatever the channel (owner, 5 November 2026: "tienen prioridad por fecha los más recientes siempre; si meto más canales se van transcribiendo de más recientes hacia atrás,
    así si salen nuevos los tenemos al momento"). A new episode of any channel goes in front of every old one; the old ones are worked through backwards. Ties: by channel."""
    return sorted(eps, key=lambda e: (e["dias"], e["feed"]))

def _usos():
    now = time.time(); e = load(COLA_ESTADO, {}) or {}
    return e, [u for u in e.get("usos", []) if now - u[0] < 86400]

def cabe(dur):
    """Does an episode of dur seconds fit in what is left of the last hour and the last 24 hours of Groq's audio limits (with a 10 % margin)?"""
    now = time.time(); _, us = _usos()
    return dur <= ASH * MARGEN and sum(s for t, s in us if now - t < 3600) + dur <= ASH * MARGEN and sum(s for _, s in us) + dur <= ASD * MARGEN

def _tick_yt(c):
    """El carril de YouTube: un vídeo cada vez, el más reciente primero, sin tocar el cupo de Groq (lee la transcripción que enseña la página)."""
    try:
        import yt_canales as YT
        if not c["activa"] or not YT.puede(): return None
        hechos = {e["d"].get("yt") for e in _episodios().values() if e["d"].get("yt")}      # la lista de pendientes se guarda 15 minutos: aquí se mira lo de ahora (qué está ya transcrito y qué ha fallado hace poco)
        for ep in ordenar([e for e in pendientes() if e.get("tipo") == "youtube"]):
            if ep["yt"] in hechos or YT.descartado({"id": ep["yt"], "duracion_s": ep.get("duracion_s")}): continue
            if _de_otro_aun(ep["fecha"], ep["titulo"], ep.get("dias"), gratis=True): continue      # es del compañero y aún no ha pasado el tiempo de espera (lo nuevo no espera: YouTube no gasta cupo)
            YT.iniciar(ep); return ep
    except Exception as ex: print("youtube tick:", ex)
    return None

def tick():
    """Called by the server every few minutes: announces a finished transcription and, when nothing runs and the limits allow it, starts the next episode of the queue."""
    c = cola_conf(); s = estado()
    e, us = _usos()
    if s.get("ok") and s.get("fin") and e.get("avisado") != s["fin"]:
        try:
            CP.lote_anadir("tema", str(s.get("titulo") or "")[:90]); save(COLA_ESTADO, {**e, "avisado": s["fin"], "usos": us})      # van en lote (compartir.lote_vaciar), no una a una
        except Exception as ex: print("podcast aviso:", ex)
    try: CP.lote_vaciar()
    except Exception as ex: print("lote avisos:", ex)
    importar_compartido(); _tick_yt(c)
    if not c["activa"] or s.get("running"): return None
    if not os.path.exists(os.path.join(ROOT, ".secrets", "groq.json")): return None     # transcribing needs the owner's own free Groq key: without it the queue waits instead of failing every five minutes
    for ep in ordenar(pendientes()):
        if ep.get("tipo") == "youtube": continue      # esos van por su carril (_tick_yt)
        dur = int(ep.get("duracion_s") or 0) or 3600
        if not cabe(dur): continue       # a shorter one further down may still fit
        if _de_otro_aun(ep["fecha"], ep["titulo"], ep.get("dias")): continue      # es del compañero (la mitad de los episodios, por su clave) y aún no ha pasado el tiempo de espera (1 h si es de los últimos 2 días)
        iniciar(ep, ep.get("idioma", "en"), ep["feed"])
        e, us = _usos(); save(COLA_ESTADO, {**e, "usos": us + [[time.time(), dur]]}); return ep
    return None

def _yt_canales():
    try:
        import yt_canales as YT; return YT.canales()
    except Exception: return []

def _yt_estado():
    try:
        import yt_canales as YT; s = YT.estado(); return {k: s.get(k) for k in ("running", "titulo", "podcast", "ok", "error", "fin", "fallos_seguidos")}
    except Exception: return {}

def cola_vista():
    """The queue panel of the Podcasts page."""
    c = cola_conf(); ps = pendientes(); now = time.time(); _, us = _usos(); ps_g = [e for e in ps if e.get("tipo") != "youtube"]; sig = next((e for e in ordenar(ps_g) if cabe(int(e.get("duracion_s") or 0) or 3600)), None)
    return {"activa": c["activa"], "sin_clave": not os.path.exists(os.path.join(ROOT, ".secrets", "groq.json")), "feeds": [{"nombre": f["nombre"], "url": f["url"], "excluido": f["url"] in c["excluidos"]} for f in feeds()],
            "pendientes": [sum(1 for e in ps_g if e["cubo"] == i) for i in range(3)], "cubos": CUBOS, "yt_pendientes": sum(1 for e in ps if e.get("tipo") == "youtube"), "canales_yt": [{"id": c["id"], "nombre": c["nombre"], "activa": c.get("activa", True)} for c in _yt_canales()], "yt": _yt_estado(),
            "hora_h": round(sum(s for t, s in us if now - t < 3600) / 3600, 1), "dia_h": round(sum(s for _, s in us) / 3600, 1), "limite_dia_h": round(ASD * MARGEN / 3600, 1),
            "siguiente": {"titulo": sig["titulo"], "fecha": sig["fecha"], "podcast": sig["podcast"]} if sig else None, "ocupado": bool(estado().get("running"))}

def cola_ajustar(activa=None, excluir=None, incluir=None):
    c = cola_conf()
    if activa is not None: c["activa"] = bool(activa)
    if excluir and excluir not in c["excluidos"]: c["excluidos"].append(excluir)
    if incluir and incluir in c["excluidos"]: c["excluidos"].remove(incluir)
    save(COLA, c); _pend["t"] = 0; return cola_vista()

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if "--cola" in sys.argv:            # python podcasts.py --cola: what the queue would do (starts nothing)
        v = cola_vista(); print({k: v[k] for k in ("activa", "pendientes", "hora_h", "dia_h", "siguiente")})
        for e in ordenar(pendientes())[:15]: print(f"  [{CUBOS[e['cubo']][:8]}] {e['fecha']} · {int(e.get('duracion_s') or 0) // 60:>3} min · {e['podcast']}: {e['titulo'][:70]}")
    elif "--transcribir" in sys.argv: _correr()
    elif "--transcribir-yt" in sys.argv:
        import yt_canales as YT; YT.correr()
    elif "--canal-yt" in sys.argv:         # python podcasts.py --canal-yt @handle: añade un canal de YouTube para transcribir
        import yt_canales as YT; c = YT.anadir(sys.argv[sys.argv.index("--canal-yt") + 1]); print("canal:", c["nombre"], c["id"])
    elif "--sin-resumen" in sys.argv:      # python podcasts.py --sin-resumen: the episodes Claude still has to summarize
        for i, r, mi, w in sin_resumen(): print(f"{i}\t{mi} min\t{w}\t{r}")
    elif "--material" in sys.argv: print(material(sys.argv[sys.argv.index("--material") + 1]))       # python podcasts.py --material <transcript.json>
    elif "--guardar" in sys.argv:          # python podcasts.py --guardar <transcript.json> <borrador.md>
        i = sys.argv.index("--guardar"); k, n, mal = guardar(sys.argv[i + 1], sys.argv[i + 2]); print(f"guardado: {k} puntos comprobados, {n} descartados"); [print("  descartado:", x) for x in mal]
