/* Mercari search page. The grid only draws the cells near the screen (the run sets a tall viewport), so the page is scrolled to the end
   and read as it goes. Since October 2026 a cell's text is only its price: the title is the image's alt text ("<title>のサムネイル"),
   cut with "…" after about 40 characters; such titles are completed later on the listing page (goldstar.py queues them). */
const mscan=()=>{for(const li of document.querySelectorAll('[data-testid="item-cell"]')){const a=li.querySelector('a[href*="/item/"],a[href*="/shops/product/"]');if(!a)continue;
const img=li.querySelector('img[alt]'),alt=img?img.alt.replace(/のサムネイル$/,''):'';const t=clean(li.innerText);if(!alt&&!/[^\d¥€.,\s]/.test(t))continue;
// yen, or euros when Mercari shows a visitor from Spain its own conversion ("€3.62", seen by the app's engine on 28 October 2026)
const pm=t.match(/([¥€])\s?([\d.,]+)/)||clean((li.querySelector('[data-testid="item-tile-price"]')||{}).textContent).match(/([¥€])\s?([\d.,]+)/);
const title=alt||t.replace(/^[¥€]\s?[\d.,]+/,'');
add(a.href.split('/').pop().split('?')[0],a.href.split('?')[0],title,pm?pm[1]+pm[2]:'',(/^SOLD/.test(t)||SOLDRE.test(li.innerHTML)||/sold/i.test((li.querySelector('[data-testid="thumbnail-sticker"]')||{}).textContent||''))?'sold':'on sale',/…$/.test(alt)?'title cut on the search page':'')}};
if(/mercari/.test(H)){for(let i=0;i<15;i++){mscan();const before=scrollY;window.scrollBy(0,3500);await new Promise(r=>setTimeout(r,700));if(scrollY===before)break}mscan();window.scrollTo(0,0)}
