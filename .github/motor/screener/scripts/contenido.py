"""Content tab, phase 3 (owner, 2 November 2026: "coge esos canales"): what the Pokémon-investing YouTube channels talk about.
Only the official YouTube Data API v3 is used (key in .secrets/youtube.json; the daily quota is 10,000 units and a full refresh costs about 70): for each followed channel
its latest videos with title, description, tags, date, views, likes and comments. It does NOT download video, audio or subtitles. From that it counts which SETS and
POKÉMON are named (in the last 30 days against the 30 before), in how many channels and with how many views, and lists the videos about sleepers / underrated cards.
Files: data/contenido/canales.json (the channels; each can be switched off), videos.json (every video seen, with its views day by day), estado.json, pokemon.json (names, from PokéAPI).
The server calls toca() every few minutes and starts "python contenido.py" once a day after 07:00; «Actualizar ahora» in the app does it too.
Usage: python contenido.py [--sembrar]   (--sembrar only resolves the starting channels)"""
import datetime as dt, json, os, re, subprocess, sys, time, unicodedata, urllib.error, urllib.parse, urllib.request
from common import P, load, save, ROOT, TZ

DIR = P("contenido"); KEY_FILE = os.path.join(ROOT, ".secrets", "youtube.json")
MAX_PAGES = 3            # a normal run: 150 videos, it stops as soon as a page is all known
MAX_DIAS = 190         # six months: older videos are dropped
KEEP_PER_CHANNEL = 600   # the deep run (--profundo, 10 pages of 50) brings about a year or two of a channel that posts daily
START = ["@pokebeardtcg", "@twicebakedjake", "@grantrudow", "@ndup", "@thecardconomist", "@erikfromvioletcity", "@gaiastormtcg", "@loadingcard",
         "@itwasneveraphasecards", "@tcgcrosscollector", "@nostalgianomics", "@tcgtraderjons", "@pokeoz91", "@christyholds", "@cardloungepodcast"]

def today(): return dt.datetime.now(TZ).date().isoformat()
def now_iso(): return dt.datetime.now(TZ).isoformat(timespec="minutes")
def estado(**kw):
    e = load(os.path.join(DIR, "estado.json"), {}) or {}; e.update(kw); save(os.path.join(DIR, "estado.json"), e); return e
def en_marcha():
    e = load(os.path.join(DIR, "estado.json"), {}) or {}
    return bool(e.get("running")) and time.time() - e.get("beat", 0) < 600

def _key():
    k = (load(KEY_FILE, {}) or {}).get("token")
    if not k: raise SystemExit("Falta la clave de YouTube en .secrets/youtube.json")
    return k

def yt(path, **q):
    q["key"] = _key()
    try: return json.load(urllib.request.urlopen("https://www.googleapis.com/youtube/v3/" + path + "?" + urllib.parse.urlencode(q), timeout=40))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"YouTube {e.code}: " + e.read().decode("utf-8", "replace")[:200])

def canales(): return load(os.path.join(DIR, "canales.json"), None)

def resolver(texto):
    """A @handle, a channel link or a channel id -> channel dict, or None."""
    t = (texto or "").strip()
    v = re.search(r"(?:youtu\.be/|[?&]v=|/shorts/|/live/|/embed/)([\w-]{11})(?![\w-])", t)      # el enlace de UN VÍDEO (Fernando, 7 nov): se busca de qué canal es y se añade ese canal
    if v and not re.search(r"(UC[\w-]{22})", t):
        vr = yt("videos", part="snippet", id=v.group(1)); vi = (vr.get("items") or [None])[0]
        if not vi: return None
        t = vi["snippet"]["channelId"]
    m = re.search(r"(UC[\w-]{22})", t); h = re.search(r"@([\w.\-]+)", t)
    if m: r = yt("channels", part="snippet,statistics,contentDetails", id=m.group(1))
    elif h: r = yt("channels", part="snippet,statistics,contentDetails", forHandle="@" + h.group(1))
    elif t: r = yt("channels", part="snippet,statistics,contentDetails", forHandle="@" + t.lstrip("@"))
    else: return None
    it = (r.get("items") or [None])[0]
    if not it: return None
    st = it.get("statistics") or {}
    return {"id": it["id"], "nombre": it["snippet"]["title"], "handle": it["snippet"].get("customUrl") or "", "subs": int(st.get("subscriberCount") or 0),
            "uploads": it["contentDetails"]["relatedPlaylists"]["uploads"], "activo": True, "idioma": (it["snippet"].get("defaultLanguage") or "")[:2]}

