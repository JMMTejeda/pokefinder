{let j=null;try{j=JSON.parse(document.body.innerText)}catch(e){}for(const p of ((((j||{}).resources||{}).results||{}).products||[])){
add('cherry'+p.id,new URL(p.url.split('?')[0],location.href).href,p.title,p.price?'AUD '+p.price:'',p.available===false?'sold':'on sale','Card shop (Shopify); Located in Australia');if(p.image)rows[rows.length-1].image=p.image}}
