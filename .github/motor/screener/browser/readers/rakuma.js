for(const box of document.querySelectorAll('.item, .item-box')){const a=box.querySelector('a[href*="item.fril.jp"]');if(!a)continue;const t=clean(box.innerText);const pm=t.match(/¥\s?([\d,]+)/);
add(a.href.split('/').pop().split('?')[0],a.href.split('?')[0],t.replace(/SOLD OUT/,'').replace(/¥\s?[\d,]+.*$/,''),pm?'¥'+pm[1]:'',(/SOLD OUT/.test(t)||SOLDRE.test(box.outerHTML))?'sold':'on sale','')}
