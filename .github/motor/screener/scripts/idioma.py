"""Idioma de la carta de un anuncio, en Python: copia fiel de app/lang.js (la pantalla y los avisos del servidor tienen que clasificar igual).
Fernando, 4 de noviembre de 2026: «las quiero en inglés o japonés, casi por no decir siempre; no trabajamos otros idiomas».
Ningún mercado da el idioma como dato: se lee del título (palabra explícita, número solo japonés, kana) y, si no dice nada, del mercado.
Resultado: "ja" | "en" | "other" (alemán, francés, italiano, español, coreano, chino...) | "unk" (no lo dice).
Si se cambia app/lang.js, hay que cambiar esto igual: `python idioma.py --probar <búsqueda>` enseña el recuento para compararlo con la pantalla."""
import re

KANA = re.compile(r"[぀-ヿ]")
EN_WORDS = re.compile(r"\benglish\b|\bingl[eé]s\b|\banglais\b|\benglisch\b|\binglese\b|英語|英文|海外版|北米版|\bUS\s*version\b", re.I)
EN_CODES = re.compile(r"(?:^|[^A-Za-z])(?:ENG|EN)(?=$|[^A-Za-z])")
JA_WORDS = re.compile(r"japan\w*|japon\w*|japonais|japanisch|giapponese|日本語|日本版|国内版|\bnihongo\b", re.I)
JA_CODES = re.compile(r"(?:^|[^A-Za-z])(?:JPN|JP|JAP)(?=$|[^A-Za-z])")
JA_NUMBERS = re.compile(r"\d{2,3}\s*/\s*(?:L-?P|PLAY)\b", re.I)
OTHER_WORDS = re.compile(r"alem[aá]n|\bdeutsch\w*|\bgerman\b|franc[eé]s|\bfrench\b|fran[cç]ais|\bitalian\w*|\bitaliano\b|espa[ñn]ol|\bspanish\b|\bkorean\b|coreano|한국|\bchino\b|\bchinese\b|中文|繁體|简体|portugu[eê]s|\bthai\b|franz[öo]sisch|italienisch|spanisch", re.I)
OTHER_TEXT = re.compile(r"\b(?:carte|cartes|carta|cartas|tarjeta|tarjetas|karte|karten|kaart|kaarten|cart[ãa]o|cart[õo]es|figurine)\b|\b(?:rara|ultra\s+rara|olografica|olografico|mint\s+condition\s+ita|avec|tr[eè]s|bon\s+[eé]tat|[eé]tat|neuve?s?|occasion|vendu|d[eé]fectueu\w*|ab[iî]m[eé]\w*|lotto|usata|ottim\w*|condizioni|nuova|nuovo|buone|stato|spedizione|usado|usada|buen\s+estado|nuev[oa]s?|estado|env[ií]o|sehr|gebraucht|zustand|versand|kostenlos|und|mit|f[uü]r|bom\s+estado|novo|nova)\b|\s(?:et|con|para|per|di|del|della|dei|de|la|le|les|el|los|las|un|une|una|uno|der|die|das|ein|eine)\s(?=\S)", re.I)
OTHER_CODES = re.compile(r"(?:^|[^A-Za-z])(?:ITA|GER|DEU|FRA|KOR|DE|FR|IT|ES)(?=$|[^A-Za-z])")
OTHER_CODES_ANY_CASE = re.compile(r"(?:^|[^A-Za-z])(?:ita|ger|deu|fra|kor|esp)(?=$|[^A-Za-z])", re.I)
OTHER_COUNTRY = re.compile(r"^(?:IT|DE|FR|ES|PT|NL|PL|AT|CH|BE|KR|CN|TW|TH|BR|MX)$", re.I)
EN_SETS = re.compile(r"call\s*of\s*legends|\bSL\d{1,2}\b|\bHGSS\s*#?\d{1,2}\b|heart\s*gold|soul\s*silver|black\s*star\s*promo|unseen\s*forces|power\s*keepers|dragon\s*frontiers|delta\s*species|holon\s*phantoms|crystal\s*guardians|team\s*rocket\s*returns|legend\s*maker|hidden\s*legends", re.I)
JA_SETS = re.compile(r"gift\s*box|half\s*deck|constructed\s*starter|deck\s*kit|vending|masaki|carddass|\d{3}\s*/\s*016\b|\bPCG\b|\bADV\b|communication\s*evolution|legend\s*perfect\s*set|mirage\s*forest|golden\s*sky|rocket\s*gang|clash\s*(?:in|of)\s*the\s*(?:blue|azure)\s*sky|miracle\s*crystal|flight\s*of\s*legends", re.I)
EU_LOCAL = re.compile(r"vinted|wallapop|milanuncios|leboncoin|kleinanzeigen|subito", re.I)
JP_MARKETS = {"mercari", "rakuma", "magi", "cardrush", "snkrdunk", "hareruya2", "rakuten", "yuyutei", "mandarake", "clabo", "jauce", "buyee", "paypay", "yshop"}

def lang_of(l):
    t = str((l or {}).get("title") or "")
    kana = bool(KANA.search(t))
    en = bool(EN_WORDS.search(t) or EN_CODES.search(t))
    ja = kana or bool(JA_WORDS.search(t) or JA_CODES.search(t) or JA_NUMBERS.search(t))
    ot = bool(OTHER_WORDS.search(t) or OTHER_CODES.search(t) or OTHER_CODES_ANY_CASE.search(t) or OTHER_TEXT.search(t))
    if kana and en: return "en"
    if en and ja: return "unk"
    if en: return "unk" if ot else "en"
    if ja: return "unk" if ot else "ja"
    if ot: return "other"
    en_set, ja_set = bool(EN_SETS.search(t)), bool(JA_SETS.search(t))
    local = bool(EU_LOCAL.search(str((l or {}).get("site_name") or (l or {}).get("site") or ""))) or bool(OTHER_COUNTRY.search(str((l or {}).get("country") or "")))
    if en_set != ja_set: return ("unk" if local else "en") if en_set else "ja"
    return "ja" if (l or {}).get("site") in JP_MARKETS else "unk"

if __name__ == "__main__":
    import collections, json, os, sys
    sys.stdout.reconfigure(encoding="utf-8")
    if "--probar" in sys.argv:
        from common import P
        s = json.load(open(P("app", "searches", sys.argv[sys.argv.index("--probar") + 1] + ".json"), encoding="utf-8")); L = s.get("listings") or []
        langs = [lang_of(l) for l in L]
        # la misma firma que se calcula en el navegador con langOf, para comparar a mano
        firma = sum((i + 1) * ord(x[0]) for i, x in enumerate(langs)) % 1000003
        print(dict(collections.Counter(langs)), "| firma", firma)
