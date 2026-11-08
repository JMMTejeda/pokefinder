"""El interruptor general de la Oficina (Jesús, 7 de noviembre de 2026: "un botón arriba a la derecha que sea empezar... pasa de rojo a verde y los agentes
empiezan a trabajar hasta que yo diga que paren").

Rojo (parado): ningún agente arranca solo. El servidor no lanza la foto de eBay, los estados, las ventas, la revisión diaria, la caza, el Tasador, la cola de
podcasts, el vídeo de la noche, el Cronista, el par ni los avisos de salud. Lo que ya estaba corriendo termina su vuelta y no empieza otra.
Las búsquedas que pides TÚ en la pestaña Búsquedas siguen funcionando: son una orden tuya.
Verde (trabajando): todo vuelve a su horario de siempre.

Estado en data/state/interruptor.json ({"activo": true|false, "cuando": "..."}). Sin ese fichero cuenta como VERDE, para que en el ordenador de
Fernando nada cambie hasta que él lo pulse."""
import json, os, time
from common import P

FICHERO = P("state", "interruptor.json")
_cache = {"t": 0.0, "v": True}

def estado():
    try:
        with open(FICHERO, encoding="utf-8") as f: d = json.load(f)
    except (OSError, ValueError): d = {}
    return {"activo": bool(d.get("activo", True)), "cuando": d.get("cuando")}

def activo():
    """Lo preguntan los bucles del servidor; se relee como mucho cada 5 s."""
    if time.time() - _cache["t"] > 5: _cache.update(t=time.time(), v=estado()["activo"])
    return _cache["v"]

def esperar(paso=15):
    """Bloquea el bucle que lo llama mientras el interruptor esté en rojo."""
    while not activo(): time.sleep(paso)

def poner(on):
    """Enciende o apaga TODO. Además de dejar el fichero, enciende/apaga los agentes que tienen su propio interruptor en la Oficina."""
    on = bool(on)
    os.makedirs(os.path.dirname(FICHERO), exist_ok=True)
    with open(FICHERO, "w", encoding="utf-8") as f: json.dump({"activo": on, "cuando": time.strftime("%Y-%m-%d %H:%M")}, f)
    _cache.update(t=time.time(), v=on)
    import oficina as OF
    hecho = []
    for pid, que in (("tasador", "lanzar" if on else "apagar"), ("cazador", "lanzar" if on else "apagar"),
                     ("revision_diaria", "encender" if on else "apagar"), ("podcast_cola", "encender" if on else "apagar")):
        try: OF.accion(pid, que); hecho.append(pid)
        except Exception as e: hecho.append(f"{pid} (no: {e})")
    try: OF.registrar("servidor", "EMPEZAR: los agentes trabajan" if on else "PARAR: ningún agente arranca solo", evento="manual")
    except Exception: pass
    return {"ok": True, "activo": on, "mensaje": ("En marcha: los agentes vuelven a su horario" if on else "Parado: ningún agente arranca solo hasta que pulses Empezar"), "agentes": hecho}
