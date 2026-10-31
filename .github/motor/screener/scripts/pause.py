"""Wait between eBay pages at a person's pace (settings.json "ebay_pacing").
Usage: python pause.py search | item | break | error | site   (site: 5 to 10 seconds between pages of the other marketplaces)"""
import random, sys, time
from common import CFG
E = CFG["ebay_pacing"]
kind = sys.argv[1] if len(sys.argv) > 1 else "item"
lo, hi = {"search": E["between_search_pages_seconds"], "item": E["between_listing_or_seller_pages_seconds"],
          "break": E["after_every_10_listing_pages_seconds"], "error": [1200, 1200], "site": [5, 10]}[kind]
s = random.randint(lo, hi)
time.sleep(s)
print(f"waited {s} seconds ({kind})")
