"""Card condition DECLARED BY THE SELLER on eBay (owner, 2 November 2026: "hay que ser muy preciso con las condiciones").
eBay's item page carries "Card Condition" as structured data (conditionDescriptors): Near Mint or Better / Lightly played (Excellent) / Moderately played
(Very good) / Heavily played (Poor), with the seller's notes on defects (surface scuffing, fuzzy corners, edge chipping...). That is a choice the seller made,
far more reliable than a word in a title. The search API gives only "Ungraded" / "Graded", so each listing is asked once (get_item_by_legacy_id, 1 call).
Saved in data/app/condiciones.json {item id: {"c": "nm|lp|mp|hp|unk", "t": the seller's text, "i": [defects], "at": day}}; the server adds it to the listings it serves.
Only ungraded eBay listings are asked, newest searches first, at most MAX_DAY calls a day (eBay allows 5,000 and the searches and the market snapshot share them).
The server runs it when a search or snapshot leaves listings without it (toca()), or by hand:  python condiciones.py [--max N] [--lista]"""
import datetime as dt, glob, json, os, re, subprocess, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor
from common import P, load, save, ROOT

FILE = P("app", "condiciones.json"); STATE = P("app", "condiciones_estado.json")
MAX_DAY = 1500
# the descriptor text comes in the language of the listing's eBay site: English, German, Spanish, French, Italian
RULES = [("graded", r"grading|authenticat|\(psa\)|\(cgc\)|\(bgs\)|\btag\b|\bace\b|^other$|^overig"),
         ("hp", r"heav(?:y|ily)|poor|zwaar\s+gebruikt|stark\s+bespielt|muy\s+usad|fortement|tr[eè]s\s+ab[iî]m|molto\s+usur|scarso"),
         ("mp", r"moderate(?:ly)?|gemiddeld\s+gebruikt|very\s+good|m[aä][sß]ig\s+bespielt|moderadamente|uso\s+moderado|mod[eé]r[eé]ment|moderatamente|molto\s+buon"),
         ("lp", r"light(?:ly)?\s+play|weinig\s+gebruikt|excellent|leicht\s+bespielt|uso\s+escaso|l[eé]g[eè]rement|leggermente|poco\s+usur|lightly"),
         ("nm", r"near\s*mint|neuwertig|casi\s+nuev|quasi\s+(?:nuovo|neuf)|presque\s+neuf|fast\s+neu|mint")]
def cond_code(text):
    t = (text or "").lower()
    for c, rx in RULES:
        if re.search(rx, t): return c
    return "unk"

def fetch(iid, tok):
    req = urllib.request.Request("https://api.ebay.com/buy/browse/v1/item/get_item_by_legacy_id?legacy_item_id=" + iid,
                                 headers={"Authorization": "Bearer " + tok, "X-EBAY-C-MARKETPLACE-ID": "EBAY_ES", "X-EBAY-C-ENDUSERCTX": "contextualLocation=country%3DES"})
    import ebay_cuota as Q
    for n in range(3):
        if not Q.permitido("estados"): return None      # only the reserve is left: the owner's searches keep it
        Q.registrar("estados")
        try:
            d = json.load(urllib.request.urlopen(req, timeout=30)); break
        except urllib.error.HTTPError as e:
            if e.code == 404: return {"c": "gone", "t": "", "i": [], "at": dt.date.today().isoformat()}
            if e.code in (429, 500, 502, 503) and n < 2: time.sleep(4 * (n + 1)); continue
            return None
        except Exception:
            if n < 2: time.sleep(3); continue
            return None
    ds = [x for x in d.get("conditionDescriptors") or [] if x.get("values")]
    if not ds: return {"c": "none", "t": "", "i": [], "at": dt.date.today().isoformat()}   # the seller chose nothing (or it is graded): the title is all there is
    v = ds[0]["values"][0]
    return {"c": cond_code(v.get("content")), "t": v.get("content") or "", "i": [str(x) for x in v.get("additionalInfo") or []][:6], "at": dt.date.today().isoformat()}

