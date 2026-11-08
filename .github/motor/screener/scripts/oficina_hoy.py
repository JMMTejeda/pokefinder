"""La vista «Hoy» de la Oficina (owner, 4 November 2026: "entrar en oficina y ver cómo va todo: qué se ha hecho, qué hay programado esta tarde por horas, qué podcasts se han transcrito y resumido
y si no, por qué y cuándo, qué contenido se ha creado, y por qué no me llegan los avisos").
Todo se lee de lo que existe en disco (actividad, ficheros de salida, estados) y de ntfy.sh; no gasta nada. vista() es barata y firma() dice si algo cambió (para el tiempo real, /api/oficina/vivo)."""
import datetime as dt, glob, json, os, re, sys, time, urllib.request
from common import P, ROOT, TZ
import oficina as O
import oficina_procesos as R

# lo programado cada día: (proceso, "HH:MM", qué hace). Los que no tienen hora fija (estados, ventas, transcripciones) salen cuando se hacen.
PLAN = [
    ("ventas", "00:04", "Leer ventas reales (SNKRDUNK y Collectr)"), ("estados", "00:05", "Preguntar a eBay el estado de las cartas"),
    ("youtube", "07:00", "Leer YouTube"), ("comunidades", "07:00", "Leer comunidades y foros"),
    ("t_resumen_comunidades", "09:30", "Claude escribe el resumen de comunidades"),
    ("precios_graduadas", "01:30", "Foto de precios y graduadas (todas las API)"), ("foto_ebay", "10:00", "Foto diaria de eBay"), ("avisos", "10:00", "Resumen diario al móvil"),
    ("salud", "11:00", "Comprobación de salud"), ("salud", "15:00", "Comprobación de salud"), ("salud", "18:00", "Comprobación de salud"),
]
HORAS_CLAUDE = [f"{h}:30" for h in range(10, 24)]      # la tarea «pokefinder-resumen-podcasts»: cada hora a y 30, de 10:30 a 23:30

def _hm(ts): return dt.datetime.fromtimestamp(ts, TZ).strftime("%H:%M")
def _hoy(): return O.hoy()
def _mt(path):
    try: return os.path.getmtime(path)
    except OSError: return 0
def _es_hoy(ts): return bool(ts) and dt.datetime.fromtimestamp(ts, TZ).date().isoformat() == _hoy()
def _min(hm): h, m = hm.split(":"); return int(h) * 60 + int(m)
def _ahora_min():
    n = dt.datetime.now(TZ); return n.hour * 60 + n.minute

def _estados():
    out = {}
    for f in R.PROCESOS: out[f["id"]] = O._estado_de(f)
    return out