def sembrar():
    L = canales()
    if L is not None: return L
    L = [c for c in (resolver(h) for h in START) if c]
    ES = {"@gaiastormtcg", "@loadingcard", "@tcgcrosscollector"}
    for c in L: c["idioma"] = "es" if c["handle"].lower() in ES else "en"
    save(os.path.join(DIR, "canales.json"), L); return L

def canal_añadir(texto):
    L = sembrar(); c = resolver(texto)
    if not c: raise ValueError("No encuentro ese canal. Pega su @nombre, su enlace o su identificador (UC…)")
    if any(x["id"] == c["id"] for x in L): raise ValueError("Ese canal ya está en la lista")
    L.append(c); save(os.path.join(DIR, "canales.json"), L); return c

def canal_ajustar(id, activo=None, quitar=False):
    L = sembrar()
    if quitar: L = [c for c in L if c["id"] != id]
    else:
        for c in L:
            if c["id"] == id and activo is not None: c["activo"] = bool(activo)
    save(os.path.join(DIR, "canales.json"), L); return L

# ---- vocabulary: sets (written here) and Pokémon (PokéAPI, once)
SETS = ["Base Set", "Jungle Set", "Fossil", "Team Rocket", "Gym Heroes", "Gym Challenge", "Neo Genesis", "Neo Discovery", "Neo Revelation", "Neo Destiny", "Legendary Collection",
        "Aquapolis", "Skyridge", "EX Ruby & Sapphire", "Team Magma vs Team Aqua", "Hidden Legends", "FireRed & LeafGreen", "Team Rocket Returns",
        "Unseen Forces", "Delta Species", "Legend Maker", "Holon Phantoms", "Crystal Guardians", "Dragon Frontiers", "Power Keepers", "Diamond & Pearl",
        "Mysterious Treasures", "Secret Wonders", "Great Encounters", "Majestic Dawn", "Legends Awakened", "Stormfront", "Rising Rivals", "Supreme Victors", "Arceus",
        "HeartGold SoulSilver", "Unleashed", "Undaunted", "Triumphant", "Call of Legends", "Black & White", "Emerging Powers", "Noble Victories", "Next Destinies", "Dark Explorers",
        "Dragons Exalted", "Boundaries Crossed", "Plasma Storm", "Plasma Freeze", "Plasma Blast", "Legendary Treasures", "Dragon Vault", "Flashfire", "Furious Fists",
        "Phantom Forces", "Primal Clash", "Roaring Skies", "Ancient Origins", "BREAKthrough", "BREAKpoint", "Fates Collide", "Steam Siege", "Generations",
        "Double Crisis", "Sun & Moon", "Guardians Rising", "Burning Shadows", "Shining Legends", "Crimson Invasion", "Ultra Prism", "Forbidden Light", "Celestial Storm",
        "Dragon Majesty", "Lost Thunder", "Team Up", "Detective Pikachu", "Unbroken Bonds", "Unified Minds", "Hidden Fates", "Cosmic Eclipse", "Shining Fates", "Champion's Path",
        "Sword & Shield", "Rebel Clash", "Darkness Ablaze", "Vivid Voltage", "Battle Styles", "Chilling Reign", "Evolving Skies", "Celebrations", "Fusion Strike", "Brilliant Stars",
        "Astral Radiance", "Pokemon GO", "Lost Origin", "Silver Tempest", "Crown Zenith", "Scarlet & Violet", "Paldea Evolved", "Obsidian Flames", "151", "Paradox Rift",
        "Paldean Fates", "Temporal Forces", "Twilight Masquerade", "Shrouded Fable", "Stellar Crown", "Surging Sparks", "Prismatic Evolutions", "Journey Together", "Destined Rivals",
        "Black Bolt", "White Flare", "Mega Evolution", "Phantasmal Flames", "Ascended Heroes", "Perfect Order", "McDonald's", "Gold Star",
        "Shiny Treasure", "Terastal Festival", "Crimson Haze", "Shiny Star V", "VMAX Climax", "Mirage Forest", "Golden Sky", "Miracle Crystal", "Flight of Legends", "Neo Premium File"]
ALIAS = {"moonbreon": "Umbreon", "moon breon": "Umbreon", "zard": "Charizard", "mewtwo": "Mewtwo", "pika": "Pikachu"}

def _norm(s): return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)).lower()

