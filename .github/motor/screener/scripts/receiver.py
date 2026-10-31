"""Local helper for the browser run (127.0.0.1 only; keep it running during the run).

Each page of the plan is read in three short browser steps (python batch.py prints them):
  1. open http://127.0.0.1:8765/step/pages/<i>?prev=<kind>/<name>: this page first saves the previous result (kept in window.name,
     which survives navigation) to data/browser/<kind>/<name>.json, then puts page i's reader script into window.name;
  2. open the marketplace page;
  3. run `eval(window.name)`: the reader runs and leaves its JSON result in window.name for the next step 1.
Marketplaces block requests to 127.0.0.1 from their own pages, hence the hop through this page. A result that is not JSON (a script
cut off by a redirect) is refused, so nothing wrong is saved. Kinds: pages (pages.json index), listing (check_queue.json index).
Usage: python receiver.py"""
import json, os, re, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from common import P, load, SCREENER

sys.path.insert(0, os.path.dirname(__file__))
from batch import wrap, safe

LISTING_JS = open(os.path.join(SCREENER, "browser", "listing.js"), encoding="utf-8").read()
PHOTO_JS = open(os.path.join(SCREENER, "browser", "photo_pick.js"), encoding="utf-8").read()   # app_images.py

def code_for(kind, i):
    if kind == "pages":
        return wrap(load(P("browser", "pages.json"))[i]["js"])
    return wrap(PHOTO_JS) if kind == "photo" else wrap(LISTING_JS)

def save(path, body):
    m = re.fullmatch(r"(pages|listing|photos|photo)/([\w.-]+)", path)
    if not m: return "bad path"
    try:
        d = json.loads(body)
    except Exception:
        return "not a result (script cut off?): nothing saved"
    if not isinstance(d, dict): return "not a result: nothing saved"
    os.makedirs(P("browser", m.group(1)), exist_ok=True)
    json.dump(d, open(P("browser", m.group(1), m.group(2) + ".json"), "w", encoding="utf-8"), ensure_ascii=False)
    print("saved", path, "blocked" if d.get("blocked") else len(d.get("rows", [])) if "rows" in d else d.get("available"), flush=True)
    return "ok"

class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="text/plain; charset=utf-8"):
        b = body.encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
        self.send_header("Access-Control-Allow-Origin", "*"); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        m = re.fullmatch(r"/step/(pages|listing|photo)/(\d+)", u.path)
        prev = (parse_qs(u.query).get("prev") or [""])[0]
        if u.path == "/done" and prev:   # last step of a batch: save the last result only
            return self._send(200, "<!doctype html><meta charset=utf-8><title>done</title><script>if(window.name){const x=new XMLHttpRequest();"
                              f"x.open('POST','/save/{prev}',false);x.send(window.name);document.title=x.responseText;window.name=''}}</script>", "text/html; charset=utf-8")
        if not m:
            return self._send(200, "<!doctype html><title>receiver</title>", "text/html; charset=utf-8")
        kind, i = m.group(1), int(m.group(2))
        code = json.dumps(code_for(kind, i), ensure_ascii=False).replace("</", "<\\/")
        html = ("<!doctype html><meta charset=utf-8><title>step</title><script>"
                + (f"if(window.name){{const x=new XMLHttpRequest();x.open('POST','/save/{prev}',false);x.send(window.name);document.title=x.responseText}}" if prev else "")
                + f"window.name={code};</script>")
        self._send(200, html, "text/html; charset=utf-8")

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8")
        path = self.path[len("/save/"):] if self.path.startswith("/save/") else self.path.lstrip("/")
        self._send(200, save(path, body))

    def log_message(self, *a): pass

if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8765), H).serve_forever()
