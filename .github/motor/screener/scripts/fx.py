"""Fetch the European Central Bank euro reference rates and write data/fx.json {"date", "rates": {"USD": 1.1195, ...}}.
Used to convert amounts eBay shows in another currency (for example an import-charge estimate in pounds).
If the fetch fails, the previous file is kept and the run says so.
Usage: python fx.py"""
import re, subprocess, urllib.request
from common import P, load, save
URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

def fetch():
    try:
        return urllib.request.urlopen(URL, timeout=30).read().decode("utf-8")
    except Exception:   # the ECB sends an incomplete certificate chain this Python rejects (26 October 2026); Windows curl completes it
        return subprocess.run(["curl", "-s", "--max-time", "30", URL], capture_output=True, check=True).stdout.decode("utf-8")

try:
    x = fetch()
    rates = {c: float(r) for c, r in re.findall(r"currency='([A-Z]{3})' rate='([\d.]+)'", x)}
    date = re.search(r"time='([\d-]+)'", x).group(1)
    save(P("fx.json"), {"date": date, "rates": rates, "source": URL})
    print("European Central Bank rates of", date, {k: rates[k] for k in ("USD", "GBP", "JPY", "CHF") if k in rates})
except Exception as e:
    old = load(P("fx.json"))
    print("exchange rates could not be fetched:", e, "| keeping rates of", old and old.get("date"))