def vocabulario():
    f = os.path.join(DIR, "pokemon.json"); names = load(f, None)
    if not names:
        try:
            r = json.load(urllib.request.urlopen(urllib.request.Request("https://pokeapi.co/api/v2/pokemon-species?limit=2000", headers={"User-Agent": "PokeFinder"}), timeout=40))
            names = sorted({x["name"].replace("-", " ").title() for x in r["results"] if len(x["name"]) >= 4}); save(f, names)
        except Exception:
            names = ["Charizard", "Pikachu", "Umbreon", "Espeon", "Mewtwo", "Mew", "Lugia", "Rayquaza", "Gengar", "Eevee", "Blastoise", "Venusaur", "Gyarados", "Dragonite", "Ho Oh", "Celebi", "Suicune", "Entei", "Raikou", "Latias", "Latios", "Groudon", "Kyogre", "Lucario", "Greninja", "Gardevoir", "Mimikyu", "Snorlax", "Umbreon", "Sylveon", "Glaceon", "Leafeon", "Vaporeon", "Jolteon", "Flareon"]
    return names

_rx = {}
def _regex():
    if not _rx:
        poke = {_norm(n): n for n in vocabulario()}
        _rx["poke"] = (re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(k) for k in sorted(poke, key=len, reverse=True)) + r")(?![a-z0-9])"), poke)
        sets = {_norm(s): s for s in SETS if len(s) >= 5}
        _rx["sets"] = (re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(k) for k in sorted(sets, key=len, reverse=True)) + r")(?![a-z0-9])"), sets)
    return _rx

def entidades(texto):
    """({sets}, {pokemon}) named in a text, normalised to their proper names."""
    t = _norm(texto); R = _regex()
    s = [R["sets"][1][m] for m in R["sets"][0].findall(t)]
    p = {R["poke"][1][m] for m in R["poke"][0].findall(t)} | {v for k, v in ALIAS.items() if re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", t)}
    if re.search(r"(?:pokemon|scarlet|violet|sv ?3\.?5|set|booster|etb|bundle|upc|elite trainer|cards?)\W+151(?![0-9/$])|(?<![0-9/$.])151\W+(?:set|booster|etb|bundle|upc|elite|pokemon|cards?|ex)", t): s.append("151")
    return sorted(set(s)), sorted(p)

TEMAS = [("sleeper", r"sleeper|underrated|undervalued|under-?valued|hidden gems?|infravalorad|subvalorad|oportunidad|bargain|for under|under \$\d+|cheap"),
         ("aviso", r"avoid|dead|overrated|bubble|crash|horrible|bad invest|burbuja|estafa|stop buying|don'?t buy|no compres|sobrevalorad"),
         ("mercado", r"market update|market news|prices?\b|predictions?|news|actualizaci[oó]n|mercado|forecast"),
         ("inversion", r"invest\w*|inversi[oó]n|invertir|\bflip\w*|profit|worth it")]
def temas_de(titulo, tags=""):
    t = _norm(titulo + " " + tags)
    return [k for k, rx in TEMAS if re.search(rx, t)]

def _dur(s):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or ""); h, mi, se = (int(x or 0) for x in m.groups()) if m else (0, 0, 0)
    return h * 3600 + mi * 60 + se

