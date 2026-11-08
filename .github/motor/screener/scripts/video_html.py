"""Vídeos verticales hechos con plantillas HTML/CSS/JS (Fernando, 5 de noviembre de 2026: «cómo hacer vídeos de la mejor manera»).
Cada plantilla (screener/plantillas/*.html) es una página que define window.setTime(t): dibuja el fotograma del segundo t (todo se anima con el tiempo, sin relojes, así que sale idéntico cada vez).
Este módulo abre la plantilla en el Chromium oculto de Playwright (el mismo de los lectores de precios; sin Node ni instalar nada), hace una captura por fotograma a 30 fps y las une con el ffmpeg de imageio.
Así hay libertad total de diseño (gráficas que se dibujan, números que suben, cartas que giran, la marca azul #0B1A33 y amarilla #FFCB3D) y todo sale de datos reales de la base.
Salida en data/reels/<nombre>.mp4 + .png (portada) + .json (el texto del post), como el resto de formatos de estudio.py.
  python video_html.py grail 246723            vídeo «Grail de la semana» de una carta del Tasador (por su número de TCGplayer)
Reglas fijas: solo precios que salen de ventas reales (el precio de mercado semanal de TCGplayer se calcula con ventas) y siempre con su fuente y su fecha en pantalla."""
import datetime as dt, json, os, re, subprocess, sys, tempfile, time
from common import P, load, save, ROOT, TZ

PLANTILLAS = os.path.join(ROOT, "screener", "plantillas"); SALIDA = P("reels")

def _bonito(n):
    """Los nombres que el Tasador sacó de una búsqueda salen en minúsculas («raikou SL9 call of legends»): se capitaliza lo que está todo en minúsculas, sin tocar «SL9», «ex», «VMAX»…"""
    peq = {"of", "the", "de", "and", "ex", "gx", "v"}
    return " ".join(w.capitalize() if (w.islower() and w not in peq and w.isalpha()) else w for w in str(n).split())

def datos_grail(tcg_id, cierre="Precios de cartas con su fecha y su fuente, cada día."):
    """Lo que necesita la plantilla «grail» de una carta con historial de 1 año (referencia.py): nombre, set, imagen, precio de hoy y las 52 semanas."""
    tcg_id = str(tcg_id); h = load(P("referencia", "historial", tcg_id + ".json"), None); r = load(P("referencia", tcg_id + ".json"), {}) or {}
    if not h or not h.get("semanas"): raise ValueError("Esa carta aún no tiene historial de 1 año: el Tasador lo guarda al leer su ficha de TCGplayer")
    carta = next((c for c in (load(P("precios", "cartas.json"), {}) or {}).get("cartas", []) if str(c.get("tcg_id")) == tcg_id), {})
    nombre = (carta.get("nombre") or r.get("nombre") or tcg_id); partes = nombre.split(" · ")
    usd = (load(P("fx.json"), {}) or {}).get("rates", {}).get("USD")
    hoy = dt.datetime.now(TZ).date()
    return {"nombre": _bonito(partes[0]), "set": partes[1] if len(partes) > 1 else carta.get("set") or "", "imagen": carta.get("imagen") or f"https://product-images.tcgplayer.com/fit-in/400x400/{tcg_id}.jpg",
            "precio_usd": (r.get("tcgplayer") or {}).get("mercado") or h["semanas"][-1]["precio_usd"], "semanas": h["semanas"], "eur_por_usd": round(1 / usd, 5) if usd else None,
            "fuente": "TCGplayer", "fecha": f"{hoy.day} {['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'][hoy.month - 1]} {hoy.year}", "duracion": 16, "cierre": cierre}

