"""Content studio (owner, 3 November 2026: "hay que innovar mucho"): animated vertical videos and photo posts built from the app's own data, all free and local
(Pillow + numpy + the ffmpeg of imageio-ffmpeg; no voice, the words are burnt into the picture). Builds on reels.py (its Video class, fonts and photo cache).
Formats:
  revela   «¿Cuánto vale?»: a card flies in, flips, shines, its price counts up and the grade ladder (ungraded, PSA 9, PSA 10) grows.
  ventas   «Así se ha vendido»: the real sales of the last 180 days of one card and grade drawn as a line, point by point (SNKRDUNK, ventas.py).
  top      «Las 5 más caras»: a countdown from 5 to 1 with each card's photo and a price that counts up.
  post     a 1080x1350 poster of one card, and a carousel (cover, one slide per card, closing) of the top, as PNG for Instagram.
Prices are market values from real sales (reels.precio), never what sellers ask. Photos are the ones the app already holds from its saved searches.
Output in data/reels/: <format>-<name>.mp4 / .png and a .json with what it says (so the text of the post can be copied).
Usage: python estudio.py [--formato revela|ventas|top|post|carrusel|todo] [--carta key[:Edition]] [--nota "PSA 10"] [--lista]"""
import argparse, glob, json, math, os, random, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps
import reels, ventas
from reels import Video, W, H, FPS, fuente, ajustar, ease, redondear, euros, nombre, foto, VERDE, BLANCO, GRIS, ORO, OUT, ED_TXT
from common import P, save

NOTAS = ["Sin gradear", "PSA 9", "PSA 10"]
CW, CH = 560, 780                      # card on screen
AZUL, ROSA = (84, 160, 255), (255, 92, 140)

# ---------------------------------------------------------------- data
_fotos = {}
def fotos_de_busquedas():
    """{card name: [photo urls]} from every saved search, raw (ungraded) cards first."""
    if _fotos: return _fotos
    for f in glob.glob(P("app", "searches", "*.json")):
        try: s = json.load(open(f, encoding="utf-8"))
        except (OSError, ValueError): continue
        for l in s.get("listings") or []:
            c = l.get("card")
            if isinstance(c, list): c = c[0] if c else None
            if c and l.get("image"): _fotos.setdefault(c, []).append((bool(l.get("grader")), l["image"]))
    for c in _fotos: _fotos[c].sort(key=lambda x: x[0])
    return _fotos

