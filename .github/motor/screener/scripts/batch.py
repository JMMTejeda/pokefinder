"""Print the browser_batch actions for pages <from> to <to> of this run's plan (or for the listing checks), as JSON.
Each page takes three short steps through receiver.py (keep it running): open http://127.0.0.1:8765/step/... (saves the previous
result and loads this page's reader into window.name), open the page, run eval(window.name). The batch ends with /done, which saves
the last result. The viewport is set at the start and whenever it changes (tall for the marketplaces, normal for Gempire).
Usage: python batch.py <from> <to>          pages a to b of data/browser/pages.json
       python batch.py listing <from> <to>  entries a to b of data/browser/check_queue.json (data/browser/listing/<key>.json)
       add --skip site1,site2 to leave out the pages of sites that cannot be reached this run (for example cardrush)"""
import json, re, sys
from common import P, load

safe = lambda k: re.sub(r"[^\w.-]", "_", k)
RUN = "(async()=>{const c=window.name;window.name='';if(!c||c[0]!=='(')return 'no reader loaded';return String(await eval(c)).slice(0,160)})()"

def wrap(js):
    """The reader, keeping its full result in window.name (survives navigation) and returning a short summary."""
    return ("(async()=>{const __r=await " + js.strip().rstrip(";") + ";window.name=__r;const d=JSON.parse(__r);"
            "return d.blocked?'BLOCKED '+(d.title||''):(d.rows?(d.n+' read, '+d.rows.length+' kept: '+d.rows.map(r=>r.price_text+' '+r.title.slice(0,45)).join(' | ').slice(0,700))"
            ":d.img!==undefined?('buy '+d.buy+(d.reason?' ('+d.reason+')':'')+' | '+(d.button||'-')+' | '+d.host):('available '+d.available+' | ship '+(d.ship||[]).join(' / ').slice(0,160)+' | '+(d.title||'').slice(0,60)))})()")

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    skip = set(sys.argv[sys.argv.index("--skip") + 1].split(",")) if "--skip" in sys.argv else set()
    if skip: sys.argv = sys.argv[:sys.argv.index("--skip")]
    if sys.argv[1] in ("listing", "photo"):   # photo: app_images.py (main photo of each listing, gone or not)
        q = load(P("browser", "check_queue.json"), [])
        a, b = int(sys.argv[2]), int(sys.argv[3])
        items = [(sys.argv[1], i, q[i]["url"], safe(q[i]["key"]), "tall") for i in range(a, min(b, len(q) - 1) + 1)]
    else:
        p = load(P("browser", "pages.json"))
        a, b = int(sys.argv[1]), int(sys.argv[2])
        items = [("pages", x["i"], x["url"], f"{x['i']:03d}", x.get("viewport", "tall")) for x in p[a:b + 1] if x["site"] not in skip and not x.get("api")]
        ebay = {x["i"] for x in p if x["site"] == "ebay"}
    ebay = locals().get("ebay") or {i for k, i, u, n, w in items if "ebay." in u}
    acts, vp, prev = [], None, ""
    for kind, i, url, name, want in items:
        if want != vp:
            acts.append({"name": "resize_window", "input": {"width": 1280, "height": 8000} if want == "tall" else {"preset": "mobile"}}); vp = want
        acts += [{"name": "navigate", "input": {"url": f"http://127.0.0.1:8765/step/{kind}/{i}" + (f"?prev={prev}" if prev else "")}},
                 *([{"name": "javascript_tool", "input": {"action": "javascript_exec",   # eBay pacing: about 40 seconds more before each eBay page (the tool allows 45 s)
                    "text": "(async()=>{await new Promise(r=>setTimeout(r,40000));return 'paused for eBay'})()"}}] if i in ebay and i > 0 else []),
                 {"name": "navigate", "input": {"url": url}},
                 {"name": "javascript_tool", "input": {"action": "javascript_exec", "text": RUN}}]
        prev = f"{kind}/{name}"
    acts.append({"name": "navigate", "input": {"url": f"http://127.0.0.1:8765/done?prev={prev}"}})
    print(json.dumps(acts, ensure_ascii=False))
