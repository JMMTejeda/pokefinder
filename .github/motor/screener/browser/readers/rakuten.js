/* Rakuten Ichiba (Japan; hundreds of small card shops: toretoku, card-museum, realize-store, fullahead, Suruga-ya...), added
   26 October 2026. Each result is .searchresultitem; the longest link to item.rakuten.co.jp is the title; price "8,660 円". */
for(let i=0;i<10&&!document.querySelector('.searchresultitem')&&!/該当する商品が見つかりませんでした|0件/.test(document.body.innerText);i++)await new Promise(r=>setTimeout(r,1000));
for(const box of document.querySelectorAll('.searchresultitem')){const a=[...box.querySelectorAll('a[href*="item.rakuten.co.jp"]')].sort((x,y)=>clean(y.innerText).length-clean(x.innerText).length)[0];if(!a)continue;
const t=clean(box.innerText);const pm=t.match(/([\d,]+)\s*円/);const u=a.href.split('?')[0];const path=u.replace(/^https?:\/\/item\.rakuten\.co\.jp\//,'').replace(/\/$/,'');
add('rk_'+path.replace(/[^\w-]+/g,'_'),u,clean(a.innerText),pm?'¥'+pm[1]:'',/売り切れ|在庫なし|SOLD OUT/i.test(t)?'sold':'on sale','Rakuten Ichiba; shop '+path.split('/')[0])}
