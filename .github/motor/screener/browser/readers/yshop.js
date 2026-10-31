/* Yahoo! Shopping Japan (many small card shops; Yahoo! JAPAN itself is closed to European visitors) read through Buyee
   ("JDirectItems Shopping"), added 26 October 2026. Each item has a photo link and a title link to /item/jdirectitems/shopping/<shop>_<code>;
   titles are Buyee's English translation ("Pokemon Card Regice ☆ Gold Star 033/086 ..."), price "50,000 YEN". */
for(let i=0;i<15&&!document.querySelector('a[href*="/item/jdirectitems/shopping/"]')&&!/\b0 results|no results|No items|見つかりません/i.test(document.body.innerText);i++)await new Promise(r=>setTimeout(r,1000));
await new Promise(r=>setTimeout(r,1500));
const YG=new Map();for(const a of document.querySelectorAll('a[href*="/item/jdirectitems/shopping/"]')){const h=a.getAttribute('href').split('?')[0].replace(/^https:\/\/buyee\.jp/,'');if(!/^\/item\/jdirectitems\/shopping\/[^/]+$/.test(h))continue;const g=YG.get(h)||{t:'',a};const tx=clean(a.innerText);if(tx.length>g.t.length){g.t=tx;g.a=a}YG.set(h,g)}
for(const [h,g] of YG){if(!g.t)continue;const box=up(g.a,/YEN/,4);const pm=clean(box.innerText).match(/([\d,]+)\s*YEN/);const shop=(h.split('/').pop().split('_')[0])||'';
add('ys_'+h.split('/').pop(),'https://buyee.jp'+h,g.t,pm?'¥'+pm[1]:'',SOLDRE.test(box.innerHTML)?'sold':'on sale','Yahoo! Shopping via Buyee; shop '+shop)}
