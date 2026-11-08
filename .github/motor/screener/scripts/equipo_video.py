"""El equipo de vídeo (Fernando, 6 de noviembre de 2026: «aumentar plantilla en creación de contenido»; ideas del artículo de Eian sobre flujos de vídeo con IA, sin su parte de pago).
Cuatro puestos, todos de código (sin tokens ni dinero), que se pasan el trabajo en este orden y dejan constancia en data/state/contenido_equipo.json y data/reels/<nombre>.equipo.json:
  1. Supervisor de datos  mira los datos ANTES de gastar tiempo en dibujar: ¿hay historial suficiente, sin ceros ni saltos absurdos, y la lectura es reciente? Si no, el vídeo no se hace.
  2. Guionista            escribe el guion (gancho en los 2 primeros segundos, planos con su duración, de dónde sale cada cifra) ANTES de renderizar.
  3. Editor               (video_html.renderizar) dibuja el vídeo.
  4. Revisor de vídeo     lo mira DESPUÉS sin saber cómo se hizo: duración, tamaño, fotogramas negros o congelados, que el texto del post lleve fuente, fecha y aviso, y que el precio del post sea el de los datos.
Si el Supervisor o el Revisor dicen «no pasa», el vídeo queda marcado como rechazado y no se da por bueno. El Revisor solo comprueba lo MEDIBLE: no ve el movimiento ni oye el sonido."""
import datetime as dt, json, os, re, subprocess, sys, time
from common import P, load, save, TZ

ESTADO = P("state", "contenido_equipo.json"); MAX_EDAD_H = 48

def _ahora(): return dt.datetime.now(TZ).isoformat(timespec="minutes")

# ------------------------------------------------------------------------------------------------ 1) Supervisor de datos
def supervisar_datos(datos, tcg_id=None):
    """Devuelve {"ok", "duros": [...], "leves": [...]}: «duros» impiden hacer el vídeo."""
    duros, leves = [], []
    sem = datos.get("semanas") or []; ps = [s.get("precio_usd") for s in sem]
    if len(sem) < 40: duros.append(f"Solo hay {len(sem)} semanas de historial (hacen falta 40 o más)")
    if any((p is None or p <= 0) for p in ps): duros.append(f"El historial tiene {sum(1 for p in ps if p is None or p <= 0)} semana(s) con precio 0 o vacío: la gráfica y el «mínimo» saldrían falsos")
    buenos = [p for p in ps if p and p > 0]
    if len(buenos) >= 2:
        saltos = [(buenos[i + 1] / buenos[i], i) for i in range(len(buenos) - 1)]
        mayor = max(saltos);
        if mayor[0] > 5 or min(saltos)[0] < 0.2: leves.append(f"Salto muy grande entre semanas (×{mayor[0]:.1f}): comprobar que es real")
    hoy = datos.get("precio_usd") or 0
    if buenos and hoy and not (0.5 <= hoy / buenos[-1] <= 2): duros.append(f"El precio de hoy (${hoy:,.0f}) se aleja mucho de la última semana del historial (${buenos[-1]:,.0f})")
    if not datos.get("fuente") or not datos.get("fecha"): duros.append("Falta la fuente o la fecha que sale en pantalla")
    if tcg_id:
        r = load(P("referencia", f"{tcg_id}.json"), {}) or {}
        try:
            h = (dt.datetime.now(TZ) - dt.datetime.fromisoformat(r["leido"])).total_seconds() / 3600
            if h > MAX_EDAD_H: duros.append(f"La lectura del Tasador tiene {h:.0f} h (máximo {MAX_EDAD_H})")
        except Exception: leves.append("No consta la hora de la lectura del Tasador")
        col = (r.get("collectr") or {}).get("sin_gradear"); tcg = (r.get("tcgplayer") or {}).get("mercado")
        if col and tcg and not (0.25 <= col / tcg <= 4): leves.append(f"TCGplayer (${tcg:,.0f}) y Collectr (${col:,.0f}) discrepan mucho: ¿están hablando de la misma edición?")
        elif not col: leves.append("No hay precio de Collectr para contrastar")
    return {"ok": not duros, "duros": duros, "leves": leves}

