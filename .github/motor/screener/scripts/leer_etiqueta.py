"""Reads the grading label in a listing photo with the text recognition built into Windows (no Claude, nothing sent anywhere).

The label's grade word decides the grade (PSA "NM-MT" = 8, BGS "GEM MINT" = 9.5...), so a misread digit does not matter; "1ST ED."
on a PSA label = 1st Edition, a PSA label read without it = Unlimited (the rule used when Claude read them, 25 October 2026).
Raw cards and Japanese plates (ARS) are left alone: the title stays.
  python leer_etiqueta.py <image url or file>     prints what it reads
Used by motor.py; read(url) returns {"grade": "PSA 8", "edition": "1st Edition"|"Unlimited"|None, "text": ...} or None."""
import hashlib, io, os, re, sys, urllib.request
from common import P

CACHE = P("app", "ocr")
# longest first, so "GEM MT" is not read as "MT"
PSA_WORDS = [(r"GEM\s*-?\s*M(?:IN)?T", "10"), (r"NM\s*-?\s*MT\s*\+", "8.5"), (r"NM\s*-?\s*MT", "8"), (r"MINT\s*\+", "9.5"),
             (r"MINT", "9"), (r"EX\s*-?\s*MT\s*\+", "6.5"), (r"EX\s*-?\s*MT", "6"), (r"VG\s*-?\s*EX\s*\+", "4.5"),
             (r"VG\s*-?\s*EX", "4"), (r"NM\s*\+", "7.5"), (r"NM", "7"), (r"EX\s*\+", "5.5"), (r"EX", "5"), (r"VG\s*\+", "3.5"),
             (r"VG", "3"), (r"GOOD\s*\+", "2.5"), (r"GOOD", "2"), (r"FR", "1.5"), (r"PR", "1")]
BGS_WORDS = [(r"PRISTINE", "10"), (r"GEM\s*MINT", "9.5"), (r"NM\s*-?\s*MT\s*\+", "8.5"), (r"NM\s*-?\s*MT", "8"), (r"MINT", "9"),
             (r"NEAR\s*MINT\s*\+", "7.5"), (r"NEAR\s*MINT", "7"), (r"EX\s*-?\s*MT\s*\+", "6.5"), (r"EX\s*-?\s*MT", "6"),
             (r"VG\s*-?\s*EX\s*\+", "4.5"), (r"VG\s*-?\s*EX", "4"), (r"EXCELLENT", "5"), (r"VERY\s*GOOD", "3"), (r"GOOD", "2"), (r"POOR", "1")]
CGC_WORDS = [(r"PRISTINE", "10"), (r"GEM\s*MINT", "10"), (r"NM\s*/\s*MINT\s*\+", "8.5"), (r"NM\s*/\s*MINT", "8"), (r"MINT\s*\+", "9.5"),
             (r"MINT", "9"), (r"NEAR\s*MINT\s*\+", "7.5"), (r"NEAR\s*MINT", "7"), (r"EX\s*/\s*NM\s*\+", "6.5"), (r"EX\s*/\s*NM", "6"),
             (r"EXCELLENT", "5"), (r"VG\s*/\s*EX", "4"), (r"VERY\s*GOOD", "3"), (r"GOOD", "2"), (r"FAIR", "1.5"), (r"POOR", "1")]

def ocr(img):
    import winocr
    from PIL import Image
    im = img.convert("RGB")
    if im.width < 1400: im = im.resize((im.width * 2, im.height * 2), Image.LANCZOS)
    return [ln["text"] for ln in winocr.recognize_pil_sync(im, "en")["lines"]]

def big(src):
    """The largest size of a listing photo: eBay search results give 225-pixel previews (s-l225), too small to read a label."""
    src = re.sub(r"(i\.ebayimg\.com/.+?/s-l)\d+(\.\w+)", r"\g<1>1600\2", src)
    # Mercari's search previews are small webp thumbnails; the listing's own photo is the original
    return re.sub(r"static\.mercdn\.net/thumb/item/webp/(m\d+_\d+)\.jpg(?:\?.*)?$", r"static.mercdn.net/item/detail/orig/photos/\1.jpg", src)

