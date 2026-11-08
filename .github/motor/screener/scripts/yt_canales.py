"""Canales de YouTube que se transcriben solos (owner, 5 November 2026: "te voy a pasar dos canales de YouTube donde ir transcribiendo; tienen prioridad por fecha los más recientes siempre; por si meto más canales
se van transcribiendo de más recientes hacia atrás, así si salen nuevos los tenemos al momento").
- Qué canales: data/podcasts/youtube_canales.json (empieza con 4SONS y Red & Blue Collectables). Añadir uno: `python podcasts.py --canal-yt @handle` (o su enlace).
- La lista de vídeos sale de la API oficial de YouTube (la misma clave de contenido.py: .secrets/youtube.json): la primera página (los 50 más nuevos) cada 15 minutos, las páginas antiguas una vez al día. Unas 10 unidades por canal y día de las 10.000.
- El texto NO sale del audio (esta app no baja nunca el audio de YouTube: sus condiciones lo prohíben, y no gasta Groq) sino de la transcripción que la propia página del vídeo ENSEÑA («Show transcript»), leída con el
  navegador oculto, un vídeo cada pocos minutos. Son los subtítulos automáticos de YouTube: peor calidad que Whisper (nombres de cartas, cifras); los resúmenes lo dicen. Sin subtítulos, se reintenta (12 h, y hasta 3 veces).
- Entra en la misma cola que los podcasts (podcasts.pendientes / ordenar: estrictamente por fecha) pero por su propio carril: no depende del cupo de Groq. El transcrito se guarda igual que los demás
  (data/transcripciones/<título>-<fecha>.json con «yt», «feed»: youtube:<canal>) y se sube a git para el compañero (compartir.py)."""
import datetime as dt, json, os, re, subprocess, sys, time
from common import P, ROOT, TZ, load, save

CANALES = P("podcasts", "youtube_canales.json"); ESTADO = P("state", "yt_job.json"); ARGS = P("state", "yt_args.json"); INTENTOS = P("podcasts", "yt_intentos.json")
MIN_SEG = 240                  # menos de 4 minutos: Shorts y clips, no se transcriben
ENTRE_VIDEOS = 240             # segundos mínimos entre dos arranques (un vídeo cada 4 minutos como mucho)
SEMILLA = [{"id": "UCMlIE3vG0J1J9CeFUBmy8-Q", "nombre": "4SONS", "handle": "@4sonstcg"}, {"id": "UC0GtXD9qAPbRVMt8UoNvTrA", "nombre": "Red & Blue Collectables", "handle": "@redbluecollectibles"}]


def ahora(): return dt.datetime.now(TZ)

def canales():
    c = load(CANALES, None)
    if c is None:
        c = [{**x, "uploads": "UU" + x["id"][2:], "activa": True, "paginas": 4} for x in SEMILLA]; save(CANALES, c)
    return c

def anadir(texto):
    """Añade un canal por su @handle, enlace o id (resuelto con la API de YouTube) y lo deja activo. Devuelve el canal."""
    import contenido
    c = contenido.resolver(texto)
    if not c: raise ValueError("No encuentro ese canal en YouTube.")
    L = canales()
    if not any(x["id"] == c["id"] for x in L): L.append({"id": c["id"], "nombre": c["nombre"], "handle": c["handle"], "uploads": c["uploads"], "activa": True, "paginas": 4}); save(CANALES, L)
    return c

def ajustar(cid, activa):
    """Enciende o apaga un canal (sin borrar nada de lo ya transcrito)."""
    L = canales()
    for c in L:
        if c["id"] == cid: c["activa"] = bool(activa)
    save(CANALES, L); return L

def _seg_iso(s):
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    return 0 if not m else int(m.group(1) or 0) * 86400 + int(m.group(2) or 0) * 3600 + int(m.group(3) or 0) * 60 + int(m.group(4) or 0)

def _pagina(canal, token=None):
    """Una página de la lista de subidas (50 vídeos, de más nuevo a más viejo) con su duración: 2 unidades de API."""
    import contenido
    q = {"part": "contentDetails", "playlistId": canal["uploads"], "maxResults": 50}
    if token: q["pageToken"] = token
    r = contenido.yt("playlistItems", **q); ids = [i["contentDetails"]["videoId"] for i in r.get("items", [])]
    out = {}
    if ids:
        for it in contenido.yt("videos", part="snippet,contentDetails", id=",".join(ids), maxResults=50).get("items", []):
            sn = it["snippet"]
            out[it["id"]] = {"id": it["id"], "titulo": sn.get("title", ""), "fecha": str(sn.get("publishedAt", ""))[:10], "duracion_s": _seg_iso(it["contentDetails"].get("duration")),
                             "vivo": sn.get("liveBroadcastContent", "none") != "none", "imagen": ((sn.get("thumbnails") or {}).get("medium") or {}).get("url")}
    return out, r.get("nextPageToken")

