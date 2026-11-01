"""The owner's PokéFinder on the phone, anywhere, with the computer off (owner, 24-25 October 2026): a public web page with every
saved search, the photo of each listing, and a search box whose requests reach the computer. Since 30 October 2026 it is on GitHub
(owner: "Cloudflare now charges: move it somewhere completely free, like GitHub"): GitHub Pages of the public repository
settings.json "github_repo", at settings.json "cloud_url". The page is the static folder ROOT/cloud/out; what the Cloudflare
Worker did is done by GitHub: requests are issues, live data are files under api/ in the repository, and the phone's own search
runs in GitHub Actions with this app's engine, in every market (ROOT/cloud/github: pages.yml, buscar.yml, buscar.py, state.py;
the engine is copied to the repository's .github/motor by `publish`; the old worker.js is kept as history).

  python nube.py build
        Writes ROOT/cloud/out/: index.html (the page, all saved searches inside it), sheets/*.jpg (the listing photos, 100 per
        sheet: one picture per 100 listings loads fast on a phone), version.json (the phone reloads when it changes), icons.
  python nube.py publish          (ROOT/cloud/publicar.bat [--no-build] = build + publish)
        Pushes cloud/out, the workflows and the phone search's engine (screener/ -> .github/motor) to the repository (local copy
        %LOCALAPPDATA%/PokeFinderWeb); GitHub publishes it in about a minute and the phone reloads by itself.
  python nube.py pending
        Tells the page the computer is checking and prints the phone requests still waiting (JSON list; [] = nothing to do).
  python nube.py asked | reject [<request id>...]
        asked: the waiting requests show "esperando tu OK en Claude" on the phone. reject: the owner said no; they close.
  python nube.py requests [<request id>...]
        Reads the searches asked from the phone (GitHub issues). Each one still waiting (or only the ids given) becomes a local job
        (as if typed in the app; the local server must be running) and is marked "taken" (label tomada). Prints what it did (JSON).
  python nube.py job <job> [--id <request or job id>]
        Sends the job's live progress to the page (api/jobs/<id>.json; the phone shows the bar and "Ver búsqueda en curso"), every
        3 minutes at most. The id is the phone request's when the job came from the phone, else the job's. A job "done" closes its issue.
  python nube.py status on|off
        Tells the page whether the computer is on (api/status.json; "Ordenador activo" for 45 minutes; sent every 20 minutes at most).
  python nube.py link
        Prints the owner's link for the phone (with the phone key that lets it ask for searches).
  python nube.py setup
        Once per GitHub account: issue labels, eBay keys as encrypted repository secrets, GitHub Pages on.

Needs git and the GitHub CLI logged in to the owner's account (`gh auth login`, once per computer). Phone key: a GitHub token the
owner makes that can only open issues in the repository, kept in ROOT/.secrets/cloud.json "phone_token" and in the owner's link
(never printed elsewhere). Photos are downloaded from the marketplaces' picture servers only (never their pages) and kept in
data/cloud/thumbs."""
import datetime as dt, glob, hashlib, io, json, os, re, secrets, shutil, subprocess, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from common import P, load, save, SCREENER
import app_lib as A

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(SCREENER)
CLOUD_DIR = os.path.join(ROOT, "cloud")
OUT = os.path.join(CLOUD_DIR, "out")
TEMPLATE = os.path.join(CLOUD_DIR, "template.html")
ENGINE_JS = os.path.join(CLOUD_DIR, "engine.js")   # the page's own search engine, put inside the page
STATIC = os.path.join(CLOUD_DIR, "static")
KEYS = os.path.join(ROOT, ".secrets", "cloud.json")
MAP = P("cloud", "requests_map.json")
THUMBS = P("cloud", "thumbs")
CW, CH, COLS, PER = 150, 200, 10, 100
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"

def thumb_path(url): return os.path.join(THUMBS, hashlib.sha1(url.encode()).hexdigest()[:20] + ".jpg")