def enderezar(im):
    """(card image, score): the card cut out of a seller's photo and turned upright (OpenCV: the biggest card-shaped outline, warped to 630x880).
    Score is how much of the photo it fills times how close it is to a card's 5:7 shape; 0 when no card was found (the photo is returned as it is)."""
    import cv2
    a = np.asarray(im.convert("RGB")); s = 900 / max(a.shape[:2]); small = cv2.resize(a, None, fx=s, fy=s) if s < 1 else a
    g = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_RGB2GRAY), (5, 5), 0); e = cv2.dilate(cv2.Canny(g, 40, 120), np.ones((5, 5), np.uint8))
    cs, _ = cv2.findContours(e, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area = small.shape[0] * small.shape[1]; best = None
    for c in cs:
        r = cv2.minAreaRect(c); (w, h) = r[1]
        if min(w, h) < 40 or w * h < 0.12 * area or w * h > 0.97 * area: continue
        asp = min(w, h) / max(w, h); sc = (w * h / area) * max(0.0, 1 - abs(asp - 0.714) * 3)
        if not best or sc > best[0]: best = (sc, r)
    if not best: return im.convert("RGB"), 0.0
    box = cv2.boxPoints(best[1]).astype(np.float32); box = box[np.argsort(box[:, 1])]            # two top points, two bottom points
    tl, tr = sorted(box[:2], key=lambda p: p[0]); bl, br = sorted(box[2:], key=lambda p: p[0])
    pts = np.array([tl, tr, br, bl], np.float32)
    ancho = np.linalg.norm(pts[1] - pts[0]); alto = np.linalg.norm(pts[3] - pts[0])
    tumbada = ancho > alto
    if tumbada: pts = np.roll(pts, -1, axis=0)                                                   # lying on its side: make the long side vertical
    m = cv2.getPerspectiveTransform(pts, np.array([[0, 0], [630, 0], [630, 880], [0, 880]], np.float32))
    out = cv2.warpPerspective(small, m, (630, 880))
    if tumbada:   # a card standing up in the photo is taken as upright; one on its side may be turned either way, so the more colourful half (the artwork) goes on top
        hsv = cv2.cvtColor(out, cv2.COLOR_RGB2HSV)[..., 1].astype(np.float32)
        if hsv[:440, 40:590].mean() < hsv[440:, 40:590].mean(): out = out[::-1, ::-1]
    return Image.fromarray(np.ascontiguousarray(out)), float(best[0])

_cartas = {}
def imagen_carta(key):
    """The best photo of one Gold Star among the raw listings of the saved searches: cut out and upright, or the plain photo when no card outline is found."""
    if key in _cartas: return _cartas[key]
    c = ventas.cartas().get(key); mejor = (0.0, None); alt = None
    for _, url in (fotos_de_busquedas().get(c["name_en"]) or [])[:14] if c else []:
        im = foto(url)
        if not im: continue
        alt = alt or im
        try: rec, sc = enderezar(im)
        except Exception: continue
        if sc > mejor[0]: mejor = (sc, rec)
        if sc > 0.55: break
    _cartas[key] = mejor[1] if mejor[1] is not None else alt
    return _cartas[key]

def datos_carta(key, ed=None):
    """{"key", "ed", "nombre", "foto", "valores": {nota: {"eur", "n", "ref"}}} of one card, or None without a photo or a single price."""
    c = ventas.cartas().get(key); im = imagen_carta(key) if c else None
    if not im: return None
    vals = {}
    for nota in NOTAS:
        v = reels.precio(key, nota, ed)
        if v: vals[nota] = {"eur": v["eur"], "n": v["n"], "ref": bool(v.get("referencia"))}
    if not vals: return None
    return {"key": key, "ed": ed, "nombre": nombre(c["name_en"]) + (f" ({ED_TXT[ed]})" if ed else ""), "foto": im, "valores": vals}

def todas(nota=None):
    out = []
    for k in ventas.cartas():
        for ed in sorted(ventas._ediciones(k)) or [None]:
            d = datos_carta(k, ed)
            if d and (not nota or nota in d["valores"]): out.append(d)
    return out

def fuente_pie(d):
    n = sum(v["n"] for v in d["valores"].values()); ref = any(v["ref"] for v in d["valores"].values())
    return (f"{n} ventas reales (SNKRDUNK)" + (" y precio de Collectr" if ref else "") if n else "Precio de mercado de Collectr") + " · " + reels.fecha_es(reels.dt.date.today().isoformat())

# ---------------------------------------------------------------- drawing pieces
def estrellas(n=70, seed=7):
    r = random.Random(seed)
    return [(r.random() * W, r.random() * H, 0.4 + r.random() * 1.6, 2 + r.random() * 5, r.random() * 6.28) for _ in range(n)]

ESTRELLAS = estrellas()

def fondo_animado(base, t):
    """The gradient with slowly rising, twinkling specks."""
    im = base.copy(); d = ImageDraw.Draw(im, "RGBA")
    for x, y, v, s, ph in ESTRELLAS:
        yy = (y - t * 40 * v) % H; a = int(60 + 90 * (0.5 + 0.5 * math.sin(t * 2 + ph)))
        d.ellipse((x - s, yy - s, x + s, yy + s), fill=(255, 255, 255, a))
    return im

def dorso():
    """A drawn card back (nothing copied): deep blue, gold ring and a spark."""
    im = Image.new("RGBA", (CW, CH), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    g = ImageOps.colorize(Image.linear_gradient("L").resize((CW, CH)), (20, 40, 110), (60, 110, 220)).convert("RGBA"); im.alpha_composite(g)
    d.rounded_rectangle((16, 16, CW - 17, CH - 17), 30, outline=ORO, width=6)
    cx, cy = CW // 2, CH // 2
    for r, w in ((190, 8), (150, 4), (110, 14)): d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(255, 255, 255, 200), width=w)
    d.ellipse((cx - 44, cy - 44, cx + 44, cy + 44), fill=ORO)
    return redondear(im, 34)

def cara(im):
    """The photo of the card on its panel at card size, with rounded corners."""
    return reels.marco(im, (CW, CH), 34)

def brillo(card, pos):
    """A diagonal holographic sweep over the card (pos 0..1 crosses it), only where the card is."""
    a = np.asarray(card).astype(np.float32); h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]; d = (xx + yy * 0.55) / (w + h * 0.55) - (pos * 1.6 - 0.3)
    band = np.exp(-(d / 0.07) ** 2)[..., None]
    tint = np.array([255, 235, 255], np.float32)
    a[..., :3] = np.clip(a[..., :3] * (1 - 0.55 * band) + tint * 0.55 * band * 1.0, 0, 255)
    return Image.fromarray(a.astype(np.uint8), "RGBA")

