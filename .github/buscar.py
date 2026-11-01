"""A search typed on the phone page, done by GitHub Actions (buscar.yml) with the computer's own engine (owner, 31 October 2026:
"from the phone, search the card the way the computer does, in every market, instead of sending me to GitHub").

The engine is the app's (screener/scripts and the page readers, copied to .github/motor by `nube.py publish`): eBay's 16 sites
through the API, then the same hidden browser (Playwright's Chromium) reading Mercari, Rakuma, Magi, Card Rush, SNKRDUNK, Hareruya2,
Rakuten, GempireCards and Vinted with the same readers and title rules, the check that each listing can be bought, the photo
checks and Cardmarket: motor.typed, step by step. Tested from GitHub on 31 October 2026: every one of those sites answers except
Card Rush (Cloudflare check, as on the computer); Buyee and Wallapop turn automated browsers away and are not opened.
Two differences with the computer: the sites are read side by side (one browser per site, each at a person's pace on its own
site), and the grade on a slab's label is not read (that is Windows text recognition): the title says it until the computer's
app completes the search (the issue stays open for it, labelled movil-hecha).

The phone follows the search on its issue: one comment, edited as it goes (progress, message, and the commit holding the newest
results); the page reads it with the phone key. Results are api/results/<search id>.json, pushed after eBay, after the markets
and at the end, so the phone shows them while the checks go on (it reads them at raw.githubusercontent.com/<repo>/<commit>/...).
What the engine learnt about listings (eBay checks, cannot be bought, photos) is kept between searches on the repository's branch
CACHE_BRANCH (one commit, replaced each time), as the computer keeps data/app/checks.json: a listing checked in the last day is
not asked about again, which spares eBay's daily allowance. (GitHub's own actions/cache cannot be written by a run an issue
started: anyone can open issues in a public repository.)
  python .github/buscar.py     (env: TITLE "Buscar: <text>", NUMBER, GITHUB_REPOSITORY, GH_TOKEN, EBAY_APP_ID, EBAY_CERT_ID,
                                BRANCH, main by default)"""
import json, os, re, shutil, subprocess, sys, tempfile, threading, time, traceback, urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))   # .github
REPO_DIR = os.path.dirname(HERE)
# the engine runs from a copy outside the repository: its data files change as it works, and the repository must stay clean to
# take the pushes of other searches before its own (31 October 2026: "charizard 4/102" could not push its results)
MOTOR = os.path.join(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir(), "pokefinder-motor")
REPO, NUMBER, BRANCH = os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("NUMBER") or "", os.environ.get("BRANCH") or "main"
QUERY = re.sub(r"\s+", " ", re.sub(r"^\s*Buscar:\s*", "", os.environ.get("TITLE", ""), flags=re.I)).strip()[:160]
DEPTH = "full" if re.search(r"\[\s*completa\s*\]\s*$", QUERY, re.I) else "light"   # light: quick; full: every market (1 November 2026)
QUERY = re.sub(r"\s*\[\s*completa\s*\]\s*$", "", QUERY, flags=re.I).strip()[:120]
MARK = "<!-- pokefinder "   # the page finds the state in the comment by this (template.html phoneState)
CACHE_BRANCH = "cache-buscador"
KEPT = {"checks.json": ("app", "checks.json"), "images.json": ("app", "images.json"), "gone.json": ("app", "images", "gone.json")}

if os.path.isdir(MOTOR): shutil.rmtree(MOTOR)
shutil.copytree(os.path.join(HERE, "motor"), MOTOR)
# the eBay keys (this repository's encrypted secrets) where the engine looks for them, before it is imported: outside the
# repository, never printed
if os.environ.get("EBAY_APP_ID") and os.environ.get("EBAY_CERT_ID"):
    os.makedirs(os.path.join(MOTOR, ".secrets"), exist_ok=True)
    with open(os.path.join(MOTOR, ".secrets", "ebay_api.json"), "w", encoding="utf-8") as f:
        json.dump({"app_id": os.environ["EBAY_APP_ID"].strip(), "cert_id": os.environ["EBAY_CERT_ID"].strip()}, f)
sys.path.insert(0, os.path.join(MOTOR, "screener", "scripts")); os.chdir(os.path.join(MOTOR, "screener", "scripts"))
import motor as M, app_lib as A, nube   # noqa: E402
from common import P, load, save        # noqa: E402