def image(src):
    from PIL import Image
    if os.path.exists(src): return Image.open(src)
    src = big(src)
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, hashlib.sha1(src.encode()).hexdigest()[:20] + ".img")
    if not os.path.exists(f):
        req = urllib.request.Request(src, headers={"user-agent": "PokeFinder-local"})
        open(f, "wb").write(urllib.request.urlopen(req, timeout=30).read())
    return Image.open(f)

def grade_word(lines, words, near=None):
    """The grade word on the label's lines (the line with the card number or the grade), first match wins."""
    for ln in lines:
        if near and not re.search(near, ln): continue
        # the longest grade word on the line: "NEAR MINT+" is 7.5, not the "MINT" inside it
        hits = [(len(m.group(0)), g) for pat, g in words for m in [re.search(rf"(?<![A-Z]){pat}(?![A-Z])", ln)] if m]
        if hits: return max(hits)[1]
    return None

def parse(lines):
    L = [re.sub(r"\s+", " ", x.upper()).replace("—", "-").replace("–", "-") for x in lines]
    text = " | ".join(L)
    ed = "1st Edition" if re.search(r"[1I]\s*ST\.?\s*ED|[1I]ST\s*EDITION|FIRST\s*EDITION", text) else None
    # other graders' labels that look alike (CCC, ACE, ARS plates): not read, the title stays
    if re.search(r"\bCCC\b|CCC GRAD|\bACE\b|ACE GRAD|\bARS\b|ARSALES", text): return None
    # CGC first: its newer labels also print sub-grades (Centering, Corners...), like BGS
    if re.search(r"\bCGC\b|CERTIFIED GUARANTY", text):
        g = grade_word(L, CGC_WORDS)
        return {"grade": f"CGC {g}", "edition": ed} if g else None
    if re.search(r"\bBECKETT\b|\bBGS\b", text) or re.search(r"CENTERING.*CORNERS|CORNERS.*SURFACE", text):
        # only the grade word: the numbers on a BGS label are mostly sub-grades
        g = grade_word(L, BGS_WORDS, r"PRISTINE|MINT|NEAR|EX|GOOD|POOR|VG")
        if not g: return None
        return {"grade": f"BGS {g}", "edition": ed or ("Unlimited" if "UNLIMITED" in text else None)}
    psa = re.search(r"P\.?\s*M\.?\s*(?:JPN|JAPANESE)|POKEMON JAPANESE|\bPSA\b|\bJPN\.", text)
    if not psa: return None
    # the grade word sits at the end of the label's second line ("LATIAS-HOLO  EX-MT"); the lines with a #number or year come first
    g = None
    for ln in L:
        m = re.search(r"(?:HOLO|-HOLO/G\.S\.|HOLO/G\.S\.|PROMO)\s*(.*)$", ln)
        if m: g = grade_word([m.group(1)], PSA_WORDS)
        if g: break
    if not g:   # a line that is only the grade word
        for ln in L:
            if re.fullmatch(r"(?:GEM\s*-?\s*M(?:IN)?T|NM\s*-?\s*MT\s*\+?|MINT\s*\+?|EX\s*-?\s*MT\s*\+?|VG\s*-?\s*EX\s*\+?|NM\s*\+?|EX\s*\+?|VG\s*\+?|GOOD\s*\+?|PR|FR)", ln.strip()):
                g = grade_word([ln], PSA_WORDS); break
    if not g: return None
    return {"grade": f"PSA {g}", "edition": ed or "Unlimited"}

def text(src):
    """Everything legible on the photo (a slab's label says 2021 / 25TH ANNIVERSARY on a reprint), or ""."""
    try:
        return " | ".join(ocr(image(src)))
    except Exception:
        return ""

def read(src):
    try:
        im = image(src); lines = ocr(im)
        r = parse(lines)
        if not r and re.search(r"P\.?\s*M\.?\s*(?:JPN|JAPANESE)|POKEMON JAPANESE", " ".join(lines).upper()):
            # a PSA label whose grade was not read: the top half again, larger
            from PIL import Image
            top = im.convert("RGB").crop((0, 0, im.width, im.height // 2))
            lines = ocr(top.resize((top.width * 3, top.height * 3), Image.LANCZOS)); r = parse(lines)
    except Exception:
        return None
    if r: r["text"] = " | ".join(lines)[:300]
    return r

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    src = sys.argv[1]
    print(ocr(image(src))); print(read(src))