# ------------------------------------------------------------------ podcasts: transcrito → resumido
def podcasts_hoy():
    import podcasts as PC
    eps = PC._episodios(); res_dir = P("podcasts", "resumenes"); out = []
    ahora = _ahora_min()
    for e in eps.values():
        t_tr = _mt(e["ruta"]); t_res = _mt(os.path.join(res_dir, e["id"] + ".md"))
        if not (_es_hoy(t_tr) or _es_hoy(t_res)): continue
        d = e["d"]; resumido = PC._resumen_de(e) == "claude"
        r = {"id": e["id"], "titulo": d.get("titulo") or e["id"], "fecha": d.get("fecha"), "min": int((d.get("duracion_s") or 0) // 60),
             "transcrito": _hm(t_tr) if _es_hoy(t_tr) else None, "resumido": _hm(t_res) if resumido and _es_hoy(t_res) else None, "estado": "resumido" if resumido else "pendiente", "yt": d.get("fuente") == "youtube-subtitulos"}
        if not resumido:
            base = _min(r["transcrito"]) if r["transcrito"] else ahora
            sig = next((h for h in HORAS_CLAUDE if _min(h) > max(ahora, base)), None)
            tarde = ahora - base
            r["proxima"] = sig or "mañana 10:30"
            r["por_que"] = "Lo resume la tarea de Claude, que pasa cada hora a y 30 (necesita la app de Claude abierta)."
            r["_tarde"] = tarde
        out.append(r)
    # «atascado» solo si Claude lleva más de hora y media sin dejar NINGÚN resumen; si ha resumido hace poco, es que va por turnos (3 por pasada) y el resto espera la siguiente
    ult = max((_min(r["resumido"]) for r in out if r["resumido"]), default=None)
    for r in out:
        t = r.pop("_tarde", None)
        if t is not None and t > 75 and r["proxima"][0].isdigit():
            if ult is not None and ahora - ult <= 90: r["por_que"] = "Claude resume 3 episodios por pasada y este va en la siguiente: no está atascado, hace cola."
            else: r["estado"] = "retrasado"; r["por_que"] = f"Lleva {t} min sin resumen y Claude no ha dejado ninguno en hora y media. Mira «Programadas» en la app de Claude."
    out.sort(key=lambda r: r["transcrito"] or r["resumido"] or "")
    return out

def cola_podcasts():
    try:
        import podcasts as PC
        v = PC.cola_vista(); job = O._j("data/state/podcast_job.json", {}) or {}
        return {"activa": v["activa"], "ocupado": v["ocupado"], "siguiente": v.get("siguiente"), "pendientes": sum(v["pendientes"]), "yt_pend": v.get("yt_pendientes", 0), "hora_h": v["hora_h"], "dia_h": v["dia_h"], "limite_dia_h": v["limite_dia_h"],
                "titulo_actual": job.get("titulo") if job.get("running") else None}
    except Exception as ex: return {"_error": str(ex)[:100]}

# ------------------------------------------------------------------ contenido creado hoy
def contenido_hoy():
    items = []
    for f in glob.glob(P("reels", "*")):
        if f.lower().endswith((".mp4", ".png")) and _es_hoy(_mt(f)): items.append({"hora": _hm(_mt(f)), "nombre": os.path.basename(f), "tipo": "vídeo" if f.endswith(".mp4") else "imagen"})
    otros = [("YouTube leído", P("contenido", "estado.json")), ("Conclusiones del Dashboard", P("conclusiones", "semana.json")), ("Afirmaciones con fecha", P("expertise", "afirmaciones.json"))]
    for nombre, f in otros:
        if _es_hoy(_mt(f)): items.append({"hora": _hm(_mt(f)), "nombre": nombre, "tipo": "dato"})
    for f in glob.glob(P("comunidades", "resumenes", "*.json")):
        if _es_hoy(_mt(f)): items.append({"hora": _hm(_mt(f)), "nombre": "Resumen de comunidades", "tipo": "resumen"})
    ultimos = sorted(glob.glob(P("reels", "*.mp4")), key=_mt)
    ultimo = os.path.basename(ultimos[-1]) + " · " + dt.datetime.fromtimestamp(_mt(ultimos[-1]), TZ).strftime("%d/%m") if ultimos else None
    return {"items": sorted(items, key=lambda x: x["hora"]), "videos_hoy": sum(1 for i in items if i["tipo"] == "vídeo"), "ultimo_video": ultimo}

# ------------------------------------------------------------------ avisos al móvil: lo que ntfy.sh ha recibido de verdad
def _ntfy_canal(topic):
    msgs = []
    r = urllib.request.urlopen(f"https://ntfy.sh/{topic}/json?poll=1&since=24h", timeout=12).read().decode("utf-8", "replace")
    for l in r.splitlines():
        try: m = json.loads(l)
        except ValueError: continue
        if m.get("event") == "message": msgs.append({"t": dt.datetime.fromtimestamp(m["time"], TZ).isoformat(timespec="seconds"), "titulo": m.get("title") or "", "texto": (m.get("message") or "")[:110]})
    return msgs

CONF = P("state", "avisos_confirmacion.json")      # {canal: {"t": iso, "ok": bool}}: lo que Fernando dice que sonó o no en el móvil (la única forma de saber si llega de verdad)
def confirmaciones():
    try:
        with open(CONF, encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError): return {}

def confirmar(canal, ok):
    if canal not in R.CANALES: raise ValueError("Canal desconocido")
    c = confirmaciones(); c[canal] = {"t": dt.datetime.now(TZ).isoformat(timespec="seconds"), "ok": bool(ok)}
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    with open(CONF, "w", encoding="utf-8") as f: json.dump(c, f)
    return c[canal]

def avisos_hoy():
    cfg = O._j(".secrets/ntfy.json", {}) or {}; canales = []
    for k, (ico, nombre, desc) in R.CANALES.items():
        t = str(cfg.get(k) or "").strip(); c = {"id": k, "icono": ico, "nombre": nombre, "configurado": bool(t), "mensajes": [], "error": None}
        if t:
            v = O._memo("ntfy_" + k, 90, lambda t=t: _ntfy_canal(t))
            if isinstance(v, dict) and v.get("_error"): c["error"] = v["_error"]
            else: c["mensajes"] = v
        c["total"] = len(c["mensajes"]); c["confirmacion"] = confirmaciones().get(k); canales.append(c)
    fallos = []
    try:
        with open(P("state", "avisar.log"), encoding="utf-8") as f: fallos = [l.strip() for l in f.readlines()[-5:] if l.startswith(_hoy())]
    except OSError: pass
    return {"canales": canales, "fallos": fallos, "total": sum(c["total"] for c in canales)}

# ------------------------------------------------------------------ la agenda en vivo (Fernando, 6 nov: «saber en todo momento cómo va: ahora trabajan estos, a las X empieza este, luego este»)
AGENDA_QUIEN = (("resumen de comunidades", "RC"), ("foto diaria", "FO"), ("resumen diario", "CA"), ("resume los podcasts", "RS"), ("salud", "VS"), ("transcribir", "TR"), ("mercado abre", "VR"))
def _orden_hora(t):
    m = re.match(r"^(mañana\s+)?(\d{1,2}):(\d{2})", str(t or ""))
    if m: return (1440 if m.group(1) else 0) + int(m.group(2)) * 60 + int(m.group(3))
    return 1430      # «con cupo», «cuando…»: después de lo de hoy con hora
def _horario(ahora, ag, ec, workers):
    """Quién trabaja AHORA, qué viene LUEGO por horas (turnos, renovaciones de cupo, vídeo de la noche) y quién está SIN PARAR. Todo sale de datos que la Oficina ya tiene."""
    quien = lambda t: next((w for k, w in AGENDA_QUIEN if k in str(t).lower()), None)
    act = [{"w": x["w"], "t": x["t"]} for x in ec.get("now", [])]; en = {x["w"] for x in act}
    luego = [{"time": a["time"], "w": quien(a["what"]), "t": a["what"]} for a in ag]
    if ahora.hour < 9:
        try: camp = O._j("data/state/campanas.json", []) or []; faltan = sum(len(c.get("consultas") or []) - len(c.get("hechas") or {}) for c in camp)
        except Exception: faltan = 0
        luego.append({"time": "09:00", "w": "CH", "t": "eBay renueva su cupo" + (f"; el Buscador retoma la campaña ({faltan} cartas por buscar)" if faltan > 0 else " (5.000 llamadas)")})
    luego.append({"time": f"{(ahora.hour + 1) % 24:02d}:00" if ahora.hour < 23 else "mañana 00:00", "w": "AQ", "t": "El Arquitecto repasa el sistema (cada hora)"})
    luego += [{"time": "mañana 01:00", "w": "TR", "t": "Se renuevan los cupos de Groq, TCGAPI y PPT"}, {"time": "mañana 03:00", "w": "ED", "t": "El Editor hace el vídeo de la noche"}]
    luego.sort(key=lambda x: _orden_hora(x["time"]))
    sin = [w for w, d in workers.items() if d.get("guardia") and w not in en and d.get("state") != "stuck"]
    return {"ahora": act, "lanes": [{"w": x["w"], "t": x["t"]} for x in ec.get("lanes", [])], "luego": luego, "sinparar": sin}

# ------------------------------------------------------------------ el día por horas
def agenda(est, act):
    ahora = _ahora_min(); filas = []; en_plan = {pid for pid, _, _ in PLAN}
    com_hoy = [f for f in glob.glob(P("comunidades", "resumenes", "*.json")) if _es_hoy(_mt(f))]
    avs = O._j("data/state/avisos.json", {}) or {}
    for pid, hm, que in PLAN:
        f = next(x for x in R.PROCESOS if x["id"] == pid); e = est[pid]
        fila = {"hora": hm, "id": pid, "icono": f["icono"], "nombre": que, "grupo": f["grupo"]}
        if e["estado"] == "corriendo": fila.update(estado="ahora", texto=e["mensaje"])
        elif pid == "salud":
            fin_slot = next((h2 for p2, h2, _q in PLAN if p2 == "salud" and h2 > hm), "24:00")
            hechos = [a for a in act if a["proceso"] == "salud" and a["evento"] == "fin" and hm <= a["t"][11:16] < fin_slot]
            if hechos: a = hechos[-1]; fila.update(hora=a["t"][11:16], estado="hecho" if a["ok"] else "fallo", texto=a["texto"].replace("�", "í")[:140])
            elif _min(hm) > ahora: fila.update(estado="previsto", texto="Comprueba que todo se ha actualizado")
            else: fila.update(estado="no_consta", texto="No consta que se haya hecho")
        elif pid == "t_resumen_comunidades":
            if com_hoy: fila.update(hora=_hm(_mt(com_hoy[0])), estado="hecho", texto="Resumen guardado")
            elif _min(hm) > ahora: fila.update(estado="previsto", texto="Tarea de Claude en la app")
            else: fila.update(estado="fallo", texto="No dejó resumen hoy. Suele ser que la tarea se quedó esperando un permiso: ábrela en «Programadas» y pulsa «Ejecutar ahora».")
        elif pid == "avisos":
            if avs.get("resumen") == _hoy(): fila.update(estado="hecho", texto="Enviado al móvil")
            elif _min(hm) > ahora: fila.update(estado="previsto", texto="Resumen de PokéFinder")
            else: fila.update(estado="no_consta", texto="No consta el resumen diario")
        else:
            u = e.get("ultimo")
            if e.get("hoy") and u: fila.update(hora=u[11:16], estado="hecho", texto=e["mensaje"])
            elif pid in ("ventas", "estados") and e["estado"] == "ok": fila.update(hora=(u or "")[11:16] or hm, estado="hecho" if e.get("hoy") else "no_consta", texto=e["mensaje"])
            elif _min(hm) > ahora: fila.update(estado="previsto", texto="Programado")
            else: fila.update(estado="atrasado" if e["estado"] in ("atrasado", "pendiente") else "no_consta", texto=e["mensaje"])
        filas.append(fila)
    # la tarea de podcasts de Claude: la próxima pasada y la última que dejó algo
    res = [t for t in (_mt(f) for f in glob.glob(P("podcasts", "resumenes", "*.md"))) if _es_hoy(t)]
    sig = next((h for h in HORAS_CLAUDE if _min(h) > ahora), None)
    filas.append({"hora": sig or "10:30", "id": "t_resumen_podcasts", "icono": "🧠", "nombre": "Claude resume los podcasts nuevos (cada hora a y 30)", "grupo": "claude", "estado": "previsto",
                  "texto": ("Última vez que dejó un resumen: " + _hm(max(res)) if res else "Hoy todavía no ha dejado ninguno") + (" · si no hay nada nuevo, termina al instante" if sig else " · hoy ya no hay más pasadas"), "manana": not sig})
    # lo que ha pasado y no tiene hora fija (transcripciones, arreglos a mano…)
    vistos = set()
    for a in act:
        if a["proceso"] in en_plan or a["evento"] == "inicio": continue
        if a["texto"] in vistos: continue
        vistos.add(a["texto"])
        filas.append({"hora": a["t"][11:16], "id": a["proceso"], "icono": next((x["icono"] for x in R.PROCESOS if x["id"] == a["proceso"]), "•"), "nombre": a["texto"].replace("�", "í")[:140],
                      "grupo": next((x["grupo"] for x in R.PROCESOS if x["id"] == a["proceso"]), ""), "estado": "hecho" if a["ok"] else "fallo", "texto": ("a mano" if a["evento"] == "manual" else "")})
    # podcasts transcritos hoy que no aparecen en el registro (antes de conectar la Oficina)
    return sorted(filas, key=lambda f: (f.get("manana", False), f["hora"]))

def colgados(act, est):
    """Procesos que apuntaron «inicio» hace más de una hora y nunca «fin», y no están trabajando ahora."""
    ini, fin, out = {}, {}, []
    for a in act:
        (ini if a["evento"] == "inicio" else fin).setdefault(a["proceso"], []).append(a["t"])
    for pid, ts in ini.items():
        ult = max(ts)
        if pid in fin and max(fin[pid]) >= ult: continue
        if est.get(pid, {}).get("hoy") or est.get(pid, {}).get("estado") == "corriendo": continue
        edad = (dt.datetime.now(TZ) - dt.datetime.fromisoformat(ult)).total_seconds() / 60
        if edad > 60: out.append({"id": pid, "texto": f"Empezó a las {ult[11:16]} y no apuntó que terminara."})
    return out

# ------------------------------------------------------------------ la plantilla (turnos por sala) y los carriles de la línea de tiempo
SALAS = [
    ("mercado", "Mercado", [("ventas", "Lector de ventas", "VR", "SNKRDUNK y Collectr"), ("estados", "Consultor de estados", "EB", "Condición que declara el vendedor"), ("foto_ebay", "Fotógrafo de eBay", "FO", "Anuncios del día"), ("precios_graduadas", "Fotógrafo de precios", "GR", "Graduadas de las API")]),
    ("comunidades", "Comunidades", [("youtube", "Lector de YouTube", "YT", "Canales y comentarios"), ("comunidades", "Lector de foros", "FR", "Reddit, PokéBeach, Elite Fourum"), ("t_resumen_comunidades", "Redactor (Claude)", "RC", "Resumen de comunidades")]),
    ("podcasts", "Podcasts y vídeos", [("podcast_cola", "Transcriptor (Groq)", "TR", "Audio a texto"), ("yt_cola", "Transcriptor de YouTube", "TY", "Subtítulos de la página, sin Groq"), ("t_resumen_podcasts", "Resumidor (Claude)", "RS", "Lo esencial, con citas")]),
    ("estudio", "Estudio", [("dashboard", "Analista del Dashboard", "AD", "Conclusiones del día"), ("expertise", "Archivero", "AF", "Afirmaciones con fecha"), ("cronista", "Cronista", "CR", "Escribe el diario y las guías de la app"), ("arquitecto", "Arquitecto", "AQ", "Mapa del sistema y huecos")]),
    ("contenido", "Contenido", [("supervisor_datos", "Supervisor de datos", "SD", "Comprueba los datos antes del vídeo"), ("guionista", "Guionista", "GU", "Escribe el guion del vídeo"), ("reels", "Editor de vídeo", "ED", "Reels de precios"), ("revisor_video", "Revisor de vídeo", "RV", "Mira el vídeo ya hecho")]),
    ("avisos", "Avisos y salud", [("ntfy", "Cartero (ntfy)", "CA", "Avisos al móvil"), ("avisos", "Resumen diario", "RD", "Parte de las 10:00"), ("salud", "Vigilante de salud", "VS", "Rondas 11, 15 y 18 h")]),
    # Los que atienden las búsquedas que pides (Fernando, 5 nov): uno por zona de mercado; trabajan mientras corre una búsqueda y esperan órdenes el resto del tiempo
    ("buscadores", "Búsquedas", [("buscador_jp", "Buscador japonés", "BJ", "Mercari, SNKRDUNK, Rakuma, Yahoo, Card Rush…"), ("buscador_eu", "Buscador europeo", "BE", "Cardmarket, Vinted, Wallapop, Cherry…"),
                                 ("buscador_us", "Buscador americano", "BA", "eBay, Fanatics, Goldin, TCGplayer…"), ("tasador", "Tasador", "TS", "Precios de TCGplayer y Collectr"),
                                 ("cazador", "Buscador de chollos", "CH", "Busca sin parar y avisa de lo que sale bajo mercado")]),
]
CARRILES = [("mercado", "Mercado", "precios, eBay"), ("comunidades", "Comunidades", "YouTube, foros"), ("pod_tr", "Podcasts y vídeos", "transcribir"), ("pod_res", "Podcasts y vídeos", "resumir"),
            ("estudio", "Estudio", "conocimiento"), ("contenido", "Contenido", "vídeos"), ("avisos", "Avisos", "ntfy"), ("salud", "Sistema", "salud")]
CARRIL_DE = {"ventas": "mercado", "estados": "mercado", "foto_ebay": "mercado", "precios_graduadas": "mercado", "youtube": "comunidades", "comunidades": "comunidades", "t_resumen_comunidades": "comunidades", "salud": "salud", "avisos": "avisos"}

def _dec(hm): h, m = hm.split(":")[:2]; return int(h) + int(m) / 60

BUSCADORES = ("BJ", "BE", "BA")      # iniciales de los tres buscadores (japonés, europeo, americano)

def _busquedas_hoy():
    """Las búsquedas de hoy ya terminadas, de la más antigua a la más reciente: [{"time", "what", "res"}] (data/app/jobs)."""
    out = []
    try:
        for f in glob.glob(P("app", "jobs", "*.json")):
            d = json.load(open(f, encoding="utf-8"))
            if d.get("status") == "done" and str(d.get("finished") or "")[:10] == _hoy(): out.append({"time": str(d["finished"])[11:16], "what": str(d.get("label") or d.get("query") or "Búsqueda")[:70], "res": d.get("message") or "Búsqueda terminada"})
    except Exception: pass
    return sorted(out, key=lambda x: x["time"])

def plantilla(ag, pods, cola, ct, av, est):
    por = {}
    for f in ag: por.setdefault(f["id"], []).append(f)
    ahora = _ahora_min(); sal = []
    for sid, nombre, ps in SALAS:
        trab = []
        for pid, puesto, ini, sub in ps:
            t = {"id": pid, "puesto": puesto, "ini": ini, "sub": sub, "estado": "sin_turno", "texto": "Sin turno", "ultimo": None, "proximo": None}
            fs = por.get(pid, [])
            if pid in ("ventas", "estados", "foto_ebay", "precios_graduadas", "youtube", "comunidades", "t_resumen_comunidades", "avisos"):
                f = fs[0] if fs else None
                if f:
                    e = {"hecho": ("hecho", "Turno hecho"), "ahora": ("trabajando", "Trabajando"), "previsto": ("proximo", "Próx. turno " + f["hora"]), "fallo": ("atascado", "Atascado desde " + f["hora"]),
                         "no_consta": ("atascado", "No consta"), "atrasado": ("atascado", "Atrasado")}.get(f["estado"], ("sin_turno", "Sin turno"))
                    t.update(estado=e[0], texto=e[1]); t["ultimo"] = f["hora"] if f["estado"] == "hecho" else None
                    if f["estado"] == "hecho": t["proximo"] = "mañana " + next(h for p, h, _q in PLAN if p == pid)
                    if f["estado"] in ("hecho", "ahora"): t["sub"] = (f["texto"] or sub)[:52]
                    if f["estado"] == "fallo": t["sub"] = "Espera un permiso: Programadas › Ejecutar ahora" if pid.startswith("t_") else (f["texto"] or sub)[:60]
            elif pid == "podcast_cola":
                lim = cola.get("dia_h") is not None and cola["dia_h"] >= cola.get("limite_dia_h", 99) - 0.3
                if cola.get("ocupado"): t.update(estado="trabajando", texto="Trabajando", sub=(cola.get("titulo_actual") or sub)[:52])
                elif lim and cola.get("pendientes"): t.update(estado="sin_cupo", texto="Sin cupo", sub=f"Límite diario de Groq: {cola['pendientes']} en cola")
                else: t.update(estado="esperando", texto="Esperando", sub=f"{cola.get('pendientes', 0)} en cola · {cola.get('yt_pend', 0)} de YouTube")
                tr = [p for p in pods if p["transcrito"] and not p.get("yt")]
                if tr: t["ultimo"] = tr[-1]["transcrito"]; t["sub"] += f" · {len(tr)} hoy"
            elif pid == "yt_cola":      # el carril de YouTube: lee la transcripción que enseña la página del vídeo (navegador oculto), un vídeo cada pocos minutos; no gasta Groq ni baja audio
                y_ = O._j("data/state/yt_job.json", {}) or {}; ty = [p for p in pods if p["transcrito"] and p.get("yt")]
                reciente = bool(y_.get("fin")) and (_ahora_min() - _min(str(y_["fin"])[11:16])) <= 25
                if y_.get("running") and time.time() - y_.get("beat", 0) < 600 or reciente: t.update(estado="trabajando", texto="Trabajando", sub=f"{len(ty)} vídeos hoy · {cola.get('yt_pend', 0)} esperando")
                else: t.update(estado="esperando", texto="Esperando", sub=f"{len(ty)} vídeos hoy · {cola.get('yt_pend', 0)} esperando")
                if ty: t["ultimo"] = ty[-1]["transcrito"]
            elif pid == "t_resumen_podcasts":
                pend = [p for p in pods if p["estado"] != "resumido"]; sig = next((h for h in HORAS_CLAUDE if _min(h) > ahora), None)
                res = [p for p in pods if p["resumido"]]
                t.update(estado="retrasado" if any(p["estado"] == "retrasado" for p in pods) else ("proximo" if sig else "sin_turno"), texto=("Próx. turno " + sig) if sig else "Sin más turnos hoy",
                         sub=f"{len(res)} resúmenes hoy" + (f" · falta {len(pend)}" if pend else ""))
                rz = _resumiendo(("podcasts", "resumenes"), "*.md")
                if rz: t.update(estado="trabajando", texto="Resumiendo", sub=f"{rz} · {len(res)} hoy"[:60])      # está en su turno de la hora: va dejando resúmenes
                t["ultimo"] = res[-1]["resumido"] if res else None
                if pend: t["estado"] = "esperando" if t["estado"] != "retrasado" else "atascado"
            elif pid in ("dashboard", "expertise"):
                f = P("conclusiones", "semana.json") if pid == "dashboard" else P("expertise", "afirmaciones.json"); m = _mt(f)
                if _es_hoy(m): t.update(estado="hecho", texto="Turno hecho", ultimo=_hm(m), proximo="mañana"); t["sub"] = sub + " · " + _hm(m)
                else: t.update(estado="esperando", texto="Sin novedades hoy")
            elif pid in ("supervisor_datos", "guionista", "revisor_video"):      # el equipo de vídeo (equipo_video.py): cada noche a las 03:00 pasan el trabajo de uno a otro
                ce = O._j("data/state/contenido_equipo.json", {}) or {}; hoy_ce = ce.get("fecha") == _hoy(); es = ce.get("estado") if hoy_ce else None; vivo_ce = time.time() - ce.get("beat", 0) < 900
                fases = {"supervisor_datos": ("supervisando",), "guionista": ("guion", "dibujando"), "revisor_video": ("revisando",)}[pid]      # (no se llama «trab»: ese nombre es la lista de la sala)
                if es in fases and vivo_ce: t.update(estado="trabajando", texto={"supervisor_datos": "Mirando los datos", "guionista": "Escribiendo el guion", "revisor_video": "Revisando el vídeo"}[pid], sub=str(ce.get("carta") or "")[:60])
                elif es and pid == "supervisor_datos": t.update(estado="hecho", texto="Rechazó los datos" if es == "rechazado_datos" else "Datos buenos", sub=str(ce.get("carta") or "")[:60], ultimo=str(ce.get("inicio") or "")[11:16], proximo="mañana 03:00")
                elif es in ("dibujando", "revisando", "aprobado", "rechazado_video") and pid == "guionista": t.update(estado="hecho", texto="Guion escrito", sub=str(ce.get("guion") or "")[:60], ultimo=str(ce.get("inicio") or "")[11:16], proximo="mañana 03:00")
                elif es in ("aprobado", "rechazado_video") and pid == "revisor_video": t.update(estado="hecho" if es == "aprobado" else "atascado", texto="Aprobó el vídeo" if es == "aprobado" else "Rechazó el vídeo", sub=str(ce.get("motivo") or ce.get("carta") or "")[:60], ultimo=str(ce.get("fin") or "")[11:16], proximo="mañana 03:00")
                else: t.update(estado="proximo", texto="Próx. 03:00", sub="Con el vídeo de la noche" if not es else ("No hizo falta: " + str(es)[:40]))
            elif pid == "reels":
                if ct["videos_hoy"]: t.update(estado="hecho", texto=f"{ct['videos_hoy']} vídeo(s) hoy")
                else: t.update(estado="sin_turno", texto="Sin turno", sub=f"{ct['videos_hoy']} vídeos hoy · último {ct['ultimo_video'].split(' · ')[-1] if ct['ultimo_video'] else '—'}")
            elif pid == "ntfy":
                conf = [c["confirmacion"] for c in av["canales"] if c.get("confirmacion")]; malos = [c for c in av["canales"] if c.get("confirmacion") and not c["confirmacion"]["ok"]]
                t.update(estado="atascado" if malos else "hecho", texto="No llegan" if malos else "Funcionando",      # Fernando (5 nov): ntfy funciona; solo se marca si él dice que no llega
                         sub=f"{av['total']} enviados · {sum(1 for c in conf if c['ok'])} confirmados")
            elif pid.startswith("buscador_"):
                hoy_b = _busquedas_hoy()
                t.update(estado="esperando", texto="Esperando órdenes", proximo="Cuando llegue una búsqueda", sub=f"{len(hoy_b)} búsquedas hoy" if hoy_b else sub)
                if hoy_b: t["ultimo"] = hoy_b[-1]["time"]
            elif pid == "cronista":      # el que escribe sin parar: una entrada del diario por commit, la guía de la app y las novedades (cronista.py)
                cr_ = O._j("data/state/cronista.json", {}) or {}
                t.update(estado="trabajando", texto="Escribiendo", sub=f"{cr_.get('hojas', 0)} hojas · {cr_.get('entradas', 0)} commits escritos"[:60])
                if cr_.get("ultima_t"): t["ultimo"] = str(cr_["ultima_t"])[11:16]
            elif pid == "arquitecto":      # el que mira el sistema entero cada hora (arquitecto.py): cuántas piezas y cuántos huecos ha encontrado
                aq_ = O._j("data/state/arquitecto.json", {}) or {}
                t.update(estado="trabajando", texto="Vigilando el sistema", sub=f"{aq_.get('modulos', 0)} piezas · {aq_.get('huecos', 0)} huecos"[:60])
                if aq_.get("ultima"): t["ultimo"] = str(aq_["ultima"])[11:16]
            elif pid == "cazador":      # el que no deja de buscar y avisa de los chollos (caza.py + avisos.py)
                c = O._j("data/state/caza.json", {}) or {}; av_ = O._j("data/state/avisos.json", {}) or {}; hoy_c = [x for x in (av_.get("refs_hoy") or []) if x.get("d") == _hoy()]
                if c.get("activa") is False: t.update(estado="sin_turno", texto="Apagado", sub="No lanza búsquedas solo: «Lanzar ahora» lo enciende")
                else: t.update(estado="trabajando", texto="Trabajando", sub=((("Cazando " + str(c["actual"])) if c.get("actual") else (str(c.get("motivo") or "Al acecho"))) + f" · {len(hoy_c)} avisos hoy")[:60])
                if c.get("ultimo"): t["ultimo"] = time.strftime("%H:%M", time.localtime(c["ultimo"]))
            elif pid == "tasador":      # la base de precios: una carta cada 40-90 s (referencia.py --servicio); se para si una web pide verificación y descansa en el tope del día
                r = O._j("data/state/referencia.json", {}) or {}; vivo = time.time() - r.get("beat", 0) < 600; pausa = bool(r.get("pausa_hasta")) and time.time() < r["pausa_hasta"]
                try: import referencia as RF; hoy_n = len(RF.lecturas_de_hoy(999))
                except Exception: hoy_n = 0
                sub_ts = f"{hoy_n} cartas hoy" + (f" · {r['cola']} en cola" if r.get("cola") else "")
                pw = O._j("data/state/pokewallet.json", {}) or {}      # el carril de PokéWallet (1.000 al día; el tope propio es 800 y se reinicia a las 00:00)
                if pw.get("dia") == time.strftime("%Y-%m-%d"): sub_ts += f" · PokéWallet {pw.get('hoy', 0)}/800" + (" (tope)" if pw.get("motivo") == "tope del día" else "")
                vivo = time.time() - r.get("beat", 0) < 120
                if not vivo: t.update(estado="sin_turno", texto="Parado", sub="El servicio de precios no late: se relanza solo")
                elif r.get("desbloqueando"): t.update(estado="atascado", texto="Esperando tu verificación", sub="Hay una ventana abierta: verifica y ciérrala")
                elif r.get("bloqueo"): t.update(estado="atascado", texto="Bloqueado", sub=f"{r['bloqueo'].get('web')} pidió verificación a las {str(r['bloqueo'].get('desde'))[11:16]}")
                elif pausa: t.update(estado="sin_cupo", texto="Pausado", sub=str(r.get("motivo") or "Una web pidió verificación")[:60])
                elif r.get("motivo") == "tope del día": t.update(estado="sin_cupo", texto="Tope del día", sub=sub_ts)
                else: t.update(estado="trabajando", texto="Trabajando", sub=(("Tasando " + str(r["actual"])) if r.get("actual") else sub_ts)[:60])      # el servicio no para en todo el día: el Tasador está siempre en su mesa
                if r.get("ultima_t"): t["ultimo"] = str(r["ultima_t"])[11:16]
            elif pid == "salud":
                f = next((x for x in fs if x["estado"] == "previsto"), None); hechos = [x for x in fs if x["estado"] in ("hecho", "fallo")]
                t.update(estado="proximo" if f else "hecho", texto=("Próx. ronda " + f["hora"]) if f else "Rondas hechas", sub=f"{len(hechos)} rondas, " + ("todo al día" if all(x["estado"] == "hecho" for x in hechos) else "con fallos"))
                if hechos: t["ultimo"] = hechos[-1]["hora"]
            trab.append(t)
        peor = next((e for e in ("atascado", "retrasado", "sin_cupo", "esperando", "trabajando", "proximo", "hecho") if any(x["estado"] == e for x in trab)), "sin_turno")
        sal.append({"id": sid, "nombre": nombre, "peor": peor, "trabajadores": trab})
    return sal

def carriles(ag, pods, av):
    ev = []; ahora = _ahora_min()
    for f in ag:
        c = CARRIL_DE.get(f["id"])
        if c: ev.append({"c": c, "h": _dec(f["hora"]), "e": {"hecho": "hecho", "ahora": "ahora", "previsto": "previsto"}.get(f["estado"], "fallo"), "t": f["nombre"] + (" · " + f["texto"][:60] if f["texto"] else "")})
    for p in pods:
        if p["transcrito"]: ev.append({"c": "pod_tr", "h": _dec(p["transcrito"]), "e": "hecho", "t": "Transcrito: " + p["titulo"][:60]})
        if p["resumido"]: ev.append({"c": "pod_res", "h": _dec(p["resumido"]), "e": "hecho", "t": "Resumido: " + p["titulo"][:60]})
    for h in HORAS_CLAUDE:
        if _min(h) > ahora: ev.append({"c": "pod_res", "h": _dec(h), "e": "previsto", "t": "Pasada de Claude (si hay algo nuevo)"})
    for nombre, f, c in (("Conclusiones del Dashboard", P("conclusiones", "semana.json"), "estudio"), ("Afirmaciones con fecha", P("expertise", "afirmaciones.json"), "estudio")):
        if _es_hoy(_mt(f)): ev.append({"c": c, "h": _dec(_hm(_mt(f))), "e": "hecho", "t": nombre})
    for f in glob.glob(P("reels", "*.mp4")):
        if _es_hoy(_mt(f)): ev.append({"c": "contenido", "h": _dec(_hm(_mt(f))), "e": "hecho", "t": "Vídeo: " + os.path.basename(f)})
    for c in av["canales"]:
        conf = c.get("confirmacion")
        for m in c["mensajes"]:
            if m["t"][:10] != _hoy(): continue
            ok = bool(conf and conf["ok"] and conf["t"] >= m["t"]); mal = bool(conf and not conf["ok"] and conf["t"] >= m["t"])
            ev.append({"c": "avisos", "h": _dec(m["t"][11:16]), "e": "confirmado" if ok else ("perdido" if mal else "sin_confirmar"), "t": f"{c['nombre']}: {(m['titulo'] + ' · ' if m['titulo'] else '')}{m['texto'][:60]}"})
    return {"carriles": [{"id": i, "nombre": n, "sub": s} for i, n, s in CARRILES], "eventos": sorted(ev, key=lambda x: x["h"])}

def queda_hoy(ag, cola):
    out = [{"hora": f["hora"], "titulo": f["nombre"], "sub": f["texto"]} for f in ag if f["estado"] == "previsto" and not f.get("manana")][:8]
    if cola.get("pendientes") and cola.get("dia_h") is not None and cola["dia_h"] >= cola.get("limite_dia_h", 99) - 0.3:
        out.append({"hora": "con cupo", "titulo": "Transcribir el siguiente episodio", "sub": f"Parado por el límite diario de Groq · {cola['pendientes']} en cola"})
    out.append({"hora": "mañana 00:04", "titulo": "Mercado abre el día", "sub": "Ventas reales y estado en eBay"})
    return out

def vista():
    est = _estados(); act = [a for a in O.actividad(400) if a["t"][:10] == _hoy()]
    act_asc = sorted(act, key=lambda a: a["t"])
    ag = agenda(est, act_asc); pods = podcasts_hoy(); av = avisos_hoy(); ct = contenido_hoy()
    problemas = []
    for f in ag:
        if f["estado"] in ("fallo", "no_consta", "atrasado"): problemas.append({"quien": f["nombre"], "texto": f["texto"], "hora": f["hora"]})
    for p in pods:
        if p["estado"] == "retrasado": problemas.append({"quien": "Resumen: " + p["titulo"][:60], "texto": p["por_que"], "hora": p["transcrito"] or ""})
    for c in colgados(act_asc, est): problemas.append({"quien": next((x["nombre"] for x in R.PROCESOS if x["id"] == c["id"]), c["id"]), "texto": c["texto"], "hora": ""})
    if av["fallos"]: problemas.append({"quien": "Avisos al móvil", "texto": f"{len(av['fallos'])} aviso(s) no salieron: {av['fallos'][-1][20:90]}", "hora": ""})
    ahora = [{"id": p["id"], "nombre": p["nombre"], "icono": p["icono"], "texto": p["mensaje"]} for g in O.vista()["grupos"] for p in g["procesos"] if p["estado"] == "corriendo"]
    cola = cola_podcasts(); conf = [c["confirmacion"] for c in av["canales"] if c.get("confirmacion")]
    sala = plantilla(ag, pods, cola, ct, av, est)
    if any(not c["ok"] for c in conf): problemas.append({"quien": "Avisos ntfy", "texto": "Dijiste que no te llegan al móvil: mira la lista de «Qué revisar en el móvil».", "hora": "", "accion": "avisos"})
    return {"ahora_iso": dt.datetime.now(TZ).isoformat(timespec="seconds"), "dia": _hoy(), "agenda": ag, "podcasts": pods, "cola": cola, "contenido": ct, "avisos": av,
            "plantilla": sala, "linea": carriles(ag, pods, av), "queda": queda_hoy(ag, cola),
            "problemas": problemas, "ahora": ahora, "veredicto": "ok" if not problemas else "atencion",
            "resumen_dia": {"hechas": sum(1 for f in ag if f["estado"] == "hecho"), "previstas": sum(1 for f in ag if f["estado"] == "previsto"), "fallos": len(problemas),
                            "podcasts_transcritos": sum(1 for p in pods if p["transcrito"]), "podcasts_resumidos": sum(1 for p in pods if p["resumido"]), "avisos": av["total"], "confirmados": sum(1 for c in conf if c["ok"])}}

# ------------------------------------------------------------------ el contrato de la página «Oficina» en estilo plano (OFICINA-GUIA-ESTILOS.md, sección 6)
ROLES = {"VR": ("Lee las ventas reales de SNKRDUNK y Collectr", "Cada día, de madrugada"), "EB": ("Pregunta a eBay el estado que declara cada vendedor", "Cada día, de madrugada · tope 1.500 al día"),
         "FO": ("Hace la foto diaria del mercado en eBay", "Cada día desde las 10:00"), "YT": ("Lee los vídeos nuevos de los canales que sigues", "Cada día desde las 07:00"),
         "FR": ("Lee comunidades y foros", "Cada día desde las 07:00"), "RC": ("Escribe el resumen de comunidades con lo que se lee en foros y Reddit", "Cada día a las 09:30 · tarea de Claude"),
         "TR": ("Pasa a texto los episodios de la cola con Groq", "Mientras haya cupo de Groq (7,2 h al día)"), "RS": ("Resume cada episodio transcrito y saca afirmaciones con fecha", "Cada hora a y 30 · necesita la app de Claude abierta"),
         "AD": ("Saca las conclusiones del día del Dashboard", "Con el resumen de la mañana"), "AF": ("Guarda las afirmaciones con fecha de los podcasts", "Junto al Resumidor"),
         "ED": ("Crea los vídeos: los reels de siempre (reels.py) y los de precios con plantillas HTML (video_html.py), con la gráfica de 1 año de TCGplayer", "Cuando lo pides; de momento a mano"), "CA": ("Envía los avisos a tus 3 temas de ntfy", "Cuando otro trabajador avisa"),
         "RD": ("Manda al móvil el resumen del día", "Cada día a las 10:00"), "VS": ("Comprueba que todo se haya actualizado", "Rondas a las 11, 15 y 18"),
         "BJ": ("Busca tus cartas en los mercados japoneses (Mercari, SNKRDUNK, Rakuma, Yahoo!, PayPay, Rakuten, Card Rush, Magi, Hareruya2…)", "Cuando pides una búsqueda"),
         "BE": ("Busca tus cartas en los mercados europeos (Cardmarket, Vinted, Wallapop, Cherry, Clabo, JapanTCG, Jauce, Mandarake…)", "Cuando pides una búsqueda"),
         "BA": ("Busca tus cartas en los mercados americanos (eBay, Fanatics, Goldin, ALT, GempireCards) y mira el precio de referencia (TCGplayer, Collectr)", "Cuando pides una búsqueda"),
         "TY": ("Pasa a texto los vídeos de los canales de YouTube que sigues leyendo la transcripción que enseña la página del vídeo (sin Groq ni bajar audio), el más reciente primero", "Sin parar: un vídeo cada pocos minutos"),
         "SD": ("Antes de hacer un vídeo comprueba los datos: que el historial no tenga ceros ni saltos absurdos, que la lectura sea de menos de 48 h y que TCGplayer y Collectr no se contradigan. Si no valen, el vídeo no se hace y se elige otra carta", "Cada noche a las 03:00, antes del Editor"),
         "GU": ("Escribe el guion antes de dibujar: el gancho de los 2 primeros segundos, los planos con su duración y de dónde sale cada cifra (data/reels/<vídeo>.guion.json)", "Cada noche a las 03:00, tras el Supervisor"),
         "RV": ("Mira el vídeo ya hecho sin saber cómo se hizo: duración, tamaño, fotogramas negros o congelados, y que el texto del post lleve fuente, fecha, aviso y el mismo precio que los datos. No ve el movimiento ni oye el sonido", "Cada noche, justo al acabar el vídeo"),
         "AQ": ("Mira el sistema entero cada hora: quién escribe y quién lee cada dato, qué piezas no se hablan, servicios parados o con cola larga y cupos que se pierden. Deja el mapa y los huecos en data/arquitecto/. No gasta tokens", "Sin parar: repasa el sistema cada hora"),
         "CR": ("Escribe a máquina, sin parar, todo lo que pasa en la app: el diario de cada commit, la guía de cómo funciona cada pieza y las novedades para Jesús (data/cronista/). No gasta tokens", "Sin parar: mira si hay commits nuevos cada 5 minutos"),
         "CH": ("Lanza búsquedas rápidas de las cartas con precio de referencia (grails primero) cuando el motor está libre, repite las tuyas cada 3 días, y avisa al móvil de lo que sale bajo mercado o bajo la referencia", "Sin parar; tus búsquedas van primero"),
         "TS": ("Va llenando la base de precios: lee TCGplayer y Collectr, una carta cada 40-90 s, y apunta cada lectura con su fecha (grails primero)", "Siempre, con tope diario y pausa si una web pide verificación"),
         "GR": ("Pide a las API de precios las ventas de eBay por nota y el precio de cada carta", "Cada día desde la 01:00 · reintenta cada 20 min")}
GUARDIA = {"CA", "TR", "TY", "BJ", "BE", "BA", "TS", "CH", "CR", "AQ"}      # los que no se van a casa nunca: el Cartero espera avisos a cualquier hora y el Transcriptor trabaja siempre que haya cupo; el resto se va cuando le queda mucho para su próximo turno (la Oficina viva)
LANZABLES = {"VR", "EB", "FO", "YT", "FR", "TR", "GR", "TS", "CH"}      # los que la Oficina puede lanzar (oficina.ACCIONES); los de Claude se lanzan desde «Programadas» en la app de Claude
ESTADO_W = {"hecho": "done", "trabajando": "wait", "esperando": "wait", "sin_cupo": "wait", "proximo": "wait", "atascado": "stuck", "retrasado": "stuck", "sin_turno": "off"}
S_TAREA = {"hecho": "ok", "ahora": "wait", "previsto": "plan", "fallo": "fail", "no_consta": "fail", "atrasado": "fail"}
S_MARCA = {"hecho": "ok", "ahora": "wait", "previsto": "plan", "fallo": "fail", "confirmado": "ok", "sin_confirmar": "wait", "perdido": "fail"}
NTFY_CHECKS = ["Suscrito a los 3 temas con el nombre exacto y en el mismo servidor que usa PokéFinder.", "Android: «Entrega instantánea» activada en cada tema.",
               "Batería de ntfy sin restricciones (y con inicio automático en Xiaomi, Huawei o Samsung).", "«No molestar» desactivado para ntfy; los avisos con prioridad 1–2 no suenan.",
               "iPhone con servidor propio: necesita upstream-base-url."]

def _ord(h): return 9999 if not h or not re.match(r"^\d{1,2}:\d{2}", str(h)) else _min(str(h)[:5])      # «0-2 s» (los planos del Guionista) no es una hora

def _resumiendo(carpeta, patron, minutos=6):
    """El último resumen guardado en los últimos `minutos`: la señal de que la rutina de Claude (que vive en la app, no en este programa) está trabajando AHORA. La Oficina no ve su sesión; ve lo que va dejando
    (Fernando, 6 nov: «me llegan resúmenes sin parar y en la Oficina no está trabajando»). Devuelve el título aproximado o None."""
    import glob
    try: fs = [(os.path.getmtime(f), f) for f in glob.glob(P(*carpeta, patron))]
    except OSError: return None
    if not fs: return None
    t, f = max(fs)
    return re.sub(r"^\d{4}-\d{2}-\d{2}-?", "", os.path.splitext(os.path.basename(f))[0]).replace("-", " ").strip() or "un resumen" if time.time() - t < minutos * 60 else None

def en_curso(v):
    """Lo que está trabajando AHORA y lo que está pedido y esperando: transcripciones (Groq y YouTube), procesos de lectura, búsquedas del motor y los resúmenes que Fernando ha pedido desde la página."""
    now, pend = [], []
    j = O._j("data/state/podcast_job.json", {}) or {}
    if j.get("running") and time.time() - j.get("beat", 0) < 1800: now.append({"w": "TR", "t": "Transcribiendo con Groq: " + str(j.get("titulo") or "")[:80]})
    y = O._j("data/state/yt_job.json", {}) or {}
    if y.get("running") and time.time() - y.get("beat", 0) < 600: now.append({"w": "TY", "t": "Leyendo los subtítulos de un vídeo de YouTube (" + str(y.get("podcast") or "")[:30] + "): " + str(y.get("titulo") or "")[:70]})
    ini = {pid: iniciales for _s, _n, ps in SALAS for pid, _p, iniciales, _sub in ps}      # proceso -> iniciales del trabajador (para abrir su ficha)
    for a in v.get("ahora") or []: now.append({"w": ini.get(a["id"], ""), "t": f"{a['nombre']}: {str(a['texto'])[:90]}"})
    try:
        import glob
        for f in glob.glob(P("app", "jobs", "*.json")):
            d = json.load(open(f, encoding="utf-8"))
            if d.get("status") in ("running", "ebay"):      # mientras corre una búsqueda, los tres buscadores trabajan en ella (cada uno en su zona de mercados)
                what = str(d.get("label") or d.get("query") or d.get("search_id") or f)[:70]; prog = f" ({d.get('progress')} %)" if d.get("progress") is not None else ""
                for w, zona in (("BJ", "mercados japoneses"), ("BE", "mercados europeos"), ("BA", "mercados americanos")): now.append({"w": w, "t": f"Buscando «{what}» en los {zona}{prog} · {str(d.get('message') or '')[:50]}"})
    except Exception: pass
    cr = O._j("data/state/cronista.json", {}) or {}
    if time.time() - cr.get("beat", 0) < 900: now.append({"w": "CR", "t": "Escribiendo: " + str(cr.get("ultima") or "el diario de la app")[:80] + f" ({cr.get('hojas', 0)} hojas)"})
    rz = _resumiendo(("podcasts", "resumenes"), "*.md")
    if rz: now.append({"w": "RS", "t": "Resumiendo con Claude: " + rz[:80]})
    rc = _resumiendo(("comunidades", "resumenes"), "*.json")
    if rc: now.append({"w": "RC", "t": "Escribiendo el resumen de comunidades"})
    ce = O._j("data/state/contenido_equipo.json", {}) or {}
    if time.time() - ce.get("beat", 0) < 900 and ce.get("estado") in ("supervisando", "guion", "dibujando", "revisando"):
        w_ = {"supervisando": "SD", "guion": "GU", "dibujando": "ED", "revisando": "RV"}[ce["estado"]]
        if w_ != "ED": now.append({"w": w_, "t": {"SD": "Comprobando los datos de ", "GU": "Escribiendo el guion de ", "RV": "Revisando el vídeo de "}[w_] + str(ce.get("carta"))[:50]})
    aq = O._j("data/state/arquitecto.json", {}) or {}
    if time.time() - aq.get("beat", 0) < 7200: now.append({"w": "AQ", "t": f"Revisando cómo se hablan las piezas: {aq.get('huecos', 0)} huecos apuntados"})
    vn = O._j("data/state/video_noche.json", {}) or {}
    if vn.get("running") and time.time() - vn.get("beat", 0) < 900: now.append({"w": "ED", "t": f"Montando el vídeo de la noche (desde las {vn.get('inicio', '03:00')}): gráfica de 1 año de la carta más cara sin vídeo"})
    cz = O._j("data/state/caza.json", {}) or {}
    if cz.get("activa") is not False: now.append({"w": "CH", "t": ("Cazando: " + str(cz["actual"])[:70] + " (búsqueda rápida)") if cz.get("actual") else ("Al acecho: " + str(cz.get("motivo") or "revisando lo que llega")[:70])})
    rf = O._j("data/state/referencia.json", {}) or {}
    if time.time() - rf.get("beat", 0) < 600 and not (rf.get("pausa_hasta") and time.time() < rf["pausa_hasta"]) and rf.get("motivo") != "tope del día":
        now.append({"w": "TS", "t": ("Tasando: " + str(rf["actual"])[:70] + " (TCGplayer y Collectr)") if rf.get("actual") else ("Tasador al pie: última «" + str(rf.get("ultima") or "—")[:50] + "» · " + str(rf.get("cola") or 0) + " cartas en cola")})
    sig = next((h for h in HORAS_CLAUDE if _min(h) > _ahora_min()), None)
    try: import podcasts as PC; eps = PC._episodios(); ped = PC.pedidos()
    except Exception: ped, eps = {}, {}
    for eid, d in sorted(ped.items(), key=lambda x: x[1].get("t", "")):
        pend.append({"w": "RS", "t": f"Resumen pedido a las {str(d.get('t', ''))[11:16]}: {str((eps.get(eid) or {}).get('d', {}).get('titulo') or eid)[:70]}", "cuando": f"lo escribe Claude a las {sig or 'mañana 10:30'}"})
    lanes = []      # los carriles que trabajan a golpes: aunque en este instante no haya nada en marcha, se ve que están vivos y cuánto les queda
    cola = v.get("cola") or {}
    if y.get("fin") or y.get("running"): lanes.append({"w": "TY", "t": f"Carril de YouTube (un vídeo cada 4 min): último «{str(y.get('titulo') or '')[:50]}» a las {str(y.get('fin') or '')[11:16]} · {cola.get('yt_pend', 0)} esperando"})
    if cola.get("pendientes"):
        lim = cola.get("dia_h") is not None and cola["dia_h"] >= cola.get("limite_dia_h", 99) - 0.3
        lanes.append({"w": "TR", "t": f"Podcasts con Groq: {'parado, ha usado el cupo diario' if lim else 'al ritmo del cupo'} · {cola['pendientes']} esperando"})
    return {"now": now, "pending": pend, "lanes": lanes}

def plano(v=None):
    v = v or vista(); ag = {}
    for f in v["agenda"]: ag.setdefault(f["id"], []).append(f)
    pods, av, cola, ct = v["podcasts"], v["avisos"], v["cola"], v["contenido"]; workers, rooms, alertas = {}, [], []
    pend = [p for p in pods if p["estado"] != "resumido"]; sig = next((h for h in HORAS_CLAUDE if _min(h) > _ahora_min()), None)
    conf = {c["id"]: c.get("confirmacion") for c in av["canales"]}
    for s in v["plantilla"]:
        for t in s["trabajadores"]:
            ini, pid = t["ini"], t["id"]; role, sched = ROLES[ini]; tareas = []
            if pid in ("ventas", "estados", "foto_ebay", "precios_graduadas", "youtube", "comunidades", "t_resumen_comunidades", "avisos", "salud"):
                tareas = [{"time": f["hora"], "what": f["nombre"], "s": S_TAREA.get(f["estado"], "plan"), "res": f["texto"] or ""} for f in ag.get(pid, [])]
            elif pid == "podcast_cola": tareas = [{"time": p["transcrito"], "what": p["titulo"][:70], "s": "ok", "res": f"{p['min']} min transcritos"} for p in pods if p["transcrito"] and not p.get("yt")]
            elif pid == "yt_cola": tareas = [{"time": p["transcrito"], "what": p["titulo"][:70], "s": "ok", "res": f"{p['min']} min · subtítulos de la página"} for p in pods if p["transcrito"] and p.get("yt")][-10:]
            elif pid == "t_resumen_podcasts":
                tareas = [{"time": p["resumido"], "what": p["titulo"][:70], "s": "ok", "res": "Resumido"} for p in pods if p["resumido"]]
                tareas += [{"time": p["proxima"] if p["proxima"][0].isdigit() else "mañana", "what": p["titulo"][:70], "s": "plan", "res": f"Pendiente: se transcribió a las {p['transcrito'] or '?'}"} for p in pend]
            elif pid in ("dashboard", "expertise") and t["ultimo"]: tareas = [{"time": t["ultimo"], "what": "Conclusiones del Dashboard" if pid == "dashboard" else "Afirmaciones con fecha", "s": "ok", "res": "Escritas" if pid == "dashboard" else "Guardadas"}]
            elif pid == "reels": tareas = [{"time": i["hora"], "what": i["nombre"], "s": "ok", "res": "Creado"} for i in ct["items"] if i["tipo"] == "vídeo"]
            elif pid == "cronista":
                try:
                    tareas = [{"time": m.group(2)[:5], "what": m.group(3)[:70], "s": "ok", "res": "Apuntado en el diario"} for m in (re.match(r"### (\S+) (\S+) · (.*)", ln) for ln in open(P("cronista", "diario.md"), encoding="utf-8")) if m][-8:]
                except OSError: tareas = []
            elif pid in ("supervisor_datos", "guionista", "revisor_video"):
                try:
                    ce = O._j("data/state/contenido_equipo.json", {}) or {}; fe = O._j(f"data/reels/{ce.get('carta')}.equipo.json", {}) or {} if ce.get("carta") else {}; hh = str(ce.get("inicio") or "")[11:16] or "—"
                    if pid == "supervisor_datos" and fe.get("supervisor"): s_ = fe["supervisor"]; tareas = [{"time": hh, "what": str(ce.get("carta")), "s": "ok" if s_["ok"] else "fail", "res": "Datos buenos" if s_["ok"] else "Rechazados"}] + [{"time": hh, "what": x[:70], "s": "fail", "res": "Impide el vídeo"} for x in s_["duros"]] + [{"time": hh, "what": x[:70], "s": "plan", "res": "A tener en cuenta"} for x in s_["leves"]]
                    elif pid == "guionista" and fe.get("guion"): tareas = [{"time": f"{p_['de']}-{p_['a']} s", "what": p_["que"][:70], "s": "ok", "res": p_["dato"][:80]} for p_ in fe["guion"]["planos"]]
                    elif pid == "revisor_video" and fe.get("revisor"): r_ = fe["revisor"]; m_ = r_.get("medido") or {}; tareas = [{"time": hh, "what": f"{m_.get('segundos')} s · {m_.get('ancho')}x{m_.get('alto')} · {m_.get('mb')} MB", "s": "ok" if r_["pasa"] else "fail", "res": "Pasa" if r_["pasa"] else "No pasa"}] + [{"time": hh, "what": x[:70], "s": "fail", "res": "Hay que arreglarlo"} for x in r_["duros"]] + [{"time": hh, "what": x[:70], "s": "plan", "res": "Menor"} for x in r_["leves"]]
                except Exception: tareas = []
            elif pid == "arquitecto":      # cada hueco que encontró es una tarea pendiente para quien quiera cerrarlo (data/arquitecto/huecos.md)
                try: tareas = [{"time": str((O._j("data/state/arquitecto.json", {}) or {}).get("ultima") or "")[11:16] or "—", "what": x["tipo"][:70], "s": "plan", "res": x["texto"][:110]} for x in (O._j("data/arquitecto/mapa.json", {}) or {}).get("huecos", [])][:8]
                except Exception: tareas = []
            elif pid == "cazador":
                av_ = O._j("data/state/avisos.json", {}) or {}; tareas = [{"time": x.get("t", "")[:5], "what": str(x.get("txt"))[:70], "s": "ok", "res": "Avisado al móvil"} for x in (av_.get("refs_hoy") or []) if x.get("d") == _hoy()][-8:]
            elif pid == "tasador":
                try: import referencia as RF; tareas = [{"time": x["time"], "what": x["what"], "s": "ok", "res": x["res"] or "Leída"} for x in RF.lecturas_de_hoy(8)]
                except Exception: tareas = []
            elif pid.startswith("buscador_"): tareas = [{"time": b["time"], "what": b["what"], "s": "ok", "res": b["res"]} for b in _busquedas_hoy()][-8:]
            elif pid == "ntfy":
                for c in av["canales"]:
                    for m in c["mensajes"]:
                        if m["t"][:10] != _hoy(): continue
                        cf = c.get("confirmacion"); ok = bool(cf and cf["t"] >= m["t"])
                        tareas.append({"time": m["t"][11:16], "what": f"{(m['titulo'] or m['texto'])[:46]} → {c['nombre'].replace('Tu tema', 'Tu tema')}", "s": ("ok" if cf["ok"] else "fail") if ok else "wait", "res": "Recibido por ntfy" + (" · sonó" if ok and cf["ok"] else " · no llegó" if ok else "")})
                tareas = sorted(tareas, key=lambda x: x["time"])[-8:]
            tareas.sort(key=lambda x: _ord(x["time"]))
            texto = t["texto"]; st = ESTADO_W.get(t["estado"], "off")
            txt = {"hecho": None, "sin_turno": None}.get(t["estado"], texto.replace("Próx. turno ", "Próx. ").replace("Próx. ronda ", "Próx. "))
            if t["estado"] == "atascado" and pid != "ntfy": txt = None
            nxt = (t.get("proximo") or "").replace("mañana ", "Mañana ") or ("Mañana" if st == "done" else "—")
            if nxt == "mañana": nxt = "Mañana"
            nota = titulo_n = None
            if ini == "RC" and st == "stuck": titulo_n, nota = "Por qué está atascado:", "la tarea se quedó esperando un permiso y no dejó resumen. Dile a Claude «haz el resumen de comunidades» y lo escribe él desde el chat; o, en el ordenador, ábrela en «Programadas» (en el móvil no sale), dale el permiso y pulsa «Ejecutar ahora»."; nxt = "Cuando la lances desde «Programadas»"
            if ini == "TR":
                if t["estado"] == "sin_cupo": titulo_n, nota, nxt = "Por qué está parado:", f"ha usado {cola.get('dia_h')} de las {cola.get('limite_dia_h')} h diarias de Groq. Quedan {cola.get('pendientes')} episodios en cola.", "Cuando Groq libere cupo"
                else: nxt = "Cuando haya cupo y episodios en cola"
            if ini == "GR":      # que se vea lo que ha hecho: los números del día, no solo los de la última vuelta (Fernando, 5 nov: «no veo resultados de su trabajo»)
                pr = O._j("data/state/precios.json", None) or O._j("data/precios/estado.json", {}) or {}
                titulo_n, nota = "Qué ha hecho hoy:", str(pr.get("message") or "Sin datos") + ". El detalle por carta y nota está en la pestaña Precios. Las API gratis tienen cupo pequeño (ppt: 100 créditos al día, tcgapi: 100 peticiones); el Tasador lee TCGplayer y Collectr sin cupo."
            if ini == "TS":
                rr = O._j("data/state/referencia.json", {}) or {}
                if rr.get("bloqueo"): titulo_n, nota, nxt = "Bloqueado:", f"{rr['bloqueo'].get('web')} pidió una verificación (CAPTCHA) a las {str(rr['bloqueo'].get('desde'))[11:16]}. Pulsa «Lanzar ahora»: se abre una ventana para que la verifiques tú; al acabar sigue solo. Si no haces nada, reintenta a los 20 minutos.", "Tras verificar"
                else:
                    try: import referencia as RF; hoy_ts = RF.lecturas_de_hoy(999)
                    except Exception: hoy_ts = []
                    titulo_n, nota, nxt = "Cómo va:", f"{len(hoy_ts)} cartas leídas hoy, {rr.get('cola') or 0} en cola" + (f"; la última, «{str(rr.get('ultima'))[:50]}» a las {str(rr.get('ultima_t'))[11:16]}" if rr.get('ultima') else "") + ". Cada lectura queda apuntada con su fecha en data/referencia/lecturas.jsonl.", "Sin parar (una carta cada 40-90 s)"
            if ini == "EB" and "tope" in t["sub"]: titulo_n, nota = "Ojo:", "llegó al tope diario de 1.500 anuncios; si hay más cartas, se quedan para mañana."
            if ini == "ED": titulo_n, nota, nxt = "Cuándo trabaja:", f"hace solo el vídeo de la noche a las 03:00 (con el Supervisor, el Guionista y el Revisor) y los demás cuando se lo pides (reels.py o video_html.py). Último vídeo: {ct['ultimo_video'] or 'ninguno'}.", "Mañana 03:00"
            if ini == "RS": nxt = (f"{sig} · {pend[0]['titulo'][:40]}" if pend and sig else sig or "Mañana 10:30")
            if ini == "VS": nxt = (t.get("texto") or "").replace("Próx. ronda ", "") if t["estado"] == "proximo" else "Mañana 11:00"
            if ini == "CA":
                nxt = "Con el próximo aviso"; malos = [k for k, x in conf.items() if x and not x["ok"]]
                titulo_n, nota = "Qué pasa:", (f"dijiste que no te llegan avisos de {len(malos)} tema(s). Mira la ficha de la sala Avisos: la lista de qué revisar en el móvil." if malos else f"ntfy ha recibido los {av['total']} avisos de hoy y te llegan al móvil: funciona.")
            w = {"room": s["id"], "pid": pid, "name": t["puesto"], "state": st, "stateText": txt, "role": role, "next": nxt, "schedule": sched, "noteTitle": titulo_n, "note": nota, "tasks": tareas, "launch": ini in LANZABLES, "stop": ini in ("TR", "TS", "CH"), "guardia": ini in GUARDIA,
                 "agotado": (ini == "TR" and (t["estado"] == "sin_cupo" or (cola.get("pendientes") and not cola.get("ocupado") and not cola.get("siguiente")))) or (ini == "EB" and "tope" in t["sub"]) or (ini == "TS" and t["estado"] == "sin_cupo"),
                 "hojas": ((O._j("data/state/cronista.json", {}) or {}).get("hojas", 0) if ini == "CR" else None)}      # sin cupo de Groq / tope diario de eBay: en la oficina viva se le ve exhausto en el sofá
            if ini == "CA": w["summary"] = f"{av['total']} enviados, {sum(1 for x in conf.values() if x and x['ok'])} confirmados"
            workers[ini] = w
            if st == "stuck": alertas.append({"sev": "fail", "text": f"{t['puesto']} atascado desde {t['texto'].split('desde ')[-1]}" if "desde" in t["texto"] else f"{t['puesto']}: {t['texto']}", "worker": ini})
            if t["estado"] == "sin_cupo": alertas.append({"sev": "wait", "text": f"Transcriptor sin cupo de Groq · {cola.get('pendientes')} en cola", "worker": ini})
            if ini == "CA" and t["estado"] in ("esperando", "atascado"): alertas.append({"sev": "wait", "text": f"Cartero ntfy: {av['total']} avisos sin confirmar en el móvil", "worker": ini})
        ids = [t["ini"] for t in s["trabajadores"]]; est = [workers[i]["state"] for i in ids]; stuck = est.count("stuck")
        if stuck: status, sv = f"{stuck} ATASCADO", "fail"
        elif s["id"] == "podcasts" and cola.get("pendientes") and cola.get("dia_h", 0) >= cola.get("limite_dia_h", 99) - 0.3: status, sv = f"{cola['pendientes']} EN COLA", "wait"
        elif s["id"] == "avisos" and workers.get("CA", {}).get("state") == "wait": status, sv = "REVISAR", "wait"
        elif "wait" in est and any(e != "off" for e in est): status, sv = ("ESPERANDO", "wait") if est.count("done") < len(est) - est.count("off") else ("AL DÍA", "ok")
        elif all(e == "off" for e in est): status, sv = "SIN TURNO", "off"
        else: status, sv = "AL DÍA", "ok"
        hechos = sum(1 for e in est if e == "done")
        res = {"mercado": f"{hechos} de {len(ids)} turnos de hoy hechos." + (" eBay llegó a su tope de 1.500 anuncios." if workers.get("EB", {}).get("note") else ""),
               "comunidades": "YouTube y foros leídos a primera hora." + (" El Redactor no escribió el resumen de las 09:30: espera un permiso." if workers.get("RC", {}).get("state") == "stuck" else ""),
               "podcasts": f"{sum(1 for p in pods if p['transcrito'])} episodios transcritos y {sum(1 for p in pods if p['resumido'])} resumidos hoy." + (f" Falta el resumen de {pend[0]['titulo'][:40]} ({sig or 'mañana'})." if pend else "") + (" El Transcriptor espera cupo de Groq." if workers.get("TR", {}).get("stateText") == "Sin cupo" else ""),
               "estudio": "Conclusiones del Dashboard por la mañana y afirmaciones con fecha de los podcasts.",
               "contenido": f"{ct['videos_hoy']} vídeos hoy. El Editor solo trabaja si lanzas reels.py; último vídeo: {ct['ultimo_video'] or 'ninguno'}.",
               "avisos": f"Los {av['total']} avisos salen bien hacia ntfy" + ("; dijiste que alguno no llega al móvil." if any(x and not x['ok'] for x in conf.values()) else " y te llegan al móvil.")}.get(s["id"], "")
        rooms.append({"id": s["id"], "name": s["nombre"], "status": status, "s": sv, "summary": res, "workers": ids})
    alertas.sort(key=lambda a: a["sev"] != "fail")
    eps = [{"title": p["titulo"], "transcribed": p["transcrito"] or "antes", "summarized": p["resumido"], "summaryEta": p.get("proxima")} for p in pods]
    callout = (f"{pend[0]['titulo'][:50]} no tiene resumen porque se transcribió a las {pend[0]['transcrito'] or '?'} y el Resumidor pasa a las y 30: lo hará a las {pend[0].get('proxima')} si la app de Claude está abierta.") if pend else None
    marks = [{"time": f"{int(e['h']):02d}:{int(round((e['h'] % 1) * 60)) % 60:02d}", "s": S_MARCA.get(e["e"], "ok"), "label": e["t"][:60]} for e in v["linea"]["eventos"]]
    try: horario = _horario(dt.datetime.now(TZ), [{"time": q["hora"], "what": q["titulo"]} for q in v["queda"]], en_curso(v), workers)
    except Exception as ex: print("horario:", type(ex).__name__, ex); horario = {"ahora": [], "luego": [], "sinparar": []}
    return {"now": dt.datetime.now(TZ).strftime("%H:%M"), "date": _hoy(), "horario": horario, "rooms": rooms, "workers": workers, "alerts": alertas, "episodes": eps, "episodeNote": callout,
            "ntfy": {"channels": [{"id": c["id"], "name": c["nombre"], "received": c["total"], "confirmed": None if not c.get("confirmacion") else c["confirmacion"]["ok"]} for c in av["canales"]], "checks": NTFY_CHECKS, "failures": av["fallos"]},
            "agenda": [{"time": q["hora"], "what": q["titulo"]} for q in v["queda"]], "dayMarks": marks, **{"inProgress": en_curso(v)}, "groq": {"h": cola.get("dia_h"), "lim": cola.get("limite_dia_h")}, "par": _par_resumen()}

def _par_resumen():
    """Si hay un ordenador compañero conectado (par.py): lo que la Oficina necesita para enseñar el botón de la «Planta 2». Sin configurar, solo dice que no."""
    try: import par; return par.resumen()
    except Exception: return {"configurado": False, "activo": False, "vivo": False}

import threading
_pc = {"t": 0.0, "v": None, "busy": False}

def _refrescar_plano():
    try: v = plano(); _pc.update(t=time.time(), v=v)
    finally: _pc["busy"] = False
    return _pc["v"]

def plano_cache(ttl=3.0):
    """El plano de la Oficina ya calculado (Fernando, 6 nov: «va lento»): varias pestañas y el tiempo real lo pedían a la vez y cada vez se recalculaba entero (0,6 a 8 s). Dentro de `ttl` segundos se
    devuelve el mismo; pasado ese tiempo se devuelve el último YA y se recalcula en segundo plano, así el que mira nunca espera salvo la primera vez."""
    if _pc["v"] is not None and time.time() - _pc["t"] < ttl: return _pc["v"]
    if _pc["v"] is not None:
        if not _pc["busy"]: _pc["busy"] = True; threading.Thread(target=_refrescar_plano, daemon=True).start()
        return _pc["v"]
    _pc["busy"] = True; return _refrescar_plano()

def invalidar_plano(): _pc["t"] = 0.0      # tras una acción (lanzar, parar): el siguiente que lo pida lo recalcula

def firma():
    """Algo que cambia cuando cambia algo que merezca repintar (para el tiempo real): fechas de los ficheros que escriben los procesos, más el minuto."""
    pats = [P("state", "*.json"), P("state", "actividad.jsonl"), P("podcasts", "resumenes", "*.md"), P("transcripciones", "*.json"), P("reels", "*.mp4"), P("comunidades", "resumenes", "*.json"),
            P("mercado", "estado.json"), P("contenido", "estado.json"), P("conclusiones", "semana.json")]
    n = 0.0
    for p in pats:
        for f in glob.glob(p): n += _mt(f)
    return f"{n:.2f}|{dt.datetime.now(TZ).strftime('%H:%M')}"

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8"); v = vista()
    print(json.dumps({k: v[k] for k in ("veredicto", "resumen_dia", "problemas", "ahora")}, ensure_ascii=False, indent=1))
    for f in v["agenda"]: print(f"{f['hora']} [{f['estado']:<9}] {f['icono']} {f['nombre'][:60]} · {f['texto'][:70]}")
    for p in v["podcasts"]: print("POD", p["transcrito"], p["resumido"], p["estado"], p["titulo"][:50], p.get("proxima"))
    print("CONT", v["contenido"]); print("AVISOS", v["avisos"]["total"], [(c["id"], c["total"]) for c in v["avisos"]["canales"]])
