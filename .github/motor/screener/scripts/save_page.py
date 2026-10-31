"""Save one page script's result, exactly as returned, to data/browser/pages/<i>.json.
Usage: python save_page.py <i> < result.json   (the result is the JSON string the page script returned)"""
import json, sys
from common import P
sys.stdin.reconfigure(encoding="utf-8")
raw = sys.stdin.read().strip()
d = json.loads(raw)
if isinstance(d, str): d = json.loads(d)
json.dump(d, open(P("browser", "pages", f"{int(sys.argv[1]):03d}.json"), "w", encoding="utf-8"), ensure_ascii=False)
print(sys.argv[1], "saved:", "blocked" if d.get("blocked") else f"{d.get('n')} rows read, {len(d.get('rows', []))} kept")
