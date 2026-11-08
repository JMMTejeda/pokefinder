"""El Jefe de la Oficina (Jesús, 7 de noviembre de 2026): "cuando yo doy una orden, el jefe se encarga de repartir las tareas entre los trabajadores:
hace un desglose de lo que significa la tarea, qué tiene que buscar, acciona a los agentes y luego da los resultados, en la pestaña que corresponda;
si no encaja en ninguna, en una de Preguntas y respuestas con datos, gráficas y todo".

El jefe ES Claude: Jesús le da la orden en una sesión de Claude Code y Claude, con tools/jefe.py, apunta la tarea, su desglose (pasos con el
trabajador que los hace), la arranca, la sigue y escribe el resultado. Este módulo solo guarda y enseña; el servidor lanza los trabajos.

Tarea (data/jefe/tareas/<id>.json):
  {"id", "orden", "creada", "estado": "preparando"|"en_marcha"|"pausada"|"terminada"|"parada",
   "pasos": [{"n", "que", "agente" (código de la Oficina: BJ, TS, TR...), "accion": {"tipo": "buscar", "query", "depth"} | {"tipo": "lanzar", "proceso"} | {"tipo": "jefe"},
              "estado": "pendiente"|"en_marcha"|"pausado"|"hecho"|"fallo", "job", "nota"}],
   "resultado": {"resumen", "destino": "busquedas"|"mercado"|"precios"|"chollos"|"estudio"|"dashboard"|"podcasts"|"preguntas", "enlaces": [{"texto", "href"}],
                 "respuesta" (texto; párrafos separados por línea en blanco), "cifras": [{"etiqueta", "valor", "nota"}],
                 "tablas": [{"titulo", "columnas": [...], "filas": [[...]]}],
                 "graficas": [{"tipo": "barras"|"linea", "titulo", "unidad", "x": [...], "series": [{"nombre", "valores": [...]}]}]}}
La tarea «actual» (la que enseña la Oficina) está en data/jefe/actual.json."""
import json, os, re, time, unicodedata
from common import P, load, save

DIR = P("jefe", "tareas")
ACTUAL = P("jefe", "actual.json")
ACTIVOS = ("queued", "waiting_claude", "claimed", "running")
DESTINOS = ("busquedas", "mercado", "precios", "chollos", "estudio", "dashboard", "podcasts", "historial", "preguntas")

def _ahora(): return time.strftime("%Y-%m-%dT%H:%M:%S")
def _ruta(tid): return os.path.join(DIR, re.sub(r"[^a-z0-9_-]", "", str(tid)) + ".json")
def _slug(t):
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40] or "tarea"

def cargar(tid): return load(_ruta(tid), None)
def guardar(t): os.makedirs(DIR, exist_ok=True); t["actualizada"] = _ahora(); save(_ruta(t["id"]), t); return t

def nueva(orden):
    orden = re.sub(r"\s+", " ", str(orden or "")).strip()
    if not orden: raise ValueError("la orden está vacía")
    tid = "t-" + time.strftime("%Y%m%d-%H%M%S") + "-" + _slug(orden)
    t = guardar({"id": tid, "orden": orden[:2000], "creada": _ahora(), "estado": "preparando", "pasos": [], "resultado": None})
    os.makedirs(os.path.dirname(ACTUAL), exist_ok=True); save(ACTUAL, {"id": tid})
    return t

def paso(tid, que, agente="", accion=None):
    t = cargar(tid)
    if not t: raise ValueError("no existe esa tarea")
    accion = accion or {"tipo": "jefe"}
    t["pasos"].append({"n": len(t["pasos"]) + 1, "que": str(que)[:500], "agente": str(agente or "").upper()[:4], "accion": accion, "estado": "pendiente", "job": None, "nota": None})
    return guardar(t)

def _job(job_path, jid):
    try:
        with open(job_path(jid), encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError, TypeError): return None

def refrescar(t, job_path):
    """Pone al día cada paso con su trabajo real (las búsquedas) y la tarea con sus pasos."""
    for p in t.get("pasos") or []:
        if p.get("job"):
            j = _job(job_path, p["job"]) or {}
            st = j.get("status")
            p["progreso"] = j.get("progress"); p["mensaje"] = j.get("message"); p["search_id"] = j.get("search_id") or p.get("search_id")
            if st == "done": p["estado"] = "hecho"
            elif st == "error": p["estado"] = "fallo"
            elif st == "cancelled": p["estado"] = "pausado" if j.get("pausada") else ("pausado" if p["estado"] == "pausado" else "fallo")
            elif st in ACTIVOS: p["estado"] = "en_marcha"
    pasos = t.get("pasos") or []
    busquedas = [p for p in pasos if p["accion"].get("tipo") != "jefe"]      # solo se cierra sola si tiene búsquedas y todas han acabado (si no, la cierra el resultado)
    if t.get("estado") == "en_marcha" and busquedas and all(p["estado"] in ("hecho", "fallo") for p in busquedas) and t.get("resultado") and not t.get("versiones"):
        t["estado"] = "terminada"
    return t

def vista(tid, job_path):
    t = cargar(tid)
    return refrescar(t, job_path) if t else None

def actual(job_path):
    a = load(ACTUAL, {}) or {}
    return vista(a.get("id"), job_path) if a.get("id") else None

