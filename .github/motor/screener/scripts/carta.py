"""Which exact card a typed search means (owner, 28 October 2026: "blaziken power keepers stamped" must bring only Blaziken EX Power
Keepers 5/108, the stamped reverse holo, and nothing else).

From the words typed, the card is found on pokemontcg.io (every English-print card: name, set, number, official image): the
Pokémon's cards whose set name is in the search, or whose number is. Its set's name in other languages comes from TCGdex
("EX Gardiens du Pouvoir"). motor.py then requires that card in titles (its set in any language, or its number), compares each photo
with its official art (comprobar_foto), and shows only that card's Cardmarket product. No card found: the search works as before.
  python carta.py "<search>"     prints the card found"""
import json, os, re, sys, time, urllib.parse, urllib.request
from common import P, load, save

DIR = P("cardmarket")
STAMP = r"stamp\w*|sello\w*|sellad\w*|estampad\w*|tampon\w*|gestempelt|stempel\w*|timbrat\w*|スタンプ"
REVERSE = r"reverse|revers[oe]|inverso|invers\w*|ミラー|mirror"

def _get(url, tries=4):
    for _ in range(tries):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"user-agent": "PokeFinder"}), timeout=40))
        except Exception:
            time.sleep(5)
    return None

def cards_of(poke):
    """Every English-print card of a Pokémon on pokemontcg.io (kept a week: the old cards do not change)."""
    cache = os.path.join(DIR, "cards.json"); saved = load(cache, {}) or {}
    hit = saved.get(poke)
    if hit and time.time() - hit["at"] < 7 * 86400: return hit["cards"]
    d = _get("https://api.pokemontcg.io/v2/cards?" + urllib.parse.urlencode(
        {"q": f'name:"{poke}*"', "select": "id,name,number,set,images", "pageSize": 250}))
    if d is None: return (hit or {}).get("cards", [])
    cards = [{"id": c["id"], "name": c["name"], "number": c["number"], "set": c["set"]["name"], "set_id": c["set"]["id"],
              "total": c["set"].get("printedTotal"), "series": c["set"].get("series"), "code": c["set"].get("ptcgoCode"),
              "image": (c.get("images") or {}).get("large") or (c.get("images") or {}).get("small")} for c in d.get("data", [])]
    saved[poke] = {"at": time.time(), "cards": cards}; os.makedirs(DIR, exist_ok=True); save(cache, saved)
    return cards

def set_names(set_id, en):
    """The set's names in other languages (TCGdex), e.g. ["Power Keepers", "EX Gardiens du Pouvoir", "EX Power Keepers"]."""
    cache = os.path.join(DIR, "set_names.json"); saved = load(cache, {}) or {}
    if set_id in saved: return saved[set_id]
    out = [en]
    for lang in ("fr", "de", "es", "it", "pt"):
        d = _get(f"https://api.tcgdex.net/v2/{lang}/sets/{set_id}", tries=2)
        if d and d.get("name") and d["name"] not in out: out.append(d["name"])
    saved[set_id] = out; os.makedirs(DIR, exist_ok=True); save(cache, saved)
    return out

def _words(s): return [w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in ("ex", "the", "and", "of", "pokemon", "pokémon")]

def identify(spec):
    """The card the search means, or None. A set counts when all its words are in the search ("power keepers" for EX Power Keepers);
    a number when "5/108", "#5" or "05/108" is."""
    poke = (spec.get("poke") or [None])[0]
    if not poke: return None
    q = (spec.get("q") or spec.get("en") or "").lower()
    qw = set(_words(q))
    found = []
    for c in cards_of(poke):
        sw = _words(c["set"])
        set_hit = bool(sw) and all(w in qw for w in sw)
        num_hit = bool(re.search(rf"(?<!\d)0*{re.escape(c['number'])}\s*/\s*0*{c['total']}(?!\d)|#\s*0*{re.escape(c['number'])}(?!\d)", q)) if c.get("total") else False
        if set_hit or num_hit: found.append((set_hit + num_hit, c))
    if not found: return None
    best = max(s for s, _ in found)
    found = [c for s, c in found if s == best]
    # "Blaziken" and "Blaziken ex" in one set: the plain card unless the search says ex / δ / ★
    plain = [c for c in found if c["name"].lower() == poke.lower()]
    if len(found) > 1 and plain and not re.search(r"\bex\b|δ|delta|★|☆|star", q.replace("stamp", "")): found = plain
    if len({(c["set_id"], c["number"]) for c in found}) != 1: return None   # still ambiguous: no exact card
    c = dict(found[0])
    c["set_names"] = set_names(c["set_id"], c["set"])
    c["stamped"] = bool(re.search(STAMP, q)); c["reverse"] = bool(re.search(REVERSE, q))
    return c

def must(card):
    """What a title must have to be that card: its set (in any language) or its number."""
    sets = sorted({re.sub(r"^ex\s+", "", n, flags=re.I) for n in card["set_names"]}, key=len, reverse=True)
    alts = [r"\s*".join(map(re.escape, n.split())) for n in sets]
    alts.append(rf"(?<!\d)0*{re.escape(card['number'])}\s*/\s*0*{card['total']}(?!\d)")
    return "|".join(alts)

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    import motor
    c = identify(motor.plan_spec(" ".join(sys.argv[1:])))
    print(json.dumps(c, ensure_ascii=False, indent=1)); print(c and must(c))
