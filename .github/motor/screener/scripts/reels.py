"""Content (owner, 2 November 2026: "automatizar la creación de Reels para TikTok, para Instagram... reels de todo tipo, que sean muy captadores
de audiencia"): vertical videos made from the app's own data. Formats so far:
  cual   «¿Cuál vale más?»: three Japanese Gold Stars, a countdown and the answer.
  notas  «La nota lo cambia todo»: one card ungraded, in PSA 9 and in PSA 10, with bars that grow.
Prices are market values from REAL sales (ventas.py: SNKRDUNK's sales, else Collectr's price), never what eBay sellers ask. A price is only
used when it belongs to one edition (a Japanese Unlimited and a 1st edition are different cards in value): never a mix.
Pictures: the photo the app already shows for each card (mercado._foto), downloaded once to data/reels/fotos.
Video: Pillow frames piped to the ffmpeg of imageio-ffmpeg (installed for the podcasts), 1080x1920, 30 fps, H.264 with a silent audio track
(music is added in Instagram / TikTok when uploading). Output in data/reels/: <name>.mp4, <name>.png (cover) and <name>.json (what it says).
Usage: python reels.py [--formato cual|notas] [--cartas k1,k2,k3 | --carta torchic:Unlimited] [--nota "Sin gradear"] [--semilla N] [--lista]"""
import argparse, datetime as dt, hashlib, io, itertools, os, random, re, subprocess, sys, unicodedata, urllib.request
from PIL import Image, ImageDraw, ImageFont, ImageOps
import mercado, ventas, voz
from common import P, save

W, H, FPS = 1080, 1920, 30
OUT = P("reels")
RATIO = 1.3          # each price at least 30 % above the next one: no near ties
LETRAS = [("A", (255, 92, 92)), ("B", (77, 166, 255)), ("C", (255, 196, 61))]
VERDE, BLANCO, GRIS, ORO, FONDO = (61, 220, 132), (255, 255, 255), (178, 182, 214), (255, 203, 5), ((14, 16, 38), (38, 30, 84))
MESES = "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split()
ED_TXT = {"1st Edition": "1ª ed.", "Unlimited": "Unlimited"}
# timeline of «¿Cuál vale más?», in seconds
T_FILAS, T_CUENTA, SEG_CUENTA, T_REVELA, T_FINAL, T_FIN = 0.5, 1.9, 5, 6.9, 10.8, 14.0

def fuente(size, bold=True):
    d = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for f in (["seguibl.ttf", "segoeuib.ttf", "arialbd.ttf"] if bold else ["segoeui.ttf", "arial.ttf"]):
        if os.path.exists(os.path.join(d, f)): return ImageFont.truetype(os.path.join(d, f), size)
    return ImageFont.load_default(size)

def nombre(label):
    """"shining mewtwo" -> "Shining Mewtwo"; the ☆ of a Gold Star is written out (the fonts have no star)."""
    s = re.sub(r"\s*[☆★]\s*", " Gold Star ", label).strip()
    return " ".join(w if any(c.isupper() or c.isdigit() for c in w) else w.capitalize() for w in s.split())

def euros(v):
    s = f"{v:,.0f}" if v >= 100 else f"{v:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".") + " €"

def fecha_es(d):
    d = dt.date.fromisoformat(d); return f"{d.day} de {MESES[d.month - 1]} de {d.year}"

def slug(s):
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40]

def fuente_texto(cards):
    n = sum(c["n"] for c in cards); col = any(c["ref"] for c in cards); hoy = fecha_es(dt.date.today().isoformat())
    if n and col: return f"{n} ventas reales (SNKRDUNK) y precio de Collectr · {hoy}"
    return f"Mediana de {n} ventas reales en SNKRDUNK · {hoy}" if n else f"Precio de mercado de Collectr · {hoy}"

# ---------------------------------------------------------------- the data
def precio(key, nota, ed):
    """Market value of one card, grade and edition (ventas.valor), only when it belongs to that edition alone."""
    v = ventas.valor(key, nota, ed)
    if not v or v.get("ambigua"): return None
    if ed is None and len(ventas._ediciones(key)) > 1: return None
    if ed and set(v.get("ediciones") or []) - {ed}: return None
    return v