# ------------------------------------------------------------------------------------------------ 2) Guionista
def guion(datos, duracion=None):
    """El guion antes de dibujar: gancho al principio, planos con su segundo y de dónde sale cada cifra. Pensado para la plantilla «grail» (gráfica de 1 año)."""
    d = duracion or datos.get("duracion", 16); ps = [s["precio_usd"] for s in datos["semanas"] if s.get("precio_usd")]
    cambio = (ps[-1] / ps[0] - 1) * 100 if ps and ps[0] else None
    gancho = f"{datos['nombre']}: ${datos['precio_usd']:,.0f} hoy" + (f" ({cambio:+.0f} % en un año)" if cambio is not None else "")
    planos = [{"de": 0, "a": 2, "que": "Gancho: carta y precio de hoy en grande", "dato": gancho},
              {"de": 2, "a": round(d * 0.65, 1), "que": "La gráfica de 52 semanas se dibuja de izquierda a derecha", "dato": "precio de mercado semanal de TCGplayer (según ventas)"},
              {"de": round(d * 0.65, 1), "a": round(d * 0.88, 1), "que": "Máximo y mínimo del año", "dato": f"máx ${max(ps):,.0f} · mín ${min(ps):,.0f}" if ps else ""},
              {"de": round(d * 0.88, 1), "a": d, "que": "Cierre con la marca y el aviso", "dato": datos.get("cierre", "")}]
    return {"gancho": gancho, "duracion": d, "planos": planos, "fuentes": [f"{datos.get('fuente')} · {datos.get('fecha')}"], "aviso": "No es consejo de inversión"}

# ------------------------------------------------------------------------------------------------ 4) Revisor de vídeo
def _ffmpeg():
    import imageio_ffmpeg; return imageio_ffmpeg.get_ffmpeg_exe()

def revisar_video(mp4, datos=None, texto="", esperado=(1080, 1920), duracion=None):
    """Mira el vídeo ya hecho. Devuelve {"pasa", "duros", "leves", "medido": {...}}. Solo lo medible."""
    duros, leves, med = [], [], {}
    if not os.path.exists(mp4) or os.path.getsize(mp4) < 50_000: return {"pasa": False, "duros": ["El vídeo no existe o está casi vacío"], "leves": [], "medido": {}}
    info = subprocess.run([_ffmpeg(), "-hide_banner", "-i", mp4], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info); seg = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else None
    v = re.search(r"Video: .*?, (\d{2,5})x(\d{2,5})", info); fps = re.search(r"([\d.]+) fps", info)
    med.update(segundos=seg, ancho=int(v[1]) if v else None, alto=int(v[2]) if v else None, fps=float(fps[1]) if fps else None, mb=round(os.path.getsize(mp4) / 1e6, 1), audio="Audio:" in info)
    if v and (int(v[1]), int(v[2])) != tuple(esperado): duros.append(f"Tamaño {v[1]}x{v[2]} en vez de {esperado[0]}x{esperado[1]}")
    if duracion and seg and abs(seg - duracion) > 0.7: duros.append(f"Dura {seg:.1f} s y el guion decía {duracion} s")
    if seg and seg > 60: leves.append(f"Dura {seg:.0f} s (los reels cortos rinden mejor por debajo de 60)")
    r = subprocess.run([_ffmpeg(), "-hide_banner", "-i", mp4, "-vf", "blackdetect=d=0.25:pix_th=0.08,freezedetect=n=0.003:d=5", "-an", "-f", "null", "-"], capture_output=True, text=True).stderr
    negros = re.findall(r"black_start:([\d.]+).*?black_duration:([\d.]+)", r); cong = re.findall(r"freeze_duration: ([\d.]+)", r)
    med.update(negros=len(negros), congelado_s=round(sum(float(x) for x in cong), 1))
    if negros: duros.append("Hay fotogramas negros: " + ", ".join(f"desde {a} s durante {b} s" for a, b in negros[:3]))
    if cong and sum(float(x) for x in cong) > 6: leves.append(f"La imagen está quieta {sum(float(x) for x in cong):.0f} s en total (¿se queda parada demasiado?)")
    if not med["audio"]: leves.append("No lleva pista de audio (hay que ponerle música o sonido al publicarlo)")
    t = texto or ""
    if t:
        if "consejo de inversión" not in t.lower(): duros.append("El texto del post no lleva el aviso «No es consejo de inversión»")
        if not re.search(r"\b\d{1,2} (ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic) 20\d\d\b", t): duros.append("El texto del post no lleva fecha")
        if not re.search(r"TCGplayer|Collectr|PokéWallet|Cardmarket", t): duros.append("El texto del post no dice de qué web sale el precio")
        if datos and datos.get("precio_usd") and f"${datos['precio_usd']:,.0f}" not in t: duros.append("El precio del texto del post no es el de los datos del vídeo")
    return {"pasa": not duros, "duros": duros, "leves": leves, "medido": med}

