"""Contador y reparto de las llamadas diarias a eBay (owner, 3 November 2026: "quiero tener yo el control sobre las búsquedas que se hacen en eBay, no llegar por la tarde sin peticiones").
eBay allows 5,000 Browse API calls a day, counted from midnight Pacific time (09:00 in Madrid in winter, I believe: not checked with eBay). They were spent by whatever ran first: the snapshot of 8:27 and the
seller-condition reader took them before the searches the owner asks for. Now every call is written down here with what asked for it, and the AUTOMATIC ones (the daily snapshot and the condition reader)
can only use what is left after RESERVA_MANUAL, kept for the searches the owner starts himself (the app's searches, «busca esto»).
Each call is one line in data/state/ebay_llamadas/<eBay day>.txt (appending one short line is safe between processes: the server, the engine and the snapshot are different processes).
  python ebay_cuota.py        -> what was spent today"""
import collections, datetime as dt, os, sys, time
from common import P

TOTAL = 5000            # eBay's daily limit for the Browse API (each owner has his own keys, so his own count: this file only counts the calls of THIS computer)
RESERVA_MANUAL = 2000   # nothing automatic can touch these: they are for the searches the owner asks for
try:    # each owner can set his own in data/mercado/config.json: {"ebay_cuota": {"total": 5000, "reserva_manual": 2000}} (his eBay account may have another limit)
    import json as _j
    _c = (_j.load(open(os.path.join(P("mercado"), "config.json"), encoding="utf-8")).get("ebay_cuota") or {})
    TOTAL = int(_c.get("total", TOTAL)); RESERVA_MANUAL = min(TOTAL, int(_c.get("reserva_manual", RESERVA_MANUAL)))
except (OSError, ValueError, TypeError): pass
AUTOMATICOS = ("foto", "estados")      # the origins that wait when only the reserve is left
ORIGENES = {"manual": "Búsquedas que pides tú", "foto": "Foto diaria del mercado", "estados": "Estado de las cartas (vendedor)", "imagenes": "Fotos y precios de anuncios"}

def dia():
    """eBay's day: the date in Pacific time."""
    from zoneinfo import ZoneInfo
    return dt.datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()

def _ruta(d=None): return os.path.join(P("state", "ebay_llamadas"), (d or dia()) + ".txt")

def registrar(origen, n=1):
    """One line per call: «HH:MM:SS origen». Never raises (counting must not break a search)."""
    try:
        os.makedirs(os.path.dirname(_ruta()), exist_ok=True)
        with open(_ruta(), "a", encoding="utf-8") as f: f.write((time.strftime("%H:%M:%S ") + origen + "\n") * n)
    except OSError: pass

def gastado(d=None):
    c = collections.Counter()
    try:
        with open(_ruta(d), encoding="utf-8") as f:
            for l in f:
                p = l.split()
                if len(p) == 2: c[p[1]] += 1
    except OSError: pass
    return c

def ritmo_hasta():
    """Lo que las llamadas AUTOMÁTICAS pueden haber gastado ya, a esta hora del día de eBay (Fernando, 7 nov: «antes no se paraba en todo el día; ahora se agota y se para»). Antes las automáticas
    (estado de las cartas, fotos de anuncios, la caza) se gastaban las 3.000 en las 2 primeras horas tras el reinicio y luego la caza se paraba 20 horas. Ahora se reparten: 10 % nada más reiniciar y el resto
    en línea recta hasta el final del día de eBay (medianoche del Pacífico)."""
    from zoneinfo import ZoneInfo
    n = dt.datetime.now(ZoneInfo("America/Los_Angeles")); frac = (n.hour * 3600 + n.minute * 60 + n.second) / 86400
    return int((TOTAL - RESERVA_MANUAL) * (0.10 + 0.90 * frac))

def permitido(origen):
    """False when an AUTOMATIC origin would eat into the reserve of the owner's searches, or is ahead of the day's pace (ritmo_hasta). The owner's own (and the rest) are only stopped by eBay itself."""
    if origen not in AUTOMATICOS: return True
    c = gastado(); return sum(c.values()) < min(TOTAL - RESERVA_MANUAL, ritmo_hasta())

def vista():
    c = gastado(); usado = sum(c.values())
    return {"dia": dia(), "total": TOTAL, "usado": usado, "quedan": max(0, TOTAL - usado), "reserva_manual": RESERVA_MANUAL,
            "automaticas_hasta": TOTAL - RESERVA_MANUAL, "ritmo_hasta": min(TOTAL - RESERVA_MANUAL, ritmo_hasta()), "origenes": [{"id": k, "nombre": v, "n": c.get(k, 0)} for k, v in ORIGENES.items()] + [{"id": k, "nombre": k, "n": n} for k, n in c.items() if k not in ORIGENES]}

if __name__ == "__main__":
    v = vista(); print(f"eBay, día {v['dia']} (hora del Pacífico): {v['usado']} de {v['total']} llamadas; quedan {v['quedan']}; reservadas para ti: {v['reserva_manual']}")
    for o in v["origenes"]: print(f"  {o['nombre']}: {o['n']}")
