/* GempireCards listings search (owner, 15 October 2026): it lists eBay worldwide (ebay.com, including sellers that do not ship to
   Spain, which ebay.es hides) plus some other auction houses. The page needs the normal viewport (it fails to load with the tall one).
   Each card is a.ebay-card; data-watch-key is "<marketplace>:<id>". Only .ebay-title is the title (the ☆ in the card is the watch button). */
for(let i=0;i<25;i++){if(document.querySelectorAll('.ebay-card').length||/No (listings|results) found/i.test(document.body.innerText))break;await new Promise(r=>setTimeout(r,1000))}
await new Promise(r=>setTimeout(r,1000));
for(const c of document.querySelectorAll('a.ebay-card')){const wk=((c.querySelector('[data-watch-key]')||{}).dataset||{}).watchKey||'';const m=wk.match(/^(\w+):(.+)$/);
const mk=m?m[1]:'other',id=m?m[2]:(c.href.match(/itm\/(\d+)/)||[])[1];if(!id)continue;
const q=s=>clean((c.querySelector(s)||{}).textContent);
add((mk==='ebay'?'':mk+'_')+id,mk==='ebay'?'https://www.ebay.es/itm/'+id:c.href.split('?')[0],q('.ebay-title'),q('.ebay-price'),'on sale',
 'via Gempire; '+(mk!=='ebay'?mk+'; ':'')+[q('.ebay-sale-row'),q('.ebay-listing-location'),q('.ebay-listing-added')].filter(Boolean).join('; '))}
