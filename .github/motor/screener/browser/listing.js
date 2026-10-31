(async()=>{await new Promise(r=>setTimeout(r,3000));
/* Listing page check: is it still for sale (a working buy / cart / bid button and no sold notice), what the page says about delivery
   to Spain, and the main photo's address for the photo check. Reads only what is on screen. */
const T=document.title,B=document.body?document.body.innerText:'',H=location.hostname;const clean=s=>(s||'').replace(/\s+/g,' ').trim();
if(/Just a moment|Security Measure|Medida de seguridad|Pardon Our Interruption|Access Denied/i.test(T+' '+B.slice(0,400))||/captcha|challenge|signin\./i.test(location.href))return JSON.stringify({blocked:true,title:T});
const btns=[...document.querySelectorAll('button,a,input[type=submit]')].filter(b=>b.offsetParent!==null).map(b=>clean(b.innerText||b.value||'')).filter(s=>s&&s.length<40);
const BUY=/購入する|購入手続き|購入に進む|カートに(入れる|追加)|今すぐ購入|Cómpralo ya|Comprar(lo)?|Añadir a la cesta|Hacer oferta|Pujar|Buy now|Add to cart|Place bid|Bid now|Place a bid|Make offer/i;
const SOLDB=/売り切れ|SOLD ?OUT|在庫なし|販売終了|取引中|Vendido|Reservado|Agotado/i;
const buy=btns.filter(s=>BUY.test(s)).slice(0,4),soldb=btns.filter(s=>SOLDB.test(s)).slice(0,4);
const top=B.slice(0,4000);
const soldText=(top.match(/売り切れました|この商品は売り切れ|SOLD OUT|Este anuncio (ha )?finalizado|ya no est[aá] disponible|La puja ha finalizado|El vendedor ha finalizado|Este artículo se ha vendido|この商品は削除|Auction (has )?ended|Bidding (has )?(ended|closed)|This (item|lot) (has )?sold|Sold for \$/i)||[])[0]||null;
let ship=[];if(/ebay\./.test(H)){const s=clean((document.querySelector('.ux-labels-values--shipping')||{}).textContent);if(s)ship.push(s.slice(0,220));const imp=(B.match(/Tarifas de importaci[oó]n:?\s*\n?\s*([^\n]{1,90})/i)||[])[1];if(imp)ship.push('Import charges: '+imp)}
else{ship=(B.match(/[^\n]{0,30}(海外発送|海外配送|海外|international|overseas|国外|送料|配送方法|発送元|Env[ií]o|Entrega|Spain|España)[^\n]{0,90}/gi)||[]).map(clean).slice(0,6)}
const noSpain=/No (se )?realiza(n)? env[ií]os a:? ?Espa[ñn]a|no env[ií]a a Espa[ñn]a|Does(n't| not) ship to Spain|海外発送(は)?(不可|できません|しておりません)|海外への発送(は)?(不可|できません)/i.test(B);
const og=(document.querySelector('meta[property="og:image"]')||{}).content||null;const eb=document.querySelector('.ux-image-carousel-item.active img, .ux-image-carousel-item img');
const imgs=[...document.images].filter(i=>i.naturalWidth>=300).sort((a,b)=>b.naturalWidth*b.naturalHeight-a.naturalWidth*a.naturalHeight).slice(0,2).map(i=>i.currentSrc||i.src);
return JSON.stringify({blocked:false,title:clean(T).slice(0,140),available:(soldb.length||soldText)?false:(buy.length?true:null),buy,sold_buttons:soldb,sold_text:soldText,no_ship_to_spain:noSpain,ship,img:eb?(eb.getAttribute('data-zoom-src')||eb.src):(og||imgs[0]||null)})})()
