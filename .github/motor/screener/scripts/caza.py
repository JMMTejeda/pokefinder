"""Ronda de caza (Fernando, 5 de noviembre de 2026: «que no deje de buscar»; «todas las que pueda»): mientras el Tasador va llenando la base de precios, esta ronda lanza una búsqueda RÁPIDA de cada carta
que tiene precio de referencia (grails primero, luego las más caras) en eBay y los portales, para que el Buscador de chollos avise de lo que salga por debajo.
Reglas, para que no estorbe ni bloquee:
- Las búsquedas que pides tú van primero: solo se lanza una cuando NO hay ninguna búsqueda activa (ni tuya ni de la ronda) y pasan al menos PAUSA_S segundos desde la anterior.
- Respeta el reparto de eBay: no lanza nada cuando las llamadas del día pasan de lo que se reserva a las automáticas (ebay_cuota: 3.000 de 5.000; las 2.000 restantes son tuyas).
- Cada carta, como mucho una vez cada REPETIR_H horas; si ya hay una búsqueda guardada de ella más reciente (la tuya), no se repite.
- Las búsquedas de la ronda no avisan de «terminada» (serían decenas al día): solo avisan los chollos (avisos.py).
El servidor llama a tick() cada 90 s. Estado en data/state/caza.json: {"activa", "actual", "jobs", "hechas", "motivo"}."""
import re, time, os
from common import P, load, save

ESTADO = P("state", "caza.json"); CAMPANAS = P("state", "campanas.json"); PAUSA_S = 90; REPETIR_H = 24; RECURRENTES_D = 0; RESERVA_NOCHE = 500
# Fernando, 7 nov: «no me parece bien que mire todo el rato las búsquedas que ya hemos hecho; esas peticiones se pueden gastar en otras cosas». Antes: cada carta se volvía a buscar cada 24 h y las búsquedas guardadas
# cada 3 días (con la comprobación de todos sus anuncios otra vez). Ahora: los grails cada 24 h (son pocos y importan); lo descubierto en los sets antiguos, una vez por semana; y las guardadas NO se repiten solas (RECURRENTES_D = 0).
REPETIR_DESCUBIERTAS_H = 168

def campana(nombre, consultas, depth="full"):
    """Añade una campaña: [(clave, texto de búsqueda)…], todas completas por defecto; si ya existe con ese nombre se amplía (lo hecho se conserva)."""
    camp = load(CAMPANAS, []) or []; c = next((x for x in camp if x["nombre"] == nombre), None)
    if not c: c = {"nombre": nombre, "depth": depth, "consultas": [], "hechas": {}}; camp.append(c)
    vistas = {x["clave"] for x in c["consultas"]}; c["consultas"] += [{"clave": k, "q": q} for k, q in consultas if k not in vistas]; save(CAMPANAS, camp); return len(c["consultas"])
RAREZA = re.compile(r"\s+(special illustration rare|illustration rare|ultra rare|secret rare|hyper rare|double rare|holo rare|rare holo|rare|uncommon|common|promo|amazing rare|radiant rare|shiny rare)\s*$", re.I)

def estado(**kw):
    s = load(ESTADO, {}) or {}
    if kw: s.update(kw); save(ESTADO, s)
    return s

def es_auto(jid): return jid in (estado().get("jobs") or [])

def consulta(e):
    """El texto de búsqueda de una carta de la cola: nombre y número, y el set."""
    if e.get("busqueda") and not re.search(r"\d+/\d+", e["nombre"]): return e["busqueda"]
    n = RAREZA.sub("", e["nombre"].split(" · ")[0]).strip()
    resto = (e["nombre"].split(" · ")[1] if " · " in e["nombre"] else (e.get("set") or "").replace("-", " "))
    return re.sub(r"\s+", " ", f"{n} {RAREZA.sub('', resto)}").strip()

def objetivos():
    """Lo que se caza, por orden: los grails que da Fernando y después lo descubierto en los sets antiguos, de más a menos caro."""
    import referencia as RF
    try: import par; mio = par.mio
    except Exception: mio = lambda k: True      # con el par activo, cada carta se caza solo en el ordenador de su dueño
    return [e for e in RF.objetivos() if e["prio"] in (0, 3) and mio(e["clave"])]

def _tick_web(s, new_job, slug, motivo):
    """La caza SIN eBay: busca la siguiente carta (grails primero, después lo descubierto en sets antiguos) solo en los demás mercados (japoneses, europeos y americanos, con el navegador oculto), así los tres
    buscadores de la Oficina no se quedan parados cuando eBay no deja más llamadas. Con su propia memoria de lo hecho (hechas_web): cada carta, como mucho una vez al día (grails) o a la semana."""
    hw = s.get("hechas_web") or {}; ahora = time.time()
    for e in objetivos():
        rep = (REPETIR_H if e["prio"] == 0 else REPETIR_DESCUBIERTAS_H) * 3600
        if ahora - hw.get(e["clave"], 0) < rep: continue
        q = consulta(e); j = new_job("text", None, q, "full", sin_ebay=True); hw[e["clave"]] = ahora
        estado(actual=e["nombre"] + " (sin eBay)", consulta=q, motivo=f"{motivo}; sigue en los demás mercados", ultimo=ahora, hechas_web=hw, jobs=((s.get("jobs") or []) + [j["id"]])[-300:],
               lanzadas_web_hoy=(s.get("lanzadas_web_hoy", 0) if s.get("dia_web") == time.strftime("%Y-%m-%d") else 0) + 1, dia_web=time.strftime("%Y-%m-%d")); return
    estado(actual=None, motivo=f"{motivo}; y ya ha buscado todo en los demás mercados")