def actualizar(profundo=False):
    L = [c for c in sembrar() if c.get("activo")]
    V = load(os.path.join(DIR, "videos.json"), {}) or {}; hoy = today(); n_nuevos = 0; unidades = 0
    estado(total=len(L), done=0, message=f"Leyendo canales (0/{len(L)})")
    for i, c in enumerate(L):
        ids, tok = [], None
        for _ in range(10 if profundo else MAX_PAGES):
            q = {"part": "contentDetails", "playlistId": c["uploads"], "maxResults": 50}
            if tok: q["pageToken"] = tok
            r = yt("playlistItems", **q); unidades += 1
            pg = [x["contentDetails"]["videoId"] for x in r.get("items", [])]; ids += pg; tok = r.get("nextPageToken")
            if not tok or (not profundo and pg and all(i in V for i in pg)): break
        ids = [i for i in ids if i not in V or (dt.date.fromisoformat(hoy) - dt.date.fromisoformat(V[i]["f"])).days <= 45]   # an old known video does not change: not asked again
        for j in range(0, len(ids), 50):
            r = yt("videos", part="snippet,statistics,contentDetails", id=",".join(ids[j:j + 50])); unidades += 1
            for it in r.get("items", []):
                s, st = it["snippet"], it.get("statistics") or {}; vid = it["id"]
                v = V.get(vid) or {}; hist = v.get("hist") or {}
                hist[hoy] = int(st.get("viewCount") or 0)
                if (dt.date.fromisoformat(hoy) - dt.date.fromisoformat(s["publishedAt"][:10])).days > 45: hist = {hoy: hist[hoy]}
                tags = " ".join(s.get("tags") or [])
                sets, poke = entidades(s["title"] + " " + tags)   # not the description: it is full of menus, links and sponsor texts
                n_nuevos += vid not in V
                V[vid] = {"c": c["id"], "canal": c["nombre"], "t": s["title"], "d": (s.get("description") or "")[:600], "f": s["publishedAt"][:10], "v": hist[hoy],
                          "l": int(st.get("likeCount") or 0), "k": int(st.get("commentCount") or 0), "s": _dur(it["contentDetails"].get("duration")), "tags": tags[:200],
                          "sets": sets, "poke": poke, "temas": temas_de(s["title"]),   # title only: the tags of some channels carry «undervalued» on every video
                          "hist": dict(sorted(hist.items())[-20:])}
        estado(done=i + 1, beat=time.time(), message=f"Leyendo canales ({i + 1}/{len(L)})")
    # per channel keep the newest KEEP_PER_CHANNEL
    por = {}
    for vid, v in V.items(): por.setdefault(v["c"], []).append((v["f"], vid))
    keep = {vid for lst in por.values() for _, vid in sorted(lst, reverse=True)[:KEEP_PER_CHANNEL]}
    V = {k: v for k, v in V.items() if k in keep and (dt.date.fromisoformat(hoy) - dt.date.fromisoformat(v["f"])).days <= MAX_DIAS}   # the owner follows what is current: nothing older than six months
    save(os.path.join(DIR, "videos.json"), V)
    estado(message="Leyendo comentarios…", beat=time.time())
    cm = comentarios_actualizar(V, {c["id"] for c in L})
    return {"videos": len(V), "nuevos": n_nuevos, "unidades": unidades + cm["llamadas"], "comentarios": cm["leidos"]}

COMM_FILE = os.path.join(DIR, "comentarios.json")
COMM_POR_CANAL = 5       # videos per channel whose comments are read (the newest ones of the last 30 days)
COMM_CUPO = 120          # calls (1 unit each) per run at most
STOP_W = set("""that this with have from they them their there what when where which would could should about because just like your youre dont cant wont thats really also been were
very much more some than then into only even still back over here make made know think need want going gonna will people these being time well them those while after before every never always could would might another ever mean actually thing things looks look seems seem getting gets lot lots cards card pokemon pokémon video videos channel love thanks thank great good best
para pero como esto esta este estos estas porque cuando donde sobre entre desde hasta muy mas más tambien también solo sólo todo todos todas video videos canal cartas carta pokemon gracias
hola tengo tiene tienen puede pueden hacer hace dice bien mucho muchos muchas algo nada ahora ahi ahí aqui aquí otro otra otros otras cada ser son fue era hay vez veces cosa cosas gusta años año""".split())
CAT = [("compra", r"\b(?:buy|buying|bought|grab|grabbed|picked up|pick up|purchase|invest(?:ed|ing)?|comprar|compre|comprado|invertir|invertido)\b"),
       ("venta", r"\b(?:sell|sold|selling|overpriced|bubble|dump|crash|scam|fake|overrated|vender|vendi|vendido|caro|cara|burbuja|estafa|bajando|bajon|too expensive|demasiado)\b"),
       ("precio", r"[$€£]|\b\d+\s?(?:usd|eur|euros?|dollars?|bucks|dolares)\b|\b(?:price|prices|precio|precios|worth|value)\b")]

