"""Listening mode: Claude runs this in the background while its session is open ("escucha el buscador").

Every 3 seconds it tells the app that Claude is listening (data/app/claude.json) and looks for searches waiting for Claude. As soon as
one appears it marks it as received ("Claude ha recibido la búsqueda…"), prints its id and exits: the background task ending wakes
Claude, who runs the job (app_job.py / the screener) and then starts this script again.
When the web page exists (settings.json "cloud_url" on Cloudflare, keys in .secrets/cloud.json) it also, every minute, picks up the
searches asked from the phone (each becomes a local job, found by the loop above) and, every 5 minutes, tells the page that Claude is
listening ("Claude conectado"). Nothing for Claude to do for that.
Usage: python escuchar.py [max hours, default 8] [--cloud-every MINUTES, default 1]"""
import glob, io, os, sys, time
from contextlib import redirect_stdout
from common import P, load, save, SCREENER
import app_lib as A
import nube

sys.stdout.reconfigure(encoding="utf-8")
argv = [a for a in sys.argv[1:]]
every = 1.0
if "--cloud-every" in argv:
    i = argv.index("--cloud-every"); every = float(argv[i + 1]); del argv[i:i + 2]
LIMIT = time.time() + 3600 * float(argv[0] if argv else 8)
CLOUD = nube.enabled()
next_cloud, next_beat = 0.0, 0.0
BEAT = P("app", "claude.json")

def waiting():
    out = []
    for f in sorted(glob.glob(P("app", "jobs", "*.json")), key=os.path.getmtime):
        try:
            j = load(f)
        except (OSError, ValueError):
            continue
        if j and j.get("status") == "waiting_claude": out.append(j)
    return out

def cloud_check():
    """Phone requests -> local jobs; heartbeat for the page. A network error only waits for the next round."""
    global next_beat
    try:
        with redirect_stdout(io.StringIO()):
            if time.time() > next_beat:
                nube.status_cmd(True); next_beat = time.time() + 300
            nube.requests_cmd()
    except (Exception, SystemExit) as e:
        print(f"(web: {type(e).__name__}: {e})", file=sys.stderr)

while time.time() < LIMIT:
    save(BEAT, {"listening": True, "at": time.time(), "pid": os.getpid()})
    if CLOUD and time.time() > next_cloud:
        cloud_check(); next_cloud = time.time() + 60 * every
    jobs = waiting()
    if jobs:
        for j in jobs:
            j.update(status="claimed", progress=max(j.get("progress", 0), 10), message="Claude ha recibido la búsqueda y empieza ahora…")
            save(A.job_path(j["id"]), j)
            if CLOUD:
                try:
                    with redirect_stdout(io.StringIO()): nube.job_cmd(j["id"])
                except (Exception, SystemExit): pass
        save(BEAT, {"listening": False, "working": [j["id"] for j in jobs], "at": time.time()})
        print("JOBS " + " ".join(j["id"] for j in jobs))
        for j in jobs: print(f"- {j['id']}  [{j['kind']}] {j['label']}")
        sys.exit(0)
    time.sleep(3)
save(BEAT, {"listening": False, "at": time.time()})
if CLOUD:
    try:
        with redirect_stdout(io.StringIO()): nube.status_cmd(False)
    except (Exception, SystemExit): pass
print("TIMEOUT: no searches in the last hours; start listening again if the owner still wants it.")
