for(const a of document.querySelectorAll('a[href*="/item/"]')){if(!clean(a.innerText))continue;const id=(a.href.match(/-(\d+)(?:\?|$)/)||[])[1]||a.href;const t=clean(up(a,/€/).innerText);const pm=t.match(/([\d.,]+)\s?€/);
add('wp'+id,a.href.split('?')[0],clean(a.innerText),pm?pm[1]+' €':'',(/vendido|reservado/i.test(t)||SOLDRE.test(up(a,/€/).outerHTML))?'sold or reserved':'on sale','')}
