(async()=>{await new Promise(r=>setTimeout(r,2500));
const H=location.hostname,T=document.title,B=document.body?document.body.innerText:'';const clean=s=>(s||'').replace(/\s+/g,' ').trim();
if(/Just a moment|Security Measure|Medida de seguridad|Pardon Our Interruption|Access Denied|Attention Required/i.test(T+' '+B.slice(0,400))||/captcha|challenge|signin\./i.test(location.href))return JSON.stringify({site:H,blocked:true,title:T});
const up=(el,re,n=5)=>{let p=el;for(let i=0;i<n&&p.parentElement;i++){p=p.parentElement;if(re.test(p.innerText))return p}return el};
const SOLDRE=/soldBadge|sold[-_ ]?out|sold[-_]icon|>\s*SOLD\s*<|売り切れ|売切|在庫なし|vendido|reservado/i;const rows=[],seen=new Set();const add=(id,url,title,price,status,extra)=>{if(!id||seen.has(id))return;seen.add(id);rows.push({id:String(id),url,title:clean(title).slice(0,240),price_text:clean(price).slice(0,80),status:status||'on sale',extra:clean(extra||'').slice(0,200)})};
