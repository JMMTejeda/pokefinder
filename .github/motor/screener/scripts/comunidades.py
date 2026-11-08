"""Communities tab, phase 4 (owner, 2 November 2026: "foros, comunidades... todo dentro de Mercado"): what collectors say in forums, subreddits, public Telegram channels,
Bluesky and blogs, over the last week / month / three months.
Only OPEN, official or public routes: a Discourse forum's public JSON (Elite Fourum), an RSS/Atom feed (PokeBeach, blogs, Substack, Reddit's own RSS), the public web preview of a
Telegram channel (t.me/s/<channel>) and the Bluesky API with the owner's own app password (.secrets/bluesky.json). It never logs in to anything with a password, joins a server or
group, or reads what needs an account. Reddit allows only a few requests a minute on RSS: one request every 15 seconds, and it stops at the first "429" and goes on the next run.
Each item is a forum TOPIC (title, replies, views, last activity), a forum POST of the hottest topics, a feed entry, a Telegram message or a Bluesky post. Sets, Pokémon and the market
themes (30th anniversary, vintage, correction...) are read from the same dictionaries the YouTube tab uses (contenido.py).
Files: data/comunidades/fuentes.json (the sources, each can be switched off), posts.json (what was read), estado.json.
The server asks toca() every few minutes and starts "python comunidades.py" once a day after 07:00; «Actualizar ahora» in the app does it too.
A SUMMARY of what is going on (owner, 2 November 2026: "insights claros... guardando lo que ha ido saliendo, una vez al día", written by Claude, not Groq):
a scheduled Claude task every morning at 9:30 (after the 07:00 reading) runs «python comunidades.py --material», writes the summary with a link for every
point and saves it with «--guardar»; a Claude session does the same when the owner asks. Each summary is kept in data/comunidades/resumenes/ and the page
shows the history."""
import datetime as dt, hashlib, html, json, os, re, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from common import P, load, save, ROOT, TZ
import contenido as CT

DIR = P("comunidades"); UA = "PokeFinder/1.0 (personal market research; reads public pages slowly)"
KEEP_DAYS = 190           # six months at most, nothing older (owner, 2 November 2026)
SEED = [
    {"id": "elite", "nombre": "Elite Fourum", "tipo": "discourse", "url": "https://www.elitefourum.com", "cats": ["Market", "Collecting", "Grading", "Articles", "News & Links"], "activo": True,
     "siempre": [32069]},      # Gold Star and Neo Shining Price Tracker
    {"id": "pokebeach-mercado", "nombre": "PokeBeach · Mercado", "tipo": "rss", "url": "https://www.pokebeach.com/forums/forums/market-pokemon-tcg.18/index.rss", "activo": True},
    {"id": "pokebeach-foros", "nombre": "PokeBeach · Foros", "tipo": "rss", "url": "https://www.pokebeach.com/forums/forums/-/index.rss", "activo": True},
    {"id": "reddit-pokeinvesting", "nombre": "Reddit · r/PokeInvesting", "tipo": "reddit", "sub": "PokeInvesting", "activo": True},
]
BSKY_QUERIES = ["pokemon investing", "pokemon tcg market", "pokemon sealed", "psa 10 pokemon", "30th anniversary pokemon", "pokemon cards crash"]

def today(): return dt.datetime.now(TZ).date().isoformat()
def now_iso(): return dt.datetime.now(TZ).isoformat(timespec="minutes")
def estado(**kw):
    e = load(os.path.join(DIR, "estado.json"), {}) or {}; e.update(kw); save(os.path.join(DIR, "estado.json"), e); return e
def en_marcha():
    e = load(os.path.join(DIR, "estado.json"), {}) or {}
    return bool(e.get("running")) and time.time() - e.get("beat", 0) < 900

def fuentes():
    L = load(os.path.join(DIR, "fuentes.json"), None)
    if L is None: L = [dict(s) for s in SEED]; save(os.path.join(DIR, "fuentes.json"), L)
    return L

def http(url, accept="*/*", data=None, headers=None, timeout=30):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept": accept, **(headers or {})})
    r = urllib.request.urlopen(req, timeout=timeout); return r.read().decode("utf-8", "replace")

def limpio(t, n=900):
    t = re.sub(r"<(?:script|style).*?</(?:script|style)>", " ", t or "", flags=re.S | re.I); t = re.sub(r"<br\s*/?>|</p>", "\n", t, flags=re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t))).strip()[:n]

def dia(s):
    try: return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).date().isoformat()
    except ValueError: pass
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(s).date().isoformat()
    except Exception: return None

