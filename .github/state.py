"""api/state.json for the phone page, made at every publish (pages.yml) from the files the computer and the phone searches write:
  api/jobs/<id>.json      a search's live progress (nube.py job)
  api/status.json         when the computer's engine was last on (nube.py status)
  api/results/<id>.json   a search's newest results (nube.py push_results, buscar.js)
-> {jobs: newest 30, claude: status or null, results: [{id, at}] newest 100, now}. The requests are GitHub issues, read by the page."""
import glob, json, os, time

def load(f):
    try:
        with open(f, encoding="utf-8") as h: return json.load(h)
    except (OSError, ValueError):
        return None

jobs = []
for f in glob.glob("api/jobs/*.json"):
    d = load(f)
    if isinstance(d, dict): jobs.append({"id": os.path.basename(f)[:-5], **d})
jobs.sort(key=lambda j: -(j.get("at") or 0))
results = []
for f in glob.glob("api/results/*.json"):
    d = load(f)
    if isinstance(d, dict) and d.get("search"): results.append({"id": os.path.basename(f)[:-5], "at": d.get("at") or 0})
results.sort(key=lambda r: -r["at"])
os.makedirs("api", exist_ok=True)
with open("api/state.json", "w", encoding="utf-8") as h:
    json.dump({"jobs": jobs[:30], "claude": load("api/status.json"), "results": results[:100], "now": int(time.time() * 1000)}, h, ensure_ascii=False)
print(f"state: {len(jobs)} jobs, {len(results)} results")
