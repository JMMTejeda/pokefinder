"""Check PSA certificate numbers (data/psa_input.json) through PSA's official public API and write data/psa_certs.json.

psacard.com/cert pages sit behind a security check that automated reading cannot pass (14 October 2026), so the
certificate check uses PSA's own API, which needs the owner's personal key (free with a PSA account, 100 checks a day):
save it as data/psa_token.txt. Without the key every certificate is reported as "Not checked".
Results are cached in data/state/psa_cache.json, so each certificate is looked up only once.
Usage: python check_certs.py"""
import json, os, re, urllib.request
from common import P, load, save, TODAY

inp = load(P("psa_input.json"), {})
cache = load(P("state", "psa_cache.json"), {})
token_file = P("psa_token.txt")
token = open(token_file, encoding="utf-8").read().strip() if os.path.exists(token_file) else None
out, used = {}, 0

def norm(s): return re.sub(r"[^a-z0-9]", "", (s or "").lower())

for item, v in inp.items():
    cert, title = v["cert"], v["title"]
    c = cache.get(cert)
    if c is None and token and used < 90:
        req = urllib.request.Request(f"https://api.psacard.com/publicapi/cert/GetByCertNumber/{cert}", headers={"Authorization": "bearer " + token})
        try:
            d = json.load(urllib.request.urlopen(req, timeout=30)).get("PSACert") or {}
            used += 1
            c = {"cert": cert, "cert_url": f"https://www.psacard.com/cert/{cert}", "year": d.get("Year"), "brand_title": d.get("Brand"),
                 "subject": d.get("Subject"), "card_number": d.get("CardNumber"), "variety": d.get("Variety"), "category": d.get("Category"),
                 "grade": d.get("CardGrade") or d.get("GradeDescription"), "population": d.get("TotalPopulation"), "pop_higher": d.get("PopulationHigher"),
                 "checked": TODAY.isoformat(), "notes": None}
            if d: cache[cert] = c
            else: c["notes"] = "PSA returned no certificate with this number"
        except Exception as e:
            c = {"cert": cert, "grade": None, "notes": f"PSA API could not be read: {e}"}
    if c is None:
        c = {"cert": cert, "grade": None, "notes": "Not checked: no PSA API key saved (data/psa_token.txt)" if not token else "Not checked: daily limit reached"}
    c = dict(c)
    # mismatch between the certificate and the listing title (card number and grade)
    mm = []
    if c.get("grade"):
        g = re.search(r"(10|[1-9](?:\.5)?)", str(c["grade"]))
        tg = re.search(r"\bPSA\b[^0-9]{0,18}?(10|[1-9](?:\.5)?)\b", title, re.I)
        if g and tg and g.group(1) != tg.group(1): mm.append(f"PSA certificate {cert} is grade {c['grade']}, the title says PSA {tg.group(1)}")
        cn = norm(c.get("card_number")).lstrip("0")
        if cn and not re.search(r"(?<!\d)0*" + re.escape(cn) + r"(?!\d)", title, re.I):   # "022" on the certificate matches "#22" or "022/PLAY" in the title
            mm.append(f"PSA certificate {cert} is card number {c.get('card_number')} ({c.get('subject')}, {c.get('year')} {c.get('brand_title')}), which the title does not show")
        if c.get("category") and not re.search(r"pok", str(c["category"]), re.I): mm.append(f"PSA certificate {cert} belongs to a {c['category']} item, not a Pokémon card")
    c["mismatch"] = "; ".join(mm) or None
    out[item] = c
save(P("psa_certs.json"), out); save(P("state", "psa_cache.json"), cache)
print(f"certificates {len(out)}; looked up today {used}; " + ("no PSA API key saved" if not token else "key in use"))
