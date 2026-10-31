/* Buyee (Japanese proxy, ships to Spain) search page for Yahoo! Auctions Japan ("JDirectItems Auction"), which Yahoo itself blocks for
   European Union visitors. Full titles are in .itemCard__itemName; current price, buyout price, time left and bids in the card. */
for(let i=0;i<15&&!document.querySelector('li.itemCard')&&!/0 hits|No items found/i.test(document.body.innerText);i++)await new Promise(r=>setTimeout(r,1000));   // the page is slow to fill
for(const li of document.querySelectorAll('li.itemCard')){const a=li.querySelector('.itemCard__itemName a')||li.querySelector('a[href*="/item/"]');if(!a)continue;
const id=(a.getAttribute('href').match(/\/([a-z]?\d{6,})/i)||[])[1]||a.getAttribute('href');const prices=[...li.querySelectorAll('.g-priceDetails__item')].map(e=>clean(e.textContent));
const cur=(prices.find(p=>/Current Price/.test(p))||prices[0]||'').replace(/^Current Price\s*/,''),buyout=(prices.find(p=>/Buyout/.test(p))||'').replace(/^Buyout Price\s*/,'');
const info=[...li.querySelectorAll('.itemCard__infoItem')].map(e=>clean(e.textContent)).filter(Boolean).join(' | ');
add('yahoo_'+id,'https://buyee.jp'+a.getAttribute('href').split('?')[0],a.textContent,(cur.match(/[\d,]+\s*YEN/)||[''])[0].replace(/([\d,]+)\s*YEN/,'¥$1'),'on sale',
 'Yahoo! Auctions via Buyee; '+(buyout?'buyout '+buyout.replace(/\s*\(.*$/,'')+'; ':'')+info)}
