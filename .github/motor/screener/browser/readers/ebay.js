for(const li of document.querySelectorAll('ul.srp-results > li')){if(li.className.includes('srp-river-answer')){if(/menos palabras|fewer words/i.test(li.textContent))break;continue}
const a=li.querySelector('a[href*="/itm/"]');if(!a)continue;const id=(a.href.match(/itm\/(\d+)/)||[])[1];
const title=((li.querySelector('.s-card__title')||{}).textContent||'').replace(/Se abre en una nueva ventana o pestaña|Opens in a new window or tab/g,'').replace(/^Anuncio nuevo|^Nuevo anuncio/,'');
const r=[...li.querySelectorAll('.s-card__attribute-row')].map(e=>clean(e.textContent));const price=r.find(x=>/^[\d.\s\u00a0\u202f]*\d,\d{2}\s?EUR/.test(x)&&!/env[ií]o/i.test(x))||'';
add(id,'https://www.ebay.es/itm/'+id,title,price,'on sale',r.filter(x=>x!==price).join(' | '))}