def listar(canal):
    """Los vídeos del canal, el más nuevo primero. La primera página se refresca cada 15 minutos; las antiguas (hasta «paginas») una vez al día. Nunca lanza: con error devuelve lo que había."""
    f = P("podcasts", f"yt_lista_{canal['id']}.json"); c = load(f, None) or {"t": 0, "t_hist": 0, "videos": {}}
    try:
        if time.time() - c["t"] > 900:
            v, tok = _pagina(canal); c["videos"].update(v); c["t"] = time.time(); c["token1"] = tok; save(f, c)
        if time.time() - c["t_hist"] > 86400 and c.get("token1"):
            tok = c["token1"]
            for _ in range(max(0, int(canal.get("paginas", 4)) - 1)):
                if not tok: break
                v, tok = _pagina(canal, tok); c["videos"].update(v)
            c["t_hist"] = time.time(); save(f, c)
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt): raise
        print("youtube lista:", canal.get("nombre"), str(e)[:120])
    return sorted(c["videos"].values(), key=lambda v: v["fecha"], reverse=True)

def _intentos(): return load(INTENTOS, {}) or {}

def descartado(v):
    """Vídeos que no toca transcribir: directos, Shorts y clips, o sin subtítulos hace poco (12 h entre intentos; tres intentos y se deja una semana)."""
    if v.get("vivo") or (v.get("duracion_s") or 0) < MIN_SEG: return True
    i = _intentos().get(v["id"])
    if not i or i.get("ok"): return False
    return time.time() - i["t"] < (7 * 86400 if i["n"] >= 3 else 12 * 3600)

def _marcar(vid, ok, motivo=""):
    d = _intentos(); i = d.get(vid, {"n": 0}); d[vid] = {"n": i["n"] + 1, "t": time.time(), "ok": ok, "motivo": motivo[:120]}; save(INTENTOS, d)

def _ts(txt):
    p = [int(x) for x in txt.strip().split(":") if x.strip().isdigit()]
    return p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else p[0] * 60 + p[1] if len(p) == 2 else 0

JS = """() => [...document.querySelectorAll('transcript-segment-view-model')].map(s => s.innerText)"""
JS_VIEJO = """() => [...document.querySelectorAll('ytd-transcript-segment-renderer')].map(s => ((s.querySelector('.segment-timestamp')||{}).innerText||'') + '\\n\\n' + ((s.querySelector('.segment-text')||{}).innerText||''))"""