def tick(new_job, active_jobs, slug):
    s = estado()
    if s.get("activa") is False: return
    if active_jobs(): estado(actual=None, motivo="espera a que acabe la búsqueda en marcha"); return
    if time.time() - s.get("ultimo", 0) < PAUSA_S: return
    try:
        import ebay_cuota as Q; v = Q.vista()
        # De noche (00:00-08:00) no hace falta guardar las 2.000 llamadas para tus búsquedas: duermes, y lo que sobre se pierde cuando eBay reinicia el contador (a las 09:00 de Madrid).
        # Fernando (5 nov): «planeo dejarlo por la noche encendido; que estén currando de noche». De noche solo se guardan RESERVA_NOCHE.
        noche = 0 <= time.localtime().tm_hour < 8; limite = v["total"] - RESERVA_NOCHE if noche else v["ritmo_hasta"]      # de día, al ritmo del reparto del día (ebay_cuota.ritmo_hasta): ya no se gasta todo de golpe por la mañana
        if v["usado"] >= limite:
            # Fernando, 7 nov: «los buscadores no pueden estar parados; aunque no haya cupo de eBay tienen que seguir buscando». Sin eBay, la caza sigue en los demás mercados (navegador, sin gastar llamadas de eBay).
            agotado = v["usado"] >= (v["total"] - RESERVA_NOCHE if noche else v["automaticas_hasta"])
            return _tick_web(s, new_job, slug, "eBay agotado hoy" if agotado else f"eBay al ritmo del día: {v['usado']} de las {limite} que tocan ahora")
    except Exception as ex: print("caza cuota:", ex)
    hechas = s.get("hechas") or {}; ahora = time.time()
    # Campañas (Fernando, 5 nov: «el set Double Crisis, búsqueda buena buena, todo el set»): una lista de búsquedas COMPLETAS, de una en una, antes que la ronda normal. data/state/campanas.json
    camp = load(CAMPANAS, []) or []
    for c in camp:
        for it in c["consultas"]:
            if it["clave"] in (c.get("hechas") or {}): continue
            j = new_job("text", None, it["q"], c.get("depth") or "full"); c.setdefault("hechas", {})[it["clave"]] = ahora; save(CAMPANAS, camp)
            try: import referencia as RF; RF.encolar(it["q"])      # y el Tasador va a por el precio de esa carta
            except Exception: pass
            hechos = sum(len(x.get("hechas") or {}) for x in camp); total = sum(len(x["consultas"]) for x in camp)
            estado(actual=f"{c['nombre']}: {it['q']}", consulta=it["q"], motivo=f"campaña «{c['nombre']}», {len(c['hechas'])} de {len(c['consultas'])}", ultimo=ahora, jobs=((s.get("jobs") or []) + [j["id"]])[-300:], campana=f"{hechos}/{total}"); return
    for e in objetivos():
        rep = (REPETIR_H if e["prio"] == 0 else REPETIR_DESCUBIERTAS_H) * 3600
        if ahora - hechas.get(e["clave"], 0) < rep: continue
        q = consulta(e); f = P("app", "searches", slug(q) + ".json")
        if os.path.exists(f) and ahora - os.path.getmtime(f) < rep: hechas[e["clave"]] = ahora; continue      # ya hay una búsqueda reciente (la tuya)
        j = new_job("text", None, q, "light"); hechas[e["clave"]] = ahora
        estado(actual=e["nombre"], consulta=q, motivo=None, ultimo=ahora, hechas=hechas, jobs=((s.get("jobs") or []) + [j["id"]])[-300:], lanzadas_hoy=(s.get("lanzadas_hoy", 0) if s.get("dia") == time.strftime("%Y-%m-%d") else 0) + 1, dia=time.strftime("%Y-%m-%d"))
        return
    # Recurrencia: las búsquedas guardadas de texto (las tuyas) que llevan RECURRENTES_D días sin repetirse se vuelven a lanzar solas, para que la base de búsquedas tenga su evolución en el tiempo
    import glob
    for f in (sorted(glob.glob(P("app", "searches", "*.json")), key=os.path.getmtime) if RECURRENTES_D else []):      # (apagado: RECURRENTES_D = 0)
        d = load(f, {}) or {}; clave = "s-" + str(d.get("id"))
        if d.get("kind") != "text" or not d.get("query") or ahora - os.path.getmtime(f) < RECURRENTES_D * 86400 or ahora - hechas.get(clave, 0) < RECURRENTES_D * 86400: continue
        j = new_job("text", None, d["query"], "light"); hechas[clave] = ahora
        estado(actual=d["query"], consulta=d["query"], motivo="repite una búsqueda de hace días", ultimo=ahora, hechas=hechas, jobs=((s.get("jobs") or []) + [j["id"]])[-300:]); return
    estado(actual=None, motivo="todo buscado en las últimas 24 h")