# ------------------------------------------------------------------------------------------------ el flujo entero
def producir(datos, texto, nombre, tcg_id=None, renderizar=None):
    """Supervisor → Guionista → Editor → Revisor. Devuelve la ficha del equipo; el vídeo solo se da por bueno si ficha['estado'] == 'aprobado'."""
    import video_html as VH
    renderizar = renderizar or VH.renderizar; ficha = {"carta": nombre, "inicio": _ahora(), "estado": "en_marcha"}
    e = load(ESTADO, {}) or {}; e.update(carta=nombre, fecha=dt.datetime.now(TZ).date().isoformat(), estado="supervisando", inicio=_ahora(), beat=time.time()); save(ESTADO, e)
    def paso(estado, **kw): e.update(estado=estado, beat=time.time(), **kw); save(ESTADO, e)
    ficha["supervisor"] = s = supervisar_datos(datos, tcg_id); paso("guion", supervisor=s)
    if not s["ok"]:
        ficha["estado"] = "rechazado_datos"; paso("rechazado_datos", fin=_ahora(), motivo="; ".join(s["duros"])[:300]); save(os.path.join(VH.SALIDA, nombre + ".equipo.json"), ficha); print("SUPERVISOR: no se hace el vídeo →", s["duros"]); return ficha
    ficha["guion"] = g = guion(datos); paso("dibujando", guion=g["gancho"]); save(os.path.join(VH.SALIDA, nombre + ".guion.json"), g)
    mp4 = renderizar("grail", datos, nombre, texto=texto); paso("revisando")
    ficha["revisor"] = rv = revisar_video(mp4, datos, texto, duracion=g["duracion"]); ficha["estado"] = "aprobado" if rv["pasa"] else "rechazado_video"; ficha["fin"] = _ahora()
    paso(ficha["estado"], fin=ficha["fin"], motivo="; ".join(rv["duros"])[:300], leves=(s["leves"] + rv["leves"])[:6])
    save(os.path.join(VH.SALIDA, nombre + ".equipo.json"), ficha); print("REVISOR:", "pasa" if rv["pasa"] else rv["duros"], "| leves:", rv["leves"]); return ficha

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) >= 3 and sys.argv[1] == "revisar":      # python equipo_video.py revisar data/reels/grail-mewtwo.mp4 [3 = tcg id] : revisa un vídeo que ya existe
        import video_html as VH; mp4 = sys.argv[2]; j = load(mp4[:-4] + ".json", {}) or {}
        d = VH.datos_grail(sys.argv[3]) if len(sys.argv) > 3 else None
        print(json.dumps({"datos": supervisar_datos(d, sys.argv[3]) if d else None, "video": revisar_video(mp4, d, j.get("texto", ""), duracion=(d or {}).get("duracion"))}, ensure_ascii=False, indent=1))
    else: print(__doc__)
