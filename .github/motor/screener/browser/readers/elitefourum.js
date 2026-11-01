await new Promise(r=>setTimeout(r,3000));
for(const r of document.querySelectorAll('.fps-result')){const a=r.querySelector('a.search-link');if(!a)continue;const m=a.href.match(/\/t\/([^/]+)\/(\d+)/);if(!m)continue;
const slug=m[1].toLowerCase(),cats=[...r.querySelectorAll('a')].map(x=>x.getAttribute('href')||'').join(' ');const tm=+((r.querySelector('[data-time]')||{}).dataset||{}).time||0;
if(!/\/c\/buy-section/.test(cats)||!/(^|-)(wts|fs|ft-fs|for-sale|selling|sale)(-|$)/.test(slug)||/(^|-)wtb(-|$)/.test(slug)||(tm&&Date.now()-tm>90*864e5))continue;
const t=clean(r.innerText),pm=t.match(/(?:\$|USD\s?)\s?([\d,]+(?:\.\d\d)?)/);
add('ef'+m[2],'https://www.elitefourum.com/t/'+m[1]+'/'+m[2],slug.replace(/-/g,' '),pm?'$'+pm[1]:'','on sale','Elite Fourum sale thread (collectors forum: price and shipping by message with the seller)')}
