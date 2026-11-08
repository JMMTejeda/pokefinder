"""Base de datos de las búsquedas (Fernando, 5 de noviembre de 2026: «que se guarden todas esas búsquedas como conocimiento y como base de datos de la parte de búsquedas»).
Cada vez que una búsqueda termina (la tuya o la de la ronda de caza) se apuntan dos cosas, en ficheros de líneas que DuckDB lee tal cual (read_json_auto):
- data/busquedas/resumen.jsonl: UNA línea por búsqueda y vez: qué se buscó, cuántos anuncios, por mercado, mínimo y mediana de lo que piden por nota (sin gradear, PSA 10…), cuántos bajo mercado.
- data/busquedas/anuncios.jsonl: cada anuncio visto con su precio; solo se apunta de nuevo si es nuevo o ha CAMBIADO de precio (así queda el historial de precios pedidos sin repetir miles de líneas).
Son precios que piden los vendedores, no ventas: ahí se ve cómo se mueve lo que hay a la venta, que es el mejor termómetro de cuándo aparece un chollo.
  from busquedas_db import archivar        archivar(search_id)      python busquedas_db.py --resumen [texto]"""
import collections, datetime as dt, json, os, statistics, sys
from common import P, load, save, TZ

DIR = P("busquedas"); RESUMEN = os.path.join(DIR, "resumen.jsonl"); ANUNCIOS = os.path.join(DIR, "anuncios.jsonl"); ULTIMO = os.path.join(DIR, "ultimo_precio.json")

def _nota(l):
    return f"{l['grader']} {l.get('grade') or ''}".strip() if l.get("grader") else "Sin gradear"

def archivar(search_id):
    """Apunta una búsqueda terminada. Devuelve (anuncios nuevos o con precio cambiado, total) o None si la búsqueda no existe."""
    import ventas
    s = load(P("app", "searches", search_id + ".json"), None)
    if not s: return None
    ventas.marcar(s); L = s.get("listings") or []; t = dt.datetime.now(TZ).isoformat(timespec="minutes"); os.makedirs(DIR, exist_ok=True)
    notas, sitios = collections.defaultdict(list), collections.Counter()
    for l in L:
        if l.get("price_eur") is not None and l.get("sale") != "auction": notas[_nota(l)].append(l["price_eur"])
        sitios[l.get("site_name") or l.get("site") or "?"] += 1
    por_nota = {k: {"n": len(v), "min": round(min(v), 2), "mediana": round(statistics.median(v), 2)} for k, v in notas.items() if v}
    bajo = sum(1 for l in L if (l.get("mercado") or {}).get("bajo"))
    with open(RESUMEN, "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": t, "search_id": search_id, "consulta": s.get("query") or s.get("label"), "tipo": s.get("kind"), "n": len(L), "mercados": dict(sitios), "por_nota": por_nota, "bajo_mercado": bajo}, ensure_ascii=False) + "\n")
    ult = load(ULTIMO, {}) or {}; nuevos = 0
    with open(ANUNCIOS, "a", encoding="utf-8") as f:
        for l in L:
            if l.get("price_eur") is None: continue
            k = f"{l.get('site')}:{l.get('id')}"
            if ult.get(k) == l["price_eur"]: continue
            ult[k] = l["price_eur"]; nuevos += 1; m = l.get("mercado") or {}
            f.write(json.dumps({"t": t, "search_id": search_id, "site": l.get("site"), "id": l.get("id"), "precio_eur": l["price_eur"], "titulo": (l.get("title") or "")[:120], "nota": _nota(l), "edicion": l.get("edition"),
                                "venta": l.get("sale"), "pct_mercado": m.get("pct"), "valor": m.get("valor"), "fuente_valor": (m.get("fuentes") or [None])[0]}, ensure_ascii=False) + "\n")
    save(ULTIMO, ult); return nuevos, len(L)

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if "--resumen" in sys.argv:
        q = " ".join(a for a in sys.argv[sys.argv.index("--resumen") + 1:]).lower()
        try:
            for ln in open(RESUMEN, encoding="utf-8"):
                d = json.loads(ln)
                if q in str(d.get("consulta")).lower(): print(d["t"], "|", d["consulta"], "|", d["n"], "anuncios |", d["bajo_mercado"], "bajo mercado |", {k: v["mediana"] for k, v in list(d["por_nota"].items())[:4]})
        except OSError: print("Todavía no hay búsquedas archivadas.")
    else: print(__doc__)
