"""Start a new daily run: move yesterday's page readings (data/browser) into data/archive/<date>/ and keep the last 7 archives.
data/state (what was read before, first-seen dates) is kept as it is.
Usage: python start_run.py"""
import os, shutil, glob, datetime as dt
from common import P, DATA, TODAY, NOW, save

src = P("browser")
if os.path.isdir(src) and os.listdir(src):
    stamp = dt.datetime.fromtimestamp(os.path.getmtime(src)).strftime("%Y-%m-%d_%H%M")
    dest = os.path.join(DATA, "archive", stamp)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.move(src, dest)
    print("previous readings moved to", dest)
for d in ("pages", "photos"):
    os.makedirs(P("browser", d), exist_ok=True)
old = sorted(glob.glob(os.path.join(DATA, "archive", "*")))[:-7]
for o in old: shutil.rmtree(o, ignore_errors=True)
print("ready for", TODAY.isoformat(), "| archives kept:", min(7, len(glob.glob(os.path.join(DATA, "archive", "*")))))

save(P("state", "run_start.json"), {"at": NOW.isoformat(timespec="minutes")})   # listings first seen from now on count as new on this run