_glow = {}
def resplandor(color):
    if color not in _glow:
        g = Image.new("RGBA", (CW + 300, CH + 300), (0, 0, 0, 0)); ImageDraw.Draw(g).rounded_rectangle((150, 150, CW + 150, CH + 150), 60, fill=color + (255,))
        _glow[color] = g.filter(ImageFilter.GaussianBlur(70))
    return _glow[color]

def pegar_carta(lienzo, card, cx, cy, esc=1.0, giro=1.0, glow=None, alpha=1.0):
    """Paste a card centred at (cx, cy); giro < 1 squeezes it sideways (a flip), glow is a colour of light behind it."""
    w, h = max(4, int(card.width * esc * max(0.02, giro))), max(4, int(card.height * esc))
    if glow:
        g = resplandor(glow); gw, gh = int(g.width * esc * max(0.3, giro)), int(g.height * esc)
        gi = g.resize((gw, gh)); gi.putalpha(gi.getchannel("A").point(lambda v: int(v * 0.55 * alpha))); lienzo.alpha_composite(gi, (int(cx - gw / 2), int(cy - gh / 2)))
    c = card.resize((w, h), Image.LANCZOS)
    if alpha < 1: c = reels.transparente(c, alpha)
    lienzo.alpha_composite(c, (int(cx - w / 2), int(cy - h / 2)))

def texto_c(d, xy, txt, size, fill=BLANCO, maxw=980, bold=True, stroke=0):
    d.text(xy, txt, font=ajustar(d, txt, size, maxw, bold), fill=fill, anchor="mm", stroke_width=stroke, stroke_fill=(0, 0, 0))

def contador(v, k): return euros(v * ease(k))

class Base(Video):
    def __init__(self): super().__init__(); self.base = self.fondo.copy()
    def lienzo(self, t): return fondo_animado(self.base, t)

