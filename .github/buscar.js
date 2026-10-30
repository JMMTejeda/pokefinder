/* The phone's search, run by GitHub Actions (buscar.yml) instead of in Safari through the Cloudflare Worker (owner, 30 October
   2026: Cloudflare is no longer free). Same engine (engine.js) with the same rules (engine.json = nube.engine_data, written by
   `nube.py publish`); eBay is asked directly with this repository's secrets. Writes api/results/<search id>.json like the
   Worker's /api/phone-results did; the page merges it on its next look at api/state.json. */
const fs = require("fs");
const { makeEngine } = require("./engine.js");

const E = JSON.parse(fs.readFileSync(".github/engine.json", "utf8"));
const query = (process.env.TITLE || "").replace(/^\s*Buscar:\s*/i, "").replace(/\s+/g, " ").trim().slice(0, 120);
const slug = (t) => "q-" + String(t).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 58);   // template.html slug

let tok = null;
async function token() {   // eBay application token (2 hours)
  if (tok) return tok;
  const clean = (s) => String(s || "").replace(/[^\x21-\x7e]/g, "");
  const r = await fetch("https://api.ebay.com/identity/v1/oauth2/token", { method: "POST",
    headers: { Authorization: "Basic " + Buffer.from(clean(process.env.EBAY_APP_ID) + ":" + clean(process.env.EBAY_CERT_ID)).toString("base64"),
      "Content-Type": "application/x-www-form-urlencoded" },
    body: "grant_type=client_credentials&scope=" + encodeURIComponent("https://api.ebay.com/oauth/api_scope") });
  if (!r.ok) throw new Error("eBay token " + r.status);
  return (tok = (await r.json()).access_token);
}
async function call(q, market, offset) {   // what the Worker's /api/ebay did: one Browse API search, seen from Spain
  const r = await fetch("https://api.ebay.com/buy/browse/v1/item_summary/search?" + new URLSearchParams({ q, limit: "200", offset: String(offset) }),
    { headers: { Authorization: "Bearer " + (await token()), "X-EBAY-C-MARKETPLACE-ID": market, "X-EBAY-C-ENDUSERCTX": "contextualLocation=country%3DES" } });
  if (!r.ok) throw Object.assign(new Error("eBay " + r.status), { status: r.status });
  return r.json();
}

(async () => {
  if (query.length < 2) throw new Error("búsqueda vacía");
  const id = slug(query), file = `api/results/${id}.json`;
  const out = await makeEngine(E).search(query, call, (p, m) => console.log(`${p}% ${m}`));
  if (out.failed === out.total) throw new Error(out.limited ? "eBay: límite diario de búsquedas" : "eBay no respondió");
  const L = out.listings, poke = out.spec.poke || [];
  let before = 0;
  try { before = (JSON.parse(fs.readFileSync(file, "utf8")).listings || []).length; } catch {}
  if (out.failed && before > L.length) { console.log("eBay no respondió a todo: se quedan los resultados anteriores"); return; }
  const now = new Date().toISOString().slice(0, 19);
  const meta = { id, kind: "text", group: null, query, label: query, updated: now, created: now, status: "done", phone: true,
    pokemon: poke.length > 1 ? poke : [], no_results: {}, count: L.length, cardmarket: [],
    min_eur: (L.find((l) => l.p != null && !l.pd && !l.pw) || {}).p ?? null, thumbs: L.filter((l) => l.x && !l.pw).slice(0, 4).map((l) => l.x) };
  fs.mkdirSync("api/results", { recursive: true });
  fs.writeFileSync(file, JSON.stringify({ at: Date.now(), by: "phone", request: "i" + process.env.NUMBER, search: meta, listings: L }));
  console.log(`${L.length} anuncios -> ${file}`);
})().catch((e) => { console.error(String(e && e.message || e)); process.exit(1); });