def comentarios_actualizar(V, act):
    """Reads (YouTube API, commentThreads.list, 1 unit a call) up to 100 of the most relevant comments of the newest videos of each channel. Only the text, the likes and
    the replies are kept (no names): what people say is counted, not who says it."""
    C = load(COMM_FILE, {}) or {}; hoy = dt.date.fromisoformat(today()); llamadas = leidos = 0
    por = {}
    for vid, v in V.items():
        if v["c"] in act and (hoy - dt.date.fromisoformat(v["f"])).days <= 30: por.setdefault(v["c"], []).append((v["f"], vid))
    cola = []
    for c, lst in por.items(): cola += [vid for _, vid in sorted(lst, reverse=True)[:COMM_POR_CANAL]]
    for vid in cola:
        if llamadas >= COMM_CUPO: break
        prev = C.get(vid); edad = (hoy - dt.date.fromisoformat(V[vid]["f"])).days
        dias_desde = (hoy - dt.date.fromisoformat(prev["at"])).days if prev else 99
        if prev and (prev.get("off") or dias_desde < (2 if edad <= 7 else 7)): continue
        try:
            r = yt("commentThreads", part="snippet", videoId=vid, maxResults=100, order="relevance", textFormat="plainText"); llamadas += 1
        except RuntimeError as e:
            llamadas += 1
            if "commentsDisabled" in str(e) or "disabled comments" in str(e): C[vid] = {"at": today(), "off": True, "items": []}; continue
            if "quota" in str(e).lower(): break
            continue
        its = []
        for it in r.get("items", []):
            sn = it["snippet"]["topLevelComment"]["snippet"]; txt = (sn.get("textDisplay") or "").strip()
            if len(txt) < 3: continue
            s, p = entidades(txt)
            its.append({"x": txt[:400], "l": int(sn.get("likeCount") or 0), "r": int(it["snippet"].get("totalReplyCount") or 0), "f": (sn.get("publishedAt") or "")[:10], "s": s, "p": p}); leidos += 1
        C[vid] = {"at": today(), "off": False, "items": its}
    C = {k: v for k, v in C.items() if k in V}      # a video that left the list takes its comments with it
    save(COMM_FILE, C)
    return {"llamadas": llamadas, "leidos": leidos}

def comentarios_view(vids, age, dias=30):
    """What the comments of the videos shown say: the sets and Pokémon named, the words and phrases that repeat, what share ask, want to buy, warn or talk prices, and the most liked."""
    C = load(COMM_FILE, {}) or {}; ids = {v["id"]: v for v in vids if age(v) <= (min(dias, 30) if dias else 30)}   # comments are only read for videos of the last 30 days
    tem_items = []
    ent = {"s": {}, "p": {}}; termos = {}; bigr = {}; n = nv = 0; cat = {"pregunta": 0, "compra": 0, "venta": 0, "precio": 0}; top = []
    for vid, v in ids.items():
        c = C.get(vid)
        if not c or c.get("off") or not c["items"]: continue
        nv += 1
        for it in c["items"]:
            n += 1; t = _norm(it["x"])
            for kind in ("s", "p"):
                for e in it[kind]:
                    x = ent[kind].setdefault(e, {"e": e, "n": 0, "videos": set()}); x["n"] += 1; x["videos"].add(vid)
            toks = [w for w in re.findall(r"[a-zñ']{4,}", t) if "'" not in w and w not in STOP_W]
            for w in set(toks): termos[w] = termos.get(w, 0) + 1
            for a, b in set(zip(toks, toks[1:])): bigr[a + " " + b] = bigr.get(a + " " + b, 0) + 1
            if "?" in it["x"]: cat["pregunta"] += 1
            for k, rx in CAT: cat[k] += bool(re.search(rx, t))
            top.append((it["l"], it["x"], vid)); tem_items.append((it["x"], it["l"], vid))
    tcom = temas_resumen([(0, c_txt, c_likes, "comentarios", vid, "") for c_txt, c_likes, vid in tem_items], 0)
    rk = lambda d: sorted(({"e": x["e"], "n": x["n"], "videos": len(x["videos"])} for x in d.values() if x["n"] >= 3), key=lambda x: (-x["n"], -x["videos"]))[:20]
    top.sort(reverse=True)
    return {"n": n, "videos": nv, "temas": tcom, "sets": rk(ent["s"]), "pokemon": rk(ent["p"]), "terminos": sorted(((w, k) for w, k in termos.items() if k >= 5), key=lambda x: -x[1])[:36],
            "frases": sorted(((w, k) for w, k in bigr.items() if k >= 4), key=lambda x: -x[1])[:20], "intencion": {k: round(100 * v / n, 1) if n else 0 for k, v in cat.items()},
            "top": [{"l": l, "x": x[:260], "id": vid, "t": ids[vid]["t"], "canal": ids[vid]["canal"]} for l, x, vid in top[:12]]}

def hecho_hoy(): return (load(os.path.join(DIR, "estado.json"), {}) or {}).get("fecha") == today()

