if(/\/used\/?$/.test(location.pathname)){const prod=T.replace(/の中古.*$/,'');
for(const a of document.querySelectorAll('a[href*="/used/"]')){const m=a.href.match(/\/used\/(\d+)/);if(!m)continue;const t=clean(a.innerText);const pm=t.match(/([\d,]+)\s*\/\s*(\S+)/);
add('snkr'+m[1],a.href.split('?')[0],prod+(pm?' ['+pm[2]+']':''),pm?'¥'+pm[1]:t,SOLDRE.test(a.outerHTML)?'sold':'on sale',pm?'condition or grade: '+pm[2]:'')}}
else{for(const a of document.querySelectorAll('a[href*="/apparels/"]')){const m=a.href.match(/\/apparels\/(\d+)(?:\/used\/(\d+))?/);if(!m)continue;const t=clean(a.innerText);const pm=t.match(/¥\s?([\d,]+)/);
add(m[2]?'snkr'+m[2]:'product'+m[1],a.href.split('?')[0],t.replace(/¥\s?[\d,]+.*/,'').replace(/^\d+\s/,''),pm?'¥'+pm[1]:'',m[2]?(SOLDRE.test(a.outerHTML)?'sold':'on sale'):'product page','product '+m[1])}}