def gitio(*a, inp=None):
    return subprocess.run(("git",) + a, cwd=REPO_DIR, input=inp, capture_output=True, text=True, encoding="utf-8", errors="replace")

def restore_cache():
    """The last searches' checks, photos and listings that cannot be bought, joined with what the computer published."""
    if gitio("fetch", "-q", "--depth=1", "origin", CACHE_BRANCH).returncode: return   # none yet
    for name, rel in KEPT.items():
        r = gitio("show", f"FETCH_HEAD:{name}")
        try: got = json.loads(r.stdout) if r.returncode == 0 else None
        except ValueError: got = None
        if got is None: continue
        if name == "gone.json": got = sorted(set(got) | set(load(P(*rel), []) or []))
        save(P(*rel), got)

def keep_cache():
    """This search's checks for the next ones (checks older than two days are dropped: they are asked again anyway): one commit
    with no history on CACHE_BRANCH, so keeping them never makes the repository grow. The last search to end wins."""
    checks = {k: v for k, v in (load(P("app", "checks.json"), {}) or {}).items() if time.time() - (v.get("at") or 0) < 2 * 86400}
    files = {"checks.json": checks, "images.json": {k: v for k, v in (load(P("app", "images.json"), {}) or {}).items() if k in checks},
             "gone.json": load(P("app", "images", "gone.json"), []) or []}
    try:
        tree = "".join(f"100644 blob {gitio('hash-object', '-w', '--stdin', inp=json.dumps(v, ensure_ascii=False)).stdout.strip()}\t{n}\n" for n, v in files.items())
        commit = gitio("commit-tree", gitio("mktree", inp=tree).stdout.strip(), "-m", "Lo que el buscador sabe de los anuncios (lo usa la próxima búsqueda)").stdout.strip()
        r = gitio("push", "-q", "-f", "origin", f"{commit}:refs/heads/{CACHE_BRANCH}")
        if r.returncode: print("  checks not kept:", (r.stderr or r.stdout).strip()[-200:])
    except Exception as e:
        print("  checks not kept:", type(e).__name__, e)

jobs_lock, say_lock = threading.Lock(), threading.Lock()

