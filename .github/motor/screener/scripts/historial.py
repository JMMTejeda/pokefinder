"""eBay history in Parquet files, queried with DuckDB (SQL). Free and local: nothing is sent anywhere.

mercado.py keeps only the last KEEP_DAYS snapshots as JSON; this keeps every listing of every day, one file per day: data/historial/fecha=AAAA-MM-DD.parquet.
Columns: fecha, clave (card or search key), etiqueta, grupo, item_id, titulo, precio_eur, mercado (eBay site), pais, vendedor, subasta, gradeada, foto.
Only the tracks asked that day are written (the ones inherited from an earlier day by mercado._heredar are skipped, so no listing is counted twice).
mercado._cerrar calls exportar() after saving a snapshot; it never raises, so a missing duckdb never stops the daily snapshot.
Usage: python historial.py --volcar                  (writes the Parquet files of every JSON snapshot already in data/mercado)
       python historial.py --resumen                 (days, listings and cards in the history)
       python historial.py --sql "SELECT ... FROM fotos ..."   (the view `fotos` reads all the days)"""
import glob, json, os, sys
from common import P, load

DIR = os.environ.get("PF_HISTORIAL") or P("historial")   # PF_HISTORIAL: another folder, to try the tab with made-up data
COLS = "fecha DATE, clave VARCHAR, etiqueta VARCHAR, grupo VARCHAR, item_id VARCHAR, titulo VARCHAR, precio_eur DOUBLE, mercado VARCHAR, pais VARCHAR, vendedor VARCHAR, subasta BOOLEAN, gradeada BOOLEAN, foto VARCHAR"

def _rows(snap):
    date = snap["date"]
    for key, t in (snap.get("tracks") or {}).items():
        if t.get("fecha", date) != date: continue
        for iid, it in (t.get("items") or {}).items():
            yield (date, key, t.get("label"), t.get("group"), iid, it.get("t"), it.get("e"), it.get("m"), it.get("c"), it.get("s"),
                   bool(it.get("a")), bool(it.get("g")), it.get("i"))