def fetch_thumb(url):
    """One listing photo -> a 150x200 JPEG on the page's dark blue (cached). Returns the file or None."""
    from PIL import Image
    f = thumb_path(url)
    if os.path.exists(f): return f
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"})
        im = Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=25).read())).convert("RGB")
    except Exception:
        return None
    im.thumbnail((CW * 2, CH * 2))
    im.thumbnail((CW, CH), Image.LANCZOS)
    bg = Image.new("RGB", (CW, CH), (8, 18, 41)); bg.paste(im, ((CW - im.width) // 2, (CH - im.height) // 2))
    os.makedirs(THUMBS, exist_ok=True); bg.save(f, "JPEG", quality=82)
    time.sleep(0.15)
    return f

def compact(l, cell):
    return {k: v for k, v in {
        "i": l["id"], "t": l.get("title"), "u": l.get("url"), "p": l.get("price_eur"),
        "o": l.get("price_text") if l.get("price_text") and not re.search(r"EUR|€", l.get("price_text") or "") else None,
        "s": l.get("site_name"), "r": l.get("region"), "c": l.get("country"), "g": l.get("grade") or l.get("grader"),
        "gr": l.get("grader"), "sa": l.get("sale"), "n": 1 if l.get("status") == "New" else None, "k": l.get("pokemon") or None,
        "a": l.get("auction_info"), "f": l.get("first_seen"), "x": cell,
        "e": l.get("edition"), "cd": l.get("card"), "gc": 1 if l.get("grade_checked") else None,
        "pd": 1 if l.get("photo_doubt") else None, "pw": 1 if l.get("price_warn") else None, "cmt": l.get("price_text") if l.get("cardmarket") else None, "cml": l.get("cm_lang")}.items() if v not in (None, "", [])}

def results_doc(sid):
    """One search's results as the page merges them (api/results/<search id>.json): the search and its listings in the page's short
    form, photos as the listing's own image address (the page's photo sheets come with the next full publish). None if no search."""
    s = load(A.search_path(sid))
    if not s: return None
    L = sorted(s.get("listings", []), key=lambda l: (l.get("price_eur") is None, l.get("price_eur") or 0))
    meta = {k: s.get(k) for k in ("id", "kind", "label", "group", "query", "updated", "created", "status")} | {
        "pokemon": s.get("pokemon") or [], "no_results": s.get("no_results") or {}, "count": len(L), "cardmarket": s.get("cardmarket") or [],
        "min_eur": next((l["price_eur"] for l in L if l.get("price_eur") is not None), None), "run_text": s.get("run_text"),
        "thumbs": [l["image"] for l in L if l.get("image")][:4]}
    return {"at": int(time.time() * 1000), "search": meta, "listings": [compact(l, l.get("image")) for l in L]}

def push_results(sid):
    """One search's results straight into the page's database (results/<search id>), so the phone shows them at once without
    rebuilding the page (motor.py after each search)."""
    d = results_doc(sid)
    if d: admin(set_=[{"coll": "results", "id": sid, "data": d}])

def engine_data():
    """What the page's own search engine needs (owner, 28 October 2026: "with only PokéFinder open on the phone, in Safari, the
    search must finish, without Claude and without anything else"): the same rules motor.py and app_job.py use to read a search and
    keep only exact titles (template.html searchOnPhone), the Pokémon names, the exchange rates and the eBay sites."""
    import motor as M, app_job as J, carta, ebay_api
    gs = M.plan_spec("x gold star")
    return {"names": [{k: p.get(k) for k in ("en", "ja", "fr", "de", "es") if p.get(k)} for p in M.names()],
            "syn": J.SYN, "accessory": J.ACCESSORY.pattern, "lotword": J.LOTWORD.pattern, "gs_star": J.GS_STAR,
            "gs_fake": J.GS_FAKE.pattern, "gs_modern": J.GS_MODERN.pattern, "gs_not": gs["not"],
            "filler": sorted(M.FILLER), "langs": {k: [v[0], sorted(v[1])] for k, v in M.LANGS.items()}, "words_ja": M.WORDS_JA,
            "graders": A.GRADERS, "first_ed": A.FIRST_ED.pattern, "unlimited": A.UNLIMITED.pattern, "not_a_card": A.NOT_A_CARD.pattern,
            "tracked": {p: rx.pattern for p, rx in A.POKEMON.items()},
            "numbers": {p: [n for c in A.CARDS if c["pokemon"] == p for n in [c["number"]] + c.get("numbers", [])] for p in A.POKEMON},
            "stamp": carta.STAMP, "reverse": carta.REVERSE, "eu": sorted(A.EU_ISO), "am": sorted(A.AM_ISO),
            "fx": (load(P("fx.json"), {}) or {}).get("rates", {}), "markets": ebay_api.MARKETS,
            "cm_urls": load(P("cardmarket", "urls.json"), {}) or {}}   # cards whose Cardmarket page is known (cardmarket.product_url)

def build():
    from PIL import Image
    idx = load(P("app", "index.json"), [])
    urls = []
    data = {"built": A.now_iso(), "v": str(int(time.time() * 1000)), "searches": [], "listings": {}}
    for card in idx:
        s = load(A.search_path(card["id"]))
        if not s: continue
        L = sorted(s.get("listings", []), key=lambda l: (l.get("price_eur") is None, l.get("price_eur") or 0))
        urls += [l["image"] for l in L if l.get("image")]
        data["searches"].append({k: s.get(k) for k in ("id", "kind", "label", "group", "query", "updated", "created", "status")} |
                                {"pokemon": s.get("pokemon") or [], "no_results": s.get("no_results") or {}, "count": len(L), "cardmarket": s.get("cardmarket") or [],
                                 "min_eur": card.get("min_eur"), "run_text": s.get("run_text")})
        data["listings"][s["id"]] = L
    todo = sorted({u for u in urls if not os.path.exists(thumb_path(u))})
    print(f"Photos: {len(set(urls))}, to download: {len(todo)}", flush=True)
    with ThreadPoolExecutor(6) as ex: list(ex.map(fetch_thumb, todo))
    # sprite sheets, one set per search (names carry a content hash so phones never show an old sheet)
    os.makedirs(os.path.join(OUT, "sheets"), exist_ok=True)
    files, groups = {}, A.GROUPS
    for s in data["searches"]:
        L = data["listings"][s["id"]]; out = []
        for k in range(0, len(L), PER):
            chunk = L[k:k + PER]
            sheet = Image.new("RGB", (CW * COLS, CH * ((len(chunk) + COLS - 1) // COLS)), (8, 18, 41))
            h = hashlib.sha1()
            cells = []
            for j, l in enumerate(chunk):
                f = thumb_path(l["image"]) if l.get("image") else None
                if f and os.path.exists(f):
                    sheet.paste(Image.open(f), ((j % COLS) * CW, (j // COLS) * CH)); h.update(l["image"].encode()); cells.append(j)
                else:
                    cells.append(None)
            name = f"sheets/{s['id']}-{k // PER}-{h.hexdigest()[:8]}.jpg"
            if not os.path.exists(os.path.join(OUT, name)):   # same name = same photos: already there
                sheet.save(os.path.join(OUT, name), "JPEG", quality=74, optimize=True)
            data.setdefault("sheets", {})[name] = (len(chunk) + COLS - 1) // COLS
            files[name] = os.path.join(OUT, name)
            for j, l in enumerate(chunk): out.append(compact(l, [name, j] if cells[j] is not None else None))
        data["listings"][s["id"]] = out
        s["thumbs"] = [x["x"] for x in out if x.get("x")][:4]
    data["groups"] = [{"id": k, "label": g["label"], "desc": g["desc"],
                       "pokemon": [{"name": c["pokemon"], "card": c["name_en"], "number": c["number"]} for c in g["cards"]]} for k, g in groups.items()]
    data["engine"] = engine_data()
    data["repo"] = repo()   # where the page opens its search requests (GitHub issues)
    page = open(TEMPLATE, encoding="utf-8").read().replace("__ENGINE__", open(ENGINE_JS, encoding="utf-8").read().replace("</", "<\\/"))
    page = page.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
    open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(page)
    save(os.path.join(OUT, "version.json"), {"v": data["v"], "built": data["built"]})
    for f in os.listdir(STATIC):   # icons, manifest, cache rules
        shutil.copyfile(os.path.join(STATIC, f), os.path.join(OUT, f))
    for old in glob.glob(os.path.join(OUT, "sheets", "*.jpg")):   # sheets no search uses any more
        if "sheets/" + os.path.basename(old) not in files: os.remove(old)
    for stale in ("publish.json",):   # left over from the claude.ai page
        if os.path.exists(os.path.join(OUT, stale)): os.remove(os.path.join(OUT, stale))
    size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(OUT) for f in fs)
    print(f"Page ready: {len(data['searches'])} searches, {sum(len(v) for v in data['listings'].values())} listings, "
          f"{len(files)} photo sheets, {size // 1024} KB in {OUT}. Publish with cloud\\publicar.bat --no-build.")

# ---------- the site: GitHub (owner, 30 October 2026: "Cloudflare now charges: move it somewhere completely free, like GitHub")
# The page is GitHub Pages (settings.json "cloud_url") of the public repository settings.json "github_repo" (Pages is free only on
# public ones). Local copy of the repository: %LOCALAPPDATA%\PokeFinderWeb (outside Google Drive, which is slow). What the
# Cloudflare database held is now:
#   requests/<id>  -> GitHub issues "Buscar: <text>" / "Grupo: <id>" opened by the owner (id "i<number>"); labels give the state
#   jobs/<id>, status/claude, results/<id> -> files api/jobs/<id>.json, api/status.json, api/results/<id>.json, pushed;
#                     .github/workflows/pages.yml publishes them with api/state.json
# git and the GitHub CLI do the work (`gh auth login` once per computer; git uses gh's login).
WEB = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "PokeFinderWeb")
GH_DIR = os.path.join(CLOUD_DIR, "github")   # the repository's own files: workflows, state.py, buscar.js
NOWINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LABELS = {"tomada": "taken", "esperando-ok": "asked", "rechazada": "rejected", "reemplazada": "replaced"}

def cfg(): return load(os.path.join(ROOT, "settings.json"), {}) or {}
def keys(): return load(KEYS, {}) or {}
def site():
    u = (cfg().get("cloud_url") or "").rstrip("/")
    return u if u.startswith("https://") and "claude.ai" not in u and "workers.dev" not in u else ""
def repo(): return cfg().get("github_repo") or ""
def owner(): return repo().split("/")[0].lower()
def enabled():
    """The phone page is set up on this computer: a page, its repository, and git and gh to reach it."""
    return bool(site() and repo() and shutil.which("git") and shutil.which("gh"))

def run(*a, cwd=None, inp=None, check=True):
    r = subprocess.run(a, cwd=cwd or WEB, input=inp, capture_output=True, text=True, encoding="utf-8", creationflags=NOWINDOW)
    if check and r.returncode: raise RuntimeError(f"{a[0]} {a[1]}: " + (r.stderr or r.stdout).strip()[-300:])
    return r.stdout

def gh(path, method="GET", body=None):
    """GitHub's API with the owner's gh login."""
    out = run("gh", "api", "-X", method, path, *(["--input", "-"] if body is not None else []), cwd=ROOT,
              inp=json.dumps(body) if body is not None else None)
    return json.loads(out) if out.strip() else None

def clone():
    if not os.path.isdir(os.path.join(WEB, ".git")):
        if not repo(): sys.exit("Falta settings.json github_repo (python nube.py setup).")
        os.makedirs(os.path.dirname(WEB), exist_ok=True)
        run("git", "clone", "-q", f"https://github.com/{repo()}.git", WEB, cwd=os.path.dirname(WEB))
    run("git", "config", "user.name", "PokéFinder"); run("git", "config", "user.email", f"{owner()}@users.noreply.github.com")
    return WEB

def sync(msg):
    """Commits what changed in the local copy and pushes it; GitHub publishes the page by itself (pages.yml, about a minute)."""
    run("git", "add", "-A")
    if run("git", "status", "--porcelain").strip(): run("git", "commit", "-q", "-m", msg)
    if not run("git", "rev-list", "--count", "HEAD", check=False).strip(): return
    for n in range(4):   # the phone searches (buscar.yml) push too: take theirs and try again
        if run("git", "ls-remote", "--heads", "origin", "main").strip(): run("git", "pull", "-q", "--rebase", "-X", "theirs", "origin", "main", check=False)
        if subprocess.run(["git", "push", "-q", "origin", "HEAD:main"], cwd=WEB, capture_output=True, creationflags=NOWINDOW).returncode == 0: return
        time.sleep(3 * (n + 1))
    raise RuntimeError("git push: GitHub no aceptó los cambios")

def doc_path(coll, i):
    if coll == "status": return os.path.join(WEB, "api", "status.json")
    if coll in ("jobs", "results") and re.fullmatch(r"[\w.-]{1,80}", i): return os.path.join(WEB, "api", coll, f"{i}.json")
    raise ValueError(f"bad write {coll}/{i}")

def issue_state(rid, data):
    """A phone request's new state, on its GitHub issue."""
    m = re.fullmatch(r"i(\d+)", str(rid))
    st = data.get("status")
    if not m or not st: return
    n, base = m.group(1), f"repos/{repo()}/issues/{m.group(1)}"
    label = {v: k for k, v in LABELS.items()}.get(st)
    if label: gh(f"{base}/labels", "POST", {"labels": [label]})
    if st == "taken" and data.get("job"): gh(f"{base}/comments", "POST", {"body": f"El ordenador la tiene (búsqueda `{data['job']}`)."})
    if st in ("done", "rejected", "replaced"):
        gh(base, "PATCH", {"state": "closed", "state_reason": "completed" if st == "done" else "not_planned"})

def admin(set_=(), merge=(), delete=()):
    """What the Worker's /api/admin did: jobs, status and results become files in the repository (pushed at once), requests
    change their GitHub issue."""
    clone(); files = False
    for w in set_:
        f = doc_path(w["coll"], w["id"]); os.makedirs(os.path.dirname(f), exist_ok=True)
        save(f, w["data"]); files = True
    for w in merge:
        if w["coll"] == "requests": issue_state(w["id"], w["data"]); continue
        f = doc_path(w["coll"], w["id"]); d = load(f, {}) or {}; d.update(w["data"])
        os.makedirs(os.path.dirname(f), exist_ok=True); save(f, d); files = True
    for w in delete:
        if w["coll"] == "requests": issue_state(w["id"], {"status": "rejected"}); continue
        f = doc_path(w["coll"], w["id"])
        if os.path.exists(f): os.remove(f); files = True
    if files: sync("Datos del ordenador")
    return {"ok": True}

def request_of(i):
    """A GitHub issue -> a phone request {id, query | group, at, status, job, phone} (only the owner's)."""
    m = re.match(r"\s*(buscar|grupo|borrar):\s*(.+)", i.get("title") or "", re.I)
    if not m or i.get("pull_request") or (i.get("user") or {}).get("login", "").lower() != owner(): return None
    lab = {l["name"] for l in i.get("labels", [])}
    st = next((v for k, v in LABELS.items() if k in lab and v in ("rejected", "replaced")), "done") if i["state"] == "closed" \
        else "taken" if "tomada" in lab else "asked" if "esperando-ok" in lab else "new"
    r = {"id": f"i{i['number']}", "at": int(dt.datetime.fromisoformat(i["created_at"].replace("Z", "+00:00")).timestamp() * 1000), "status": st}
    text = m.group(2).strip()
    if re.search(r"\[\s*completa\s*\]\s*$", text, re.I): r["depth"] = "full"   # "Buscar: <text> [completa]": full search
    text = re.sub(r"\s*\[\s*completa\s*\]\s*$", "", text, flags=re.I)[:120]
    r[{"grupo": "group", "borrar": "delete"}.get(m.group(1).lower(), "query")] = text
    if "movil-hecha" in lab: r["phone"] = "done"
    elif "movil-error" in lab: r["phone"] = "error"
    return r

def state():
    """The phone requests (the last 50 issues of the repository)."""
    iss = gh(f"repos/{repo()}/issues?state=all&per_page=50&sort=created&direction=desc") or []
    return {"requests": [r for r in map(request_of, iss) if r]}

def mirror(src, dst, keep=()):
    """dst becomes a copy of src (files of the same size are left alone; extra files go), except the names in keep."""
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(dst):
        if name in keep or os.path.exists(os.path.join(src, name)): continue
        p = os.path.join(dst, name); shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    for name in os.listdir(src):
        s, d = os.path.join(src, name), os.path.join(dst, name)
        if os.path.isdir(s): mirror(s, d)
        elif not os.path.exists(d) or os.path.getsize(d) != os.path.getsize(s) or name in ("index.html", "version.json"): shutil.copyfile(s, d)

def bundle(dst):
    """The engine GitHub Actions runs for the phone's searches (cloud/github/buscar.py, owner, 31 October 2026: "search like the
    computer, in every market"), at dst (the repository's .github/motor): the scripts and page readers, the card lists, today's
    exchange rates, the card and Cardmarket caches, and what the computer already knows about listings (cannot be bought, not the
    card, grades read on the label), so the phone's results match the computer's. Never .secrets (the eBay keys are the
    repository's encrypted secrets), never the photo caches, and settings.json without the owner's private links."""
    if os.path.isdir(dst): shutil.rmtree(dst)
    shutil.copytree(os.path.join(SCREENER, "scripts"), os.path.join(dst, "screener", "scripts"), ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(os.path.join(SCREENER, "browser"), os.path.join(dst, "screener", "browser"))
    for f in ("cards.json", "pokemon_names.json", "shipping.json"):
        shutil.copyfile(os.path.join(SCREENER, f), os.path.join(dst, "screener", f))
    s = cfg()
    for k in ("dashboard_url", "cloud_url_cloudflare_old", "cloud_url_claude_old"): s[k] = ""
    save(os.path.join(dst, "settings.json"), s)
    for rel in (("fx.json",), ("app", "images", "gone.json"), ("cardmarket", "cards.json"), ("cardmarket", "images.json"),
                ("cardmarket", "set_names.json"), ("cardmarket", "urls.json")):
        if os.path.exists(P(*rel)):
            os.makedirs(os.path.dirname(os.path.join(dst, "data", *rel)), exist_ok=True)
            shutil.copyfile(P(*rel), os.path.join(dst, "data", *rel))
    grades = {k: {x: v[x] for x in ("grade", "edition", "raw") if v.get(x) not in (None, "")}
              for k, v in (load(P("app", "grades.json"), {}) or {}).items() if v.get("grade") or v.get("edition") or v.get("raw")}
    save(os.path.join(dst, "data", "app", "grades.json"), grades)
    save(os.path.join(dst, "data", "app", "photo_auto.json"),
         {k: {"verdict": v["verdict"]} for k, v in (load(P("app", "photo_auto.json"), {}) or {}).items() if v.get("verdict") in ("other", "wrong")})
    save(os.path.join(dst, "data", "app", "photo_review.json"),
         {k: {"ok": False} for k, v in (load(P("app", "photo_review.json"), {}) or {}).items() if not v.get("ok")})

def publish():
    """The page built by `build` (cloud/out), the repository's workflows and the engine of the phone searches, pushed to GitHub.
    The page is up again about a minute later; the phone reloads by itself (version.json)."""
    clone()
    mirror(OUT, WEB, keep={".git", ".github", "api"})
    for stale in ("_headers",):   # Cloudflare's cache rules
        if os.path.exists(os.path.join(WEB, stale)): os.remove(os.path.join(WEB, stale))
    wf = os.path.join(WEB, ".github", "workflows"); os.makedirs(wf, exist_ok=True)
    for f in os.listdir(GH_DIR):
        shutil.copyfile(os.path.join(GH_DIR, f), os.path.join(wf if f.endswith(".yml") else os.path.dirname(wf), f))
    # the phone's eBay-only search of 30 October 2026 (engine.js in Node), replaced by the whole engine on 31 October 2026
    for stale in ("buscar.js", "engine.js", "engine.json"):
        if os.path.exists(os.path.join(WEB, ".github", stale)): os.remove(os.path.join(WEB, ".github", stale))
    bundle(os.path.join(WEB, ".github", "motor"))
    sync("Página publicada " + ((load(os.path.join(OUT, "version.json"), {}) or {}).get("built") or ""))
    print(f"PUBLICADA: {site()}/  (GitHub la pone en marcha en un minuto)")

def setup():
    """Once per GitHub account: issue labels, the eBay keys as the repository's encrypted secrets (for the phone searches; read
    from .secrets/ebay_api.json, never printed) and GitHub Pages published by the workflow. The repository must exist
    (settings.json github_repo; created with `gh repo create <owner>/pokefinder --public`)."""
    R = repo()
    if not R: sys.exit("Falta settings.json github_repo.")
    for name, (color, desc) in {"tomada": ("1f6feb", "El ordenador la tiene"), "esperando-ok": ("d4a72c", "Esperando el OK del dueño en Claude"),
                                "movil-hecha": ("2da44e", "Buscada en todos los mercados desde GitHub"), "movil-error": ("cf222e", "La búsqueda en GitHub falló"),
                                "rechazada": ("6e7781", "El dueño dijo que no"), "reemplazada": ("6e7781", "Pedida otra vez")}.items():
        run("gh", "label", "create", name, "--color", color, "--description", desc, "--repo", R, "--force", cwd=ROOT)
    eb = load(os.path.join(ROOT, ".secrets", "ebay_api.json"), {}) or {}
    for secret, k in (("EBAY_APP_ID", "app_id"), ("EBAY_CERT_ID", "cert_id")):
        if eb.get(k): run("gh", "secret", "set", secret, "--repo", R, cwd=ROOT, inp=eb[k])
    run("gh", "api", "-X", "POST", f"repos/{R}/pages", "-f", "build_type=workflow", cwd=ROOT, check=False)   # already on: 409, fine
    print("GitHub listo:", R, "· página", site())

def link():
    """The owner's link: the page plus the phone key, a GitHub token that can only open issues in this repository (.secrets/cloud.json
    "phone_token"; made by the owner at github.com/settings/personal-access-tokens/new)."""
    t = keys().get("phone_token")
    print(f"{site()}/?k={t}" if t else f"{site()}/   (sin clave: para pedir búsquedas desde el móvil hace falta phone_token en .secrets/cloud.json)")

def waiting_requests(st=None):
    """Phone requests nobody has taken yet: "new" (just asked) or "asked" (Claude asked the owner for the OK). A search GitHub is
    still doing for the phone (buscar.yml: no movil-hecha / movil-error label yet, asked less than 45 minutes ago, its time limit)
    waits until it ends: the computer then completes it instead of searching it at the same time (31 October 2026)."""
    st = st or state()
    github = lambda r: r.get("query") and not r.get("phone") and time.time() * 1000 - r["at"] < 45 * 60e3
    return [r for r in st.get("requests", []) if r.get("status") in ("new", "asked") and (r.get("query") or r.get("group") or r.get("delete")) and not github(r)]

def pending_cmd():
    """For the scheduled check: tells the page Claude is checking (heartbeat) and prints the waiting requests (JSON list)."""
    status_cmd(True, quiet=True)
    out = [{"id": r["id"], "search": r.get("query") or A.GROUPS.get(r.get("group"), {}).get("label") or r.get("group"),
            "asked_min_ago": round((time.time() * 1000 - r["at"]) / 60000)} for r in waiting_requests()]
    print(json.dumps(out, ensure_ascii=False))

def asked_cmd():
    """The owner is being asked for the OK in Claude: the phone shows it."""
    ids = [r["id"] for r in waiting_requests() if r["status"] == "new"]
    if ids: admin(merge=[{"coll": "requests", "id": i, "data": {"status": "asked"}} for i in ids])
    print(f"ok ({len(ids)})")

def reject_cmd(ids):
    """The owner said no in Claude: the requests close on the phone."""
    ids = ids or [r["id"] for r in waiting_requests()]
    if ids: admin(merge=[{"coll": "requests", "id": i, "data": {"status": "rejected"}} for i in ids])
    print(f"ok ({len(ids)})")

def requests_cmd(only=None):
    st = state()
    mp = load(MAP, {}) or {}
    out = []
    for r in waiting_requests(st):
        if only and r["id"] not in only: continue
        if r.get("delete"):   # "Borrar: <id>" from the phone page (owner, 1 November 2026): the saved search goes, here and on the page
            sid = r["delete"]
            try:
                req = urllib.request.Request("http://127.0.0.1:8800/api/delete", data=json.dumps({"id": sid}).encode(),
                                             headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=20).read()
                gone = [{"coll": "results", "id": sid}] if os.path.exists(doc_path("results", sid)) else []
                admin(merge=[{"coll": "requests", "id": r["id"], "data": {"status": "done"}}], delete=gone)
                out.append({"request": r["id"], "deleted": sid})
            except Exception as e:
                out.append({"request": r["id"], "delete": sid, "error": f"{type(e).__name__}: {e}"})
            continue
        q = re.sub(r"\s+", " ", str(r.get("query") or ""))[:120].strip()
        ask = {**({"group": r["group"]} if r.get("group") in A.GROUPS else {"query": q}), "depth": r.get("depth") or "light"}
        try:
            req = urllib.request.Request("http://127.0.0.1:8800/api/search", data=json.dumps(ask).encode(),
                                         headers={"Content-Type": "application/json"})
            j = json.load(urllib.request.urlopen(req, timeout=20))
        except Exception as e:
            out.append({"request": r["id"], "query": q or r.get("group"), "error": f"{type(e).__name__}: {e}"}); continue
        mp[j["id"]] = r["id"]
        admin(merge=[{"coll": "requests", "id": r["id"], "data": {"status": "taken", "job": j["id"], "search": j["search_id"]}}],
              set_=[{"coll": "jobs", "id": r["id"], "data": job_data(j["id"])}])
        out.append({"request": r["id"], "query": q or r.get("group"), "job": j["id"], "search": j["search_id"]})
    save(MAP, mp)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return out

def job_data(jid):
    j = load(A.job_path(jid))
    if not j: sys.exit(f"no job {jid}")
    return {"label": j["label"], "status": j["status"], "progress": j.get("progress", 0), "message": j.get("message", ""),
            "search": j["search_id"], "at": int(time.time() * 1000)}

def job_cmd(jid, doc_id=None):
    rid = (load(MAP, {}) or {}).get(jid)
    doc_id = doc_id or rid or jid
    d = job_data(jid)
    # every write is a publish on GitHub (about a minute): the bar moves every 3 minutes at most, a change of state at once
    last = load(os.path.join(WEB, "api", "jobs", f"{doc_id}.json"), {}) or {}
    if last.get("status") == d["status"] and d["at"] - (last.get("at") or 0) < 180e3:
        print(json.dumps({"id": doc_id, **d, "sent": False}, ensure_ascii=False)); return
    writes = {"merge": [{"coll": "requests", "id": rid, "data": {"status": "done"}}]} if rid and d["status"] in ("done", "error", "cancelled") else {}
    admin(set_=[{"coll": "jobs", "id": doc_id, "data": d}], **writes)
    print(json.dumps({"id": doc_id, **d}, ensure_ascii=False))

def status_cmd(on, quiet=False):
    """The page shows "Ordenador activo" for 45 minutes after this; on GitHub every write is a publish, so it is sent every
    20 minutes at most (motor.py calls it every minute), and at once when it changes."""
    last = load(os.path.join(WEB, "api", "status.json"), {}) or {}
    if last.get("listening") != on or time.time() * 1000 - (last.get("at") or 0) > 20 * 60e3:
        admin(set_=[{"coll": "status", "id": "claude", "data": {"at": int(time.time() * 1000), "listening": on}}])
    if not quiet: print("ok")

if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else ""
    if c == "build": build()
    elif c == "requests": requests_cmd(sys.argv[2:] or None)
    elif c == "pending": pending_cmd()
    elif c == "asked": asked_cmd()
    elif c == "reject": reject_cmd(sys.argv[2:])
    elif c == "publish": publish()
    elif c == "job": job_cmd(sys.argv[2], sys.argv[sys.argv.index("--id") + 1] if "--id" in sys.argv else None)
    elif c == "status": status_cmd(sys.argv[2:3] != ["off"])
    elif c == "link": link()
    elif c == "setup": setup()
    else: print(__doc__)