def lista():
    out = []
    if os.path.isdir(DIR):
        for f in sorted(os.listdir(DIR), reverse=True):
            t = load(os.path.join(DIR, f), None)
            if t: out.append({"id": t["id"], "orden": t["orden"], "creada": t.get("creada"), "estado": t.get("estado"),
                              "destino": (t.get("resultado") or {}).get("destino"), "resumen": (t.get("resultado") or {}).get("resumen")})
    return out

def empezar(tid, new_job, lanzar, job_path):
    """Arranca los pasos pendientes: busca (cola del motor), lanza un proceso de la Oficina o lo hace el propio jefe (Claude)."""
    t = cargar(tid)
    if not t: raise ValueError("no existe esa tarea")
    for p in t["pasos"]:
        if p["estado"] != "pendiente": continue
        a = p["accion"]
        try:
            if a.get("tipo") == "buscar":
                j = new_job("text", None, a.get("query"), a.get("depth")); p["job"] = j["id"]; p["estado"] = "en_marcha"
            elif a.get("tipo") == "lanzar":
                r = lanzar(a.get("proceso"), "lanzar"); p["estado"] = "en_marcha"; p["nota"] = r.get("mensaje")
            else: p["estado"] = "en_marcha"      # lo hace el jefe (Claude) en su sesión
        except Exception as e: p["estado"] = "fallo"; p["nota"] = str(e)[:200]
    t["estado"] = "en_marcha"; t["empezada"] = t.get("empezada") or _ahora(); save(ACTUAL, {"id": tid})      # «empezada»: la Oficina reúne a todos en el despacho al empezar
    return refrescar(guardar(t), job_path)

def pausar(tid, job_path):
    """PAUSAR: las búsquedas que van por la mitad se paran guardando lo leído (el motor retoma por páginas al continuar)."""
    t = cargar(tid)
    if not t: raise ValueError("no existe esa tarea")
    for p in t["pasos"]:
        j = _job(job_path, p.get("job")) if p.get("job") else None
        if j and j.get("status") in ACTIVOS:
            j.update(status="cancelled", pausada=True, message="En pausa (se retoma donde iba)"); save(job_path(j["id"]), j)
        if p["estado"] == "en_marcha": p["estado"] = "pausado"
    t["estado"] = "pausada"
    return refrescar(guardar(t), job_path)

def continuar(tid, job_path):
    """CONTINUAR: vuelve a poner en cola lo pausado; el motor sigue desde la página donde se quedó."""
    t = cargar(tid)
    if not t: raise ValueError("no existe esa tarea")
    for p in t["pasos"]:
        if p["estado"] != "pausado": continue
        j = _job(job_path, p.get("job")) if p.get("job") else None
        if j and j.get("status") == "cancelled":
            j.update(status="queued", pausada=False, message="Reanudada"); save(job_path(j["id"]), j)
        p["estado"] = "en_marcha"
    t["estado"] = "en_marcha"
    return refrescar(guardar(t), job_path)

def parar(tid, job_path):
    t = pausar(tid, job_path); t["estado"] = "parada"
    return guardar(t)

def reabrir(tid):
    """Mejorar una pregunta ya respondida SIN crear otra (Jesús, 7 nov 2026: "cuando te digo que hagas upgrades, no tienes que crear una nueva pregunta,
    sino mejorar la que ya tienes"): misma tarea, mismo título; se vacían los pasos para el nuevo desglose y se guarda el resultado anterior hasta que
    llegue el nuevo (la pestaña lo sigue enseñando mientras tanto)."""
    t = cargar(tid)
    if not t: raise ValueError("no existe esa tarea")
    if t.get("resultado"): t.setdefault("versiones", []).append({"cuando": t.get("actualizada"), "resumen": t["resultado"].get("resumen")})
    t["pasos"] = []; t["estado"] = "preparando"; t["empezada"] = None
    os.makedirs(os.path.dirname(ACTUAL), exist_ok=True); save(ACTUAL, {"id": tid})
    return guardar(t)

def borrar(tid):
    p = _ruta(tid)
    if not os.path.exists(p): raise ValueError("no existe esa tarea")
    os.remove(p)
    a = load(ACTUAL, {}) or {}
    if a.get("id") == tid: os.remove(ACTUAL)
    return True

def marcar(tid, n, estado=None, nota=None, progreso=None):
    """El jefe anota cómo va un paso que hace él (o un trabajador sin búsqueda): «en_marcha», «hecho» o «fallo», con una nota y un % que se ven en la Oficina."""
    t = cargar(tid)
    if not t: raise ValueError("no existe esa tarea")
    p = next((x for x in t["pasos"] if x["n"] == int(n)), None)
    if not p: raise ValueError("no existe ese paso")
    if estado: p["estado"] = estado
    if nota is not None: p["nota"] = str(nota)[:300]
    if progreso is not None: p["progreso"] = int(progreso)
    return guardar(t)

def resultado(tid, r):
    t = cargar(tid)
    if not t: raise ValueError("no existe esa tarea")
    if not isinstance(r, dict): raise ValueError("el resultado tiene que ser un objeto JSON")
    if r.get("destino") not in DESTINOS: r["destino"] = "preguntas"
    t["resultado"] = r
    if all(p["estado"] in ("hecho", "fallo") or p["accion"].get("tipo") == "jefe" for p in t["pasos"]):
        for p in t["pasos"]:
            if p["accion"].get("tipo") == "jefe": p["estado"] = "hecho"
        t["estado"] = "terminada"
    return guardar(t)
