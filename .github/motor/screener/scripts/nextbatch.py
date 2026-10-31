"""Print the next browser_batch (at most 25 actions, at most 2 eBay pages) starting where the last one stopped.
State in data/browser/next_page.txt. Usage: python nextbatch.py [--skip site1,site2] [--from N]
browser_batch takes at most 25 actions (checked 26 October 2026), so 7 pages per batch is the most."""
import json, subprocess, sys, os
from common import P, load
skip = sys.argv[sys.argv.index("--skip") + 1] if "--skip" in sys.argv else ""
st = P("browser", "next_page.txt")
start = int(sys.argv[sys.argv.index("--from") + 1]) if "--from" in sys.argv else int(open(st).read()) if os.path.exists(st) else 0
pages = load(P("browser", "pages.json")); n = len(pages)
if start >= n: print("ALL DONE"); sys.exit()
def acts(a, b):
    out = subprocess.run([sys.executable, "batch.py", str(a), str(b)] + (["--skip", skip] if skip else []), capture_output=True, text=True, encoding="utf-8").stdout
    return json.loads(out) if out.strip() else []
end = start
while end + 1 < n:
    x = acts(start, end + 1)
    if len(x) > 25 or sum("setTimeout(r,40000)" in a["input"].get("text", "") for a in x) > 2 or sum(1 for a in x if a["name"] == "javascript_tool" and "eval(c)" in a["input"]["text"]) > 7: break
    end += 1
x = acts(start, end)
open(st, "w").write(str(end + 1))
sys.stdout.reconfigure(encoding="utf-8")
print(f"pages {start}-{end} of {n - 1}")
print(json.dumps(x, ensure_ascii=False).replace("slice(0,160)", "slice(0,60)"))