def pending():
    """Ungraded eBay listings of the saved searches that have no answer yet. Two searches sharing a listing ask once."""
    done, out, seen = load(FILE, {}) or {}, [], set()
    files = sorted(glob.glob(P("app", "searches", "*.json")), key=os.path.getmtime, reverse=True)
    for f in files:
        s = load(f) or {}
        for l in s.get("listings") or []:
            m = re.search(r"/itm/(\d{9,})", l.get("url") or "")
            if l.get("site") == "ebay" and not l.get("grader") and m and m.group(1) not in done and m.group(1) not in seen:
                seen.add(m.group(1)); out.append(m.group(1))
    return out

def used_today():
    s = load(STATE, {}) or {}
    return s.get("n", 0) if s.get("day") == dt.date.today().isoformat() else 0

def run(limit=None):
    from ebay_api import token
    try:      # the conditions the other owner already read are taken from the repository, not asked again (compartir.py)
        import compartir; aj = compartir.estados_ajenos()
        if aj:
            mios = load(FILE, {}) or {}; nuevos = {k: v for k, v in aj.items() if k not in mios}
            if nuevos: mios.update(nuevos); save(FILE, mios)
    except Exception: pass
    todo = pending(); room = max(0, MAX_DAY - used_today()); todo = todo[:min(room, limit or MAX_DAY)]
    if not todo: return 0
    tok, done = token(), load(FILE, {}) or {}
    hechos = {}
    save(STATE, {"day": dt.date.today().isoformat(), "n": used_today() + len(todo), "running": True, "beat": time.time()})
    with ThreadPoolExecutor(8) as ex:
        for i in range(0, len(todo), 80):
            for iid, r in zip(todo[i:i + 80], ex.map(lambda x: fetch(x, tok), todo[i:i + 80])):
                if r: done[iid] = r; hechos[iid] = r
            save(FILE, done); save(STATE, {**load(STATE, {}), "beat": time.time()})
    save(STATE, {**load(STATE, {}), "running": False})
    try: import compartir; compartir.publicar_estados(dt.date.today().isoformat(), hechos)      # what this computer read today is shared; the other one will not ask for it
    except Exception: pass
    try: import oficina; oficina.registrar("estados", f"{len(hechos)} estados leídos de {len(todo)} pedidos")
    except Exception: pass
    return len(todo)

def toca():
    s = load(STATE, {}) or {}
    if s.get("running") and time.time() - s.get("beat", 0) < 600: return False
    return used_today() < MAX_DAY and bool(pending()) and os.path.exists(os.path.join(ROOT, ".secrets", "ebay_api.json"))

def lanzar():
    here = os.path.dirname(os.path.abspath(__file__))
    log = open(P("state", "condiciones.log"), "a", encoding="utf-8")
    subprocess.Popen([sys.executable, os.path.join(here, "condiciones.py")], cwd=here, env={**os.environ, "PYTHONIOENCODING": "utf-8"}, stdin=subprocess.DEVNULL,
                     stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

_cache = [None, None]
def todas():
    """Answers for the server (cached until the file changes)."""
    try: m = os.path.getmtime(FILE)
    except OSError: return {}
    if _cache[0] != m: _cache[0], _cache[1] = m, load(FILE, {}) or {}
    return _cache[1]

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    lim = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else None
    if "--lista" in sys.argv:
        n = len(pending()); print(f"sin condición: {n} anuncios de eBay sin gradear; hoy quedan {max(0, MAX_DAY - used_today())} llamadas de {MAX_DAY}"); sys.exit(0)
    t0 = time.time(); n = run(lim); done = load(FILE, {}) or {}
    from collections import Counter
    print(f"{n} anuncios preguntados en {time.time() - t0:.0f} s;", dict(Counter(v["c"] for v in done.values())))