# ---------------------------------------------------------------- the issue comment the phone reads
def api(path, method="GET", body=None):
    req = urllib.request.Request("https://api.github.com/repos/" + REPO + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + os.environ.get("GH_TOKEN", ""), "Accept": "application/vnd.github+json",
                                          "Content-Type": "application/json", "User-Agent": "PokeFinder"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
        return json.loads(body) if body else None

STATE = {"progress": 0, "status": "running", "message": "", "sha": None, "search": None, "count": None}
SENT = {"comment": None, "body": None}
send_lock, wake = threading.Lock(), threading.Event()

def say(**kw):
    """The search's new state for the phone. Only remembered here: the sender (below) puts it on the issue at once when the stage or
    the results change, else every 3 seconds, so no browser ever waits for GitHub's API."""
    with say_lock:
        before = (STATE["status"], STATE["sha"])
        p = kw.pop("progress", None)
        STATE.update({k: v for k, v in kw.items() if v is not None})
        if p is not None: STATE["progress"] = p if STATE["status"] == "done" else max(STATE["progress"], p)   # the bar never goes back
        if (STATE["status"], STATE["sha"]) != before: wake.set()

def send(tries=1):
    """The state on the issue: one comment, edited (the one buscar.yml's first step opened). True when GitHub has it."""
    if not NUMBER: return True
    with send_lock:
        with say_lock: doc = dict(STATE)
        body = f"**{doc['progress']} %** · {doc['message']}\n\n{MARK}{json.dumps(doc, ensure_ascii=False)} -->"
        for n in range(tries):
            if body == SENT["body"]: return True
            try:
                if not SENT["comment"]:   # only GitHub's own comment: anyone can comment on a public repository (the page checks too)
                    SENT["comment"] = next((c["id"] for c in api(f"/issues/{NUMBER}/comments?per_page=100") or []
                                            if MARK in (c.get("body") or "") and (c.get("user") or {}).get("login") == "github-actions[bot]"), None)
                if SENT["comment"]: api(f"/issues/comments/{SENT['comment']}", "PATCH", {"body": body})
                else: SENT["comment"] = api(f"/issues/{NUMBER}/comments", "POST", {"body": body})["id"]
                SENT["body"] = body
                return True
            except Exception as e:
                print("  comment not updated:", type(e).__name__, e, flush=True)
                if n + 1 < tries: time.sleep(2 * 2 ** n)
        return False

def sender():
    while True:
        wake.wait(3); wake.clear()
        send()

def finish(**kw):
    """The last state (done or error): sent at once, and tried again for half a minute if GitHub does not take it."""
    say(**kw); send(tries=5)

def phone_job(jid):
    """motor.put's link to the phone: the job's progress and message, as the computer's app shows them."""
    j = M.job(jid) or {}
    msg = j.get("message") or ""
    if msg.startswith("Leyendo las notas"): msg = "Comprobando las fotos y los precios de Cardmarket…"   # no label reading here
    say(progress=j.get("progress"), message=msg)

# ---------------------------------------------------------------- results in the repository
def git(*a, check=True):
    r = subprocess.run(("git",) + a, cwd=REPO_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode: raise RuntimeError(f"git {a[0]}: {(r.stderr or r.stdout).strip()[-300:]}")
    return r

def push(sid, final=False):
    """The search's results so far -> api/results/<sid>.json, committed and pushed (only that file). Returns the commit."""
    doc = nube.results_doc(sid)
    if not doc: return None
    doc.update(by="phone", request=f"i{NUMBER}" if NUMBER else None)
    doc["search"].update(phone=True, final=final)
    rel = f"api/results/{sid}.json"
    os.makedirs(os.path.join(REPO_DIR, "api", "results"), exist_ok=True)
    with open(os.path.join(REPO_DIR, rel), "w", encoding="utf-8") as h: json.dump(doc, h, ensure_ascii=False, separators=(",", ":"))
    git("add", rel)
    if git("diff", "--cached", "--quiet", check=False).returncode:
        git("commit", "-q", "-m", f"Búsqueda desde el móvil{' #' + NUMBER if NUMBER else ''}: {QUERY}" + ("" if final else " (sigue)"))
    why = ""
    for n in range(6):   # the computer and other phone searches push too (other files): take theirs and try again
        r = git("pull", "-q", "--rebase", "-X", "theirs", "origin", BRANCH, check=False)
        if r.returncode: why = (r.stderr or r.stdout).strip()[-200:]; git("rebase", "--abort", check=False)
        r = git("push", "-q", "origin", "HEAD:" + BRANCH, check=False)
        if r.returncode == 0: return git("rev-parse", "HEAD").stdout.strip()
        why = why or (r.stderr or r.stdout).strip()[-200:]
        time.sleep(3 * (n + 1))
    raise RuntimeError("git push: GitHub no aceptó los resultados: " + why)

def publish_page():
    """api/state.json (what other devices see) is made by pages.yml; a push made here with GitHub's own token does not start it."""
    if BRANCH == "main": subprocess.run(["gh", "workflow", "run", "pages.yml", "--ref", "main", "-R", REPO], capture_output=True)

# ---------------------------------------------------------------- the engine's browser steps, sites side by side
def put(jid, **kw):
    with jobs_lock: return M.put(jid, **kw)

SIDE = 3   # browsers at once: with eight, GitHub's machine (4 processors) drew Mercari and Rakuten too slowly and they read 0 (31 October 2026)

def side_by_side(items, host, read, jid, lo, hi, label):
    """Each site's items in its own hidden browser, three sites at a time; a person's pace within each site (motor.Browser.pace)."""
    groups, done = {}, [0]
    for x in items: groups.setdefault(host(x), []).append(x)
    def worker(xs):
        br = None
        try:   # a browser that fails leaves its site unread (listed as not read), never the whole search
            br = M.Browser()
            for x in xs:
                name = read(br, x)
                with jobs_lock:
                    done[0] += 1; n = done[0]
                put(jid, progress=lo + int((hi - lo) * n / len(items)), message=label(name, n, len(items)))
        except Exception as e:
            M.log(f"  browser failed on {host(xs[0])}:", type(e).__name__, str(e)[:200])
        finally:
            if br: br.close()
    # the biggest sites first, so the last one to finish is not a long one started late
    with ThreadPoolExecutor(min(SIDE, len(groups))) as ex: list(ex.map(worker, sorted(groups.values(), key=len, reverse=True)))

def again(items, read):
    """Pages that came back empty in the side-by-side pass, read once more alone (as the computer reads them)."""
    if not items: return
    br = None
    try:
        br = M.Browser()
        for x in items: read(br, x)
    except Exception as e:
        M.log("  second reading failed:", type(e).__name__, str(e)[:200])
    finally:
        if br: br.close()

def read_pages(jid, bdir, lo=15, hi=80, label="Leyendo"):
    """motor.read_pages, side by side; a page that read nothing (not blocked) is read again alone."""
    todo = [p for p in load(os.path.join(M.P(), bdir, "pages.json"), []) if not p.get("api") and p["site"] not in M.SKIP
            and not os.path.exists(os.path.join(M.P(), bdir, "pages", f"{p['i']:03d}.json"))]
    if not todo: return
    os.makedirs(os.path.join(M.P(), bdir, "pages"), exist_ok=True)
    out = lambda p: os.path.join(M.P(), bdir, "pages", f"{p['i']:03d}.json")
    def read(br, p):
        d = br.read(p["url"], p["js"], p.get("viewport", "tall"))
        old = load(out(p))
        # a second reading never replaces a fuller one, nor a page read with one that was turned away
        if not (old and not old.get("blocked") and (d.get("blocked") or (old.get("n") and not d.get("n")))): save(out(p), d)
        M.log(f"  page {p['i']} {p['site']}:", "BLOCKED " + str(d.get("title")) if d.get("blocked") else f"{d.get('n')} read, {len(d.get('rows', []))} kept")
        return A.SITE_NAME.get(p["site"], p["site"])
    side_by_side(todo, lambda p: p["site"], read, jid, lo, hi, lambda name, n, t: f"{label}: {name} ({n} de {t} páginas)")
    # Mercari (drawn while scrolling) and Rakuten (10 seconds for its results) are the readers a busy machine can cut short; the
    # others wait for their results. Read again when they found nothing while another site found something.
    empty = [p for p in todo if p["site"] in ("mercari", "rakuten") and not (load(out(p)) or {}).get("blocked") and not (load(out(p)) or {}).get("n")]
    if empty and any((load(out(p)) or {}).get("n") for p in todo):
        put(jid, message=f"{label}: otra vez {', '.join(sorted({A.SITE_NAME.get(p['site'], p['site']) for p in empty}))}")
        again(empty, read)

def read_queue(jid, queue, outdir, js, lo, hi, label, skip_site=None):
    """motor.read_queue (still for sale? can it be bought?), side by side, with the same listings left out; a listing found
    without a buy button is opened once more alone before it is ruled out (a page drawn slowly shows its button late)."""
    os.makedirs(outdir, exist_ok=True)
    todo = [q for q in queue if not os.path.exists(os.path.join(outdir, M.safe(q["key"]) + ".json"))
            and not M.SKIP_HOSTS.search(M.direct(q["url"])) and not (skip_site and skip_site(q))
            and not (M.HAS_KEYS and re.search(r"//(?:www\.)?ebay\.", M.direct(q["url"])))]
    if not todo: return
    out = lambda q: os.path.join(outdir, M.safe(q["key"]) + ".json")
    def read(br, q):
        d = br.read(M.direct(q["url"]), js)
        if d.get("blocked"): M.log("  blocked:", q["url"], d.get("title"))   # not saved: no verdict
        else: save(out(q), d)
    side_by_side(todo, lambda q: re.sub(r"^https?://(?:www\.)?([^/]+).*", r"\1", M.direct(q["url"])), read, jid, lo, hi,
                 lambda name, n, t: f"{label} ({n} de {t})")
    again([q for q in todo if (load(out(q)) or {}).get("reason") == "sin botón de compra"], read)

def prefetch_photos(sid):
    """Every listing photo downloaded, twelve at a time and at its largest size, while the listings are checked (the photo checks
    then read them from the cache; motor.check_photos waits for this to end)."""
    import leer_etiqueta as E
    urls = [l["image"] for l in (load(A.search_path(sid)) or {}).get("listings", []) if l.get("image")]
    def get(u):
        try: E.image(u)
        except Exception: pass
    def all_of_them():
        with ThreadPoolExecutor(12) as ex: list(ex.map(get, urls))
    t = threading.Thread(target=all_of_them, daemon=True); t.start()
    check_photos = M.check_photos
    def after_photos(*a, **kw):
        t.join(); return check_photos(*a, **kw)
    M.check_photos = after_photos

# ---------------------------------------------------------------- the search
def new_job(query):
    """server.new_job for a typed search, without the local server."""
    sid = A.slug(query)
    jid = f"{sid}-{A.now_iso()[:16].replace(':', '').replace('-', '').replace('T', '-')}"
    save(A.job_path(jid), {"id": jid, "search_id": sid, "kind": "text", "group": None, "query": query, "label": query, "status": "queued", "depth": DEPTH,
                           "progress": 3, "created": A.now_iso(), "message": "En cola", "browser_dir": f"app/jobs/{jid}/browser"})
    A.save_search({"id": sid, "kind": "text", "group": None, "query": query, "label": query, "listings": [], "pokemon": [],
                   "no_results": {}, "status": "searching", "job": jid})
    return jid, sid

def count(sid): return len((load(A.search_path(sid)) or {}).get("listings", []))

def complete_before(sid):
    """The search already has complete results on the page (searched before, here or on the computer). They stay until this search
    ends, instead of eBay's or the markets' results without their checks (a refresh cut off half way would lose them)."""
    f = os.path.join(REPO_DIR, "api", "results", sid + ".json")
    if os.path.exists(f): return ((load(f) or {}).get("search") or {}).get("final") is not False
    try: return f'"id":"{sid}"' in open(os.path.join(REPO_DIR, "index.html"), encoding="utf-8").read()   # the page's own searches
    except OSError: return False

def main():
    if len(QUERY) < 2: raise SystemExit("búsqueda vacía")
    threading.Thread(target=sender, daemon=True).start()
    restore_cache()
    jid, sid = new_job(QUERY)
    say(progress=5, search=sid, message="GitHub la recibe. Buscando en eBay (16 países)…")
    M.cloud_on = lambda: False   # the computer's link to the page; here the comment and the pushes do that
    M.phone_job, M.phone_results = phone_job, lambda sids: None
    M.read_pages, M.read_queue = read_pages, read_queue
    early = not complete_before(sid)   # results shown as they come (a refresh keeps the complete ones until the end)
    def show(s, **kw):
        try: say(sha=push(s) if early else None, count=count(s), **kw)
        except Exception as e:   # the phone sees them at the end; the search goes on
            print("  results so far not pushed:", e); say(count=count(s), **kw)
    def partial(s):   # every market read, before the checks: the phone shows what was found while the checks go on
        show(s, progress=78, message=f"{count(s)} anuncios en todos los mercados. Comprobando que se pueden comprar…")
        if early: publish_page()
        prefetch_photos(s)
    M.partial = partial
    if M.HAS_KEYS:   # eBay first, at once, as the computer's server does (app_job.py ebay); motor.typed then goes on from there
        put(jid, status="ebay", progress=6, message="Buscando en eBay (16 países)…")
        M.run(["app_job.py", "ebay", jid], check=False)
        show(sid, progress=15, message=f"eBay: {count(sid)} anuncios. Ahora Mercari, Rakuma, Magi, SNKRDUNK, Rakuten, Vinted…")
    M.typed(jid)
    keep_cache()
    s = load(A.search_path(sid)) or {}
    nr = (s.get("no_results") or {}).get("not_read") or []
    finish(progress=100, status="done", sha=push(sid, final=True), count=count(sid),
           message=f"Lista: {count(sid)} anuncios." + (f" No se pudieron leer: {', '.join(nr)}." if nr else ""))
    publish_page()
    if NUMBER:   # after the last message (the page goes by the message first; the label is for the computer and other devices)
        try: api(f"/issues/{NUMBER}/labels", "POST", {"labels": ["movil-hecha"]})
        except Exception as e: print("  label not added:", e)
    print(f"{count(sid)} anuncios -> api/results/{sid}.json")

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        main()
    except BaseException as e:
        traceback.print_exc()
        if NUMBER:
            try: api(f"/issues/{NUMBER}/labels", "POST", {"labels": ["movil-error"]})
            except Exception: pass
        finish(status="error", message=f"No se pudo terminar la búsqueda ({type(e).__name__}). Inténtalo otra vez.")
        sys.exit(1)
