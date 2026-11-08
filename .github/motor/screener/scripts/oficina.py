"""La «Oficina»: el panel central de PokéFinder (owner, 3 November 2026: "ver todos los workers, cómo van, todo, súper centralizado").
Lee el registro (oficina_procesos.py: una ficha por proceso) y, para cada proceso, su ESTADO REAL desde los ficheros que ya escribe (sin tocar a los procesos), y lo junta con:
  - el gasto de lo que tiene límite (llamadas de eBay, audio de Groq, cuota de YouTube, disco),
  - las alertas (un proceso con error o que debería haberse hecho y no),
  - el registro de actividad (data/state/actividad.jsonl: cada proceso apunta aquí lo que hace con registrar()),
  - la actividad del equipo (los avisos firmados del tema compartido de ntfy: qué ha hecho cada uno).
Y deja ejecutar ahora o encender/apagar lo que tiene un mando que ya existía (ACCIONES, INTERRUPTORES).
Todo es lectura salvo las acciones, y ninguna cosa de aquí puede romper a un proceso: cada lectura está protegida y, si falla, el proceso sale «desconocido».
  python oficina.py            -> resumen en texto (para comprobar sin abrir la app)
  from oficina import vista    -> lo que sirve /api/oficina"""
import datetime as dt, glob, json, os, shutil, subprocess, sys, time, urllib.request
from common import P, load, save, ROOT, TZ
import oficina_procesos as R

INICIO = time.time()
ACT = P("state", "actividad.jsonl")
_cache = {}

def _memo(clave, ttl, fn):
    """Slow reads (network, git, big files) are kept for ttl seconds: the panel refreshes often and must stay light."""
    t, v = _cache.get(clave, (0, None))
    if time.time() - t > ttl:
        try: v = fn()
        except Exception as e: v = {"_error": f"{type(e).__name__}: {str(e)[:100]}"}
        _cache[clave] = (time.time(), v)
    return v

def hoy(): return dt.datetime.now(TZ).date().isoformat()
def _ruta(rel): return os.path.join(ROOT, *rel.split("/"))
def _j(rel, d=None): return load(_ruta(rel), d)
def _edad(ts): return None if not ts else max(0, time.time() - ts)

def _iso_a_ts(s):
    try: return dt.datetime.fromisoformat(str(s)).timestamp()
    except (TypeError, ValueError): return None

def yo():
    try: import compartir; return compartir.rama() or "yo"
    except Exception: return "yo"