def toca():
    if not os.path.exists(KEY_FILE) or en_marcha() or dt.datetime.now(TZ).hour < 7 or hecho_hoy(): return False
    e = load(os.path.join(DIR, "estado.json"), {}) or {}
    return not (e.get("error") and str(e.get("finished") or "")[:10] == today())

def lanzar():
    if en_marcha(): return estado()
    os.makedirs(P("state"), exist_ok=True)
    estado(running=True, beat=time.time(), started=now_iso(), message="Empezando…", error=None)
    log = open(P("state", "contenido.log"), "a", encoding="utf-8"); here = os.path.dirname(os.path.abspath(__file__))
    subprocess.Popen([sys.executable, os.path.join(here, "contenido.py")], cwd=here, env={**os.environ, "PYTHONIOENCODING": "utf-8"}, stdin=subprocess.DEVNULL,
                     stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return estado()

# ---- market THEMES: what is being said about the market itself, not about one card (30th anniversary, vintage against modern, a correction...)
TEMAS_MERCADO = [
    ("🎂 30 aniversario", r"30th|30 anniversary|30 aniversario|treinta aniversario|30 ?th celebration|anniversary (?:set|cards?|celebration)|first partner illustration|30 years"),
    ("🏛 Vintage", r"vintage|wotc|\bbase set\b|1st edition|first edition|shadowless|\be-?series\b|\bex era\b|neo (?:genesis|discovery|revelation|destiny)|skyridge|aquapolis|expedition|old school|original 151|clasic[oa]s?|antigu[oa]s?"),
    ("🆕 Moderno", r"\bmodern\b|\bsv era\b|scarlet (?:&|and) violet|sword (?:&|and) shield|\bswsh\b|\bsv\d|new sets?|current sets?|moderno|actual(?:es)? sets?"),
    ("📉 Corrección / caída", r"correction|crash|bubble|dump(?:ing)?|dropping|falling|plummet|bear market|sell.?off|collapse|bleeding|tanking|down \d+ ?%|all.?time lows?|burbuja|ca[ií]da|cayendo|bajando|baj[oó]n|correcci[oó]n|hundimiento|desplom|derrumb|pinchazo"),
    ("📈 Subida / rally", r"rally|surging|skyrocket|moon(?:ing)?|all.?time highs?|\bath\b|record|pumping|rising|bull market|breakout|sube\b|subiendo|subida|disparad|r[eé]cord|se dispara"),
    ("📦 Producto sellado", r"sealed|booster box|\betbs?\b|elite trainer|booster bundle|\bupc\b|display box|booster pack|sellad[oa]|caja de sobres|cofre"),
    ("🧾 Gradeo y slabs", r"\bpsa\b|\bcgc\b|\btag\b|\bbgs\b|beckett|grading|graded|slabs?|gem mint|pop report|population|gradeo|gradead[oa]|arena club"),
    ("🇯🇵 Japonés", r"japanese|japan\b|\bjpn\b|\bjp\b|japon[eé]s|japonesa|jap[oó]n"),
    ("🖨 Reimpresión / exceso de producto", r"reprint|overprint|print run|more supply|oversupply|flood(?:ing|ed)?|reimpresi|exceso de producto|sobreproducci"),
    ("🛒 Restock / escasez / reventa", r"restock|sold out|shortage|\bmsrp\b|scalpers?|resellers?|agotad[oa]|escasez|reventa|revendedor"),
    ("💶 Economía / aranceles", r"tariffs?|inflation|recession|stock market|interest rates?|aranceles?|inflaci[oó]n|recesi[oó]n|bolsa"),
    ("🎯 Inversión: consejos y avisos", r"invest\w*|inversi[oó]n|invertir|flip\w*|sleeper|undervalued|underrated|overrated|infravalorad|sobrevalorad|should you buy|don'?t buy|stop buying|worth it"),
]
_TM = [(n, re.compile(rx)) for n, rx in TEMAS_MERCADO]
_BEAR = re.compile(r"correction|crash|bubble|dump|dropping|falling|plummet|bear|sell.?off|collapse|bleeding|tanking|all.?time lows?|overrated|overprint|oversupply|horrible|avoid|dead|burbuja|ca[ií]da|cayendo|bajando|baj[oó]n|correcci[oó]n|hundimiento|desplom|sobrevalorad|evita")
_BULL = re.compile(r"rally|surging|skyrocket|moon|all.?time highs?|\bath\b|record|pumping|rising|bull|breakout|sube\b|subiendo|subida|disparad|r[eé]cord|undervalued|underrated|sleeper|infravalorad|buy now|best")
_tm_cache = {}
def temas_mercado(texto):
    k = texto
    if k not in _tm_cache:
        t = _norm(texto); _tm_cache[k] = ([n for n, rx in _TM if rx.search(t)], bool(_BEAR.search(t)), bool(_BULL.search(t)))
        if len(_tm_cache) > 60000: _tm_cache.clear()
    return _tm_cache[k]

def temas_resumen(items, dias):
    """items: [(age_days, text, views, channel_or_source, id)] -> per theme: mentions in the period and in the one before, sources, views, tone (bearish / bullish wording) and the most viewed example."""
    ag = {}
    for a, texto, vistas, fuente, ident, titulo in items:
        temas, bear, bull = temas_mercado(texto)
        for n in temas:
            x = ag.setdefault(n, {"e": n, "n": 0, "antes": 0, "fuentes": set(), "vistas": 0, "bear": 0, "bull": 0, "ej": None, "n14": 0})
            if dias == 0 or a <= dias:
                x["n"] += 1; x["fuentes"].add(fuente); x["vistas"] += vistas; x["bear"] += bear; x["bull"] += bull
                if not x["ej"] or vistas > x["ej"]["v"]: x["ej"] = {"id": ident, "t": titulo, "v": vistas, "fuente": fuente}
            elif dias and a <= 2 * dias: x["antes"] += 1
            if a <= 14: x["n14"] += 1
    return sorted(({**x, "fuentes": len(x["fuentes"])} for x in ag.values() if x["n"] >= 1), key=lambda x: -x["n"])

def es_short(v):
    """A Short: up to a minute, or up to three with #shorts in the title or description (YouTube allows three minutes since 2024; the API does not say which is which)."""
    return v.get("s", 0) <= 60 or (v.get("s", 0) <= 180 and "#short" in ((v.get("t") or "") + " " + (v.get("d") or "")).lower())

def view(modo="todos", dias=30):
    dias = dias if dias in (7, 30, 90) else 30      # the owner follows what is current: a week, a month, at most three months
    """What the page shows: the channels, the entities most named in the last 30 days (against the 30 before), the sleeper videos and the latest videos."""
    L = sembrar() if os.path.exists(KEY_FILE) else (canales() or []); V = load(os.path.join(DIR, "videos.json"), {}) or {}
    act = {c["id"] for c in L if c.get("activo")}; hoy = dt.date.fromisoformat(today())
    vids = [dict(v, id=k, short=es_short(v)) for k, v in V.items() if v["c"] in act]
    n_shorts = sum(v["short"] for v in vids); n_largos = len(vids) - n_shorts
    allv = vids
    if modo == "largos": vids = [v for v in vids if not v["short"]]
    elif modo == "shorts": vids = [v for v in vids if v["short"]]
    age = lambda v: (hoy - dt.date.fromisoformat(v["f"])).days
    def ranking(campo):
        """Per set / Pokémon: mentions in the chosen period against the period before, channels, views, when it was last named, a weekly line of the last 26 weeks and a
        verdict from the DATES (last 14 days against days 15-60): rising / steady / cooling / old. dias 0 = no limit."""
        ag = {}
        for v in vids:
            a = age(v)
            for e in v[campo]:
                x = ag.setdefault(e, {"e": e, "n": 0, "antes": 0, "canales": set(), "vistas": 0, "vpd": 0, "sleeper": 0, "aviso": 0, "ej": None, "total": 0, "n14": 0, "n30": 0, "n60": 0, "n90": 0,
                                      "min_age": 99999, "max_age": 0, "sem": [0] * 26})
                x["total"] += 1; x["min_age"] = min(x["min_age"], a); x["max_age"] = max(x["max_age"], a)
                if a <= 14: x["n14"] += 1
                if a <= 30: x["n30"] += 1
                if a <= 60: x["n60"] += 1
                if a <= 90: x["n90"] += 1
                if a // 7 < 26: x["sem"][a // 7] += 1
                if dias == 0 or a <= dias:
                    x["n"] += 1; x["canales"].add(v["canal"]); x["vistas"] += v["v"]; x["vpd"] += v["v"] / max(1, a); x["sleeper"] += "sleeper" in v["temas"]; x["aviso"] += "aviso" in v["temas"]
                    if not x["ej"] or v["v"] > x["ej"]["v"]: x["ej"] = {"id": v["id"], "t": v["t"], "v": v["v"], "canal": v["canal"]}
                elif dias and a <= 2 * dias: x["antes"] += 1
        def veredicto(x):
            rec, prev = x["n14"] / 14, max(0, x["n60"] - x["n14"]) / 46
            if x["n14"] >= 2 and rec > 1.5 * prev: return "subiendo"
            if x["n14"] == 0 and x["n60"] > 0: return "enfriando"
            if x["n14"] == 0: return "antiguo"
            return "estable"
        fecha = lambda d: (hoy - dt.timedelta(days=d)).isoformat()
        out = [dict(x, canales=len(x["canales"]), vpd=round(x["vpd"]), ultima=fecha(x["min_age"]), hace=x["min_age"], primera=fecha(x["max_age"]), serie=x["sem"][::-1], estado=veredicto(x))
               for x in ag.values() if x["n"] >= (1 if dias and dias <= 7 else 2)]
        viejos = [{"e": x["e"], "total": x["n90"], "ultima": fecha(x["min_age"]), "hace": x["min_age"], "canales": len(x["canales"]) or None, "tipo": campo}
                  for x in ag.values() if x["n30"] == 0 and x["n90"] >= 3]      # named 1-3 months ago, not in the last month
        return sorted(out, key=lambda x: (-x["canales"], -x["n"], -x["vistas"]))[:30], viejos
    (sets_r, sets_v), (poke_r, poke_v) = ranking("sets"), ranking("poke")
    enf = sorted([dict(x, tipo="set") for x in sets_v] + [dict(x, tipo="pokemon") for x in poke_v], key=lambda x: -x["total"])[:16]
    sl = sorted((v for v in vids if "sleeper" in v["temas"] and age(v) <= 90), key=lambda v: -v["v"])[:40]
    rec = sorted(vids, key=lambda v: v["f"], reverse=True)[:60]
    cut = lambda v: {k: v[k] for k in ("id", "canal", "t", "f", "v", "l", "k", "s", "sets", "poke", "temas", "short")} | {"crece": _crece(v), "dias": age(v), "vpd": round(v["v"] / max(1, age(v)))}
    com = comentarios_view(vids, age, dias)
    temas = temas_resumen([(age(v), v["t"] + " " + v.get("tags", ""), v["v"], v["canal"], v["id"], v["t"]) for v in vids], dias)
    chs = []
    for c in L:
        mine = [v for v in vids if v["c"] == c["id"]] if c.get("activo") else [dict(v, id=k, short=es_short(v)) for k, v in V.items() if v["c"] == c["id"]]
        r30 = [v for v in mine if age(v) <= 30]
        chs.append({**{k: c[k] for k in ("id", "nombre", "handle", "subs", "activo", "idioma")}, "videos": len(mine), "videos30": len(r30), "vistas30": sum(v["v"] for v in r30), "shorts30": sum(1 for v in allv if v["c"] == c["id"] and age(v) <= 30 and v["short"])})
    return {"estado": {**(load(os.path.join(DIR, "estado.json"), {}) or {}), "running": en_marcha()}, "canales": chs, "videos": len(vids), "modo": modo, "dias": dias, "temas": temas, "enfriando": enf, "n_shorts": n_shorts, "n_largos": n_largos, "sets": sets_r, "pokemon": poke_r,
            "sleepers": [cut(v) for v in sl], "recientes": [cut(v) for v in rec], "unidades_dia": 190, "comentarios": com, "hoy": today()}

def _crece(v):
    h = v.get("hist") or {}; ks = sorted(h)
    return h[ks[-1]] - h[ks[0]] if len(ks) >= 2 else None

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if "--sembrar" in sys.argv:
        L = sembrar(); print(len(L), "canales:", [c["nombre"] for c in L]); sys.exit(0)
    try:
        estado(running=True, beat=time.time(), started=now_iso(), error=None)
        r = actualizar(profundo="--profundo" in sys.argv); estado(running=False, finished=now_iso(), fecha=today(), message="Actualizado", error=None, **{"ultimo": r})
        print("Contenido:", r)
        try: import oficina; oficina.registrar("youtube", "Lectura terminada: " + str(r)[:120])
        except Exception: pass
    except BaseException as ex:
        estado(running=False, finished=now_iso(), message="Falló la actualización", error=str(ex)[:300])
        try: import oficina; oficina.registrar("youtube", "Falló: " + str(ex)[:120], ok=False)
        except Exception: pass
        raise