def renderizar(plantilla, datos, nombre, fps=30, ancho=1080, alto=1920, portada_en=8.0, texto=""):
    """Renderiza plantillas/<plantilla>.html con window.DATA = datos y deja data/reels/<nombre>.mp4 (+ portada .png y .json). Devuelve la ruta del vídeo."""
    from playwright.sync_api import sync_playwright
    import imageio_ffmpeg
    os.makedirs(SALIDA, exist_ok=True); mp4 = os.path.join(SALIDA, nombre + ".mp4"); n = int(datos["duracion"] * fps); t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
        b = p.chromium.launch(headless=True); pg = b.new_context(viewport={"width": ancho, "height": alto}, device_scale_factor=1, locale="es-ES").new_page()
        pg.add_init_script("window.DATA = " + json.dumps(datos, ensure_ascii=False))
        pg.goto("file:///" + os.path.join(PLANTILLAS, plantilla + ".html").replace("\\", "/")); pg.wait_for_timeout(500)
        pg.wait_for_function("(() => { const c = document.getElementById('carta'); return !c || (c.complete && c.naturalWidth > 0); })()", timeout=45000)
        for i in range(n):
            pg.evaluate("(t) => window.setTime(t)", i / fps); pg.screenshot(path=os.path.join(tmp, f"f{i:05d}.jpg"), type="jpeg", quality=92)
            if i % 120 == 0: print(f"  fotograma {i}/{n} ({time.time() - t0:.0f} s)", flush=True)
        pg.evaluate("(t) => window.setTime(t)", portada_en); pg.screenshot(path=os.path.join(SALIDA, nombre + ".png"), type="png"); b.close()
        r = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-framerate", str(fps), "-i", os.path.join(tmp, "f%05d.jpg"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium", "-movflags", "+faststart", mp4],
                           capture_output=True, text=True)
        if r.returncode: raise RuntimeError("ffmpeg falló: " + r.stderr[-300:])
    save(os.path.join(SALIDA, nombre + ".json"), {"texto": texto, "plantilla": plantilla, "creado": dt.datetime.now(TZ).isoformat(timespec="minutes")})
    print(f"listo: {mp4} ({os.path.getsize(mp4) / 1e6:.1f} MB, {time.time() - t0:.0f} s)"); return mp4

def elegir_grail(min_usd=50):
    """La carta con historial de 1 año a la que le toca vídeo: la más cara de las que no han tenido uno en los últimos 30 días (para el vídeo que se hace solo de noche)."""
    import glob
    hechos = {os.path.basename(f) for f in glob.glob(os.path.join(SALIDA, "grail-*.mp4")) if time.time() - os.path.getmtime(f) < 30 * 86400}; cand = []
    for f in glob.glob(P("referencia", "historial", "*.json")):
        pid = os.path.basename(f)[:-5]; r = load(P("referencia", pid + ".json"), {}) or {}; precio = (r.get("tcgplayer") or {}).get("mercado") or 0
        nombre = (r.get("nombre") or "").split(" · ")[0]; slug = re.sub(r"[^a-z0-9]+", "-", nombre.lower()).strip("-")
        if precio >= min_usd and slug and f"grail-{slug}.mp4" not in hechos: cand.append((precio, pid))
    import equipo_video as EV      # el Supervisor de datos descarta las cartas cuyo historial no vale (ceros, saltos, lectura vieja): se elige la más cara de las que SÍ valen
    for precio, pid in sorted(cand, reverse=True):
        try:
            if EV.supervisar_datos(datos_grail(pid), pid)["ok"]: return pid
        except Exception: continue
    return None

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8"); a = sys.argv[1:]
    if a and a[0] == "noche":      # el vídeo de la noche: elige solo una carta y lo hace
        pid = elegir_grail(); print("nada que hacer: todas las cartas con historial ya tienen vídeo reciente" if not pid else "elegida " + pid)
        if pid: a = ["grail", pid]
    if len(a) >= 2 and a[0] == "grail":
        d = datos_grail(a[1]); slug = re.sub(r"[^a-z0-9]+", "-", d["nombre"].lower()).strip("-")
        ps = [s["precio_usd"] for s in d["semanas"]]
        txt = (f"{d['nombre']} ({d['set']}): ${d['precio_usd']:,.0f} hoy en TCGplayer; en 1 año ha ido de ${ps[0]:,.0f} a ${ps[-1]:,.0f}, con un máximo de ${max(ps):,.0f} y un mínimo de ${min(ps):,.0f}. "
               f"Precio de mercado semanal de TCGplayer (según ventas), {d['fecha']}. No es consejo de inversión. #pokemontcg #pokemoncards #pokefinder")
        import equipo_video as EV      # Supervisor de datos → Guionista → Editor → Revisor (equipo_video.py)
        EV.producir(d, txt, f"grail-{slug}", tcg_id=a[1])
    else: print(__doc__)