# ---------------------------------------------------------------- activity log: what each process did, in one place
def registrar(proceso, texto, ok=True, evento="fin"):
    """One line in data/state/actividad.jsonl. Never raises: writing a log must not break the process that calls it."""
    try:
        os.makedirs(os.path.dirname(ACT), exist_ok=True)
        with open(ACT, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": dt.datetime.now(TZ).isoformat(timespec="seconds"), "quien": yo(), "proceso": proceso, "evento": evento, "texto": str(texto)[:300], "ok": bool(ok)}, ensure_ascii=False) + "\n")
    except OSError: pass

def actividad(n=80):
    try:
        with open(ACT, encoding="utf-8") as f: ls = f.readlines()[-n:]
    except OSError: return []
    out = []
    for l in reversed(ls):
        try: out.append(json.loads(l))
        except ValueError: continue
    return out

# ---------------------------------------------------------------- the state readers (one per kind of process)
def _est(estado, mensaje="", ultimo=None, hoy_=None, metricas=None):
    return {"estado": estado, "mensaje": mensaje, "ultimo": ultimo, "hoy": hoy_, "metricas": metricas or []}

def a_json_estado(p, a):
    s = _j(a["archivo"], {}) or {}
    if not s: return _est("desconocido", "Todavía no hay datos de este proceso.")
    fin = s.get(a.get("fin", "finished")) or s.get("finished") or s.get("fin")
    dia = s.get(a.get("dia", "fecha")) or s.get("fecha") or s.get("dia") or (str(fin)[:10] if fin else None)
    if a.get("hoy"): dia = (_j(a["hoy"][0], {}) or {}).get(a["hoy"][1]) or dia
    corriendo = bool(s.get("running")) and (_edad(s.get("beat")) or 0) < 600
    err = s.get("error")
    msg = s.get("message") or ""
    m = []
    if s.get("total"): m.append(["Avance", f"{s.get('done', 0)}/{s['total']}"])
    for k, v in (s.get("ultimo") or {}).items():
        if isinstance(v, (int, float)): m.append([k.capitalize(), v])
    if corriendo: return _est("corriendo", msg or "Trabajando…", fin, dia == hoy(), m)
    if err and str(fin or "")[:10] == hoy(): return _est("error", str(err)[:200], fin, False, m)
    return _est("ok", msg or "Terminó bien.", fin, dia == hoy(), m)

def a_condiciones(p, a):
    s = _j("data/app/condiciones_estado.json", {}) or {}
    n = s.get("n", 0) if s.get("day") == hoy() else 0
    corriendo = bool(s.get("running")) and (_edad(s.get("beat")) or 0) < 600
    return _est("corriendo" if corriendo else "ok", f"{n} anuncios preguntados hoy (tope 1.500)", dt.datetime.fromtimestamp(s["beat"], TZ).isoformat(timespec="minutes") if s.get("beat") else None,
                s.get("day") == hoy(), [["Hoy", n], ["Tope", 1500]])

def a_revision_diaria(p, a):
    import mercado as M
    on = bool(M.conf().get("diario")); d = _j("data/mercado/diario.json", {}) or {}; cola = len(d.get("cola") or [])
    if not on: return _est("apagado", "Apagada: no se lanza ninguna búsqueda sola. Se activa desde Mercado → Búsquedas.", None, None, [["Cola", cola]])
    return _est("ok", f"Encendida · {cola} búsqueda(s) en la cola de hoy", d.get("at"), d.get("day") == hoy(), [["En cola", cola], ["Hechas hoy", d.get("hechas", 0)]])

def a_motor(p, a):
    b = _j("data/app/claude.json", {}) or {}
    vivo = time.time() - b.get("at", 0) < 120
    n = {"cola": 0, "buscando": 0}
    for f in glob.glob(_ruta("data/app/jobs/*.json")):
        try: st = (json.load(open(f, encoding="utf-8")) or {}).get("status")
        except (OSError, ValueError): continue
        if st in ("running", "claimed", "ebay"): n["buscando"] += 1
        elif st in ("queued", "waiting_claude"): n["cola"] += 1
    if not vivo: return _est("error", "El motor no responde (no ha dado señales en 2 minutos).", None, None, [["En cola", n["cola"]]])
    return _est("corriendo" if n["buscando"] else "ok", "Buscando…" if n["buscando"] else "Esperando búsquedas", dt.datetime.fromtimestamp(b["at"], TZ).isoformat(timespec="seconds"), None,
                [["Buscando", n["buscando"]], ["En cola", n["cola"]], ["PID", b.get("pid")]])

def a_historial(p, a):
    fs = sorted(glob.glob(_ruta("data/historial/fecha=*.parquet")))
    if not fs: return _est("desconocido", "Todavía no hay días guardados.")
    ult = os.path.basename(fs[-1])[6:16]
    return _est("ok" if ult == hoy() else "atrasado", f"{len(fs)} día(s) guardados; el último es {ult}", ult, ult == hoy(), [["Días", len(fs)], ["Tamaño", f"{sum(os.path.getsize(f) for f in fs) // 1024} KB"]])

def a_estudio(p, a):
    d = _ruta("data/reels"); fs = [f for f in os.listdir(d) if f.endswith((".mp4", ".png"))] if os.path.isdir(d) else []
    ult = max((os.path.getmtime(os.path.join(d, f)) for f in fs), default=None)
    return _est("manual", f"{len(fs)} archivo(s) montados", dt.datetime.fromtimestamp(ult, TZ).isoformat(timespec="minutes") if ult else None, None, [["Archivos", len(fs)]])

def _cola_vista():
    import podcasts as PC
    return _memo("cola", 60, PC.cola_vista)

def a_podcast_cola(p, a):
    v = _cola_vista()
    if v.get("_error"): return _est("desconocido", v["_error"])
    job = _j("data/state/podcast_job.json", {}) or {}
    m = [["Hoy", f"{v['dia_h']} h de {v['limite_dia_h']} h"], ["Última hora", f"{v['hora_h']} h"], ["Pendientes", "/".join(str(x) for x in v["pendientes"])]]
    if v.get("sin_clave"): return _est("error", "Falta la clave de Groq (.secrets/groq.json).", job.get("fin"), None, m)
    if not v["activa"]: return _est("apagado", "Cola apagada: no transcribe nada sola.", job.get("fin"), None, m)
    if job.get("running"): return _est("corriendo", "Transcribiendo: " + str(job.get("titulo") or "")[:80], job.get("started"), None, m)
    if job.get("ok") is False: return _est("error", str(job.get("error") or "falló el último episodio")[:200], job.get("fin"), None, m)
    return _est("ok", ("Último: " + str(job.get("titulo") or "")[:70]) if job.get("titulo") else "Esperando hueco en el límite de Groq", job.get("fin"), None, m)

def a_expertise(p, a):
    def leer():
        import duckdb
        c = duckdb.connect(_ruta("data/expertise/expertise.duckdb"), read_only=True)
        r = {t: c.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("hechos", "jerga", "sets")}
        r["dudosos"] = c.execute("SELECT count(*) FROM hechos WHERE confianza IN ('dudoso','por comprobar')").fetchone()[0]; c.close(); return r
    if not os.path.exists(_ruta("data/expertise/expertise.duckdb")): return _est("desconocido", "Todavía no existe la base.")
    r = _memo("expertise", 120, leer)
    if r.get("_error"): return _est("manual", "La base está ocupada ahora mismo.", None, None, [])
    return _est("manual", f"{r['hechos']} hechos, {r['jerga']} apodos y {r['sets']} sets", None, None, [["Hechos", r["hechos"]], ["Por comprobar", r["dudosos"]], ["Jerga", r["jerga"]], ["Sets", r["sets"]]])

def a_claude_tarea(p, a):
    tareas = os.path.join(os.path.expanduser("~"), ".claude", "scheduled-tasks", a["id"], "SKILL.md")
    m = []
    if a.get("pendientes") == "resumenes":
        def pend():
            import podcasts as PC; return {"n": len(PC.sin_resumen())}
        v = _memo("sinres", 90, pend)
        if not v.get("_error"): m.append(["Episodios sin resumen de Claude", v["n"]])
    if not os.path.exists(tareas): return _est("pendiente", "Todavía no existe: hay que crearla.", None, None, m)
    return _est("ok", "Programada en la app de Claude (mira la sección «Programadas» para ver cuándo corrió).", dt.datetime.fromtimestamp(os.path.getmtime(tareas), TZ).isoformat(timespec="minutes"), None, m)

def a_avisos(p, a):
    s = _j("data/state/avisos.json", {}) or {}; f = _ruta("data/state/avisos.json")
    return _est("ok" if s else "desconocido", f"{len(s.get('jobs') or {})} búsquedas vistas y {len(s.get('chollos') or [])} chollos avisados", dt.datetime.fromtimestamp(os.path.getmtime(f), TZ).isoformat(timespec="minutes") if os.path.exists(f) else None,
                None, [["Búsquedas vistas", len(s.get("jobs") or {})], ["Chollos avisados", len(s.get("chollos") or [])]])

def a_salud(p, a):
    s = _j("data/state/salud.json", {}) or {}
    if not s: return _est("desconocido", "Todavía no ha comprobado nada.")
    ult = str(s.get("ultimo") or ""); mal = ult.endswith(hoy())
    return _est("ok", ("Hoy avisó de: " + ult[:-10][:150]) if mal else "Todo en orden en la última comprobación.", None, None, [["Franja", str(s.get("slot") or "")]])

def a_compartir(p, a):
    try: import compartir; ok = compartir.disponible(); rama = compartir.rama()
    except Exception: ok, rama = False, ""
    if not ok: return _est("error", "Falta «git config pokefinder.rama <fernando|jesus>»: no se puede repartir.", None, None, [])
    try: ls = open(_ruta("data/state/compartir.log"), encoding="utf-8").read().strip().splitlines()
    except OSError: ls = []
    ult = ls[-1] if ls else ""
    mal = "falló" in ult
    return _est("atrasado" if mal else "ok", ult[20:160] if ult else "Todavía no ha repartido nada.", ult[:19].replace(" ", "T") if ult else None, None,
                [["Tu rama", rama], ["Subidos", sum(1 for x in ls if "publicado" in x)]])

def a_cuota_ebay(p, a):
    import ebay_cuota as Q
    v = Q.vista(); auto = v["automaticas_hasta"]; usadas_auto = sum(o["n"] for o in v["origenes"] if o["id"] in Q.AUTOMATICOS)
    return _est("atrasado" if usadas_auto >= auto else "ok", f"{v['usado']} de {v['total']} llamadas hoy (día de eBay {v['dia']})" + ("; las automáticas han llegado al límite" if usadas_auto >= auto else ""), None, None,
                [[o["nombre"], o["n"]] for o in v["origenes"]] + [["Reservadas para ti", v["reserva_manual"]]])

def a_sincronizar(p, a):
    def git():
        r = subprocess.run(["git", "-C", ROOT, "status", "--short", "-b"], capture_output=True, text=True, encoding="utf-8", timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.splitlines()
        return {"rama": r[0][3:].split("...")[0] if r else "", "cambios": max(0, len(r) - 1), "adelante": "ahead" in (r[0] if r else "")}
    v = _memo("git", 60, git)
    if v.get("_error"): return _est("desconocido", v["_error"])
    return _est("pendiente" if v["cambios"] or v["adelante"] else "ok", f"{v['cambios']} archivo(s) sin subir" + (" y commits sin subir" if v["adelante"] else "") if v["cambios"] or v["adelante"] else "Todo está subido.", None, None, [["Rama", v["rama"]], ["Sin subir", v["cambios"]]])

def a_servidor(p, a):
    lnk = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Startup", "PokeFinder.lnk")
    return _est("ok", "En marcha desde " + dt.datetime.fromtimestamp(INICIO, TZ).strftime("%d/%m %H:%M"), dt.datetime.fromtimestamp(INICIO, TZ).isoformat(timespec="minutes"), None,
                [["Puerto", 8800], ["Arranque con Windows", "sí" if os.path.exists(lnk) else "no"]])

def a_tailscale(p, a):
    def ts():
        exe = next((x for x in (r"C:\Program Files\Tailscale\tailscale.exe", shutil.which("tailscale") or "") if x and os.path.exists(x)), "")
        if not exe: return {"ip": ""}
        r = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=6, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip().splitlines()
        return {"ip": r[0] if r else ""}
    v = _memo("ts", 120, ts)
    if v.get("_error") or not v.get("ip"): return _est("desconocido", "No se puede leer el estado de Tailscale desde aquí.")
    return _est("ok", f"Desde el móvil: http://{v['ip']}:8800", None, None, [["IP de Tailscale", v["ip"]]])

def a_ntfy(p, a):
    import json as _json
    try: c = _json.load(open(_ruta(".secrets/ntfy.json"), encoding="utf-8"))
    except (OSError, ValueError): return _est("error", "Falta .secrets/ntfy.json: no se puede avisar al móvil.")
    falt = [k for k in ("tema", "salud", "equipo") if not str(c.get(k) or "").strip()]
    try: fallos = len(open(_ruta("data/state/avisar.log"), encoding="utf-8").read().splitlines())
    except OSError: fallos = 0
    return _est("atrasado" if falt else "ok", ("Faltan: " + ", ".join(falt)) if falt else "Los tres temas están configurados.", None, None,
                [["Tu nombre", c.get("nombre") or "—"], ["Temas", 3 - len(falt)], ["Envíos fallidos", fallos]])

def a_sin_estado(p, a): return _est("manual", a.get("texto") or "Sin estado propio.")

ADAPTADORES = {k[2:]: v for k, v in globals().items() if k.startswith("a_") and callable(v)}

# ---------------------------------------------------------------- what can be started and switched from the panel (only what already had a control)
def _lanzar(mod, fn="lanzar", **kw):
    import importlib; return getattr(importlib.import_module(mod), fn)(**kw)

ACCIONES = {
    "foto_ebay": lambda: _lanzar("mercado", forzar=True),       # «Hacer foto ahora»: asks eBay even if today's is done (it spends ~160 calls)
    "estados": lambda: _lanzar("condiciones"), "ventas": lambda: _lanzar("ventas"),
    "youtube": lambda: _lanzar("contenido"), "comunidades": lambda: _lanzar("comunidades"),
    "podcast_cola": lambda: _lanzar("podcasts", "tick"), "precios_graduadas": lambda: _lanzar("precios_graduadas"),
}

def i_revision_diaria(on):
    import mercado as M; M.set_conf(None, None, None, bool(on)); return {"encendido": bool(M.conf().get("diario"))}

def i_podcast_cola(on):
    import podcasts as PC; PC.cola_ajustar(bool(on), None, None); return {"encendido": bool(PC.cola_conf()["activa"])}

INTERRUPTORES = {"revision_diaria": i_revision_diaria, "podcast_cola": i_podcast_cola}

def _tasador(que):
    """Mandos del Tasador (la base de precios, referencia.py --servicio): «lanzar» lo arranca si no late; si una web le pidió verificación, abre una ventana VISIBLE para que Fernando la haga a mano
    (nunca se resuelve sola) y sigue solo al acabar; «apagar» lo para (el servidor lo vuelve a arrancar en unos minutos si no se le dice otra cosa)."""
    import referencia as RF
    s = RF.estado()
    if que == "apagar": RF.estado(parar=True, apagado=True); return {"ok": True, "mensaje": "Tasador: parado y apagado (no se arranca solo hasta que pulses «Lanzar ahora»)"}
    if s.get("apagado"): RF.estado(apagado=False, parar=False)
    if not RF.viva(): RF.lanzar(); return {"ok": True, "mensaje": "Tasador: arrancado"}
    if s.get("bloqueo"): RF.estado(desbloquear=True); return {"ok": True, "mensaje": f"Tasador: se abre una ventana en {s['bloqueo'].get('web')} para que verifiques; al acabar sigue solo"}
    return {"ok": True, "mensaje": "El Tasador ya está trabajando"}

def _cazador(que):
    """Mandos del Buscador de chollos (caza.py): «apagar» deja de lanzar búsquedas y campañas solo; «lanzar» las reanuda. Las búsquedas que pides tú no se tocan."""
    import caza
    caza.estado(activa=(que != "apagar"))
    return {"ok": True, "mensaje": "Buscador de chollos: " + ("apagado: no lanzará búsquedas solo" if que == "apagar" else "encendido: vuelve a buscar solo cuando el motor esté libre")}

def accion(pid, que):
    if pid == "tasador": return _tasador(que)
    if pid == "cazador": return _cazador(que)
    f = next((x for x in R.PROCESOS if x["id"] == pid), None)
    if not f: raise ValueError("No existe ese proceso")
    if que == "lanzar":
        if pid not in ACCIONES or not f.get("lanzar"): raise ValueError("Este proceso no se puede lanzar desde aquí")
        ACCIONES[pid](); registrar(pid, "Lanzado a mano desde la Oficina", evento="manual"); _cache.clear(); return {"ok": True, "mensaje": f"{f['nombre']}: lanzado"}
    if que in ("encender", "apagar"):
        if pid not in INTERRUPTORES: raise ValueError("Este proceso no tiene interruptor aquí")
        r = INTERRUPTORES[pid](que == "encender"); registrar(pid, ("Encendido" if que == "encender" else "Apagado") + " desde la Oficina", evento="manual"); _cache.clear(); return {"ok": True, **r}
    if pid == "ntfy" and que.startswith("confirmar:"):      # «Sonó» / «No llegó»: the owner says whether the last test reached the phone (confirmar:<canal>:1|0)
        _, canal, ok = que.split(":"); import oficina_hoy; oficina_hoy.confirmar(canal, ok == "1"); registrar(pid, f"Canal {canal}: " + ("sonó en el móvil" if ok == "1" else "NO llegó al móvil"), ok=ok == "1", evento="manual"); _cache.clear()
        return {"ok": True, "mensaje": "Anotado"}
    if que == "prueba" and pid == "ntfy":      # one test notice to each channel: the owner checks on the phone which ones arrive
        sys.path.insert(0, os.path.join(ROOT, "tools")); from avisar import avisar
        h = dt.datetime.now(TZ).strftime("%H:%M")
        r = [avisar(f"Prueba de las {h}: si lees esto, este canal llega al móvil.", f"Prueba {n} de 3 - {nom}", canal=c, equipo=(c == "equipo")) for n, (c, nom) in enumerate([("tema", "tu tema"), ("salud", "salud"), ("equipo", "equipo")], 1)]
        registrar(pid, f"Prueba enviada a los tres canales ({sum(bool(x) for x in r)}/3 salieron)", ok=all(r), evento="manual"); _cache.clear(); return {"ok": all(r), "mensaje": f"{sum(bool(x) for x in r)} de 3 pruebas enviadas"}
    raise ValueError("Acción desconocida")

# ---------------------------------------------------------------- the whole panel
def _estado_de(f):
    a = dict(f.get("estado") or {"adaptador": "sin_estado"}); fn = ADAPTADORES.get(a.pop("adaptador", "sin_estado"), a_sin_estado)
    try: e = fn(f, a)
    except Exception as ex: e = _est("desconocido", f"No se pudo leer su estado ({type(ex).__name__}).")
    # «atrasado»: it should have been done today by now and was not (and it is not running or switched off)
    h = f.get("hora")
    if h and e["estado"] == "ok" and e.get("hoy") is False and dt.datetime.now(TZ).hour >= h + 1: e["estado"] = "atrasado"; e["mensaje"] = "Debería haberse hecho hoy y no consta. " + e["mensaje"]
    return e

def _recursos():
    out = []
    try:
        import ebay_cuota as Q; v = Q.vista()
        out.append({"id": "ebay", "nombre": "eBay · llamadas", "usado": v["usado"], "limite": v["total"], "unidad": "llamadas", "marca": v["automaticas_hasta"], "texto_marca": "tope de las automáticas", "detalle": f"{v['reserva_manual']} reservadas para tus búsquedas"})
    except Exception: pass
    try:
        c = _cola_vista()
        if not c.get("_error"): out.append({"id": "groq", "nombre": "Groq · audio transcrito hoy", "usado": c["dia_h"], "limite": c["limite_dia_h"], "unidad": "h", "detalle": f"Última hora: {c['hora_h']} h de 1,8 h"})
    except Exception: pass
    try:
        u = ((_j("data/contenido/estado.json", {}) or {}).get("ultimo") or {}).get("unidades")
        if u is not None: out.append({"id": "youtube", "nombre": "YouTube · API", "usado": u, "limite": 10000, "unidad": "unidades", "detalle": "Última lectura"})
    except Exception: pass
    try:
        d = shutil.disk_usage(os.path.splitdrive(ROOT)[0] + "\\"); out.append({"id": "disco", "nombre": "Disco libre", "usado": round((d.total - d.free) / 1e9), "limite": round(d.total / 1e9), "unidad": "GB", "detalle": f"Quedan {d.free / 1e9:.0f} GB"})
    except Exception: pass
    return out

def _equipo():
    """What the team topic says (the signed notices: who did what in the last 24 h). The topic's name is a secret and never leaves this function."""
    def leer():
        c = _j(".secrets/ntfy.json", {}) or {}; t = str(c.get("equipo") or "").strip()
        if not t: return {"mensajes": [], "sin_tema": True}
        r = urllib.request.urlopen(urllib.request.Request(f"https://ntfy.sh/{t}/json?poll=1&since=24h", headers={"User-Agent": "PokeFinder personal"}), timeout=15).read().decode("utf-8", "replace").splitlines()
        out = []
        for l in r:
            try: m = json.loads(l)
            except ValueError: continue
            if m.get("event") != "message": continue
            txt = m.get("message") or ""; de, _, resto = txt.partition(": ")
            out.append({"t": dt.datetime.fromtimestamp(m["time"], TZ).isoformat(timespec="minutes"), "de": de if resto and len(de) < 24 else "", "texto": resto or txt, "titulo": m.get("title") or ""})
        return {"mensajes": out[-40:][::-1], "yo": str(c.get("nombre") or "")}
    return _memo("equipo", 90, leer)

def vista():
    grupos, alertas, cuenta, por_canal = [], [], {}, {k: [] for k in R.CANALES}
    for gid, ico, nombre, desc in R.GRUPOS:
        ps = []
        for f in (x for x in R.PROCESOS if x["grupo"] == gid):
            e = _estado_de(f); cuenta[e["estado"]] = cuenta.get(e["estado"], 0) + 1
            for c, _ in f.get("notifica", []): por_canal.setdefault(c, []).append(f["id"])
            if e["estado"] in ("error", "atrasado", "pendiente"): alertas.append({"id": f["id"], "nombre": f["nombre"], "estado": e["estado"], "texto": e["mensaje"]})
            ps.append({**{k: f.get(k) for k in ("id", "nombre", "icono", "que", "ejecuta", "cuando", "recursos", "notifica", "equipo", "datos", "ver", "modo")}, **e,
                       "compartido": not str(f.get("equipo") or "No").startswith(("No", "Cada", "Pendiente")),      # worked out between both computers (the card says how in «equipo»)
                       "lanzable": bool(f.get("lanzar") and f["id"] in ACCIONES), "interruptor": f["id"] in INTERRUPTORES and bool(f.get("interruptor")),
                       "encendido": None if f["id"] not in INTERRUPTORES else e["estado"] != "apagado"})
        grupos.append({"id": gid, "icono": ico, "nombre": nombre, "desc": desc, "procesos": ps})
    cfg = _j(".secrets/ntfy.json", {}) or {}
    canales = [{"id": k, "icono": v[0], "nombre": v[1], "desc": v[2], "procesos": por_canal.get(k, []), "configurado": bool(str(cfg.get(k) or "").strip())} for k, v in R.CANALES.items()]
    orden = {"error": 0, "atrasado": 1, "pendiente": 2}
    return {"ahora": dt.datetime.now(TZ).isoformat(timespec="seconds"), "yo": yo(), "dia": hoy(),
            "resumen": {"total": sum(cuenta.values()), **cuenta}, "alertas": sorted(alertas, key=lambda a: orden.get(a["estado"], 9)), "recursos": _recursos(),
            "grupos": grupos, "canales": canales, "actividad": actividad(60), "equipo": _equipo(), "recursos_info": R.RECURSOS}

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8"); v = vista()
    print(f"OFICINA · {v['dia']} · {v['yo']} · {v['resumen']}")
    for g in v["grupos"]:
        print(f"\n{g['icono']} {g['nombre']}")
        for p in g["procesos"]: print(f"  [{p['estado']:<10}] {p['nombre']}: {p['mensaje'][:100]}")
    print("\nAlertas:", [(a['nombre'], a['estado']) for a in v["alertas"]])
    print("Recursos:", [(r['nombre'], r['usado'], r['limite']) for r in v["recursos"]])
