for(const a of document.querySelectorAll('a[href*="/items/"]')){const m=a.href.match(/\/items\/(\d+)/);if(!m)continue;const t=clean(up(a,/¥/).innerText);const pm=t.match(/¥\s?([\d,]+)/);
add('magi'+m[1],a.href.split('?')[0],t.replace(/¥\s?[\d,]+.*$/,''),pm?'¥'+pm[1]:'',(/SOLD|売り切れ|売切/.test(t)||SOLDRE.test(up(a,/¥/).outerHTML))?'sold':'on sale','')}
