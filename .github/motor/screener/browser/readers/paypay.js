/* PayPay Flea Market (Yahoo! JAPAN's flea market, closed to European visitors) read through Buyee ("JDirectItems Fleamarket"),
   added 26 October 2026. Each result is li.list in ul.item-lists; the photo's alt text is the seller's own Japanese title (the
   card text is Buyee's English translation); price "400,000 YEN". Buyee shows only items for sale by default. */
for(let i=0;i<15&&!document.querySelector('ul.item-lists li.list')&&!/\b0 results|No items|見つかりません/i.test(document.body.innerText);i++)await new Promise(r=>setTimeout(r,1000));
for(const li of document.querySelectorAll('ul.item-lists li.list')){const a=li.querySelector('a[href*="/paypayfleamarket/item/"]');if(!a)continue;
const id=(a.getAttribute('href').match(/\/item\/([a-z0-9]+)/i)||[])[1];if(!id)continue;const img=li.querySelector('img');const t=clean(li.innerText);const pm=t.match(/([\d,]+)\s*YEN/);
const en=t.replace(/[\d,]+\s*YEN.*$/,'').trim();
add('pp_'+id,'https://buyee.jp/paypayfleamarket/item/'+id,(img&&img.alt)||en,pm?'¥'+pm[1]:'',SOLDRE.test(li.innerHTML)?'sold':'on sale','PayPay Flea Market via Buyee; '+en.slice(0,90))}
