"""Is the listing's photo the card it should be? Compares it with photos of the same card already confirmed (data/app/photo_review.json),
with image feature matching (OpenCV ORB), on this computer: no Claude, nothing sent anywhere.
Measured on 25 October 2026 against Claude's own verdicts on 887 photos: every wrong photo (Mezastar discs, the δ Gyarados without
the star, another card, a booster pack) scored 57 or less; 95 % of the right ones scored 152 or more.
  score < WRONG  -> not the card (left out, like revisar_fotos.py did)       score >= RIGHT -> the card
  in between, or no confirmed photo of that card yet -> kept, unconfirmed
  python comprobar_foto.py <image url> "<card name, e.g. Gyarados ☆ δ>"     prints the score"""
import glob, hashlib, json, os, random, sys
from common import P, load
import leer_etiqueta as E

WRONG, RIGHT = 60, 100
DESC = P("app", "orb")
_refs = None

def descriptors(url):
    import cv2, numpy as np
    os.makedirs(DESC, exist_ok=True)
    f = os.path.join(DESC, hashlib.sha1(url.encode()).hexdigest()[:20] + ".npy")
    if os.path.exists(f):
        d = np.load(f); return d if d.size else None
    E.image(url)   # downloads into the shared photo cache, at the largest size (eBay previews are 225 pixels)
    img = os.path.join(E.CACHE, hashlib.sha1(E.big(url).encode()).hexdigest()[:20] + ".img")
    a = cv2.imdecode(np.fromfile(img, np.uint8), cv2.IMREAD_GRAYSCALE)
    d = None
    if a is not None:
        s = 800 / max(a.shape)
        if s < 1: a = cv2.resize(a, None, fx=s, fy=s)
        d = cv2.ORB_create(1500).detectAndCompute(a, None)[1]
    np.save(f, d if d is not None else np.zeros((0, 32), np.uint8))
    return d

def score(d1, d2):
    import cv2
    if d1 is None or d2 is None or len(d1) < 10 or len(d2) < 10: return 0
    m = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(d1, d2, k=2)
    return sum(1 for p in m if len(p) == 2 and p[0].distance < 0.75 * p[1].distance)

def references():
    """card name -> image urls of listings whose photo was confirmed as that card."""
    global _refs
    if _refs is None:
        ok = {k for k, v in load(P("app", "photo_review.json"), {}).items() if v.get("ok")}
        imgs = load(P("app", "images.json"), {}) or {}
        _refs = {}
        for f in glob.glob(P("app", "searches", "*.json")):
            for l in (load(f) or {}).get("listings", []):
                u = l.get("image") or imgs.get(l["id"])
                if l["id"] in ok and l.get("card") and u: _refs.setdefault(l["card"], []).append((l["id"], u))
    return _refs

def check(lid, url, card):
    """-> (verdict "ok" | "wrong" | None, score). None: no confirmed photos of this card, or the score is in between."""
    refs = [u for k, u in references().get(card, []) if k != lid]
    if len(refs) < 2: return None, None
    random.seed(lid); refs = random.sample(refs, min(12, len(refs)))
    try:
        d = descriptors(url)
    except Exception:
        return None, None
    best = 0
    for u in refs:
        try: best = max(best, score(d, descriptors(u)))
        except Exception: pass
        if best >= RIGHT: return "ok", best
    return ("wrong" if best < WRONG else None), best

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(check("-", sys.argv[1], sys.argv[2]))

# ---- the card's art (owner, 28 October 2026: "if the card in the photo is not the card searched for, it is not, whatever the
# title says"). SIFT keypoints of the photo matched to the card's official image (pokemontcg.io) and to photos already confirmed as
# that card, kept only when they agree on one placement of the card (RANSAC homography): a slab, a tilt or a distant photo still
# matches, another illustration does not. ART_MIN and its measurement: see art_verdict.
ART_MIN = 20   # measured 28 October 2026 on 984 photos judged by eye (5000 SIFT points): catches 17 of 18 wrong ones, hides 2.6 % of right ones (backs, tilted, lots)
_sift, _art_refs = None, {}

def _sift_feats(url, maxside=1000, art_only=False):
    import cv2, numpy as np
    global _sift
    if _sift is None: _sift = cv2.SIFT_create(5000)   # 5000: a card on a patterned rug kept too few points on the card with 2000
    E.image(url)
    f = os.path.join(E.CACHE, hashlib.sha1(E.big(url).encode()).hexdigest()[:20] + ".img")
    a = cv2.imdecode(np.fromfile(f, np.uint8), cv2.IMREAD_GRAYSCALE)
    if a is None: return None
    if art_only:   # an official scan: only the illustration box (not the frame, text and symbols every card of the era shares)
        h, w = a.shape
        a = a[int(h * 0.09):int(h * 0.55), int(w * 0.07):int(w * 0.93)]
    s = maxside / max(a.shape)
    if s < 1: a = cv2.resize(a, None, fx=s, fy=s)
    k, d = _sift.detectAndCompute(a, None)
    return (k, d) if d is not None and len(d) >= 8 else None

def _inliers(ref, kd):
    import cv2, numpy as np
    (k1, d1), (k2, d2) = ref, kd
    m = [a for a, b in (p for p in cv2.FlannBasedMatcher(dict(algorithm=1, trees=5), dict(checks=50)).knnMatch(d1, d2, k=2) if len(p) == 2)
         if a.distance < 0.75 * b.distance]
    if len(m) < 8: return 0
    H, mask = cv2.findHomography(np.float32([k1[x.queryIdx].pt for x in m]).reshape(-1, 1, 2),
                                 np.float32([k2[x.trainIdx].pt for x in m]).reshape(-1, 1, 2), cv2.RANSAC, 5.0)
    return int(mask.sum()) if mask is not None else 0

def art_refs(poke, goldstar=True, skip=()):
    """The art to look for: the illustration of each of the Pokémon's Gold Stars on its official scan (or of every card of it when not
    goldstar). Only official scans: photos of other copies share slabs, labels and backgrounds, which match any slabbed photo
    (measured 28 October 2026: Mezastar discs reached 70 points against confirmed photos)."""
    import re, cardmarket as CM
    key = (poke, goldstar)
    if key not in _art_refs:
        urls = [u for (n, s), u in CM.images(poke).items() if u and (not goldstar or re.search(r"★|☆|\bstar\b", n, re.I))][:6]
        feats = []
        for u in urls:
            for v in (u.replace(".png", "_hires.png"), u):
                try:
                    x = _sift_feats(v, art_only=True)
                    if x: feats.append((v, x)); break
                except Exception:
                    pass
        _art_refs[key] = feats
    return [x for k, x in _art_refs[key] if k not in skip]

def A_cards():
    import app_lib
    return app_lib.CARDS

def art_score(url, refs):
    """How many keypoints of the photo agree with the card's art (best reference); None when the photo cannot be read."""
    try:
        kd = _sift_feats(url)
    except Exception:
        return None
    if not kd or not refs: return None
    best = 0
    for r in refs:
        best = max(best, _inliers(r, kd))
        if best >= 60: break
    return best

_card_refs = {}
def card_refs(url):
    """The art of one exact card (its official image, cropped to the illustration), for a search that names the card."""
    if url not in _card_refs:
        x = None
        for v in (url, url.replace("_hires.png", ".png")):
            try:
                x = _sift_feats(v, art_only=True)
                if x: break
            except Exception:
                pass
        _card_refs[url] = [x] if x else []
    return _card_refs[url]
