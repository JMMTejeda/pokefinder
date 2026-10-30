/* PokéFinder's search engine inside the phone page (owner, 28 October 2026: "with only PokéFinder open on the phone, in Safari, the
   search must finish and be done as it should, without Claude and without anything else").
   Same reading of a search and same title rules as the computer's engine: motor.plan_spec / exact_card (Python) -> planSpec /
   exactCard, app_job.matcher / goldstar_rule -> matcher. The patterns themselves come from Python (nube.engine_data, D.engine), so
   both stay the same; nube.py build puts this file inside the page. eBay is searched through the site's own API (/api/ebay: the eBay
   keys stay on Cloudflare); the card's identity, picture and Cardmarket prices come from pokemontcg.io and TCGdex (open to any page).
   What only the computer does (Mercari, SNKRDUNK... the photo checks, the grade on the label) is added when the app is open there.
   Regexes are built without the "u" flag: Python's re.escape writes "\ " and "\-", which JavaScript only accepts without it.
   Test: node cloud/engine_test.js (compares with the Python rules on every saved title). */
function makeEngine(E, opts = {}) {
  // Safari before iOS 16.4 has no lookbehind "(?<!x)" and stops at the first rule that uses one (owner, 29 October 2026: the phone
  // search failed before asking eBay anything). Every lookbehind in the rules is "not right after one character of a set", which
  // "(start or one character outside the set)" says the same way for a yes/no match
  const LOOKBEHIND = !opts.noLookbehind && (() => { try { return new RegExp("(?<!a)b").test("b"); } catch { return false; } })();
  const flat = (p) => (LOOKBEHIND ? p : p.replace(/\(\?<!(\\d|\[[^\]]*\])\)/g, (_, x) => (x === "\\d" ? "(?:^|\\D)" : "(?:^|[^" + x.slice(1, -1) + "])")));
  const RX = (p, f = "i") => new RegExp(flat(p), f);
  const esc = (s) => String(s).replace(/[.*+?^${}()|[\]\\\/-]/g, "\\$&");
  const KANA = "ァ-ヴー";
  const nameRe = (n) => (RX(`[${KANA}]`).test(n) ? esc(n) + `(?=スター|ゴールドスター|[^${KANA}]|$)` : "(?<![A-Za-z])" + esc(n) + "(?![A-Za-z])");
  const plain = (s) => s.normalize("NFKD").replace(/[^\x00-\x7f]/g, "");
  const NAMES = [...E.names].sort((a, b) => b.en.length - a.en.length);   // "Mr. Mime" before "Mime"
  const FILLER = new Set(E.filler);
  const LANGS = Object.entries(E.langs);
  const LANG_WORD = { es: "español", en: "english", fr: "français", de: "deutsch", it: "italiano" };
  const ACCESSORY = RX(E.accessory), LOTWORD = RX(E.lotword), GS_FAKE = RX(E.gs_fake), GS_MODERN = RX(E.gs_modern);
  const NOT_A_CARD = RX(E.not_a_card, "gi");
  const TRACKED = Object.entries(E.tracked).map(([p, pat]) => [p, RX(pat)]);
  const FIRST_ED = RX(E.first_ed), UNLIMITED = RX(E.unlimited);
  const titleCase = (s) => s.replace(/\w\S*/g, (w) => w[0].toUpperCase() + w.slice(1).toLowerCase());

  /* ---- the search typed (motor.plan_spec) */
  function planSpec(query) {
    let q = query.normalize("NFKC").trim();
    const toks = q.toLowerCase().match(/[^\s,.;]+/g) || [];
    let lang = null;
    for (const [c, [, ws]] of LANGS) if (toks.some((w) => ws.includes(w))) { lang = c; break; }
    const drop = new Set([...FILLER, ...LANGS.flatMap(([, [, ws]]) => ws)]);
    q = q.split(/\s+/).filter((w) => !drop.has(w.toLowerCase().replace(/^[,.;]+|[,.;]+$/g, ""))).join(" ") || q;
    const low = q.toLowerCase();
    const poke = [], jaNames = [], alias = {};
    for (const p of NAMES) {
      if (!RX(`(?<![a-z])${esc(p.en.toLowerCase())}(?![a-z])`, "").test(low) || poke.some((x) => x.includes(p.en))) continue;
      poke.push(p.en); jaNames.push(p.ja);
      const key = p.en.toLowerCase().split(/\s+/)[0];
      const a = [p.ja, ...[p.fr, p.de, p.es].filter((n) => n && n.toLowerCase() !== p.en.toLowerCase())];
      alias[key] = a.concat(a.filter((n) => n && plain(n) && plain(n) !== n && plain(n).toLowerCase() !== p.en.toLowerCase()).map(plain));   // sellers drop the accents
    }
    const words = low.match(/[^\s]+/g) || [];
    const qja = [...jaNames];
    for (const w of words) {
      if (/^#?\d+\/\w+$/.test(w)) qja.push(w.replace(/^#/, "").toUpperCase());
      else if (E.words_ja[w] && !qja.includes(E.words_ja[w])) qja.push(E.words_ja[w]);
      if (w === "masaki") (alias[w] = alias[w] || []).push("マサキ");
    }
    const hasJa = /[぀-ヿ一-鿿]/.test(q);
    const lead = poke.map((p) => p.toLowerCase());
    const rest = lead.length ? low.replace(RX(lead.map(esc).join("|"), "g"), " ") : low;
    const en = [...lead, ...rest.split(/\s+/).filter(Boolean)].join(" ");
    const spec = { en, ja: jaNames[0] || (hasJa ? q : ""), qja: jaNames.length ? qja.join(" ") : hasJa ? q : "", q, poke, alias, must: [], not: [] };
    if (lang) {
      spec.lang = lang; spec.must = [E.langs[lang][0]];
      if (lang !== "ja") { spec.ja = ""; spec.qja = ""; spec.extra_q = [`${en} ${LANG_WORD[lang]}`]; }
    }
    if (/gold\s*star|goldstar/.test(low) && !/celebrations|25th|anniversary|classic/.test(low)) { spec.goldstar = true; spec.not = [...E.gs_not]; }
    return spec;
  }

  /* ---- the exact card a search names (carta.py) */
  const cache = (k, v) => { try { if (v === undefined) return JSON.parse(localStorage.getItem(k) || "null"); localStorage.setItem(k, JSON.stringify(v)); } catch { return null; } };
  async function getJSON(url, ms = 20000) {
    const ac = new AbortController(), t = setTimeout(() => ac.abort(), ms);
    try { const r = await fetch(url, { signal: ac.signal }); return r.ok ? await r.json() : null; } catch { return null; } finally { clearTimeout(t); }
  }
  async function cardsOf(poke) {   // every English-print card of the Pokémon on pokemontcg.io, kept a week on the phone
    const k = "pf_cards_" + poke.toLowerCase(), hit = cache(k);
    if (hit && Date.now() - hit.at < 7 * 86400e3) return hit.cards;
    const d = await getJSON("https://api.pokemontcg.io/v2/cards?" + new URLSearchParams({ q: `name:"${poke}*"`, select: "id,name,number,set,images,cardmarket", pageSize: "250" }));
    if (!d) return hit ? hit.cards : null;
    const cards = (d.data || []).map((c) => ({ id: c.id, name: c.name, number: c.number, set: c.set.name, set_id: c.set.id, total: c.set.printedTotal,
      image: (c.images || {}).large || (c.images || {}).small, small: (c.images || {}).small, cm: c.cardmarket || null }));
    cache(k, { at: Date.now(), cards });
    return cards;
  }
  async function setNames(id, en) {   // the set's names in other languages (TCGdex): "EX Gardiens du Pouvoir"
    const k = "pf_set_" + id, hit = cache(k);
    if (hit) return hit;
    const out = [en];
    const got = await Promise.all(["fr", "de", "es", "it", "pt"].map((l) => getJSON(`https://api.tcgdex.net/v2/${l}/sets/${id}`, 12000)));
    for (const d of got) if (d && d.name && !out.includes(d.name)) out.push(d.name);
    cache(k, out);
    return out;
  }
  const words = (s) => (s.toLowerCase().match(/[a-z0-9]+/g) || []).filter((w) => !["ex", "the", "and", "of", "pokemon", "pokémon"].includes(w));
  async function identify(spec, cards) {
    const poke = (spec.poke || [])[0];
    if (!poke || !cards) return null;
    const q = (spec.q || spec.en || "").toLowerCase(), qw = new Set(words(q));
    let found = [];
    for (const c of cards) {
      const sw = words(c.set);
      const setHit = sw.length > 0 && sw.every((w) => qw.has(w));
      const numHit = c.total ? RX(`(?<!\\d)0*${esc(c.number)}\\s*/\\s*0*${c.total}(?!\\d)|#\\s*0*${esc(c.number)}(?!\\d)`).test(q) : false;
      if (setHit || numHit) found.push([setHit + numHit, c]);
    }
    if (!found.length) return null;
    const best = Math.max(...found.map(([s]) => s));
    found = found.filter(([s]) => s === best).map(([, c]) => c);
    const plainCards = found.filter((c) => c.name.toLowerCase() === poke.toLowerCase());
    if (found.length > 1 && plainCards.length && !/\bex\b|δ|delta|★|☆|star/.test(q.replaceAll("stamp", ""))) found = plainCards;
    if (new Set(found.map((c) => c.set_id + "|" + c.number)).size !== 1) return null;
    const c = { ...found[0] };
    c.set_names = await setNames(c.set_id, c.set);
    c.stamped = RX(E.stamp).test(q); c.reverse = RX(E.reverse).test(q);
    return c;
  }
  function cardMust(card) {
    const sets = [...new Set(card.set_names.map((n) => n.replace(/^ex\s+/i, "")))].sort((a, b) => b.length - a.length);
    const alts = sets.map((n) => n.split(/\s+/).map(esc).join("\\s*"));
    alts.push(`(?<!\\d)0*${esc(card.number)}\\s*/\\s*0*${card.total}(?!\\d)`);
    return alts.join("|");
  }
  async function exactCard(spec, cards) {
    let card = null;
    try { card = await identify(spec, cards); } catch { card = null; }
    if (!card || spec.goldstar) return spec;
    spec = { ...spec, card };
    const setw = new Set(card.set_names.flatMap(words));
    spec.en = spec.en.split(" ").filter((w) => !setw.has(w) && !/^#?\d+\/\d+$/.test(w)).join(" ") || spec.en;
    spec.must = [...(spec.must || []), cardMust(card)];
    if (card.stamped) spec.not = [...(spec.not || []), "\\b(?:no|non|not|sin|without|sans|ohne)[\\s-]*(?:stamp|stamped|sello|tampon)\\w*|\\bunstamped\\b"];
    if ((spec.poke || []).map((p) => p.toLowerCase()).includes(card.name.toLowerCase())) {   // the plain card: not its ex, GX, V, δ... versions
      const names = [card.name, ...(spec.alias[card.name.toLowerCase().split(/\s+/)[0]] || [])];
      spec.not = [...spec.not, `(?:${names.map(esc).join("|")})[\\s-]*(?:ex|gx|v|vmax|vstar|lv\\.?\\s*x|δ|delta|break|prime|legend)\\b`];
    }
    return spec;
  }

  /* ---- which titles are the card (app_job.matcher, goldstar_rule) */
  function pokemonIn(title, extra = []) {
    const t = String(title || "").replace(NOT_A_CARD, " ");
    const out = TRACKED.filter(([, rx]) => rx.test(t)).map(([p]) => p);
    for (const n of extra) if (n && RX(nameRe(n)).test(title || "") && !out.includes(titleCase(n))) out.push(titleCase(n));
    return out;
  }
  let OTHERS = {};
  function otherPokemon(mine) {
    const key = [...mine].sort().join("|");
    if (!OTHERS[key]) {
      const en = [...new Set(E.names.filter((p) => !mine.has(p.en) && p.en.length > 2).map((p) => p.en))].sort((a, b) => b.length - a.length);
      const ja = [...new Set(E.names.filter((p) => !mine.has(p.en) && p.ja).map((p) => p.ja))].sort((a, b) => b.length - a.length);
      OTHERS = { [key]: `(?:(?<![a-z])(?:${en.map(esc).join("|")})(?![a-z])|(?<![${KANA}])(?:${ja.map(esc).join("|")})(?![${KANA}]))` };
    }
    return OTHERS[key];
  }
  function goldstarRule(spec) {
    const poke = spec.poke || [];
    const names = [...new Set(poke.flatMap((p) => [p, ...(spec.alias[p.toLowerCase()] || [])]).filter(Boolean))].sort((a, b) => b.length - a.length);
    if (!names.length) return (t) => !GS_FAKE.test(t) && !GS_MODERN.test(t);
    const nm = `(?:${names.map(esc).join("|")})`;
    const named = RX(`(?<![a-z])${nm}(?![a-z])`), star = RX(E.gs_star);
    const nums = poke.flatMap((p) => E.numbers[p] || []);
    const own = nums.length ? RX(nums.map(esc).join("|")) : null;
    const others = otherPokemon(new Set(poke));
    const mineStar = RX(`(?<![a-z])${nm}(?![a-z])(?:[\\s,&+/・、]+${others}){0,3}[\\s\\-:・()（）]{0,3}(?:holo\\s*)?${E.gs_star}`);
    const otherStar = RX(`${others}[\\s\\-:・()（）]{0,3}(?:holo\\s*)?${E.gs_star}`);
    const modernName = RX(`(?<![a-z])${nm}\\s*(?:ex|gx|v|vmax|vstar)(?![a-z])`);
    return (t) => {
      let u = t.replace(/bl[a-z]{0,2}ck\s*star|ブラックスター|shining\s*star|シャイニースター|star\s*wars|starter|スターター/gi, " ");
      u = u.replace(/\bex\s+(?:deoxys|team\s*rocket|unseen|delta|dragon|holon|legend|crystal|power|emerald|hidden|firered|ruby|sandstorm)|gift\s*b(?:o)?x\s*mew|ギフトボックス\s*ミュウ/gi, " ");
      if (!named.test(u) || GS_FAKE.test(u) || GS_MODERN.test(u) || modernName.test(u)) return false;
      if (!(star.test(u) || (own && own.test(u)))) return false;
      return !(otherStar.test(u) && !mineStar.test(u));
    };
  }
  function matcher(spec) {
    let ws = spec.en.toLowerCase().split(/\s+/).filter((w) => w && !["pokemon", "pokémon", "card", "carta", "tcg"].includes(w));
    if (spec.goldstar) ws = ws.filter((w) => !["gold", "star", "goldstar"].includes(w));
    const req = ws.map((w) => {
      const m = w.match(/^#?(\d+)\/(\d+)$/);
      const pat = m ? `(?<!\\d)0*${+m[1]}\\s*/\\s*0*${+m[2]}(?!\\d)` : E.syn[w] ?? nameRe(w);
      return RX([pat, ...((spec.alias || {})[w] || []).map((x) => nameRe(x.toLowerCase()))].join("|"));
    });
    req.push(...(spec.must || []).map((m) => RX(m)));
    const bad = (spec.not || []).map((m) => RX(m));
    if (!ACCESSORY.test(spec.en + " " + (spec.q || ""))) bad.push(ACCESSORY);
    const named = ws.filter((w) => !/^#?\d+\/\d+$/.test(w) && !(w in E.syn));
    if (named.length) bad.push(RX(`\\b(?:no|not|non)\\b(?!\\.?\\s*\\d)[^|/]{0,30}?(?<![A-Za-z])(?:${named.map(esc).join("|")})(?![A-Za-z])`));
    const mine = new Set(spec.poke || []);
    const stuffed = (t) => pokemonIn(t).filter((p) => !mine.has(p)).length >= 2 && !LOTWORD.test(t);   // another card's title padded with famous names
    const gold = spec.goldstar ? goldstarRule(spec) : () => true;
    const ok = (t) => { t = t || ""; return req.every((r) => r.test(t)) && !bad.some((r) => r.test(t)) && !stuffed(t) && gold(t); };
    // a reprint, fake or product word in any title the listing goes by (eBay's sites translate titles: "Celebrazioni")
    ok.bad = (t) => bad.some((r) => r.test(t || "")) || (!!spec.goldstar && (GS_FAKE.test(t || "") || GS_MODERN.test(t || "")));
    return ok;
  }

  /* ---- an eBay result -> a page listing (ebay_api.row + app_lib.from_page_row, in the page's short form) */
  const GRADE = RX(`\\b(${E.graders})\\s*-?\\s*(\\d+(?:\\.\\d)?)(\\s*(?:以下|or lower|o menos))?`);
  const toEur = (v, cur) => (cur === "EUR" ? Math.round(v * 100) / 100 : E.fx[cur] ? Math.round((v / E.fx[cur]) * 100) / 100 : null);
  function region(iso) {
    if (!iso) return "OTHER";
    if (iso === "GB") return "UK";
    if (E.eu.includes(iso)) return "EU";
    if (iso === "JP") return "JP";
    return E.am.includes(iso) ? "AM" : "OTHER";
  }
  function listing(it, spec, ali) {
    const id = it.itemId && it.itemId.includes("|") ? it.itemId.split("|")[1] : it.legacyItemId || it.itemId;
    const t = it.title || "", opts = it.buyingOptions || [], auction = opts.includes("AUCTION");
    const pr = auction && it.currentBidPrice ? it.currentBidPrice : it.price;
    const v = pr && pr.value != null ? parseFloat(pr.value) : null, cur = pr && pr.currency;
    const from = pr && pr.convertedFromCurrency ? [pr.convertedFromCurrency, parseFloat(pr.convertedFromValue)] : [cur, v];
    const g = t.match(GRADE), grader = g ? g[1].toUpperCase().replace("BECKETT", "BGS") : null;
    const iso = (it.itemLocation || {}).country || null;
    const poke = (spec.poke || []).filter((x) => ali[x].some((n) => RX(nameRe(n)).test(t)));
    const end = it.itemEndDate ? new Date(it.itemEndDate) : null;
    const l = { i: "ebay:" + id, t, u: "https://www.ebay.es/itm/" + id, p: v == null ? null : toEur(v, cur),
      o: from[0] && from[0] !== "EUR" && from[1] != null ? `${from[0]} ${from[1].toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : null,
      s: "eBay", r: region(iso), c: iso, g: g ? (g[3] ? `${grader} ≤${g[2]}` : `${grader} ${g[2]}`) : null, gr: grader,
      sa: auction ? "auction" : "buy", n: 1, k: [...poke, ...pokemonIn(t).filter((x) => !poke.includes(x))],
      a: auction ? `${it.bidCount || 0} pujas` + (end && !isNaN(end) ? " · termina " + end.toLocaleString("es-ES", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "") : null,
      f: new Date().toISOString().slice(0, 19), x: ((it.image || {}).imageUrl || "").replace(/\/s-l\d+\./, "/s-l500.") || null,
      e: FIRST_ED.test(t) && !UNLIMITED.test(t) ? "1st Edition" : UNLIMITED.test(t) && !FIRST_ED.test(t) ? "Unlimited" : "not stated" };
    for (const k of Object.keys(l)) if (l[k] == null || l[k] === "" || (Array.isArray(l[k]) && !l[k].length)) delete l[k];
    return l;
  }
  function aliases(spec) {   // app_job.build: each Pokémon of the search and the names it goes by
    const poke = spec.poke || [], al = spec.alias || {};
    return Object.fromEntries(poke.map((p) => [p, [p, ...(al[p.toLowerCase()] || []), ...(poke.length === 1 ? al[spec.en.toLowerCase().split(" ")[0]] || [] : [])]]));
  }

  /* ---- Cardmarket: today's prices of the card (pokemontcg.io carries Cardmarket's price guide), with a link to its offers */
  const CM_LANG = { en: 1, fr: 2, de: 3, es: 4, it: 5, ja: 7 }, LANG_NAME = { es: "español", en: "inglés", fr: "francés", de: "alemán", it: "italiano", ja: "japonés" };
  const money = (v) => v.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " €";
  function cardmarket(spec, cards) {
    if (!cards || spec.lang === "ja") return [];   // Japanese prints are not on pokemontcg.io
    let pick = [];
    if (spec.card) pick = cards.filter((c) => c.id === spec.card.id);
    else if (spec.goldstar) pick = cards.filter((c) => /★|☆|\bstar\b/i.test(c.name) && !/celebrations|classic collection/i.test(c.set));
    const poke = (spec.poke || [])[0];
    return pick.filter((c) => c.cm && c.cm.prices).map((c) => {
      const pr = c.cm.prices, rev = spec.card && (spec.card.stamped || spec.card.reverse);
      const low = (rev ? pr.reverseHoloLow : pr.lowPrice) || null, trend = (rev ? pr.reverseHoloTrend : pr.trendPrice) || null;
      if (low == null && trend == null) return null;
      const known = E.cm_urls[c.id], lang = spec.lang;
      const url = known ? known + (CM_LANG[lang] ? `?language=${CM_LANG[lang]}` : "") : (c.cm.url || "https://www.cardmarket.com/es/Pokemon/Products/Search?searchString=" + encodeURIComponent(c.name));
      return { i: "cardmarket:" + c.id, t: `${c.name}${rev ? " (reverse holo)" : ""} · ${c.set}`, u: url, p: low ?? trend, s: "Cardmarket", r: "EU", sa: "buy",
        k: [poke], x: c.small || c.image, cmt: "desde " + (low != null ? money(low) : "—") + (trend ? " · tendencia " + money(trend) : ""),
        cml: known && LANG_NAME[lang] ? LANG_NAME[lang] : undefined, f: (c.cm.updatedAt || "").replace(/\//g, "-") };
    }).filter(Boolean);
  }

  /* ---- the whole search. call(q, market, offset) asks eBay through the site; tick(progress, message) shows the bar */
  async function search(query, call, tick) {
    tick(4, "Leyendo la búsqueda…");
    let spec = planSpec(query);
    const poke = (spec.poke || [])[0];
    const cards = poke ? await cardsOf(poke) : null;   // to find the card it names, and its Cardmarket prices
    const asked = spec.en;
    spec = await exactCard(spec, cards);
    const qs = [...new Set([asked, spec.en, spec.ja, ...(spec.extra_q || [])].filter(Boolean))];
    const tasks = qs.flatMap((q) => E.markets.map((m) => [q, m]));
    tick(10, spec.card ? `Carta: ${spec.card.name} · ${spec.card.set} ${spec.card.number}/${spec.card.total}. Buscando en eBay (${E.markets.length} países)…` : `Buscando en eBay (${E.markets.length} países)…`);
    const ok = matcher(spec), ali = aliases(spec);
    // every copy of each listing (one per eBay site that returned it): the first in the order searched is kept, as the computer does
    // (app_job.cmd_ebay: eBay US first, in English); eBay Italy or Poland show the same US listing with a machine-translated title
    const copies = new Map();
    let done = 0, seen = 0, failed = 0, limited = 0;
    // eBay allows the app 5,000 searches a day (shared with the computer's engine): one page of 200 per eBay site, two on the
    // three biggest; a call that fails for a moment is tried again, eBay's daily limit (429) is not
    const BIG = ["EBAY_US", "EBAY_GB", "EBAY_DE"];
    const ask = async (q, m, offset) => {
      // a refusal (429) is waited out once too: right after eBay's daily renewal it still refused for some minutes (29 October 2026)
      for (let n = 0; n < 2; n++) {
        try { return await call(q, m, offset); } catch (e) {
          if (e.status === 429 && n === 1) { limited++; return null; }
          await new Promise((r) => setTimeout(r, e.status === 429 ? 4000 : 2500));
        }
      }
      return null;
    };
    const one = async ([q, m], ti) => {
      for (let offset = 0; offset < (BIG.includes(m) ? 400 : 200); offset += 200) {
        const d = await ask(q, m, offset);
        if (!d) { failed++; break; }
        const items = d.itemSummaries || [];
        seen += items.length;
        items.forEach((it, k) => {
          const id = it.itemId && it.itemId.includes("|") ? it.itemId.split("|")[1] : it.legacyItemId || it.itemId;
          const rank = ti * 1000 + offset + k;
          if (!copies.has(id)) copies.set(id, []);
          copies.get(id).push([rank, it]);
        });
        if (items.length < 200 || offset + 200 >= (d.total || 0)) break;
      }
      done++;
      tick(10 + Math.round((done / tasks.length) * 80), `Buscando en eBay: ${done} de ${tasks.length} búsquedas · ${E.markets.length} países`);
    };
    const queue = tasks.map((t, i) => [t, i]);
    await Promise.all(Array.from({ length: 6 }, async () => { while (queue.length) await one(...queue.shift()); }));
    tick(92, "Comprobando anuncios…");
    const L = [];
    for (const cs of copies.values()) {
      cs.sort((a, b) => a[0] - b[0]);
      const first = cs[0][1];
      if (!ok(first.title) || cs.some(([, it]) => ok.bad(it.title))) continue;
      const priced = cs.find(([, it]) => (it.currentBidPrice || it.price || {}).value != null);
      L.push(listing({ ...(priced ? priced[1] : first), title: first.title }, spec, ali));
    }
    if (spec.goldstar) {   // motor.check_photos: an ungraded copy at a tenth of the cheapest graded one is a reprint, a fake or a wreck
      const graded = L.filter((l) => l.gr && l.p && l.sa !== "auction").map((l) => l.p);
      const floor = graded.length ? Math.min(...graded) * 0.1 : null;
      for (const l of L) if (floor && !l.gr && l.p && l.p < floor && l.sa !== "auction") l.pw = 1;
    }
    const cm = cardmarket(spec, cards);
    for (const c of cm) if (!c.x) { const g = L.find((l) => l.x && !l.pw); if (g) c.x = g.x; }
    const all = [...L, ...cm].sort((a, b) => (a.p == null) - (b.p == null) || (a.p || 0) - (b.p || 0));
    return { spec, listings: all, seen, failed, limited, total: tasks.length };
  }

  return { LOOKBEHIND, flat, planSpec, exactCard, identify, cardMust, matcher, goldstarRule, pokemonIn, listing, aliases, cardmarket, search, cardsOf };
}
if (typeof module !== "undefined") module.exports = { makeEngine };