# ---------------------------------------------------------------- 1. revela
class Revela(Base):
    DURACION = 13.0
    def __init__(self, d):
        super().__init__(); self.d = d; self.cara = cara(d["foto"]); self.dorso = dorso(); self.vals = d["valores"]
        self.nota_hero = "Sin gradear" if "Sin gradear" in self.vals else next(iter(self.vals))
    def frame(self, t):
        im = self.lienzo(t); d = ImageDraw.Draw(im, "RGBA"); k = lambda a, b: (t - a) / (b - a)
        texto_c(d, (W // 2, 150), "¿CUÁNTO VALE?", 92, ORO, stroke=4)
        texto_c(d, (W // 2, 250), self.d["nombre"], 60, BLANCO, stroke=3)
        cy = 860
        if t < 1.2: pass
        elif t < 4.2:
            e = ease(k(1.2, 2.6)); y = cy + (1 - e) * 900; g = ease(k(2.6, 3.8))
            giro = abs(math.cos(math.pi * g)); card = self.dorso if g < 0.5 else self.cara
            pegar_carta(im, card, W // 2, y, 0.72 + 0.28 * e, giro if g < 1 else 1.0, glow=AZUL)
        else:
            card = brillo(self.cara, k(4.2, 6.2) % 1.6 / 1.0) if 4.2 <= t < 6.2 else self.cara
            pegar_carta(im, card, W // 2, cy + math.sin(t * 1.6) * 8, 1.0, 1.0, glow=ORO if self.nota_hero != "Sin gradear" else AZUL)
        if t >= 4.6:
            v = self.vals[self.nota_hero]; a = ease(k(4.6, 5.2)); y0 = 1380
            d.rounded_rectangle((90, y0 - 80, W - 90, y0 + 90), 40, fill=(0, 0, 0, int(170 * a)))
            texto_c(d, (W // 2, y0 - 38), self.nota_hero.upper() + (" · PRECIO DE REFERENCIA" if v["ref"] else ""), 34, GRIS)
            texto_c(d, (W // 2, y0 + 28), contador(v["eur"], k(5.0, 8.0)), 100, VERDE, stroke=3)
        if t >= 8.3:
            filas = [(n, self.vals[n]) for n in NOTAS if n in self.vals and n != self.nota_hero][:2]
            mx = max([self.vals[self.nota_hero]["eur"]] + [v["eur"] for _, v in filas])
            for i, (n, v) in enumerate(filas):
                y = 1560 + i * 100; g = ease(k(8.3 + i * 0.5, 9.8 + i * 0.5)); wmax = 560
                d.text((90, y), n, font=fuente(40), fill=BLANCO, anchor="lm")
                d.rounded_rectangle((300, y - 24, 300 + max(14, wmax * (v["eur"] / mx) * g), y + 24), 24, fill=ROSA if "10" in n else AZUL)
                d.text((W - 90, y), euros(v["eur"] * g), font=fuente(44), fill=BLANCO, anchor="rm")
        d.text((W // 2, 1860), fuente_pie(self.d), font=fuente(28, False), fill=GRIS, anchor="mm")
        if t > 11.2: texto_c(d, (W // 2, 1790), "¿Lo tenías tan caro? Dímelo en comentarios", 44, ORO, stroke=3)
        return im.convert("RGB")

# ---------------------------------------------------------------- 2. ventas reales
class Ventas(Base):
    DURACION = 12.0
    def __init__(self, d, nota, ventas_):
        super().__init__(); self.d, self.nota, self.v = d, nota, ventas_      # ventas_: [{"fecha", "eur"}] oldest first
        ys = [x["eur"] for x in ventas_]; self.lo, self.hi = min(ys), max(ys); self.med = float(np.median(ys))
        self.card = cara(d["foto"]).resize((CW * 6 // 10, CH * 6 // 10), Image.LANCZOS)
    def frame(self, t):
        im = self.lienzo(t); d = ImageDraw.Draw(im, "RGBA")
        texto_c(d, (W // 2, 140), "ASÍ SE HA VENDIDO", 84, ORO, stroke=4)
        texto_c(d, (W // 2, 235), f"{self.d['nombre']} · {self.nota}", 54, BLANCO, stroke=3)
        im.alpha_composite(reels.transparente(self.card, ease(t / 0.8)), (W // 2 - self.card.width // 2, 300))
        x0, x1, y0, y1 = 110, W - 90, 930, 1620
        pad = (self.hi - self.lo) * 0.15 or self.hi * 0.1
        Y = lambda v: y1 - (v - (self.lo - pad)) / ((self.hi + pad) - (self.lo - pad)) * (y1 - y0)
        n = len(self.v); X = lambda i: x0 + (x1 - x0) * (i / max(1, n - 1))
        for g in range(5):
            gv = self.lo - pad + ((self.hi + pad) - (self.lo - pad)) * g / 4; d.line((x0, Y(gv), x1, Y(gv)), fill=(255, 255, 255, 34), width=2)
            d.text((x0 - 14, Y(gv)), euros(gv), font=fuente(26, False), fill=GRIS, anchor="rm")
        prog = ease((t - 0.8) / 7.5) * (n - 1); pts = [(X(i), Y(x["eur"])) for i, x in enumerate(self.v)]
        vis = pts[: int(prog) + 1]
        if int(prog) + 1 < n:
            f = prog - int(prog); a, b = pts[int(prog)], pts[int(prog) + 1]; vis.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
        if len(vis) > 1: d.line(vis, fill=AZUL + (255,), width=8, joint="curve")
        for i, (x, y) in enumerate(vis[: int(prog) + 1]): d.ellipse((x - 10, y - 10, x + 10, y + 10), fill=BLANCO)
        if vis:
            x, y = vis[-1]; d.ellipse((x - 16, y - 16, x + 16, y + 16), fill=ORO)
            i = min(int(prog), n - 1); texto_c(d, (min(max(x, 240), W - 240), y - 52), euros(self.v[i]["eur"]), 46, BLANCO, 460, stroke=3)
            d.text((x0, y1 + 40), self.v[0]["fecha"][5:].replace("-", "/"), font=fuente(26, False), fill=GRIS, anchor="lm")
            d.text((x1, y1 + 40), self.v[i]["fecha"][5:].replace("-", "/"), font=fuente(26, False), fill=GRIS, anchor="rm")
        if t > 8.6:
            a = ease((t - 8.6) / 0.8); d.rounded_rectangle((90, 1690, W - 90, 1830), 36, fill=(0, 0, 0, int(190 * a)))
            texto_c(d, (W // 2, 1735), f"{n} ventas reales · mediana {euros(self.med)}", 50, VERDE, stroke=2)
            texto_c(d, (W // 2, 1792), f"de {euros(self.lo)} a {euros(self.hi)} en 6 meses", 38, GRIS, bold=False)
        d.text((W // 2, 1880), "SNKRDUNK · " + reels.fecha_es(reels.dt.date.today().isoformat()), font=fuente(26, False), fill=GRIS, anchor="mm")
        return im.convert("RGB")

# ---------------------------------------------------------------- 3. top
class Top(Base):
    POR = 3.2
    def __init__(self, cards, nota):
        super().__init__(); self.cards, self.nota = cards, nota; self.DURACION = 2.0 + self.POR * len(cards) + 2.0
        self.caras = [cara(c["foto"]).resize((CW * 6 // 10, CH * 6 // 10), Image.LANCZOS) for c in cards]
    def frame(self, t):
        im = self.lienzo(t); d = ImageDraw.Draw(im, "RGBA"); n = len(self.cards)
        texto_c(d, (W // 2, 130), f"LAS {n} MÁS CARAS", 92, ORO, stroke=4); texto_c(d, (W // 2, 225), f"Gold Stars japonesas · {self.nota}", 48, GRIS, bold=False)
        i = int((t - 2.0) // self.POR) if t >= 2.0 else -1
        if t < 2.0:
            texto_c(d, (W // 2, 900), "¿Sabes cuál es la nº 1?", 74, BLANCO, stroke=4, maxw=940); return im.convert("RGB")
        i = min(i, n - 1); c = self.cards[i]; k = ((t - 2.0) - i * self.POR) / self.POR; rank = n - i
        e = ease(k / 0.18); texto_c(d, (150, 420 + (1 - e) * 60), f"#{rank}", 200, ORO if rank > 1 else (255, 120, 140), 400, stroke=6)
        pegar_carta(im, self.caras[i], W // 2 + 130 + (1 - e) * 700, 900, 1.0, 1.0, glow=(AZUL if rank > 1 else ROSA))
        texto_c(d, (W // 2, 1400), c["nombre"], 62, BLANCO, 980, stroke=3)
        texto_c(d, (W // 2, 1520), contador(c["valores"][self.nota]["eur"], k / 0.5), 118, VERDE, stroke=4)
        v = c["valores"][self.nota]; d.text((W // 2, 1620), ("precio de referencia" if v["ref"] else f"mediana de {v['n']} ventas reales"), font=fuente(32, False), fill=GRIS, anchor="mm")
        d.text((W // 2, 1860), fuente_pie(c), font=fuente(26, False), fill=GRIS, anchor="mm")
        return im.convert("RGB")

# ---------------------------------------------------------------- 4. posts
def poster(d, nota, tam=(1080, 1350)):
    """A still poster of one card: photo with glow, name, price and the grade ladder."""
    w, h = tam; im = ImageOps.colorize(Image.linear_gradient("L").resize((w, h)), reels.FONDO[0], reels.FONDO[1]).convert("RGBA"); dr = ImageDraw.Draw(im, "RGBA")
    for x, y, v, s, ph in ESTRELLAS: dr.ellipse((x % w - s, y % h - s, x % w + s, y % h + s), fill=(255, 255, 255, 110))
    texto_c(dr, (w // 2, 90), "CARTA DEL DÍA", 54, ORO, stroke=3); texto_c(dr, (w // 2, 168), d["nombre"], 62, BLANCO, 980, stroke=3)
    c = cara(d["foto"]); esc = 0.78; pegar_carta(im, c, w // 2, 620, esc, 1.0, glow=AZUL)
    v = d["valores"][nota]; dr.rounded_rectangle((90, 1010, w - 90, 1190), 40, fill=(0, 0, 0, 170))
    texto_c(dr, (w // 2, 1055), nota.upper() + (" · REFERENCIA" if v["ref"] else ""), 32, GRIS); texto_c(dr, (w // 2, 1135), euros(v["eur"]), 96, VERDE, stroke=3)
    texto_c(dr, (w // 2, 1255), "  ·  ".join(f"{k} {euros(x['eur'])}" for k, x in d["valores"].items() if k != nota) or " ", 38, BLANCO, 980, bold=False)
    dr.text((w // 2, 1315), fuente_pie(d), font=fuente(24, False), fill=GRIS, anchor="mm")
    return im.convert("RGB")

def carrusel(cards, nota, base):
    """[path] of a carousel: cover, one slide per card (best last) and a closing slide, 1080x1350."""
    w, h = 1080, 1350; out = []
    def lienzo(): return ImageOps.colorize(Image.linear_gradient("L").resize((w, h)), reels.FONDO[0], reels.FONDO[1]).convert("RGBA")
    def guarda(im, i): p = f"{base}-{i:02d}.png"; im.convert("RGB").save(p); out.append(p)
    n = len(cards); im = lienzo(); d = ImageDraw.Draw(im, "RGBA")
    texto_c(d, (w // 2, 330), f"LAS {n} GOLD STARS", 110, ORO, stroke=5); texto_c(d, (w // 2, 460), "MÁS CARAS", 110, ORO, stroke=5)
    texto_c(d, (w // 2, 600), f"japonesas · {nota}", 52, BLANCO, stroke=3); pegar_carta(im, cara(cards[-1]["foto"]), w // 2, 930, 0.52, 1.0, glow=ROSA)
    texto_c(d, (w // 2, 1280), "DESLIZA  >>", 46, GRIS, bold=False); guarda(im, 0)   # the fonts have no arrow glyph
    for i, c in enumerate(cards):
        im = lienzo(); d = ImageDraw.Draw(im, "RGBA"); rank = n - i; v = c["valores"][nota]
        texto_c(d, (150, 130), f"#{rank}", 150, ORO if rank > 1 else (255, 120, 140), 300, stroke=5); texto_c(d, (w // 2 + 100, 140), c["nombre"], 52, BLANCO, 760, stroke=3)
        pegar_carta(im, cara(c["foto"]), w // 2, 660, 0.84, 1.0, glow=AZUL if rank > 1 else ROSA)
        d.rounded_rectangle((120, 1120, w - 120, 1270), 40, fill=(0, 0, 0, 170)); texto_c(d, (w // 2, 1195), euros(v["eur"]), 100, VERDE, stroke=3); guarda(im, i + 1)
    im = lienzo(); d = ImageDraw.Draw(im, "RGBA")
    texto_c(d, (w // 2, 520), "¿Cuál querrías?", 100, ORO, stroke=5); texto_c(d, (w // 2, 680), "Sigue para más precios reales", 56, BLANCO, stroke=3)
    texto_c(d, (w // 2, 1230), fuente_pie(cards[0]), 28, GRIS, 1000, bold=False); guarda(im, n + 1)
    return out

# ---------------------------------------------------------------- run
def guardar(nom, objeto, texto):
    os.makedirs(OUT, exist_ok=True); base = os.path.join(OUT, nom)
    if isinstance(objeto, Video):
        objeto.video(base + ".mp4"); objeto.frame(objeto.DURACION * 0.55).save(base + ".png")
    save(base + ".json", {"nombre": nom, "texto": texto, "creado": reels.dt.datetime.now().isoformat(timespec="minutes")})
    return base

TAGS = "#pokemon #pokemontcg #pokemoncards #goldstar #coleccionismo #tcg"

def texto_revela(d):
    l = " · ".join(f"{k} {euros(v['eur'])}" for k, v in d["valores"].items())
    return f"¿Cuánto vale la {d['nombre']}? 💰\n{l}\n{fuente_pie(d)}\n{TAGS}"

def texto_ventas(d, nota, s):
    p = [v["eur"] for v in s]; med = float(np.median(p))
    return f"Así se ha vendido la {d['nombre']} en {nota}: {len(s)} ventas reales en 6 meses, mediana {euros(med)}, de {euros(min(p))} a {euros(max(p))}.\nSNKRDUNK · {reels.fecha_es(reels.dt.date.today().isoformat())}\n{TAGS}"

def texto_top(cs, nota):
    lin = "\n".join(f"{i}. {c['nombre']}: {euros(c['valores'][nota]['eur'])}" for i, c in enumerate(cs, 1))
    return f"Las {len(cs)} Gold Stars japonesas más caras en {nota} 🏆\n{lin}\n{fuente_pie(cs[0])}\n¿Cuál querrías?\n{TAGS}"

def elegir_carta(pedida, nota):
    if pedida:
        k, _, ed = pedida.partition(":"); return datos_carta(k, None if ed in ("", "-") else ed)
    c = [x for x in todas(nota) if len(x["valores"]) >= 2] or todas(nota)
    return max(c, key=lambda x: x["valores"][nota]["eur"]) if c else None

def series_ventas(key, nota, ed=None):
    d = (ventas._datos(key).get("ventas") or []); vs = [v for v in d if v["nota"] == nota and v.get("eur") and (not ed or not v.get("edicion") or v["edicion"] == ed)]
    return sorted(({"fecha": v["fecha"], "eur": v["eur"]} for v in vs), key=lambda v: v["fecha"])

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--formato", default="todo"); ap.add_argument("--carta"); ap.add_argument("--nota"); ap.add_argument("--lista", action="store_true")
    a = ap.parse_args(); sys.stdout.reconfigure(encoding="utf-8")
    nota_rev = a.nota or "Sin gradear"; nota_top = a.nota or "PSA 10"      # rankings by PSA 10 (real sales), the reveal starts from the ungraded card
    if a.lista:
        for d in todas(): print(d["nombre"], {k: v["eur"] for k, v in d["valores"].items()})
        return
    hechos = []
    if a.formato in ("revela", "todo"):
        d = elegir_carta(a.carta, nota_rev)
        if d: nom = "revela-" + reels.slug(d["nombre"]); guardar(nom, Revela(d), texto_revela(d)); hechos.append(nom)
    if a.formato in ("ventas", "todo"):
        notas_v = [a.nota] if a.nota else ["PSA 10", "PSA 9", "PSA ≤8"]; cand = []
        for d in todas():
            for nv in notas_v:
                s = series_ventas(d["key"], nv, d["ed"])
                if len(s) >= 4: cand.append((len(s), d, nv, s))
        if cand:
            _, d, nv, s = max(cand, key=lambda x: x[0]); nom = "ventas-" + reels.slug(d["nombre"]) + "-" + reels.slug(nv); guardar(nom, Ventas(d, nv, s), texto_ventas(d, nv, s)); hechos.append(nom)
    if a.formato in ("top", "post", "carrusel", "todo"):
        cs = sorted(todas(nota_top), key=lambda x: x["valores"][nota_top]["eur"], reverse=True)
        vistos, uno = set(), []
        for c in cs:                                  # each card once (its dearest edition)
            if c["key"] not in vistos: vistos.add(c["key"]); uno.append(c)
        cs = uno[:5]
        if len(cs) >= 3:
            orden = list(reversed(cs))                # shown from the 5th to the 1st
            if a.formato in ("top", "todo"): nom = "top-" + reels.slug(nota_top); guardar(nom, Top(orden, nota_top), texto_top(cs, nota_top)); hechos.append(nom)
            if a.formato in ("carrusel", "todo"):
                b = "carrusel-" + reels.slug(nota_top); ps = carrusel(orden, nota_top, os.path.join(OUT, b)); hechos += [os.path.basename(p) for p in ps]
                save(os.path.join(OUT, b + ".json"), {"nombre": b, "texto": texto_top(cs, nota_top)})
            if a.formato in ("post", "todo"):
                im = poster(cs[0], nota_top); os.makedirs(OUT, exist_ok=True); b = "post-" + reels.slug(cs[0]["nombre"]); im.save(os.path.join(OUT, b + ".png")); hechos.append(b + ".png")
                save(os.path.join(OUT, b + ".json"), {"nombre": b, "texto": texto_revela(cs[0])})
    print("Hecho:", ", ".join(hechos) if hechos else "no hay datos suficientes (hacen falta cartas con foto y precio)")

if __name__ == "__main__": main()
