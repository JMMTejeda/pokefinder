/* One listing page (app_images.py): its main photo, and whether it can really be bought today.
   Mercari and Rakuma are opened on Buyee, the way the owner buys them from Spain. Waits for the page's own scripts.
   buy: "yes" (an enabled buy / cart / bid button and nothing blocking), "no" (gone, sold, blocked, or no buy button on a site
   whose button is known), "unknown" (page read but no clear sign either way). */
(async()=>{
const H=location.hostname.replace(/^www\./,'');
const BADIMG=/logo|icon|sprite|avatar|badge|flag|placeholder|opengraph-image|default|banner|favicon|\/static\/media\/|spacer|noimage|loading|dummy|\.svg(\?|$)/i;
// buy buttons per site (text of an enabled button or link); KNOWN: sites where a missing button means it cannot be bought
const BUY={
  'buyee.jp':/add to (shopping )?cart|proceed to order|bid now|place (a )?bid|snipe it|buy it now|buy now|カートに入れる|入札する|購入手続き/i,
  'snkrdunk.com':/購入する|購入手続き|今すぐ購入|カートに入れる|購入へ進む/,
  'magi.camp':/購入手続き|購入する|カートに入れる|今すぐ購入/,
  'cardrush-pokemon.jp':/カートに入れる|カートに追加/,
  'hareruya2.com':/カートに追加|カートに入れる|add to cart/i,
  'fril.jp':/購入に進む|購入手続き|購入する/,
  'jp.mercari.com':/購入手続きへ|Buyeeで購入/,
  'vinted.es':/^comprar$|buy now/i, 'es.wallapop.com':/^comprar$|hacer oferta|^chat$/i,
  'alt.xyz':/buy now|place bid|make offer|place a bid/i, 'fanaticscollect.com':/buy now|place bid|make offer|bid now/i,
  'goldin.co':/place bid|bid now|buy now|make offer/i, 'ebay.es':/c[oó]mpralo ya|pujar|buy it now|place bid|hacer oferta/i,
  'ebay.com':/buy it now|place bid|make offer/i,
  'item.rakuten.co.jp':/買い物かごに入れる|かごに追加|ご購入手続きへ|今すぐ購入/,   // Rakuten Ichiba (26 October 2026)
};
// sites whose buy button has a fixed id (their menus also say "Comprar", even on sold items)
const SEL={'vinted.es':'[data-testid="item-buy-button"]'};
const KNOWN=/buyee\.jp|snkrdunk|magi\.camp|cardrush|hareruya2|fril\.jp|mercari|vinted|item\.rakuten/;
// HARD: the page says it cannot be bought, whatever buttons it shows. SOFT: gone or sold words, trusted only when there is no buy
// button (descriptions often say things like 売り切れ次第終了). Both are searched near the top of the page, before "similar items".
const HARD=/cannot be (purchased|ordered)|can'?t be (purchased|ordered)|unable to (purchase|order)|not available for (purchase|order)|has not logged in|seller.{0,40}inactive|inactive.{0,40}seller|this item (has been|was) (deleted|removed)|page not found|ページが見つかりません|お探しのページ|購入できません|出品停止|公開停止|この商品は削除/i;
const SOFT=/this (item|auction|listing) (has )?(been )?(ended|closed|sold)|auction (has )?ended|out of stock|sold out|no longer available|売り切れ|在庫なし|品切れ|取引中|販売終了|オークションは終了|vendido|reservado|ya no está disponible|sold for|bidding (has )?closed/i;
const CUT=/you may also like|similar items|この商品を見ている人|関連商品|似ている商品|おすすめ商品|también te puede|related (items|listings)/i;
// shown on the page (not a size check: a background tab has no layout)
const visible=e=>e.checkVisibility?e.checkVisibility({visibilityProperty:true,opacityProperty:true}):getComputedStyle(e).display!=='none';
const off=e=>e.disabled||e.getAttribute('aria-disabled')==='true'||/(^|[\s_-])disabled?($|[\s_-])/i.test(String(e.className||''))||getComputedStyle(e).pointerEvents==='none';
const buyRe=BUY[H]||(Object.entries(BUY).find(([k])=>H.endsWith(k))||[])[1]||/buy|purchase|cart|bid|comprar|購入|カート/i;
let best=null,btn=null,dead=null,head='';
for(let t=0;t<14;t++){
  const og=(document.querySelector('meta[property="og:image"],meta[name="twitter:image"]')||{}).content;
  const imgs=[...document.querySelectorAll('img')].map(i=>({s:i.getAttribute('data-src')||i.currentSrc||i.src||'',a:(i.naturalWidth||i.width)*(i.naturalHeight||i.height)})).filter(x=>x.s&&!x.s.startsWith('data:')&&!BADIMG.test(x.s)&&x.a>40000).sort((a,b)=>b.a-a.a);
  best=(og&&!BADIMG.test(og))?og:(imgs[0]||{}).s||null;
  const cands=[...document.querySelectorAll(SEL[H]||'button,a,input[type=submit],[role=button]')].filter(e=>{
    const tx=(e.textContent||e.value||e.getAttribute('aria-label')||'').trim();
    return tx&&tx.length<40&&buyRe.test(tx)&&(SEL[H]||visible(e))});
  btn=cands.find(e=>!off(e))||null; dead=!btn&&cands.length?cands[0]:null;
  const main=document.querySelector('main,#main,[role=main]')||document.body;
  head=document.title+' \n '+(main?main.innerText:'');
  const cut=head.search(CUT); head=head.slice(0,cut>0?cut:2500).slice(0,2500);
  if(best&&t>=2&&(btn||HARD.test(head)||SOFT.test(head)))break;
  await new Promise(r=>setTimeout(r,700));
}
const hard=head.match(HARD)||(/\b404\b|not found/i.test(document.title)?['404']:null),soft=head.match(SOFT);
let buy,reason=null;
if(hard){buy='no';reason=hard[0]}
else if(btn){buy='yes'}
else if(dead){buy='no';reason='botón de compra desactivado'}
else if(soft){buy='no';reason=soft[0]}
else if(KNOWN.test(H)){buy='no';reason='sin botón de compra'}
else buy='unknown';
return JSON.stringify({blocked:false,img:best?new URL(best,location.href).href:null,gone:buy==='no',buy,reason,button:btn?(btn.innerText||btn.value||'').trim().slice(0,40):null,host:H,title:document.title.slice(0,120)});
})()
