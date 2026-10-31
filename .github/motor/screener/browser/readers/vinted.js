for(const a of document.querySelectorAll('a[href*="/items/"]')){const id=(a.href.match(/\/items\/(\d+)/)||[])[1];if(!id)continue;const t=clean(a.getAttribute('title')||a.innerText);const pm=t.match(/([\d.,]+)\s?€/g)||[];
add('vi'+id,a.href.split('?')[0],t.split(', Marca:')[0],pm[0]||'',/vendido|reservado|sold/i.test(t)?'sold':'on sale',pm[1]?'price including Vinted buyer fee: '+pm[1]:'')}