def leer_transcripcion(vid):
    """Abre la página del vídeo con el navegador oculto, pulsa «Show transcript» y lee lo que enseña: [[segundos, texto]]. Lanza ValueError si el vídeo no tiene transcripción."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        try:
            ctx = b.new_context(locale="en-US", viewport={"width": 1280, "height": 900}); pg = ctx.new_page()
            pg.goto(f"https://www.youtube.com/watch?v={vid}", wait_until="domcontentloaded", timeout=60000); pg.wait_for_timeout(3000)
            for txt in ("Reject all", "Reject the use of cookies", "Rechazar todo"):      # el aviso de cookies de Europa: lo más privado
                try:
                    btn = pg.get_by_role("button", name=re.compile(txt, re.I)).first
                    if btn.is_visible(timeout=1200): btn.click(); pg.wait_for_timeout(2500); break
                except Exception: pass
            try: pg.locator("#expand, tp-yt-paper-button#expand").first.click(timeout=4000); pg.wait_for_timeout(800)
            except Exception: pass
            try: pg.get_by_role("button", name=re.compile(r"show transcript|mostrar transcripci", re.I)).first.click(timeout=6000)
            except Exception: raise ValueError("el vídeo no tiene transcripción (sin subtítulos)")
            filas = []
            for _ in range(16):      # hasta 8 s a que carguen los segmentos
                pg.wait_for_timeout(500); filas = pg.evaluate(JS) or pg.evaluate(JS_VIEJO)
                if filas: break
            if not filas: raise ValueError("la transcripción no cargó")
        finally: b.close()
    seg = []
    for f in filas:
        partes = [x.strip() for x in str(f).split("\n") if x.strip()]
        if len(partes) < 2 or not re.fullmatch(r"\d+(?::\d{2}){1,2}", partes[0]): continue
        texto = " ".join(partes[2:] if len(partes) > 2 and re.search(r"second|minute|hour|segundo|minuto|hora", partes[1], re.I) else partes[1:])
        texto = re.sub(r"\[(?:music|applause|laughter|música|aplausos)\]", " ", texto, flags=re.I); texto = re.sub(r"\s+", " ", texto).strip()
        if texto: seg.append([_ts(partes[0]), texto])
    if len(seg) < 5: raise ValueError("transcripción demasiado corta")
    return seg

# ------------------------------------------------------------------------------------------------------------- el carril de la cola
def estado():
    s = load(ESTADO, {}) or {}
    if s.get("running") and time.time() - s.get("beat", 0) > 600: s = {**s, "running": False, "ok": False, "error": "La lectura se quedó parada."}
    return s

def puede():
    """¿Toca arrancar otro vídeo? Ninguno en marcha, 4 minutos desde el último arranque y, tras 3 fallos seguidos, media hora de descanso."""
    s = estado()
    if s.get("running"): return False
    if time.time() - s.get("ultimo_inicio", 0) < ENTRE_VIDEOS: return False
    return not (s.get("fallos_seguidos", 0) >= 3 and time.time() - s.get("fin_t", 0) < 1800)

def iniciar(ep):
    """Arranca en segundo plano la lectura de la transcripción de un vídeo (python podcasts.py --transcribir-yt)."""
    ep = {k: ep.get(k) for k in ("titulo", "fecha", "duracion_s", "yt", "imagen", "podcast", "feed")}
    os.makedirs(P("state"), exist_ok=True); s = load(ESTADO, {}) or {}
    save(ARGS, {"ep": ep})
    save(ESTADO, {**s, "running": True, "beat": time.time(), "titulo": str(ep["titulo"])[:200], "podcast": ep.get("podcast"), "ultimo_inicio": time.time(), "started": ahora().isoformat(timespec="minutes"), "ok": None, "error": None})
    log = open(P("state", "yt.log"), "a", encoding="utf-8"); here = os.path.dirname(os.path.abspath(__file__))
    subprocess.Popen([sys.executable, os.path.join(here, "podcasts.py"), "--transcribir-yt"], cwd=here, env={**os.environ, "PYTHONIOENCODING": "utf-8"}, stdin=subprocess.DEVNULL,
                     stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

def correr():
    """El subproceso: lee la transcripción, la guarda como las demás y la sube a git para el compañero."""
    import podcasts as PC
    ep = (load(ARGS, {}) or {}).get("ep") or {}; vid = ep.get("yt"); s = load(ESTADO, {}) or {}
    try:
        seg = leer_transcripcion(vid)
        d = {"fecha": ep.get("fecha"), "titulo": ep.get("titulo"), "feed": ep.get("feed") or "", "podcast": ep.get("podcast"), "yt": vid, "duracion_s": ep.get("duracion_s") or int(seg[-1][0]),
             "fuente": "youtube-subtitulos", "imagen": ep.get("imagen"), "idioma": "en", "segmentos": seg}
        archivo = PC._slug(d["titulo"])[:80] + "-" + str(d["fecha"]) + ".json"; ruta = os.path.join(PC.DIRS[0], archivo)
        os.makedirs(PC.DIRS[0], exist_ok=True); json.dump(d, open(ruta, "w", encoding="utf-8"), ensure_ascii=False)
        try: import historial; historial.exportar_transcripcion(ruta)
        except Exception: pass
        _marcar(vid, True)
        save(ESTADO, {**(load(ESTADO, {}) or {}), "running": False, "ok": True, "fallos_seguidos": 0, "fin": ahora().isoformat(timespec="minutes"), "fin_t": time.time(), "palabras": sum(len(t.split()) for _, t in seg)})
        try: import oficina; oficina.registrar("podcast_cola", "Transcrito (YouTube): " + str(d["titulo"])[:90])
        except Exception: pass
        try: PC.CP.publicar_item("transcripciones", d["fecha"] + "-" + PC._slug(d["titulo"])[:40], {"archivo": archivo, "datos": d}, "Transcripción " + str(d["titulo"])[:60],
                                 "Transcrito y subido (YouTube, " + str(ep.get("podcast"))[:30] + "): " + str(d["titulo"])[:70] + ". No hace falta repetirlo: se importa solo.")
        except Exception as ex: print("compartir transcripción:", ex)
    except BaseException as e:
        motivo = str(e)[:200]; _marcar(vid, False, motivo)
        sin_sub = "transcripción" in motivo or "subtítulos" in motivo      # que un vídeo no tenga subtítulos no es un fallo del sistema: no cuenta para el descanso
        save(ESTADO, {**(load(ESTADO, {}) or {}), "running": False, "ok": False, "error": motivo, "fin": ahora().isoformat(timespec="minutes"), "fin_t": time.time(),
                      "fallos_seguidos": (s.get("fallos_seguidos", 0) if sin_sub else s.get("fallos_seguidos", 0) + 1)})
        if not sin_sub:
            try: import oficina; oficina.registrar("podcast_cola", "Falló (YouTube): " + motivo[:100], ok=False)
            except Exception: pass
        if isinstance(e, KeyboardInterrupt): raise


def pendientes_yt(hechos_ids):
    """Los vídeos de los canales que aún no tienen transcripción, con la misma forma que los episodios de podcast (podcasts.pendientes). Nunca lanza."""
    out = []; hoy = dt.date.today()
    try:
        for c in canales():
            if not c.get("activa", True): continue
            for v in listar(c):
                if v["id"] in hechos_ids or descartado(v): continue
                try: dias = (hoy - dt.date.fromisoformat(v["fecha"])).days
                except (TypeError, ValueError): dias = 9999
                out.append({"titulo": v["titulo"], "fecha": v["fecha"], "audio": None, "duracion_s": v["duracion_s"], "feed": "youtube:" + c["id"], "podcast": c["nombre"], "dias": dias,
                            "cubo": 0 if dias <= 30 else 1 if dias <= 90 else 2, "idioma": "en", "yt": v["id"], "imagen": v.get("imagen"), "tipo": "youtube"})
    except Exception as ex: print("youtube pendientes:", ex)
    return out