def carta(key, ed, nota="Sin gradear"):
    """One Gold Star in one edition, with its photo and its value in nota (or None)."""
    c = ventas.cartas().get(key); cur, _ = mercado.snaps(); t = ((cur or {}).get("tracks") or {}).get("gs-" + key)
    url = mercado._foto("gs-" + key, c["name_en"], mercado.limpios(t["items"])) if c and t else None
    v = precio(key, nota, ed) if url else None
    if not v: return None
    return {"key": key, "ed": ed, "nombre": nombre(c["name_en"]) + (f" ({ED_TXT[ed]})" if ed else ""), "med": v["eur"], "n": v["n"],
            "ref": bool(v.get("referencia")), "foto": url}

def candidatas(nota="Sin gradear"):
    """{"key:edition": card}: every Japanese Gold Star (and edition) with a value in nota and a photo."""
    out = {}
    for k in ventas.cartas():
        for ed in sorted(ventas._ediciones(k)) or [None]:
            c = carta(k, ed, nota)
            if c: out[f"{k}:{ed or '-'}"] = c
    return out

def separadas(cards):
    p = sorted(c["med"] for c in cards)
    return p[1] >= RATIO * p[0] and p[2] >= RATIO * p[1] and len({c["key"] for c in cards}) == 3

def elegir(cands, rnd):
    """Three cards with clearly different prices, shown in a random order; when it can, not one worth 5 times the cheapest (too easy)."""
    combos = [c for c in itertools.combinations(cands.values(), 3) if separadas(c)]
    reñidas = [c for c in combos if max(x["med"] for x in c) <= 5 * min(x["med"] for x in c)]
    if not combos: return None
    c = list(rnd.choice(reñidas or combos)); rnd.shuffle(c); return c

def foto(url):
    """The picture of a card, downloaded once (the largest size eBay gives for that photo)."""
    os.makedirs(os.path.join(OUT, "fotos"), exist_ok=True)
    f = os.path.join(OUT, "fotos", hashlib.sha1(url.encode()).hexdigest()[:16] + ".jpg")
    if not os.path.exists(f):
        for u in dict.fromkeys([re.sub(r"s-l\d+", "s-l1600", url), url]):
            try:
                data = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read()
                Image.open(io.BytesIO(data)).verify()
                with open(f, "wb") as fh: fh.write(data)
                break
            except Exception: continue
        else: return None
    return Image.open(f).convert("RGB")

# ---------------------------------------------------------------- drawing
def ease(x): x = min(1, max(0, x)); return 1 - (1 - x) ** 3

def ajustar(draw, text, size, maxw, bold=True, minimo=28):
    """The biggest font, from size down, that fits text in maxw."""
    while size > minimo and draw.textlength(text, font=fuente(size, bold)) > maxw: size -= 2
    return fuente(size, bold)

def lineas(draw, text, font, maxw, n=2):
    out, cur = [], ""
    text = re.sub(r"(\d) ([$€%])", "\\1\u00a0\\2", text)          # "1.000 $" never splits before its symbol
    for w in text.split(" "):
        if cur and draw.textlength(cur + " " + w, font=font) > maxw: out.append(cur); cur = w
        else: cur = (cur + " " + w).strip()
    out.append(cur)
    return out if len(out) <= n else out[:n - 1] + [" ".join(out[n - 1:])]

def transparente(img, f):
    if f >= 1: return img
    img = img.copy(); img.putalpha(img.getchannel("A").point(lambda a: int(a * f))); return img

def redondear(img, r):
    m = Image.new("L", img.size, 0); ImageDraw.Draw(m).rounded_rectangle((0, 0, *img.size), r, fill=255)
    out = img.convert("RGBA"); out.putalpha(m); return out