# ---- the readers
def leer_discourse(s, corte):
    base = s["url"].rstrip("/"); out = []
    cats = json.loads(http(base + "/categories.json", "application/json"))["category_list"]["categories"]
    quiero = {c.lower() for c in s.get("cats") or []}
    cats = [c for c in cats if not quiero or c["name"].lower() in quiero]
    calientes = []
    for c in cats:
        for pg in range(50):
            d = json.loads(http(f"{base}/c/{c['slug']}/{c['id']}.json?page={pg}", "application/json")); ts = d["topic_list"]["topics"]
            if not ts: break
            vivos = 0
            for t in ts:
                u = dia(t.get("last_posted_at") or t.get("created_at"))
                if not u or u < corte: continue
                vivos += 1
                out.append({"id": f"{s['id']}-t{t['id']}", "fuente": s["id"], "tipo": "hilo", "t": t["title"], "x": t["title"], "f": dia(t.get("created_at")) or u, "u": u, "r": t.get("posts_count", 0) - 1,
                            "v": t.get("views", 0), "l": t.get("like_count", 0), "url": f"{base}/t/{t['slug']}/{t['id']}", "cat": c["name"]})
                if t.get("posts_count", 0) >= 40: calientes.append((t["id"], t["slug"], t["title"], t.get("posts_count", 0), u, dia(t.get("created_at")) or u))
            if not vivos: break
            time.sleep(0.6)
    # the posts of the hottest topics of the last two weeks (the market threads are daily commentary), and of the topics the owner always wants
    # read even when they are not among the biggest ("siempre" in fuentes.json: the Gold Star and Neo Shining Price Tracker, owner, 2 November 2026)
    # the 6 biggest with recent activity, and up to 4 topics opened in the last 3 weeks with most posts (the news of the week: a fake slab on Fanatics,
    # 424 posts in 5 days, was not among the 6 biggest of all time)
    visto = set(); hace = lambda d: (dt.date.fromisoformat(today()) - dt.timedelta(days=d)).isoformat()
    nuevos = [c for c in sorted(calientes, key=lambda x: -x[3]) if c[5] >= hace(21) and c[4] >= hace(14)][:4]
    grandes = [c for c in sorted(calientes, key=lambda x: -x[3]) if c[4] >= hace(14) and c not in nuevos][:6]
    for tid, slug, titulo, n, u, cr in nuevos + grandes:
        visto.add(tid)
        try: _mensajes(s, base, tid, corte, out, "hilo nuevo" if cr >= hace(21) else "hilo caliente")
        except Exception: continue
    for tid in s.get("siempre") or []:
        if tid in visto: continue
        try: _mensajes(s, base, tid, corte, out, "hilo seguido")
        except Exception: continue
    return out

def _mensajes(s, base, tid, corte, out, cat, n=60):
    """The last n posts of one Discourse topic, as items of type «mensaje»."""
    d = json.loads(http(f"{base}/t/{tid}.json?track_visit=false", "application/json")); ids = d["post_stream"]["stream"][-n:]; slug, titulo = d["slug"], d["title"]
    for i in range(0, len(ids), 20):
        q = "&".join(f"post_ids[]={x}" for x in ids[i:i + 20]); r = json.loads(http(f"{base}/t/{tid}/posts.json?{q}", "application/json")); time.sleep(0.6)
        for p in r["post_stream"]["posts"]:
            f = dia(p["created_at"])
            if f and f >= corte and len(limpio(p.get("cooked"), 400)) > 25:
                out.append({"id": f"{s['id']}-p{p['id']}", "fuente": s["id"], "tipo": "mensaje", "t": titulo, "x": limpio(p.get("cooked"), 900), "f": f, "u": f, "r": p.get("reply_count", 0),
                            "v": 0, "l": next((a["count"] for a in p.get("actions_summary", []) if a.get("id") == 2), 0), "url": f"{base}/t/{slug}/{tid}/{p['post_number']}", "cat": cat})

