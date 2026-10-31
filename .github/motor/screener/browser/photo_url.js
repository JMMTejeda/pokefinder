(()=>{const og=(document.querySelector('meta[property="og:image"]')||{}).content||null;
const imgs=[...document.images].filter(i=>i.naturalWidth>=300).sort((a,b)=>b.naturalWidth*b.naturalHeight-a.naturalWidth*a.naturalHeight).slice(0,4).map(i=>i.getAttribute('data-zoom-src')||i.currentSrc||i.src);
const ebay=(document.querySelector('.ux-image-carousel-item.active img, .ux-image-carousel-item img')||{});
return JSON.stringify({blocked:/Just a moment|Security Measure|Medida de seguridad/i.test(document.title),title:document.title,og,ebay:ebay.getAttribute?ebay.getAttribute('data-zoom-src')||ebay.src:null,imgs,text:document.body.innerText.replace(/\s+/g,' ').slice(0,600)})})()