def marco(im, box, r=22):
    """A card photo fitted in box over a dark rounded panel."""
    im = ImageOps.contain(im, box, Image.LANCZOS)
    f = Image.new("RGBA", box, (8, 9, 22, 255)); f.paste(im, ((box[0] - im.width) // 2, (box[1] - im.height) // 2))
    return redondear(f, r)

def cabecera(grupo, titulo, sub):
    t = Image.new("RGBA", (W, 460), (0, 0, 0, 0)); d = ImageDraw.Draw(t, "RGBA")
    d.text((W // 2, 140), grupo.upper(), font=ajustar(d, grupo.upper(), 40, 940), fill=ORO, anchor="mm")
    d.text((W // 2, 265), titulo, font=ajustar(d, titulo, 118, 980), fill=BLANCO, anchor="mm")
    d.text((W // 2, 375), sub, font=ajustar(d, sub, 40, 960, bold=False), fill=GRIS, anchor="mm")
    return t

def check(d, x, y, s, color):
    d.line([(x - s, y), (x - s * 0.3, y + s * 0.7), (x + s, y - s * 0.8)], fill=color, width=max(6, s // 4), joint="curve")

def pie(d, s, linea1, linea2):
    k = ease(s / 0.5)
    d.rectangle((0, 1700, W, H), fill=(14, 16, 38, int(235 * k)))
    d.text((W // 2, 1770), linea1, font=ajustar(d, linea1, 50, 1000), fill=BLANCO + (int(255 * k),), anchor="mm")
    d.text((W // 2, 1840), linea2, font=ajustar(d, linea2, 30, 980, bold=False), fill=GRIS + (int(255 * k),), anchor="mm")

def subtitulo(d, txt, y=1655):
    """A burnt-in subtitle: big white words on a dark pill (most people watch Reels without sound)."""
    if not txt: return
    f = ajustar(d, txt, 62, 960); w = d.textlength(txt, font=f)
    d.rounded_rectangle((W / 2 - w / 2 - 28, y - 50, W / 2 + w / 2 + 28, y + 50), 26, fill=(0, 0, 0, 175))
    d.text((W // 2, y), txt, font=f, fill=BLANCO, anchor="mm", stroke_width=3, stroke_fill=(0, 0, 0))

def medir(textos, carpeta):
    """[(wav, seconds)] of each line spoken (voz.decir), to lay the video out around the voice."""
    out = []
    for i, x in enumerate(textos):
        wav = os.path.join(carpeta, f"m{i:02d}.wav"); out.append((wav, voz.decir(x, wav)))
    return out

class Video:
    """A video: subclasses give frame(t) -> RGB image and DURACION in seconds; with a voice, self.pista (voz.Pista) gives the sound and subtitles."""
    pista = None
    def __init__(self): self.fondo = ImageOps.colorize(Image.linear_gradient("L").resize((W, H)), FONDO[0], FONDO[1]).convert("RGBA")

    def sub(self, d, t, y=1655):
        if self.pista: subtitulo(d, self.pista.subtitulo(t), y)

    def video(self, path):
        import imageio_ffmpeg
        tmp = path + ".tmp.mp4"
        audio = ["-i", self.pista.wav(path + ".wav", self.DURACION)] if self.pista else ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
        p = subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", *audio,
                              "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                              "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", tmp], stdin=subprocess.PIPE)
        for n in range(int(self.DURACION * FPS)): p.stdin.write(self.frame(n / FPS).tobytes())
        p.stdin.close()
        if p.wait(): sys.exit("ffmpeg no pudo montar el vídeo.")
        os.replace(tmp, path)
        if self.pista and os.path.exists(path + ".wav"): os.remove(path + ".wav")

FILA_Y, FILA_H, FILA_X, FILA_W = 470, 390, 60, 960

def fila(card, i):
    """The still part of a row: panel, photo, letter and name."""
    t = Image.new("RGBA", (FILA_W, FILA_H), (0, 0, 0, 0)); d = ImageDraw.Draw(t, "RGBA")
    d.rounded_rectangle((0, 0, FILA_W - 1, FILA_H - 1), 36, fill=(255, 255, 255, 22), outline=(255, 255, 255, 40), width=2)
    t.alpha_composite(marco(card["img"], (250, 340)), (25, 25))
    letra, color = LETRAS[i]
    d.ellipse((310, 30, 410, 130), fill=color); d.text((360, 80), letra, font=fuente(64), fill=(14, 16, 38), anchor="mm")
    f = ajustar(d, card["nombre"], 62, 600) if len(card["nombre"]) < 16 else fuente(54)
    for j, l in enumerate(lineas(d, card["nombre"], f, 610)):
        d.text((310, 165 + j * (f.size + 8)), l, font=f, fill=BLANCO)
    return t

class CualValeMas(Video):
    DURACION = T_FIN
    def __init__(self, cards, nota, carpeta_voz=None):
        super().__init__()
        self.cards, self.pregunta = cards, "¿CUÁL VALE MÁS?"
        self.cab = cabecera("Gold Star japonesas", self.pregunta, f"{nota[0].upper() + nota[1:]} · valor de mercado por ventas reales")
        self.filas = [fila(c, i) for i, c in enumerate(cards)]
        self.maxp = max(c["med"] for c in cards)
        self.gana = max(range(3), key=lambda i: cards[i]["med"])
        self.fuente_txt = fuente_texto(cards)
        if carpeta_voz:   # the cards are on screen: the voice asks and answers, without subtitles over the rows
            g = cards[self.gana]
            self.pista = voz.Pista([(0.4, "¿Cuál de estas tres Gold Star japonesas vale más? Piensa y comenta.", False),
                                    (T_REVELA + 0.1, f"La más cara es {g['nombre']}: unos {euros(g['med'])}.", False),
                                    (T_FINAL + 0.2, "¿Acertaste? Cuéntalo en comentarios.", False)], carpeta_voz)
            self.DURACION = max(T_FIN, self.pista.fin + 0.6)

    def frame(self, t):
        im = self.fondo.copy()
        im.alpha_composite(transparente(self.cab, ease(t / 0.6)), (0, int(40 * (1 - ease(t / 0.6)))))
        for i, f in enumerate(self.filas):
            k = ease((t - T_FILAS - 0.25 * i) / 0.5)
            if k <= 0: continue
            im.alpha_composite(transparente(f, k), (FILA_X + int(W * (1 - k)), FILA_Y + i * (FILA_H + 30)))
        im = im.convert("RGB"); d = ImageDraw.Draw(im, "RGBA")   # on an RGB image a translucent colour blends; on RGBA it would replace the pixels
        if T_CUENTA <= t < T_REVELA: self.cuenta(d, t - T_CUENTA)
        if t >= T_REVELA: self.revela(d, t - T_REVELA)
        if t >= T_FINAL: pie(d, t - T_FINAL, "¿Acertaste? Cuéntalo en comentarios", self.fuente_txt)
        return im

    def cuenta(self, d, s):
        n = SEG_CUENTA - int(s); frac = 1 - (s % 1)
        cx, cy, r = W // 2, 1790, 82
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(255, 255, 255, 50), width=14)
        d.arc((cx - r, cy - r, cx + r, cy + r), -90, -90 + 360 * frac, fill=ORO, width=14)
        d.text((cx, cy), str(n), font=fuente(int(96 + 24 * (1 - ease((s % 1) / 0.25)))), fill=BLANCO, anchor="mm")
        d.text((cx - 140, cy), "Piensa", font=fuente(44), fill=GRIS, anchor="rm")
        d.text((cx + 140, cy), "y comenta", font=fuente(44), fill=GRIS, anchor="lm")

    def revela(self, d, s):
        k = ease(s / 0.9)
        for i, c in enumerate(self.cards):
            y0 = FILA_Y + i * (FILA_H + 30); x0 = FILA_X
            gana = i == self.gana
            if not gana: d.rounded_rectangle((x0, y0, x0 + FILA_W - 1, y0 + FILA_H - 1), 36, fill=(8, 9, 22, int(110 * k)))
            else: d.rounded_rectangle((x0 - 4, y0 - 4, x0 + FILA_W + 3, y0 + FILA_H + 3), 40, outline=VERDE + (int(255 * k),), width=8)
            color = VERDE if gana else BLANCO
            d.text((x0 + 440, y0 + 80), euros(c["med"] * k), font=fuente(76), fill=color + (int(255 * min(1, k * 2)),), anchor="lm")
            bx0, bx1, by = x0 + 310, x0 + FILA_W - 40, y0 + FILA_H - 62
            d.rounded_rectangle((bx0, by, bx1, by + 22), 11, fill=(255, 255, 255, 30))
            w = (bx1 - bx0) * c["med"] / self.maxp * k
            if w > 22: d.rounded_rectangle((bx0, by, bx0 + w, by + 22), 11, fill=color)
            fuente_c = f"{c['n']} venta{'s' if c['n'] != 1 else ''} reales" if c["n"] else "precio de Collectr"
            d.text((bx0, by - 14), fuente_c, font=fuente(30, bold=False), fill=GRIS + (int(255 * k),), anchor="ls")
            if gana and s > 0.9:
                p = ease((s - 0.9) / 0.35)
                check(d, x0 + FILA_W - 70, y0 + 80, int(36 * p) + 1, VERDE)
                d.text((x0 + FILA_W - 40, by - 14), "LA MÁS CARA", font=fuente(30), fill=VERDE + (int(255 * p),), anchor="rs")

class LaNota(Video):
    """«La nota lo cambia todo»: the same card ungraded, PSA 9 and PSA 10; the bars grow one after the other and the end says how many times it multiplies.
    With a voice, each bar appears when its line starts and the video lasts what the voice needs."""
    def __init__(self, card, escalones, carpeta_voz=None):
        super().__init__()
        self.card, self.esc = card, escalones          # [(label, card-with-med)], cheapest first
        self.cab = cabecera(card["nombre"], "LA NOTA LO CAMBIA TODO", "Misma carta japonesa · valor de mercado")
        self.img = marco(card["img"], (420, 560), 28)
        self.maxp = max(e["med"] for _, e in escalones)
        self.veces = escalones[-1][1]["med"] / escalones[0][1]["med"]
        self.vtxt = f"×{self.veces:.0f}" if self.veces >= 10 else f"×{self.veces:.1f}".replace(".", ",")
        self.fuente_txt = fuente_texto([e for _, e in escalones])
        self.t_bar = [2.0 + 1.6 * i for i in range(len(escalones))]; self.t_mult = self.t_bar[-1] + 2.0; self.t_pie = 10.4; self.DURACION = 13.0
        if carpeta_voz:
            textos = [f"La nota lo cambia todo. {card['nombre'].split(' (')[0]}, versión japonesa."] + \
                     [f"{lab}: {euros(e['med'])}." for lab, e in escalones] + \
                     [f"De sin gradear a {escalones[-1][0]}, multiplica {self.vtxt}.", "¿La gradearías? Cuéntalo en comentarios."]
            m = medir(textos, carpeta_voz); t = 0.4; ini = []
            for i, (_, dur) in enumerate(m):
                t = max(t, 2.0) if i == 1 else t; ini.append(t); t += dur + 0.35
            self.t_bar, self.t_mult, self.t_pie = ini[1:1 + len(escalones)], ini[-2], ini[-1]
            self.pista = voz.Pista([(a, x, True, mm) for a, x, mm in zip(ini, textos, m)], carpeta_voz)
            self.DURACION = self.pista.fin + 1.6

    def frame(self, t):
        im = self.fondo.copy()
        im.alpha_composite(transparente(self.cab, ease(t / 0.6)), (0, int(40 * (1 - ease(t / 0.6)))))
        k = ease((t - 0.4) / 0.7)
        if k > 0: im.alpha_composite(transparente(self.img, k), ((W - 420) // 2, 450 + int(60 * (1 - k))))
        im = im.convert("RGB"); d = ImageDraw.Draw(im, "RGBA")
        y = 1200
        for i, (lab, e) in enumerate(self.esc):
            s = t - self.t_bar[i]
            if s < 0: break
            k = ease(s / 1.0); yy = y + i * 170
            d.text((80, yy), lab, font=fuente(46), fill=BLANCO + (int(255 * min(1, k * 2)),), anchor="lm")
            bx0, bx1 = 360, 1000
            d.rounded_rectangle((bx0, yy - 26, bx1, yy + 26), 26, fill=(255, 255, 255, 25))
            w = max(52, (bx1 - bx0) * e["med"] / self.maxp) * k
            col = VERDE if i == len(self.esc) - 1 else ORO if i else (124, 200, 255)
            if w > 30: d.rounded_rectangle((bx0, yy - 26, bx0 + w, yy + 26), 26, fill=col)
            txt = euros(e["med"] * k)
            d.text((bx0 + 18, yy + 62), txt + ("  ·  " + (f"{e['n']} ventas" if e["n"] else "Collectr")), font=fuente(36), fill=GRIS + (int(255 * k),), anchor="lm")
        s = t - self.t_mult
        if s > 0:
            k = ease(s / 0.6)
            d.text((W // 2, 1095), f"De sin gradear a {self.esc[-1][0]}: {self.vtxt}", font=fuente(int(40 + 14 * k)), fill=ORO + (int(255 * k),), anchor="mm")
        if t >= self.t_pie: pie(d, t - self.t_pie, "¿Lo gradearías? Cuéntalo en comentarios", self.fuente_txt)
        else: self.sub(d, t, 1780)
        return im

class Temas(Video):
    """Slides about a topic (owner, 2 November 2026: "no solo de precios... cartas infravaloradas, bajadas de precio, famosas; no te lo inventes,
    apóyate en los podcasts, los vídeos que vayamos transcribiendo, las comunidades"). The script is a JSON in data/reels/guiones/ written FROM those
    notes: {"grupo", "titulo", "sub", "pie", "fuente", "diapositivas": [{"titulo", "texto", "fuente", "carta"?}]}; "carta" (a Gold Star key) adds its photo."""
    T0, TD, TF = 2.4, 4.2, 3.2
    def __init__(self, g, carpeta_voz=None):
        super().__init__()
        self.g, self.d = g, g["diapositivas"]
        self.cab = cabecera(g.get("grupo", ""), g["titulo"], g.get("sub", ""))
        self.capas = [self.capa(i, x) for i, x in enumerate(self.d)]
        # each slide lasts what its voice needs (a slide's "voz" is read and subtitled; without it, its title and text are read, already on screen)
        self.ini = [self.T0 + self.TD * i for i in range(len(self.d))]; self.t_pie = self.T0 + self.TD * len(self.d)
        if carpeta_voz:
            tit = re.sub(r"^([¿¡]?)(\w)", lambda m: m.group(1) + m.group(2).upper(), g["titulo"].lower())
            textos = [f"{g.get('gancho', '')} {tit}{'' if tit[-1] in '?!.' else '.'}".strip()] +[x.get("voz") or f"{x['titulo']}. {x['texto']}" for x in self.d] + \
                     [g.get("pie", "¿Tú qué opinas? Cuéntalo en comentarios")]
            m = medir(textos, carpeta_voz); ini = [0.5]; t = max(self.T0, 0.5 + m[0][1] + 0.4)
            for _, dur in m[1:-1]: ini.append(t); t += max(self.TD, dur + 1.0)
            ini.append(t); self.ini, self.t_pie = ini[1:-1], t
            subs = [True] + [bool(x.get("voz")) for x in self.d] + [False]
            self.pista = voz.Pista([(a, x, s, mm) for a, x, s, mm in zip(ini, textos, subs, m)], carpeta_voz)
        self.DURACION = self.t_pie + max(self.TF, (self.pista.items[-1]["dur"] + 0.8) if self.pista else 0)

    def capa(self, i, x):
        t = Image.new("RGBA", (FILA_W, 1180), (0, 0, 0, 0)); d = ImageDraw.Draw(t, "RGBA")
        d.rounded_rectangle((0, 0, FILA_W - 1, 1179), 40, fill=(255, 255, 255, 20), outline=(255, 255, 255, 40), width=2)
        d.ellipse((40, 40, 150, 150), fill=ORO); d.text((95, 95), str(i + 1), font=fuente(64), fill=(14, 16, 38), anchor="mm")
        f = fuente(80); y = 200
        for l in lineas(d, x["titulo"], f, 860, 3): d.text((50, y), l, font=f, fill=BLANCO); y += 96
        y += 34; f2 = fuente(56, bold=False)
        for l in lineas(d, x["texto"], f2, 860, 9): d.text((50, y), l, font=f2, fill=(220, 223, 245)); y += 74
        if x.get("carta"):
            c = carta(x["carta"], None) or next((carta(x["carta"], e) for e in sorted(ventas._ediciones(x["carta"])) if carta(x["carta"], e)), None)
            im = foto(c["foto"]) if c else None
            if im: t.alpha_composite(marco(im, (300, 410)), ((FILA_W - 300) // 2, min(y + 30, 1180 - 520)))
        if x.get("fuente"): d.text((50, 1130), x["fuente"], font=ajustar(d, x["fuente"], 32, 860, bold=False), fill=GRIS, anchor="ls")
        return t

    def frame(self, t):
        im = self.fondo.copy()
        k = ease(t / 0.6); intro = t < self.ini[0]
        cab = self.cab if intro else self.cab.crop((0, 0, W, 300))
        im.alpha_composite(transparente(cab, k), (0, int(40 * (1 - k)) + (0 if intro else -40)))
        i = max((j for j, a in enumerate(self.ini) if a <= t), default=-1)    # the last slide stays during the ending
        if i >= 0:
            s = t - self.ini[i]; k = ease(s / 0.45); largo = (self.ini + [self.t_pie])[i + 1] - self.ini[i]
            fuera = 0 if i == len(self.d) - 1 else ease((s - largo + 0.35) / 0.35)
            im.alpha_composite(transparente(self.capas[i], k * (1 - fuera)), (FILA_X + int(W * (1 - k)) - int(W * fuera), 300))
        im = im.convert("RGB"); d = ImageDraw.Draw(im, "RGBA")
        if 0 <= i < len(self.d):
            for j in range(len(self.d)):
                x0 = W // 2 + (j - (len(self.d) - 1) / 2) * 34
                d.ellipse((x0 - 8, 1520, x0 + 8, 1536), fill=ORO if j == i else (255, 255, 255, 60))
        if intro and t > 0.8:
            s = ease((t - 0.8) / 0.5); d.text((W // 2, 900), self.g.get("gancho", ""), font=fuente(56), fill=ORO + (int(255 * s),), anchor="mm")
        if t >= self.t_pie: pie(d, t - self.t_pie, self.g.get("pie", "¿Tú qué opinas? Cuéntalo en comentarios"), self.g.get("fuente", ""))
        else: self.sub(d, t, 1250 if intro else 1640)
        return im

# ---------------------------------------------------------------- run
NOTAS_ESCALERA = [("Sin gradear", "Sin gradear"), ("PSA 9", "PSA 9"), ("PSA 10", "PSA 10")]

def escalera(key, ed):
    """[(label, card)] ungraded -> PSA 9 -> PSA 10 for one card and edition, only the grades with a value (at least 3)."""
    out = [(lab, c) for lab, n in NOTAS_ESCALERA if (c := carta(key, ed, n))]
    return out if len(out) >= 3 and out[0][0] == "Sin gradear" else None

def cifra(n):
    """2162278 -> "2,2 millones de", 45611 -> "45.611" (followed by a noun: "2,2 millones de visualizaciones", "45.611 visualizaciones")."""
    return f"{n / 1e6:.1f} millones de".replace(".", ",") if n >= 1e6 else f"{n:,}".replace(",", ".")

def guion_youtube():
    """A «temas» script made only from the YouTube numbers the app gathers (contenido.view): what is named most in the followed channels in the
    last 30 days, against the 30 before. Only counts and views: what each video says is not known (only its title)."""
    import contenido
    v = contenido.view(); P_ = [x for x in v.get("pokemon") or [] if (x.get("canales") or 0) >= 2][:3]
    crece = max((x for x in v.get("pokemon") or [] if x.get("n", 0) >= 5), key=lambda x: x["n"] - (x.get("antes") or 0), default=None)
    sets = (v.get("sets") or [])[:1]; nc = len([c for c in v.get("canales") or [] if c.get("activo")])
    d = [{"titulo": f"{x['e']}: {x['n']} vídeos", "texto": f"En los últimos 30 días ({x.get('antes', 0)} en los 30 anteriores). Suman {cifra(x['vistas'])} visualizaciones en {x['canales']} canales.",
          "voz": f"{x['e']} sale en {x['n']} vídeos este mes, con {cifra(x['vistas'])} visualizaciones.", "fuente": f"YouTube · {nc} canales seguidos · 30 días"} for x in P_]
    if crece and crece not in P_:
        d.append({"titulo": f"El que más crece: {crece['e']}", "texto": f"De {crece.get('antes', 0)} a {crece['n']} vídeos de un mes a otro.",
                  "voz": f"El que más crece es {crece['e']}: de {crece.get('antes', 0)} a {crece['n']} vídeos.", "fuente": f"YouTube · {nc} canales seguidos · 30 días"})
    for x in sets:
        d.append({"titulo": f"El set del mes: {x['e']}", "texto": f"{x['n']} vídeos en 30 días y {cifra(x['vistas'])} visualizaciones.",
                  "voz": f"Y el set del que más se habla es {x['e']}, con {x['n']} vídeos.", "fuente": f"YouTube · {nc} canales seguidos · 30 días"})
    g = {"grupo": "Lo más hablado en YouTube", "titulo": "¿DE QUÉ SE HABLA?", "sub": f"Los Pokémon y sets más nombrados este mes en {nc} canales",
         "gancho": "Esto es lo que más se mueve", "pie": "¿Cuál falta en la lista?", "fuente": f"Datos de YouTube recogidos por PokéFinder · {fecha_es(v.get('hoy') or dt.date.today().isoformat())}",
         "diapositivas": d}
    save(os.path.join(OUT, "guiones", "youtube.json"), g); return g

def carpeta(base):
    """Where the spoken lines of one video are kept (data/reels/voz/<video>/)."""
    d = os.path.join(OUT, "voz", os.path.basename(base)); os.makedirs(d, exist_ok=True); return d

def main():
    a = argparse.ArgumentParser(description="Reels con los datos de PokéFinder.")
    a.add_argument("--formato", choices=["cual", "notas", "temas"], default="cual")
    a.add_argument("--guion", help="temas: nombre del guion en data/reels/guiones/ (sin .json)")
    a.add_argument("--cartas", help="cual: tres cartas «clave:edición» separadas por comas (ver --lista)")
    a.add_argument("--carta", help="notas: una carta «clave:edición»"); a.add_argument("--nota", default="Sin gradear")
    a.add_argument("--semilla", type=int); a.add_argument("--lista", action="store_true")
    a.add_argument("--voz", action="store_true", help="voz en off y subtítulos (voz.py: Kokoro si está instalado, si no la voz de Windows)")
    o = a.parse_args()
    seed = o.semilla if o.semilla is not None else random.randrange(10 ** 6); rnd = random.Random(seed)
    hoy = dt.date.today().isoformat(); os.makedirs(OUT, exist_ok=True)
    if o.formato == "temas":
        gd = os.path.join(OUT, "guiones")
        if o.lista or not o.guion:
            print("Guiones:", ", ".join(f[:-5] for f in sorted(os.listdir(gd)) if f.endswith(".json")) if os.path.isdir(gd) else "ninguno"); return
        from common import load
        g = guion_youtube() if o.guion == "youtube" else load(os.path.join(gd, o.guion + ".json"), None)
        if not g: sys.exit(f"No existe el guion {o.guion}")
        base = os.path.join(OUT, f"{hoy}-temas-{slug(o.guion)}" + ("-voz" if o.voz else "")); r = Temas(g, carpeta(base) if o.voz else None)
        r.frame(1.8).save(base + ".png"); r.video(base + ".mp4")
        print(f"{base}.mp4\n{g['titulo']}: {len(g['diapositivas'])} diapositivas, {r.DURACION:.0f} s"); return
    if o.formato == "notas":
        esc = {f"{k}:{ed or '-'}": e for k in ventas.cartas() for ed in (sorted(ventas._ediciones(k)) or [None]) if (e := escalera(k, ed))}
        if o.lista:
            for i, e in esc.items(): print(f"  {i:<24} " + " → ".join(f"{lab} {euros(c['med'])}" for lab, c in e))
            return
        if not esc: sys.exit("Ninguna carta tiene valor sin gradear, PSA 9 y PSA 10 de una misma edición.")
        k = o.carta if o.carta in esc else rnd.choice(sorted(esc)); e = esc[k]
        for _, c in e: c["img"] = foto(c["foto"])
        if any(c["img"] is None for _, c in e): sys.exit("No pude descargar la foto.")
        base = os.path.join(OUT, f"{hoy}-la-nota-{slug(e[0][1]['nombre'])}" + ("-voz" if o.voz else "")); r = LaNota(e[0][1], e, carpeta(base) if o.voz else None)
        r.frame(9.5).save(base + ".png"); r.video(base + ".mp4")
        save(base + ".json", {"fecha": hoy, "tipo": "la_nota", "carta": k, "escalones": [{"nota": lab, "eur": c["med"], "ventas": c["n"]} for lab, c in e],
                              "video": os.path.basename(base) + ".mp4", "fuente": r.fuente_txt})
        print(f"{base}.mp4\n{e[0][1]['nombre']}: " + " → ".join(f"{lab} {euros(c['med'])}" for lab, c in e))
        return
    C = candidatas(o.nota)
    if o.lista:
        for i, c in sorted(C.items(), key=lambda x: -x[1]["med"]): print(f"  {euros(c['med']):>12}  {(str(c['n']) + ' ventas') if c['n'] else 'Collectr':>10}  {c['nombre']}   [{i}]")
        return
    if o.cartas:
        keys = [k.strip() for k in o.cartas.split(",")]; falta = [k for k in keys if k not in C]
        if len(keys) != 3 or falta: sys.exit(f"Hacen falta tres cartas con valor; no valen: {', '.join(falta) or o.cartas}")
        cards = [C[k] for k in keys]
    else:
        cards = elegir(C, rnd)
        if not cards: sys.exit("No hay tres cartas con valores bien distintos.")
    for c in cards:
        c["img"] = foto(c["foto"])
        if c["img"] is None: sys.exit(f"No pude descargar la foto de {c['nombre']}.")
    base = os.path.join(OUT, f"{hoy}-cual-vale-mas-{slug(o.nota)}-{seed}" + ("-voz" if o.voz else "")); r = CualValeMas(cards, o.nota, carpeta(base) if o.voz else None)
    r.frame(T_CUENTA + 0.5).save(base + ".png"); r.video(base + ".mp4")
    save(base + ".json", {"fecha": hoy, "tipo": "cual_vale_mas", "nota": o.nota, "semilla": seed, "pregunta": r.pregunta, "respuesta": cards[r.gana]["key"],
                          "video": os.path.basename(base) + ".mp4", "fuente": r.fuente_txt,
                          "cartas": [{k: c[k] for k in ("key", "ed", "nombre", "med", "n", "ref", "foto")} for c in cards]})
    print(f"{base}.mp4\n{r.pregunta}: " + ", ".join(f"{c['nombre']} {euros(c['med'])}" for c in cards) + f" -> {cards[r.gana]['nombre']}")

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