def leer_feed(s, corte, url=None, prefijo=None):
    x = http(url or s["url"], "application/rss+xml, application/atom+xml, text/xml"); x = re.sub(r'\sxmlns="[^"]+"', "", x, count=1); root = ET.fromstring(x); out = []
    for it in root.iter("item"):
        f = dia((it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date") or "")); t = (it.findtext("title") or "").strip()
        if not f or f < corte or not t: continue
        link = (it.findtext("link") or "").strip(); out.append({"id": f"{s['id']}-{hashlib.sha1((link or t).encode()).hexdigest()[:12]}", "fuente": s["id"], "tipo": "hilo", "t": t, "x": t + ". " + limpio(it.findtext("description") or "", 500), "f": f, "u": f, "r": 0, "v": 0, "l": 0, "url": link, "cat": ""})
    for it in root.iter("entry"):
        f = dia(it.findtext("updated") or it.findtext("published") or ""); t = (it.findtext("title") or "").strip(); le = it.find("link"); link = le.get("href") if le is not None else ""
        if not f or f < corte or not t: continue
        out.append({"id": f"{s['id']}-{hashlib.sha1((link or t).encode()).hexdigest()[:12]}", "fuente": s["id"], "tipo": "hilo", "t": t, "x": t + ". " + limpio(it.findtext("content") or it.findtext("summary") or "", 500), "f": f, "u": f, "r": 0, "v": 0, "l": 0, "url": link, "cat": ""})
    return out

def leer_reddit(s, corte):
    """Reddit's own RSS: the newest 100 and the top of the week and of the month, one request every 15 s; the first 429 stops it (it goes on the next run)."""
    sub, out = s["sub"], []
    for ruta in (f"new.rss?limit=100", f"top.rss?t=week&limit=100", f"top.rss?t=month&limit=100"):
        try: out += leer_feed(s, corte, f"https://www.reddit.com/r/{sub}/{ruta}")
        except urllib.error.HTTPError as e:
            if e.code == 429: break
        time.sleep(15)
    return out

def leer_telegram(s, corte):
    canal, out, antes = s["canal"], [], None
    for _ in range(12):
        h = http(f"https://t.me/s/{canal}" + (f"?before={antes}" if antes else "")); bloques = re.findall(r'<div class="tgme_widget_message_wrap.*?(?=<div class="tgme_widget_message_wrap|$)', h, flags=re.S)
        if not bloques: break
        ids, viejo = [], False
        for b in bloques:
            m = re.search(r'data-post="[^/]+/(\d+)"', b); tm = re.search(r'<time[^>]*datetime="([^"]+)"', b); tx = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', b, flags=re.S)
            if not (m and tm): continue
            ids.append(int(m.group(1))); f = dia(tm.group(1))
            if not f: continue
            if f < corte: viejo = True; continue
            if tx and len(limpio(tx.group(1))) > 20:
                t = limpio(tx.group(1), 900); out.append({"id": f"{s['id']}-{m.group(1)}", "fuente": s["id"], "tipo": "mensaje", "t": t[:90], "x": t, "f": f, "u": f, "r": 0, "v": 0, "l": 0, "url": f"https://t.me/{canal}/{m.group(1)}", "cat": ""})
        if viejo or not ids: break
        antes = min(ids); time.sleep(1.5)
    return out

RUIDO_BSKY = re.compile(r"^\s*(?:ad:|for sale|wts\b|wtb\b|\[?sponsored)|#ad\b|#sponsored|link in bio|use code|discount code|giveaway|follow (?:me|us) for|affiliate", re.I)   # ads and sales posts are not conversation
def bsky_ok(c): return bool(c and str(c.get("handle", "")).strip() and not str(c.get("handle")).startswith("PEGA") and str(c.get("app_password", "")).strip() and not str(c.get("app_password")).startswith("PEGA"))

def leer_bluesky(s, corte):
    cred = load(os.path.join(ROOT, ".secrets", "bluesky.json"), None)
    if not bsky_ok(cred): raise RuntimeError("falta rellenar .secrets/bluesky.json (handle y app_password)")
    ses = json.loads(http("https://bsky.social/xrpc/com.atproto.server.createSession", "application/json", json.dumps({"identifier": cred["handle"], "password": cred["app_password"]}).encode(), {"Content-Type": "application/json"}))
    tok = {"Authorization": "Bearer " + ses["accessJwt"]}; out = []
    for q in ([s["q"]] if s.get("q") else BSKY_QUERIES):
        cur = None
        for _ in range(3):
            u = "https://bsky.social/xrpc/app.bsky.feed.searchPosts?" + urllib.parse.urlencode({"q": q, "limit": 100, "sort": "latest", "since": corte + "T00:00:00Z", **({"cursor": cur} if cur else {})})
            d = json.loads(http(u, "application/json", headers=tok)); time.sleep(1)
            for p in d.get("posts", []):
                f = dia(p["record"].get("createdAt")); tx = p["record"].get("text") or ""
                if f and len(tx) > 20 and not RUIDO_BSKY.search(tx) and tx.count("#") <= 6: out.append({"id": f"{s['id']}-{p['cid']}", "fuente": s["id"], "tipo": "mensaje", "t": tx[:90], "x": tx[:700], "f": f, "u": f, "r": p.get("replyCount", 0), "v": 0, "l": p.get("likeCount", 0),
                                                   "url": "https://bsky.app/profile/%s/post/%s" % (p["author"]["handle"], p["uri"].rsplit("/", 1)[-1]), "cat": q})
            cur = d.get("cursor")
            if not cur: break
    return out

LECTORES = {"discourse": leer_discourse, "rss": leer_feed, "reddit": leer_reddit, "telegram": leer_telegram, "bluesky": leer_bluesky}

def actualizar():
    corte = (dt.date.fromisoformat(today()) - dt.timedelta(days=KEEP_DAYS)).isoformat()
    L = [s for s in fuentes() if s.get("activo")]; P_ = load(os.path.join(DIR, "posts.json"), {}) or {}; res = {}
    estado(total=len(L), done=0, message=f"Leyendo comunidades (0/{len(L)})")
    for i, s in enumerate(L):
        try:
            its = LECTORES[s["tipo"]](s, corte)
            for it in its: P_[it["id"]] = it
            res[s["id"]] = len(its); s["error"] = None; s["ultima_lectura"] = now_iso()
        except Exception as e:
            s["error"] = str(e)[:160]; res[s["id"]] = f"error: {s['error']}"
        estado(done=i + 1, beat=time.time(), message=f"Leyendo comunidades ({i + 1}/{len(L)})")
    todos = fuentes()
    for s in todos:
        for l in L:
            if l["id"] == s["id"]: s["error"], s["ultima_lectura"] = l.get("error"), l.get("ultima_lectura", s.get("ultima_lectura"))
    save(os.path.join(DIR, "fuentes.json"), todos)
    P_ = {k: v for k, v in P_.items() if v["u"] >= corte}
    save(os.path.join(DIR, "posts.json"), P_)
    return {"items": len(P_), "fuentes": res}

# ---- sources the owner adds himself
def fuente_añadir(texto):
    t = (texto or "").strip()
    if not t: raise ValueError("Pega el enlace o el nombre de la fuente")
    L = fuentes(); nuevo = None
    m = re.search(r"(?:reddit\.com)?/?\br/([A-Za-z0-9_]{2,30})", t)
    if m and ("reddit" in t or t.lower().startswith("r/")): nuevo = {"tipo": "reddit", "sub": m.group(1), "nombre": "Reddit · r/" + m.group(1)}
    elif re.search(r"t\.me/(?:s/)?([A-Za-z0-9_]{4,})", t): c = re.search(r"t\.me/(?:s/)?([A-Za-z0-9_]{4,})", t).group(1); nuevo = {"tipo": "telegram", "canal": c, "nombre": "Telegram · " + c}
    elif t.lower().startswith("bluesky:") or t.lower().startswith("bsky:"): q = t.split(":", 1)[1].strip(); nuevo = {"tipo": "bluesky", "q": q, "nombre": "Bluesky · «" + q + "»"}
    elif t.startswith("http"):
        try: json.loads(http(t.rstrip("/") + "/categories.json", "application/json", timeout=20))["category_list"]; nuevo = {"tipo": "discourse", "url": t.rstrip("/"), "nombre": urllib.parse.urlparse(t).netloc, "cats": []}
        except Exception:
            try: leer_feed({"id": "x"}, "1900-01-01", t); nuevo = {"tipo": "rss", "url": t, "nombre": urllib.parse.urlparse(t).netloc + " (RSS)"}
            except Exception: raise ValueError("No es un foro Discourse ni un RSS/Atom que pueda leer. Prueba con su enlace de RSS (suele acabar en /feed o .rss).")
    if not nuevo: raise ValueError("No reconozco eso. Admito: un subreddit (r/nombre), un canal público de Telegram (t.me/nombre), «bluesky: búsqueda», un foro Discourse o el enlace de un RSS/Atom.")
    nuevo["id"] = re.sub(r"[^a-z0-9]+", "-", nuevo["nombre"].lower()).strip("-")[:40]; nuevo["activo"] = True
    if any(x["id"] == nuevo["id"] for x in L): raise ValueError("Esa fuente ya está en la lista")
    L.append(nuevo); save(os.path.join(DIR, "fuentes.json"), L); return nuevo

def fuente_ajustar(id, activo=None, quitar=False):
    L = fuentes()
    if quitar: L = [s for s in L if s["id"] != id]
    else:
        for s in L:
            if s["id"] == id and activo is not None: s["activo"] = bool(activo)
    save(os.path.join(DIR, "fuentes.json"), L); return L

def hecho_hoy(): return (load(os.path.join(DIR, "estado.json"), {}) or {}).get("fecha") == today()
def toca():
    if en_marcha() or dt.datetime.now(TZ).hour < 7 or hecho_hoy(): return False
    e = load(os.path.join(DIR, "estado.json"), {}) or {}
    return not (e.get("error") and str(e.get("finished") or "")[:10] == today())

def lanzar():
    if en_marcha(): return estado()
    os.makedirs(P("state"), exist_ok=True); estado(running=True, beat=time.time(), started=now_iso(), message="Empezando…", error=None)
    log = open(P("state", "comunidades.log"), "a", encoding="utf-8"); here = os.path.dirname(os.path.abspath(__file__))
    subprocess.Popen([sys.executable, os.path.join(here, "comunidades.py")], cwd=here, env={**os.environ, "PYTHONIOENCODING": "utf-8"}, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return estado()

# ---- what the page shows
def view(dias=30, fuente="", q=""):
    dias = dias if dias in (7, 30, 90) else 30
    F = fuentes(); P_ = load(os.path.join(DIR, "posts.json"), {}) or {}; hoy = dt.date.fromisoformat(today())
    nombre = {s["id"]: s["nombre"] for s in F}
    age = lambda it: (hoy - dt.date.fromisoformat(it["u"])).days
    items = [dict(v) for v in P_.values() if (not fuente or v["fuente"] == fuente) and v["fuente"] in nombre]
    palabras = [w for w in CT._norm(q).split() if len(w) >= 2]
    if palabras: items = [v for v in items if all(w in CT._norm(v["t"] + " " + v["x"]) for w in palabras)]
    ventana = [v for v in items if age(v) <= dias]
    for v in items: v["sets"], v["poke"] = CT.entidades(v["t"] + " " + v["x"][:500]); v["fuente_n"] = nombre[v["fuente"]]
    def ranking(campo):
        ag = {}
        for v in items:
            a = age(v)
            for e in v[campo]:
                x = ag.setdefault(e, {"e": e, "n": 0, "antes": 0, "canales": set(), "vistas": 0, "n14": 0, "n60": 0, "min_age": 99999, "sem": [0] * 26, "ej": None, "sleeper": 0, "aviso": 0, "vpd": None})
                x["min_age"] = min(x["min_age"], a)
                if a <= 14: x["n14"] += 1
                if a <= 60: x["n60"] += 1
                if a // 7 < 26: x["sem"][a // 7] += 1
                if a <= dias:
                    x["n"] += 1; x["canales"].add(v["fuente_n"]); x["vistas"] += v["v"] + v["r"] * 20
                    if not x["ej"] or v["r"] + v["v"] / 50 > x["ej"]["peso"]: x["ej"] = {"url": v["url"], "t": v["t"][:90], "v": v["v"], "peso": v["r"] + v["v"] / 50, "fuente": v["fuente_n"]}
                elif a <= 2 * dias: x["antes"] += 1
        def veredicto(x):
            rec, prev = x["n14"] / 14, max(0, x["n60"] - x["n14"]) / 46
            if x["n14"] >= 2 and rec > 1.5 * prev: return "subiendo"
            if x["n14"] == 0 and x["n60"] > 0: return "enfriando"
            if x["n14"] == 0: return "antiguo"
            return "estable"
        fecha = lambda d: (hoy - dt.timedelta(days=d)).isoformat()
        return sorted((dict(x, canales=len(x["canales"]), ultima=fecha(x["min_age"]), hace=x["min_age"], serie=x["sem"][::-1], estado=veredicto(x)) for x in ag.values() if x["n"] >= 2), key=lambda x: (-x["canales"], -x["n"]))[:30]
    temas = CT.temas_resumen([(age(v), v["t"] + " " + v["x"][:500], 1 + v["r"], v["fuente_n"], v["url"], v["t"]) for v in items], dias)
    hilos = sorted((v for v in ventana if v["tipo"] == "hilo" and (v["r"] or v["v"])), key=lambda v: -(v["r"] * 30 + v["v"] / 20))[:20]
    cut = lambda v: {k: v[k] for k in ("t", "x", "f", "u", "r", "v", "l", "url", "fuente_n", "tipo", "cat")} | {"dias": age(v)}
    rec = sorted(ventana, key=lambda v: (v["u"], v["r"]), reverse=True)[:100 if palabras or fuente else 60]
    fs = []
    for s in F:
        mios = [v for v in P_.values() if v["fuente"] == s["id"]]
        fs.append({"id": s["id"], "nombre": s["nombre"], "tipo": s["tipo"], "activo": s.get("activo", True), "error": s.get("error"), "ultima_lectura": s.get("ultima_lectura"), "items": len(mios),
                   "items_periodo": sum(1 for v in mios if age(v) <= dias), "ultima": max((v["u"] for v in mios), default=None)})
    bsky = bsky_ok(load(os.path.join(ROOT, ".secrets", "bluesky.json"), None))
    return {"estado": {**(load(os.path.join(DIR, "estado.json"), {}) or {}), "running": en_marcha()}, "dias": dias, "fuente": fuente, "q": q, "fuentes": fs, "temas": temas, "sets": ranking("sets"), "pokemon": ranking("poke"),
            "hilos": [cut(v) for v in hilos], "recientes": [cut(v) for v in rec], "n_periodo": len(ventana), "n_total": len(items), "bluesky_creds": bsky, "hoy": today(),
            "resumenes": resumenes()[:90], "resumen": resumen()}

# ---- the summary of what is going on: written by Claude (a scheduled Claude task every morning at 9:30, or a session when the owner asks), saved here
RES = os.path.join(DIR, "resumenes")
INSTRUCCIONES = """Resumen de comunidades de PokéFinder para Fernando (coleccionista e inversor, sobre todo Gold Star y Shining japonesas y vintage), en español:
- Escribe TAKES, no un resumen de hilos: cada punto es una afirmación o dato concreto que alguien pueda usar, no «en el hilo X hablan de Y». Formato: «- **Título que ya dice el take:** qué se dice, con la cifra, la carta, el vendedor o la casa de gradeo, y la fecha. *Fiabilidad:* dato con cifra / opinión / rumor / experiencia de un usuario. Por qué importa a Fernando en una frase. ([hilo](url))».
- «## Lo importante» (3 a 5 takes, los de más peso) y después solo las secciones con material: «## Precios y mercado», «## Fraude y avisos», «## Gradeo», «## Japón», «## Novedades».
- Qué vale: ventas o pujas con precio, cambios de política o plazos de PSA/CGC/BGS, métodos de falsificación y cómo se detectan, supply y población, movimientos de Gold Star, Shining y vintage, y lo que cuenta alguien que ha comprado o vendido de verdad. Qué NO: fotos de colecciones, bromas, quién cae bien, debates sin dato. Si un hilo solo es charla, no lo menciones.
- Si el material trae «RESUMEN ANTERIOR», no repitas esos puntos: cuenta lo nuevo o lo que ha cambiado (y di que cambió). Si casi nada es nuevo, dilo en una línea en lugar de rellenar.
- Cada afirmación con su enlace del material; una cifra sin enlace no se pone. Si dos usuarios se contradicen, pon las dos posturas. Nada de consejos de inversión: di qué vigilar. 350 a 600 palabras, sin tablas."""

def material(dias=7, tope=60000):
    """(text, n): what the summary is written from: the new topics of the last weeks by echo, the latest posts of the followed and hottest topics, Reddit and
    PokeBeach, each with its link. Bluesky is left out: almost all of it is anniversary posts, shop deals and drawings (owner's review, 2 November 2026)."""
    P_ = load(os.path.join(DIR, "posts.json"), {}) or {}; corte = (dt.date.fromisoformat(today()) - dt.timedelta(days=dias)).isoformat()
    X = [v for v in P_.values() if v["u"] >= corte]; partes = []
    hace21 = (dt.date.fromisoformat(today()) - dt.timedelta(days=21)).isoformat()
    elite = [v for v in X if v["tipo"] == "hilo" and v["fuente"] == "elite"]
    nuevos = sorted((v for v in elite if v["f"] >= hace21), key=lambda v: -(v["r"] * 3 + v["l"]))[:25]
    viejos = sorted((v for v in elite if v["f"] < hace21), key=lambda v: -(v["r"] * 3 + v["l"]))[:15]
    partes.append("### Hilos NUEVOS de Elite Fourum (abiertos en 3 semanas) por eco: título · creado · respuestas · me gusta · enlace\n" + "\n".join(
        f"- {v['t']} · creado {v['f']} · {v['r']} resp · {v['l']} ♥ · {v['url']}" for v in nuevos))
    por = {}
    for v in sorted((v for v in X if v["tipo"] == "mensaje" and v["fuente"] != "bluesky"), key=lambda v: v["f"]): por.setdefault((v.get("cat") or "", v["t"]), []).append(v)
    orden = {"hilo nuevo": 0, "hilo seguido": 1}
    for (cat, t), L in sorted(por.items(), key=lambda kv: (orden.get(kv[0][0], 2), -sum(v["l"] for v in kv[1]))):
        partes.append(f"### Mensajes del hilo «{t}» ({cat or 'hilo caliente'}), por fecha\n" + "\n".join(f"- [{v['f']}] ♥{v['l']} {v['x'][:600]} ({v['url']})" for v in L[-40:]))
    partes.append("### Hilos de siempre de Elite Fourum con actividad\n" + "\n".join(f"- {v['t']} · {v['r']} resp · {v['url']}" for v in viejos))
    red = sorted((v for v in X if v["fuente"].startswith("reddit") and v["f"] >= corte), key=lambda v: v["f"], reverse=True)[:80]
    partes.append("### Reddit (título · texto · enlace)\n" + "\n".join(f"- [{v['f']}] {v['t'][:140]} · {v['x'][len(v['t']):][:300].strip(' .')} ({v['url']})" for v in red))
    pb = list({v["t"]: v for v in X if v["fuente"].startswith("pokebeach")}.values())[:40]
    partes.append("### PokeBeach (noticias y hilos)\n" + "\n".join(f"- [{v['f']}] {v['t'][:150]} ({v['url']})" for v in pb))
    texto = ""
    for p in partes:
        if len(texto) + len(p) > tope: p = p[:max(0, tope - len(texto))]
        texto += p + "\n\n"
    return texto, len(X)

# ---- v2 (owner, 5 November 2026: «el barrido de comunidades no está sacando muchos buenos takes como los podcasts»). The first version spent almost the whole budget on the 3 hottest
# threads (their last 40 messages, mostly banter) and the cut left Reddit and PokeBeach out. Now every source gets its own budget, a message is chosen for its substance
# (figures, grading/fraud/sales vocabulary, replies that got ♥, length) and not for being the newest, and the previous summary is included so the new one reports what CHANGED.
SUSTANCIA = re.compile(r"\b(sold|sells?|bought|paid|price[sd]?|asking|offer|bid|comp|pop(?:ulation)?|psa|bgs|cgc|tag|ars|grade[sd]?|grading|regrade|crack|cert|fake|counterfeit|altered|scam|refund|policy|fee|turnaround|snkrdunk|mercari|yahoo|ebay|fanatics|goldin|heritage|pwcc|alt\b|auction|gold star|shining|vintage|shadowless|1st edition|neo|e-?reader|japanese|jpn|jp\b|sealed|booster|box|etb|reprint|print run|supply|demand|dump|crash|rally|spike|drop|up \d+|down \d+)\b|[$€£¥]\s?\d|\d[\d,.]*\s?(?:k\b|usd|eur|yen|%)", re.I)
RUIDO_MSG = re.compile(r"^(?:lol|haha|this|same|\+1|agreed?|nice|congrats|thanks?|wow|rip|based|true|facts?)\b[^\n]{0,40}$", re.I)

def _puntos(v):
    """How much a forum message is worth as material: figures and market vocabulary first, then likes and length; banter and one-liners score nothing."""
    x = v["x"].strip()
    if len(x) < 60 and v["l"] < 10 or RUIDO_MSG.match(x): return 0
    s = len(SUSTANCIA.findall(x)) * 3 + min(v["l"], 40) * 0.5 + min(len(x), 500) / 100
    return s + (3 if re.search(r"[$€£¥]\s?\d|\d\s?(?:k|usd|eur|yen|%)\b", x, re.I) else 0)

def _anterior(chars=2200):
    """The latest saved summary, trimmed: it is given so the new one says what is NEW and does not repeat the old points."""
    try: fs = sorted(f for f in os.listdir(RES) if f.endswith(".json"))
    except OSError: return ""
    return (load(os.path.join(RES, fs[-1]), {}) or {}).get("texto", "")[:chars] if fs else ""

def material_v2(dias=7, tope=52000, por_hilo=10, hilos=9):
    P_ = load(os.path.join(DIR, "posts.json"), {}) or {}; hoy = dt.date.fromisoformat(today()); corte = (hoy - dt.timedelta(days=dias)).isoformat()
    X = [v for v in P_.values() if v["u"] >= corte]; partes = []
    elite = [v for v in X if v["tipo"] == "hilo" and v["fuente"] == "elite"]
    hace21 = (hoy - dt.timedelta(days=21)).isoformat()
    nuevos = sorted((v for v in elite if v["f"] >= hace21), key=lambda v: -(v["r"] * 3 + v["l"]))[:18]
    partes.append(("Hilos NUEVOS de Elite Fourum (3 semanas) por eco: título · creado · respuestas · ♥ · enlace", 5000, [f"- {v['t'][:120]} · {v['f']} · {v['r']} resp · {v['l']} ♥ · {v['url']}" for v in nuevos]))
    # messages: per thread, the ones with substance (not the newest), shown in date order; threads ranked by how much substance they carry
    por = {}
    for v in X:
        if v["tipo"] == "mensaje" and v["fuente"] != "bluesky": por.setdefault((v.get("cat") or "", v["t"]), []).append(v)
    ranking = []
    for k, L in por.items():
        buenos = sorted(((_puntos(v), v) for v in L), key=lambda a: -a[0])
        buenos = [v for p, v in buenos if p >= 3][:por_hilo]
        if buenos: ranking.append((sum(_puntos(v) for v in buenos), k, sorted(buenos, key=lambda v: v["f"]), len(L)))
    for _, (cat, t), L, total in sorted(ranking, key=lambda a: -a[0])[:hilos]:
        partes.append((f"Hilo «{t}» ({cat or 'hilo caliente'}): {len(L)} mensajes elegidos de {total}, por fecha", 4200, [f"- [{v['f']}] ♥{v['l']} {v['x'][:520]} ({v['url']})" for v in L]))
    red = sorted((v for v in X if v["fuente"].startswith("reddit")), key=lambda v: -(v.get("r", 0) * 2 + v["l"]))[:45]
    partes.append(("Reddit (fecha · título · texto · enlace), los de más eco", 9000, [f"- [{v['f']}] {v['t'][:140]} · {v['x'][len(v['t']):][:350].strip(' .')} ({v['url']})" for v in red]))
    pb = list({v["t"]: v for v in X if v["fuente"].startswith("pokebeach")}.values())
    pb.sort(key=lambda v: v["f"], reverse=True)
    partes.append(("PokeBeach (noticias y hilos, más recientes primero)", 5000, [f"- [{v['f']}] {v['t'][:150]} ({v['url']})" for v in pb[:35]]))
    ant = _anterior()
    out = ""
    for tit, cupo, lineas in partes:
        cuerpo = ""
        for ln in lineas:
            if len(cuerpo) + len(ln) > cupo: break
            cuerpo += ln + "\n"
        if cuerpo: out += f"### {tit}\n{cuerpo}\n"
    if ant: out += "### RESUMEN ANTERIOR (no repitas sus puntos: cuenta solo lo que ha cambiado o es nuevo desde entonces)\n" + ant + "\n"
    return out[:tope + 2500], len(X)

def guardar_resumen(texto, autor="Claude", dias=7):
    """Saves a summary written by Claude into data/comunidades/resumenes/<date-time>.json; a link to a page that is not in what was read is dropped."""
    mat, n = material(dias); validas = set(re.findall(r"https?://[^\s)]+", mat)) | {v["url"] for v in (load(os.path.join(DIR, "posts.json"), {}) or {}).values()}
    texto = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", lambda m: m.group(0) if m.group(2) in validas or re.sub(r"/\d+$", "", m.group(2)) in validas else m.group(1), texto.strip())
    r = {"id": dt.datetime.now(TZ).strftime("%Y-%m-%d-%H%M"), "fecha": today(), "hecho": now_iso(), "dias": dias, "autor": autor, "elementos": n, "texto": texto}
    os.makedirs(RES, exist_ok=True); save(os.path.join(RES, r["id"] + ".json"), r); return r

def resumenes():
    """[{id, fecha, hecho, autor, elementos}] newest first."""
    fs = sorted((f for f in os.listdir(RES) if f.endswith(".json")), reverse=True) if os.path.isdir(RES) else []
    return [{k: (load(os.path.join(RES, f), {}) or {}).get(k) for k in ("id", "fecha", "hecho", "autor", "elementos", "dias")} for f in fs]

def resumen(id=None):
    L = resumenes()
    if not L: return None
    id = id if id and any(x["id"] == id for x in L) else L[0]["id"]
    return load(os.path.join(RES, re.sub(r"[^0-9-]", "", id) + ".json"), None)

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1 and sys.argv[1] == "--material":      # what Claude reads to write the summary
        t, n = material_v2(int(sys.argv[2]) if len(sys.argv) > 2 else 7); print(INSTRUCCIONES + "\n\n" + t); sys.exit(0)
    if len(sys.argv) > 2 and sys.argv[1] == "--guardar":       # python comunidades.py --guardar resumen.md ["Claude · tarea diaria"]
        with open(sys.argv[2], encoding="utf-8") as fh: r = guardar_resumen(fh.read(), sys.argv[3] if len(sys.argv) > 3 else "Claude")
        print("guardado:", r["id"]); sys.exit(0)
    try:
        estado(running=True, beat=time.time(), started=now_iso(), error=None)
        r = actualizar(); estado(running=False, finished=now_iso(), fecha=today(), message="Actualizado", error=None, ultimo=r)
        print("Comunidades:", r)
        try: import oficina; oficina.registrar("comunidades", "Lectura terminada: " + str(r)[:120])
        except Exception: pass
    except BaseException as ex:
        estado(running=False, finished=now_iso(), message="Falló la actualización", error=str(ex)[:300])
        try: import oficina; oficina.registrar("comunidades", "Falló: " + str(ex)[:120], ok=False)
        except Exception: pass
        raise
