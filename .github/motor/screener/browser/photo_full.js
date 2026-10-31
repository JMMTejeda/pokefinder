(()=>{const i=document.querySelector('img');if(!i)return JSON.stringify({ok:false});
i.style.cssText='width:'+i.naturalWidth+'px;height:'+i.naturalHeight+'px;max-width:none;max-height:none;position:absolute;left:0;top:0;cursor:auto';
window.scrollTo(Math.max(0,(i.naturalWidth-innerWidth)/2),Math.round(i.naturalHeight*0.15));
return JSON.stringify({ok:true,w:i.naturalWidth,h:i.naturalHeight,x:scrollX,y:scrollY,vw:innerWidth,vh:innerHeight})})()