def exportar(snap):
    """Writes (or rewrites) the Parquet file of the snapshot's day. Returns the number of listings, or None if it could not."""
    try:
        import duckdb
        rows = list(_rows(snap))
        if not rows: return 0
        os.makedirs(DIR, exist_ok=True)
        out = os.path.join(DIR, f"fecha={snap['date']}.parquet"); tmp = out + ".tmp"
        con = duckdb.connect()
        con.execute(f"CREATE TABLE d ({COLS})")
        con.executemany("INSERT INTO d VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        if os.path.exists(out):   # a second snapshot the same day (another collection, "Hacer foto ahora"): keep the cards it did not ask again
            con.execute("INSERT INTO d SELECT * FROM read_parquet(?) WHERE clave NOT IN (SELECT unnest(?::VARCHAR[]))", [out.replace(chr(92), "/"), sorted({r[1] for r in rows})])
        con.execute(f"COPY d TO '{tmp.replace(chr(92), '/')}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        con.close(); os.replace(tmp, out)   # swapped in whole, like common.save: a query never meets a half-written file
        return len(rows)
    except Exception as e:
        print("historial:", e); return None

def conectar():
    import duckdb
    con = duckdb.connect()
    files = glob.glob(os.path.join(DIR, "*.parquet"))
    if files: con.execute("CREATE VIEW fotos AS SELECT * FROM read_parquet('" + os.path.join(DIR, "*.parquet").replace(chr(92), "/") + "')")
    return con

def cartas():
    """[{clave, etiqueta, grupo, dias, ultima, anuncios}] of everything in the history, for the price-history tab."""
    if not glob.glob(os.path.join(DIR, "*.parquet")): return []
    rows = conectar().execute("SELECT clave, any_value(etiqueta), any_value(grupo), count(DISTINCT fecha), max(fecha)::VARCHAR, count(*) FROM fotos GROUP BY clave ORDER BY any_value(grupo), any_value(etiqueta)").fetchall()
    return [{"clave": c, "etiqueta": e, "grupo": g, "dias": d, "ultima": u, "anuncios": n} for c, e, g, d, u, n in rows]

def serie(clave, dias=90):
    """One point per day for a card: listings, minimum, median and quartiles of the price in euros. Like mercado.sospechosos, listings under 7 % of that day's
    median (accessories, proxies) are left out when the day has 15 or more."""
    if not glob.glob(os.path.join(DIR, "*.parquet")): return []
    sql = """WITH d AS (SELECT fecha, precio_eur FROM fotos WHERE clave = ? AND precio_eur IS NOT NULL AND fecha >= current_date - CAST(? AS INTEGER)),
             m AS (SELECT fecha, median(precio_eur) AS med, count(*) AS n FROM d GROUP BY fecha),
             l AS (SELECT d.fecha, d.precio_eur FROM d JOIN m USING (fecha) WHERE m.n < 15 OR d.precio_eur >= 0.07 * m.med)
             SELECT fecha::VARCHAR, count(*), min(precio_eur), median(precio_eur), quantile_cont(precio_eur, 0.25), quantile_cont(precio_eur, 0.75) FROM l GROUP BY fecha ORDER BY fecha"""
    return [{"fecha": f, "n": n, "min": round(a, 2), "med": round(b, 2), "p25": round(c, 2), "p75": round(d, 2)} for f, n, a, b, c, d in conectar().execute(sql, [clave, int(dias)]).fetchall()]

# ---------------------------------------------------------------- podcast transcripts (owner, 3 November 2026: "se van almacenando en duckdb?")
# One Parquet per episode in data/transcripciones_db/ with one row per phrase: podcast, fecha, titulo, segundo, minuto, texto. The JSON of the episode stays as it is (the app reads it);
# the Parquet is for questions across episodes: when was a card named, what did they say about it in September, which month talked most about Gold Stars.
DIR_T = os.environ.get("PF_TRANSCRIPCIONES_DB") or P("transcripciones_db")

def _min(s): s = int(s); return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"

def exportar_transcripcion(ruta, podcast=None):
    """Writes (or refreshes) the Parquet of one transcript JSON. Returns the number of phrases, or None if it could not. Never raises."""
    try:
        import duckdb
        j = json.load(open(ruta, encoding="utf-8")); seg = j.get("segmentos") or []
        if not seg: return 0
        if not podcast:
            try:
                import podcasts; podcast = next((f["nombre"] for f in podcasts.feeds() if f["url"] == j.get("feed")), None)
            except Exception: podcast = None
        podcast = podcast or (os.path.basename(ruta).split("-ep")[0].replace("-", " ").title() if j.get("feed") is None else "?")
        os.makedirs(DIR_T, exist_ok=True); out = os.path.join(DIR_T, os.path.splitext(os.path.basename(ruta))[0] + ".parquet")
        if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(ruta): return -1      # already up to date
        con = duckdb.connect(); con.execute("CREATE TABLE t (podcast VARCHAR, fecha DATE, titulo VARCHAR, segundo INTEGER, minuto VARCHAR, texto VARCHAR)")
        con.executemany("INSERT INTO t VALUES (?,?,?,?,?,?)", [(podcast, j.get("fecha"), j.get("titulo"), int(s), _min(s), str(x)) for s, x in seg])
        tmp = out + ".tmp"; con.execute(f"COPY t TO '{tmp.replace(chr(92), '/')}' (FORMAT PARQUET, COMPRESSION ZSTD)"); con.close(); os.replace(tmp, out)
        return len(seg)
    except Exception as e:
        print("historial transcripcion:", e); return None

def volcar_transcripciones():
    """Every transcript JSON of data/transcripciones and notas/transcripciones into its Parquet (the ones already up to date are skipped). Returns how many were written."""
    from common import ROOT
    n = 0
    for d in (os.path.join(ROOT, "data", "transcripciones"), os.path.join(ROOT, "notas", "transcripciones")):
        for f in sorted(glob.glob(os.path.join(d, "*.json"))):
            r = exportar_transcripcion(f)
            if r and r > 0: n += 1
    return n

def buscar(texto, desde=None, podcast=None, limite=60):
    """Phrases of the transcripts that contain texto (ignoring case and accents), newest first: [{podcast, fecha, titulo, minuto, segundo, texto}]."""
    if not glob.glob(os.path.join(DIR_T, "*.parquet")): return []
    import duckdb
    con = duckdb.connect(); con.execute("CREATE VIEW frases AS SELECT * FROM read_parquet('" + os.path.join(DIR_T, "*.parquet").replace(chr(92), "/") + "')")
    sql = "SELECT podcast, fecha::VARCHAR, titulo, minuto, segundo, texto FROM frases WHERE strip_accents(lower(texto)) LIKE '%' || strip_accents(lower(?)) || '%'"; args = [texto]
    if desde: sql += " AND fecha >= CAST(? AS DATE)"; args.append(desde)
    if podcast: sql += " AND podcast = ?"; args.append(podcast)
    sql += " ORDER BY fecha DESC, segundo LIMIT ?"; args.append(int(limite))
    return [dict(zip(("podcast", "fecha", "titulo", "minuto", "segundo", "texto"), r)) for r in con.execute(sql, args).fetchall()]

def volcar():
    """Backfill: every JSON snapshot still in data/mercado (AAAA-MM-DD.json)."""
    from mercado import DIR as MD
    ds = sorted(f for f in os.listdir(MD) if len(f) == 15 and f.endswith(".json")) if os.path.isdir(MD) else []
    for f in ds: print(f[:-5], exportar(load(os.path.join(MD, f), {}) or {}), "anuncios")
    if not ds: print("No hay fotos en data/mercado todavía.")

if __name__ == "__main__":
    a = sys.argv[1:]
    if "--volcar-podcasts" in a: print("transcripciones escritas:", volcar_transcripciones())
    elif "--buscar" in a:
        for r in buscar(a[a.index("--buscar") + 1])[:15]: print(f"{r['fecha']} {r['podcast']} [{r['minuto']}] {r['texto'][:110]}")
    elif "--volcar" in a: volcar()
    elif "--resumen" in a:
        con = conectar()
        if not glob.glob(os.path.join(DIR, "*.parquet")): print("Todavía no hay historial: se crea con la primera foto diaria de eBay.")
        else:
            d, n, c, desde, hasta = con.execute("SELECT count(DISTINCT fecha), count(*), count(DISTINCT clave), min(fecha), max(fecha) FROM fotos").fetchone()
            print(f"{d} días ({desde} a {hasta}), {n} anuncios, {c} cartas")
    elif "--sql" in a:
        con = conectar()
        for r in con.execute(a[a.index("--sql") + 1]).fetchall(): print(r)
    else: print(__doc__)
