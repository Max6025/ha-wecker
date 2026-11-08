/* Oberflaeche der Wecker-App. Aufbau, Masse und Bedienlogik 1:1 nach dem
   Mockup (Hora Wecker, Stand 08.11.2026). Alle Daten kommen ueber die
   Bruecke window.Android aus dem Kotlin-Backend und gehen dort auch hin. */
(function(){
"use strict";

var A=window.Android||null;
var $=function(s){return document.querySelector(s)};
var $$=function(s){return Array.prototype.slice.call(document.querySelectorAll(s))};
var pad=function(n){return ("0"+n).slice(-2)};
function fmt(h,m){return pad(h)+":"+pad(m)}
function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}

/* ===================== Bühne ===================== */
var WOLKEN=5, LEBEN_MIN=10, LEBEN_MAX=17, TON_VON=186, TON_BIS=262;
var z=function(a,b){return a+Math.random()*(b-a)};
function Buehne(wurzel,anzahl){
 this.wurzel=wurzel; this.formen=[]; this.aktiv=false;
 for(var i=0;i<anzahl;i++){
  var el=document.createElement("div"); el.className="wolke";
  wurzel.appendChild(el); this.formen.push({el:el,tAus:0,tNeu:0});
 }
}
Buehne.prototype._gebaeren=function(f){
 var el=f.el, groesse=z(38,72);
 el.style.width=groesse+"vw";
 el.style.height=groesse*z(.7,1.2)+"vw";
 el.style.setProperty("--weich",Math.round(groesse*z(.8,1.3))+"px");
 el.style.background="radial-gradient(circle at "+z(32,68)+"% "+z(32,68)+"%, hsl("+
   z(TON_VON,TON_BIS)+" "+z(82,98)+"% "+z(48,64)+"%), transparent 72%)";
 el.style.transition="none";
 el.style.left=z(-22,86)+"vw";
 el.style.top=z(-25,50)+"vh";
 el.style.transform="translate3d(0,0,0) scale("+z(.8,1.05)+")";
 el.style.opacity="0";
 void el.offsetWidth;
 var leben=z(LEBEN_MIN,LEBEN_MAX), blende=Math.min(6,leben/4);
 el.style.transition="transform "+leben+"s cubic-bezier(.37,.16,.32,.96), opacity "+blende+"s ease-in-out";
 el.style.transform="translate3d("+z(-42,42)+"vw, "+z(-24,28)+"vh, 0) scale("+z(.8,1.6)+")";
 el.style.opacity=String(z(.55,.9));
 clearTimeout(f.tAus); clearTimeout(f.tNeu);
 var self=this;
 f.tAus=setTimeout(function(){el.style.opacity="0"},(leben-blende)*1000);
 f.tNeu=setTimeout(function(){self._gebaeren(f)},leben*1000);
};
Buehne.prototype.starten=function(){
 if(this.aktiv)return; this.aktiv=true; var self=this;
 this.formen.forEach(function(f,i){
  clearTimeout(f.tAus); clearTimeout(f.tNeu);
  f.tNeu=setTimeout(function(){self._gebaeren(f)}, i*z(400,1600));
 });
};
Buehne.prototype.stoppen=function(){
 this.aktiv=false;
 this.formen.forEach(function(f){clearTimeout(f.tAus);clearTimeout(f.tNeu);f.el.style.opacity="0"});
};
var buehne=null;
(function(){
 var wurzel=document.getElementById("stage");
 var ruhig=window.matchMedia&&window.matchMedia("(prefers-reduced-motion: reduce)").matches;
 buehne=new Buehne(wurzel,ruhig?3:WOLKEN);
 if(ruhig){
  buehne.formen.forEach(function(f,i){
   var el=f.el,g=42+i*8;
   el.style.width=g+"vw"; el.style.height=g*.9+"vw";
   el.style.setProperty("--weich",Math.round(g*1.2)+"px");
   el.style.background="radial-gradient(circle, hsl("+(200+i*22)+" 90% 56%), transparent 72%)";
   el.style.left=(-10+i*34)+"vw"; el.style.top=(-12+i*14)+"vh"; el.style.opacity=".6";
  });
 }else{
  buehne.starten();
  document.addEventListener("visibilitychange",function(){
   if(document.hidden)buehne.stoppen(); else buehne.starten();
  });
 }
})();

/* ===================== Daten ===================== */
var DAYS=[1,2,3,4,5,6,0], DL=["Mo","Di","Mi","Do","Fr","Sa","So"];
var DLONG={0:"Sonntag",1:"Montag",2:"Dienstag",3:"Mittwoch",4:"Donnerstag",5:"Freitag",6:"Samstag"};
/* Wecktoene kommen aus dem Handy (Alarm- und Klingeltoene), Wert ist die URI, leer = Standard */
var TONES=[{n:"Standard (Alarmton des Handys)",v:""}];
try{ if(A) TONES=JSON.parse(A.toene()); }catch(e){}
function tonName(v){ for(var i=0;i<TONES.length;i++) if(TONES[i].v===(v||"")) return TONES[i].n.replace(" (Alarmton des Handys)",""); return v?"Eigener Ton":"Standard"; }
var VIBES=["Herzschlag","Kurz","Stakkato","Welle","Aus"];
var SNOOZE=[5,7,9];
var VORWARN=[2,5,10,15,30];
var PERMS={notify:"Benachrichtigungen",fullscreen:"Vollbild-Weckruf",exact:"Exakte Alarme",battery:"Akku-Optimierung",promote:"Live-Benachrichtigung"};

var S=null;
function leer(){
 return {vol:75,fade:true,vib:true,defTone:"",defSnooze:9,
  cats:[{id:"k1",n:"Aufstehen",bild:"sonne",c:"#FFB457"}],alarms:[],
  api:{url:"",id:"",on:true,letzter:""},prewarn:5,
  sleep:{on:false,start:"22:30",end:"06:30",notify:true,active:false},perms:{},version:""};
}
/* Ohne Bruecke (Vorschau im Browser am Rechner): Beispieldaten des Mockups */
function demo(){
 var s=leer(), t=Date.now();
 s.cats=[{id:"k1",n:"Aufstehen",bild:"sonne",c:"#FFB457"},{id:"k2",n:"Arbeit",bild:"werkzeug",c:"#B8C4D6"},
  {id:"k3",n:"Baustelle",bild:"kegel",c:"#F2C94C"},{id:"k4",n:"Training",bild:"hantel",c:"#45D6B4"},
  {id:"k5",n:"Abfahrt",bild:"transporter",c:"#FF8FA3"},{id:"k6",n:"Pause",bild:"tasse",c:"#A98BFF"},
  {id:"k7",n:"Erinnerung",bild:"klemmbrett",c:"#7FE0A0"}];
 s.alarms=[
  {id:1,h:5,m:30,label:"Frühschicht",cat:"k2",days:[1,2,3,4,5],on:true,tone:"",vibe:"Herzschlag",snooze:9,next:t+15*3600e3},
  {id:2,h:6,m:10,label:"Aufstehen",cat:"k1",days:[1,2,3,4,5],on:true,tone:"",vibe:"Welle",snooze:9,next:t+16*3600e3},
  {id:3,h:6,m:45,label:"Laufrunde Isar",cat:"k4",days:[2,4],on:true,tone:"",vibe:"Kurz",snooze:5,next:t+40*3600e3},
  {id:4,h:7,m:15,label:"Abfahrt Baustelle",cat:"k5",days:[1,2,3,4,5],on:true,tone:"",vibe:"Stakkato",snooze:5,next:t+17*3600e3},
  {id:5,h:9,m:30,label:"Brotzeit",cat:"k6",days:[1,2,3,4,5],on:false,tone:"",vibe:"Aus",snooze:5,next:null},
  {id:6,h:12,m:0,label:"Material bestellen",cat:"k7",days:[3],on:true,tone:"",vibe:"Kurz",snooze:10,next:t+60*3600e3},
  {id:7,h:13,m:30,label:"Messgerät kalibrieren",cat:"k3",days:[],on:false,tone:"",vibe:"Stakkato",snooze:10,next:null}];
 s.perms={notify:true,fullscreen:true,exact:true,battery:true,promote:true};
 return s;
}
/* Zustand aus dem Backend holen */
function laden(){
 var n=null;
 try{ if(A) n=JSON.parse(A.zustand()); }catch(e){}
 S=n||demo();
 if(!S.cats||!S.cats.length) S.cats=leer().cats;
 if(!S.alarms) S.alarms=[];
 if(!S.api) S.api=leer().api;
 if(!S.sleep) S.sleep=leer().sleep;
 if(!S.perms) S.perms={};
}
/* Zustand ins Backend schreiben; es plant die Weckrufe neu und meldet an HA,
   und gibt den bereinigten Zustand (neue IDs, naechste Ausloesung) zurueck */
function save(pushen){
 var n=null;
 try{ if(A) n=JSON.parse(A.speichern(JSON.stringify(S), pushen!==false)); }catch(e){}
 if(n) S=n;
}
laden();

function kat(id){
 for(var i=0;i<S.cats.length;i++) if(S.cats[i].id===id) return S.cats[i];
 return S.cats[0];
}
function nextOf(a){ return (a.on&&a.next)?new Date(a.next):null }
function upcoming(){
 var l=[];
 S.alarms.forEach(function(a){var d=nextOf(a);if(d)l.push({a:a,d:d})});
 l.sort(function(x,y){return x.d-y.d});
 return l;
}
function dur(ms){
 var min=Math.max(0,Math.round(ms/60000)),h=Math.floor(min/60),m=min%60;
 return h?(h+" Std "+m+" Min"):(m+" Min");
}
/* Restzeit-Pille der Hero-Box: unter 12 Stunden eine Dauer ("in 2 Std 10 Min"),
   sonst Tag und Uhrzeit ("morgen 09:00", "Samstag 09:00", "Sa, 15.11. 09:00") */
function heroRest(d){
 var n=new Date(), ms=d-n;
 if(ms<=12*3600e3) return "in "+dur(ms);
 var tag;
 if(d.toDateString()===n.toDateString()) tag="heute";
 else{
  var t=new Date(n.getFullYear(),n.getMonth(),n.getDate()+1);
  if(d.toDateString()===t.toDateString()) tag="morgen";
  else if(ms<6*86400e3) tag=DLONG[d.getDay()];
  else tag=DL[DAYS.indexOf(d.getDay())]+", "+d.getDate()+"."+(d.getMonth()+1)+".";
 }
 return tag+" "+fmt(d.getHours(),d.getMinutes());
}
function relDay(d){
 var n=new Date();
 if(d.toDateString()===n.toDateString())return "heute";
 var t=new Date(n.getFullYear(),n.getMonth(),n.getDate()+1);
 if(d.toDateString()===t.toDateString())return "morgen";
 return DLONG[d.getDay()];
}
function repeatText(a){
 if(a.days.length===0)return "einmalig";
 if(a.days.length===7)return "täglich";
 if(a.days.length===5&&[1,2,3,4,5].every(function(d){return a.days.indexOf(d)>-1}))return "Mo–Fr";
 if(a.days.length===2&&a.days.indexOf(6)>-1&&a.days.indexOf(0)>-1)return "Wochenende";
 return DAYS.filter(function(d){return a.days.indexOf(d)>-1}).map(function(d){return DL[DAYS.indexOf(d)]}).join(" ");
}
function haptik(ms){ if(S.vib&&A)try{A.haptik(ms)}catch(e){} }

/* ===================== Weckerliste ===================== */
var heroVorher=null, heroZeitVorher=0;
function huerde(){
 var p=S.perms||{};
 if(p.notify===false) return {t:"Benachrichtigungen sind gesperrt. Ohne sie gibt es weder Weckruf noch Vorwarnung. Hier tippen und erlauben.",k:"notify"};
 if(p.fullscreen===false) return {t:"Vollbild-Weckruf ist gesperrt. Bei ausgeschaltetem Bildschirm kommt sonst nur eine Benachrichtigung. Hier tippen und erlauben.",k:"fullscreen"};
 if(p.exact===false) return {t:"Exakte Alarme sind nicht erlaubt, der Wecker klingelt sonst ungenau. Hier tippen und erlauben.",k:"exact"};
 if(p.battery===false) return {t:"Akku-Optimierung ist aktiv. Android kann den Weckruf verzögern. Hier tippen und ausnehmen.",k:"battery"};
 return null;
}
function renderAlarms(){
 var g=$("#grid"); g.innerHTML="";
 var up=upcoming(), nx=up[0];
 var heroId=nx?nx.a.id:0, heroZeit=nx?nx.d.getTime():0;

 var hero=document.createElement("button"); hero.className="hero";
 if(nx){
  var a=nx.a, k=kat(a.cat);
  hero.style.setProperty("--c",k.c);
  hero.innerHTML=
   bild(k.bild,128,"art")+
   '<div class="hrow"><span class="eyebrow">Nächster Weckruf</span><span class="countdown" id="heroCd">'+heroRest(nx.d)+'</span></div>'+
   '<div class="htime">'+fmt(a.h,a.m)+'</div>'+
   '<div class="hlabel">'+esc(a.label||"Wecker")+'</div>'+
   '<div class="hmeta"><i></i>'+relDay(nx.d)+' · '+esc(k.n)+' · '+repeatText(a)+'</div>';
  hero.addEventListener("click",function(){openEdit(a.id)});
 }else{
  hero.style.setProperty("--c","#6E86B8");
  hero.innerHTML='<div class="hrow"><span class="eyebrow">Nächster Weckruf</span></div>'+
   '<div class="htime">--:--</div><div class="hlabel">Kein aktiver Wecker</div>'+
   '<div class="hmeta"><i></i>'+(S.alarms.length?"alle Wecker ausgeschaltet":"noch kein Wecker angelegt")+'</div>';
  hero.addEventListener("click",function(){openEdit(null)});
 }
 if(heroVorher!==null && heroVorher!==heroId){
  hero.classList.add("neu", (heroZeit&&heroZeitVorher&&heroZeit<heroZeitVorher)?"hoch":"runter");
 }
 heroVorher=heroId; heroZeitVorher=heroZeit;
 g.appendChild(hero);

 S.alarms.slice().sort(function(a,b){return (a.h*60+a.m)-(b.h*60+b.m)||a.id-b.id}).forEach(function(a){
  var k=kat(a.cat);
  var t=document.createElement("button");
  t.className="tile"+(a.on?"":" off"); t.style.setProperty("--c",k.c);
  t.setAttribute("aria-label",(a.label||"Wecker")+" "+fmt(a.h,a.m));
  var days=a.days.length===0
   ? '<span class="once">Einmalig</span>'
   : DAYS.map(function(d,i){return '<span class="d'+(a.days.indexOf(d)>-1?" on":"")+'">'+DL[i]+'</span>'}).join('');
  var label=esc(a.label||"Wecker");
  if(a.on&&a.skipNext) label+=' <span class="skip">· nächster übersprungen</span>';
  else if(a.on&&a.snoozedUntil&&a.snoozedUntil>Date.now()) label+=' <span class="skip">· schlummert</span>';
  t.innerHTML=
   bild(k.bild,104,"art")+
   '<div class="row1"><span class="chip'+(k.n.length>8?" lang":"")+'">'+bild(k.bild,17)+'<span>'+esc(k.n)+'</span></span>'+
   '<span class="sw" role="switch" aria-checked="'+a.on+'" data-tog="'+a.id+'" tabindex="0"></span></div>'+
   '<div class="ttime">'+fmt(a.h,a.m)+'</div>'+
   '<div class="label">'+label+'</div>'+
   '<div class="days">'+days+'</div>';
  kachelBedienung(t,a.id);
  g.appendChild(t);
 });

 var n=S.alarms.length,on=S.alarms.filter(function(a){return a.on}).length;
 $("#alarmCount").textContent=n?(on+" von "+n+" aktiv · lange drücken zum Bearbeiten"):"";
 $("#emptyState").hidden=n>0;

 var w=$("#warnRow"), h=huerde();
 if(h){ w.hidden=false; w.innerHTML=icon("schutz",19,1.8)+'<span>'+h.t+'</span>'; w.onclick=function(){ if(A)A.berechtigung(h.k) }; }
 else { w.hidden=true; }

 requestAnimationFrame(chipsAnpassen);
}
/* Kategoriename soll immer vollständig lesbar sein: Schrift so weit verkleinern, bis sie passt */
function chipsAnpassen(){
 $$(".tile .chip").forEach(function(c){
  c.style.fontSize="";
  var fs=parseFloat(getComputedStyle(c).fontSize)||10, schutz=0;
  while(c.scrollWidth>c.clientWidth+0.5 && fs>6 && schutz++<24){ fs-=0.4; c.style.fontSize=fs.toFixed(1)+"px"; }
 });
}
window.addEventListener("resize",function(){requestAnimationFrame(chipsAnpassen)});
/* Kurz tippen: an/aus. Lange drücken: Einstellungen des Weckers. */
function kachelBedienung(el,id){
 var timer=null, lang=false, bewegt=false, x0=0, y0=0;
 el.addEventListener("contextmenu",function(e){e.preventDefault()});
 el.addEventListener("pointerdown",function(e){
  lang=false; bewegt=false; x0=e.clientX; y0=e.clientY;
  el.classList.add("halten");
  clearTimeout(timer);
  timer=setTimeout(function(){
   lang=true; el.classList.remove("halten");
   haptik(18);
   openEdit(id);
  },480);
 });
 el.addEventListener("pointermove",function(e){
  if(Math.abs(e.clientX-x0)>10||Math.abs(e.clientY-y0)>10){bewegt=true;clearTimeout(timer);el.classList.remove("halten")}
 });
 el.addEventListener("pointerup",function(){clearTimeout(timer);el.classList.remove("halten")});
 el.addEventListener("pointercancel",function(){clearTimeout(timer);bewegt=true;el.classList.remove("halten")});
 el.addEventListener("click",function(){ if(lang||bewegt)return; toggle(id); });
}
function toggle(id){
 var a=S.alarms.filter(function(x){return x.id===id})[0]; if(!a)return;
 a.on=!a.on; if(!a.on){a.skipNext=false;a.snoozedUntil=0;}
 save(); renderAlarms();
}
function show(v){
 $$(".view").forEach(function(s){s.classList.toggle("on",s.id==="v-"+v)});
 $$("#nav button").forEach(function(b){if(b.dataset.v===v)b.setAttribute("aria-current","page");else b.removeAttribute("aria-current")});
 if(v==="settings") renderSettings();
}
$("#nav").addEventListener("click",function(e){var b=e.target.closest("button");if(b)show(b.dataset.v)});
function openSheet(s){var e=$(s);e.classList.add("on");e.setAttribute("aria-hidden","false")}
function closeSheet(s){var e=$(s);e.classList.remove("on");e.setAttribute("aria-hidden","true"); if(s==="#s-pick"&&A)try{A.tonStopp()}catch(err){} }
/* Zurueck-Taste von Android: oberste Systemseite schliessen, sonst false */
window.zurueck=function(){
 var offen=$$(".sheet.on");
 if(!offen.length){
  if($("#v-settings").classList.contains("on")){ show("alarms"); return true; }
  return false;
 }
 offen.sort(function(a,b){return (parseInt(getComputedStyle(b).zIndex)||0)-(parseInt(getComputedStyle(a).zIndex)||0)});
 closeSheet("#"+offen[0].id);
 return true;
};

/* ===================== Einstellungen ===================== */
function renderSettings(){
 $("#p-cats-v").textContent=S.cats.length+" ›";
 $("#p-tone-v").textContent=tonName(S.defTone)+" ›";
 $("#p-snooze-v").textContent=(S.defSnooze?S.defSnooze+" Min":"Aus")+" ›";
 $("#p-vol").value=S.vol; $("#p-vol-v").textContent=S.vol+"%";
 $("#p-fade").setAttribute("aria-checked",String(!!S.fade));
 $("#p-vib").setAttribute("aria-checked",String(!!S.vib));
 $("#p-prewarn-v").textContent=(S.prewarn?S.prewarn+" Min vorher":"Aus")+" ›";
 $("#p-sleep-v").textContent=(S.sleep.on?S.sleep.start+"–"+S.sleep.end:"Aus")+" ›";
 var v=$("#p-api-v"), api=S.api;
 if(!api.id){v.textContent="nicht eingerichtet ›";v.className="val bad";}
 else if(!api.on){v.textContent="Push aus ›";v.className="val";}
 else {v.textContent="Push aktiv ›";v.className="val gut";}
 $$("[data-perm]").forEach(function(b){
  var ok=S.perms[b.dataset.perm], val=b.querySelector(".val");
  if(ok===true){val.textContent="erlaubt ›";val.className="val gut";}
  else if(ok===false){val.textContent="gesperrt ›";val.className="val bad";}
  else {val.textContent="›";val.className="val";}
 });
 $("#version").textContent=S.version?("HA Wecker "+S.version):"";
}
$$("[data-perm]").forEach(function(b){ b.addEventListener("click",function(){ if(A)A.berechtigung(b.dataset.perm) }) });
$("#p-testring").addEventListener("click",function(){ if(A)A.testWeckruf(15) });
$("#p-vol").addEventListener("input",function(){S.vol=Number(this.value);$("#p-vol-v").textContent=S.vol+"%"});
$("#p-vol").addEventListener("change",function(){save(false)});
$("#p-fade").addEventListener("click",function(){S.fade=!S.fade;this.setAttribute("aria-checked",String(S.fade));save(false)});
$("#p-vib").addEventListener("click",function(){S.vib=!S.vib;this.setAttribute("aria-checked",String(S.vib));save(false)});
$("#addBtn").addEventListener("click",function(){openEdit(null)});

/* ===================== Wecker bearbeiten ===================== */
var draft=null, editingId=null;
function openEdit(id){
 var a=id?S.alarms.filter(function(x){return x.id===id})[0]:null;
 editingId=id||null;
 draft=a?JSON.parse(JSON.stringify(a))
  :{id:0,h:6,m:30,label:"",cat:S.cats[0].id,days:[],on:true,tone:S.defTone||"",vibe:"Herzschlag",snooze:S.defSnooze};
 if(!kat(draft.cat)||kat(draft.cat).id!==draft.cat) draft.cat=S.cats[0].id;
 $("#e-title").textContent=a?"Wecker bearbeiten":"Neuer Wecker";
 $("#e-delete").hidden=!a;
 $("#e-label").value=draft.label;
 buildPicker(draft.h,draft.m); buildDays(); syncEditRows(); openSheet("#s-edit");
}
function akzent(){
 var c=kat(draft.cat).c;
 $("#s-edit").style.setProperty("--accent",c);
 $("#s-pick").style.setProperty("--accent",c);
}
function syncEditRows(){
 var k=kat(draft.cat);
 $("#e-cat-v").innerHTML='<span class="catdot" style="background:'+k.c+'22">'+bild(k.bild,22)+'</span>'+esc(k.n)+' ›';
 $("#e-tone-v").textContent=tonName(draft.tone)+" ›";
 $("#e-vibe-v").textContent=draft.vibe+" ›";
 $("#e-snooze-v").textContent=(draft.snooze?draft.snooze+" Min":"Aus")+" ›";
 akzent();
}
function buildDays(){
 var w=$("#daysPick"); w.innerHTML="";
 DAYS.forEach(function(d,i){
  var b=document.createElement("button"); b.textContent=DL[i];
  b.setAttribute("aria-pressed",String(draft.days.indexOf(d)>-1));
  b.addEventListener("click",function(){
   var k=draft.days.indexOf(d); if(k>-1)draft.days.splice(k,1); else draft.days.push(d);
   b.setAttribute("aria-pressed",String(draft.days.indexOf(d)>-1));
  });
  w.appendChild(b);
 });
}
var ITEM=46;

/* Ein Rad: endlos, mit Klick bei jedem Schritt und Übertrag auf die Stunde */
function Rad(el,max){
 this.el=el; this.max=max; this.wert=0; this.offset=0; this.aufUeberlauf=null;
 this.posten=[];
 for(var i=0;i<7;i++){ var d=document.createElement("div"); el.appendChild(d); this.posten.push(d); }
 this._binden(); this.zeichnen();
}
Rad.prototype.zeichnen=function(weich){
 var self=this, n=this.max+1;
 this.posten.forEach(function(d,i){
  var rel=i-3, v=((self.wert+rel)%n+n)%n;
  d.textContent=pad(v);
  d.style.transition=weich?"transform .16s cubic-bezier(.3,.9,.4,1)":"none";
  d.style.transform="translateY("+(rel*ITEM+self.offset)+"px)";
  d.style.opacity=rel===0?1:(Math.abs(rel)===1?".5":".22");
 });
};
Rad.prototype.setzen=function(v){ this.wert=((v%(this.max+1))+this.max+1)%(this.max+1); this.offset=0; this.zeichnen(); };
Rad.prototype.schritt=function(d){
 for(var i=0;i<Math.abs(d);i++){
  var s=d>0?1:-1, neu=this.wert+s;
  if(neu>this.max){ neu=0; if(this.aufUeberlauf)this.aufUeberlauf(1); }
  else if(neu<0){ neu=this.max; if(this.aufUeberlauf)this.aufUeberlauf(-1); }
  this.wert=neu;
 }
};
/* Übertrag: die Stunde rutscht sichtbar eine Stelle weiter statt umzuspringen */
Rad.prototype.huepfen=function(d){
 var self=this;
 this.schritt(d);
 this.offset=d>0?ITEM:-ITEM;
 this.zeichnen();
 this.el.classList.add("springt");
 requestAnimationFrame(function(){
  requestAnimationFrame(function(){
   self.offset=0;
   self.posten.forEach(function(el,i){
    var rel=i-3;
    el.style.transition="transform .42s cubic-bezier(.22,1.3,.36,1), opacity .3s ease";
    el.style.transform="translateY("+(rel*ITEM)+"px)";
    el.style.opacity=rel===0?1:(Math.abs(rel)===1?".5":".22");
   });
  });
 });
 clearTimeout(this._sprungT);
 this._sprungT=setTimeout(function(){ self.el.classList.remove("springt") },480);
};
Rad.prototype._binden=function(){
 var self=this, zieht=false, y0=0, letzte=0;
 this.el.addEventListener("pointerdown",function(e){
  zieht=true; y0=e.clientY; letzte=0; self.el.setPointerCapture(e.pointerId);
 });
 this.el.addEventListener("pointermove",function(e){
  if(!zieht)return;
  var dy=e.clientY-y0, schritte=Math.round(-dy/ITEM);
  if(schritte!==letzte){ self.schritt(schritte-letzte); letzte=schritte; klickTon(); }
  self.offset=dy+schritte*ITEM;
  self.zeichnen();
 });
 function los(){
  if(!zieht)return; zieht=false;
  self.offset=0; self.zeichnen(true);
 }
 this.el.addEventListener("pointerup",los);
 this.el.addEventListener("pointercancel",function(){zieht=false;self.offset=0;self.zeichnen(true)});
 this.el.addEventListener("wheel",function(e){
  e.preventDefault();
  self.schritt(e.deltaY>0?1:-1); klickTon(); self.zeichnen();
 },{passive:false});
};

var radH=new Rad($("#rad-h"),23), radM=new Rad($("#rad-m"),59);
radM.aufUeberlauf=function(d){ radH.huepfen(d); };   /* 59 -> 00 zieht die Stunde mit */
function buildPicker(h,m){ radH.setzen(h); radM.setzen(m); }
function readPicker(){ draft.h=radH.wert; draft.m=radM.wert; }

$("#e-cancel").addEventListener("click",function(){closeSheet("#s-edit")});
$("#e-save").addEventListener("click",function(){
 readPicker();
 draft.label=$("#e-label").value.trim();
 if(editingId){for(var i=0;i<S.alarms.length;i++)if(S.alarms[i].id===editingId)S.alarms[i]=draft;}
 else{draft.id=0;draft.on=true;S.alarms.push(draft);}
 save(); renderAlarms(); closeSheet("#s-edit"); show("alarms");
});
$("#e-delete").addEventListener("click",function(){
 S.alarms=S.alarms.filter(function(a){return a.id!==editingId});
 save(); renderAlarms(); closeSheet("#s-edit");
});
$("#e-preview").addEventListener("click",function(){
 readPicker();
 var d=JSON.parse(JSON.stringify(draft)); d.label=$("#e-label").value.trim(); d.kat=kat(d.cat);
 if(A)A.weckrufVorschau(JSON.stringify(d));
});

/* ===================== Auswahllisten ===================== */
/* eigene: {n:"Eigene Zeit", einheit:"Min", min:1, max:180} haengt eine Zeile mit Eingabefeld an */
function openPick(title,items,current,onPick,render,eigene){
 $("#k-title").textContent=title;
 var l=$("#k-list"); l.innerHTML="";
 var alle=function(){Array.prototype.forEach.call(l.children,function(c){c.firstChild.classList.remove("on")})};
 items.forEach(function(it){
  var b=document.createElement("button"); b.className="item";
  b.innerHTML='<span class="radio'+(it.v===current?" on":"")+'"></span>'+esc(it.n)+'<span class="val">'+(render?render(it):"")+'</span>';
  b.addEventListener("click",function(){ alle(); b.firstChild.classList.add("on"); onPick(it.v); });
  l.appendChild(b);
 });
 if(eigene){
  var fest=items.some(function(it){return it.v===current});
  var row=document.createElement("div"); row.className="item";
  row.innerHTML='<span class="radio'+(!fest&&current>0?" on":"")+'"></span>'+esc(eigene.n)+
   '<input type="number" inputmode="numeric" min="'+eigene.min+'" max="'+eigene.max+'" placeholder="'+(eigene.platzhalter||"")+'" value="'+(!fest&&current>0?current:"")+'">'+
   '<span class="val">'+esc(eigene.einheit||"")+'</span>';
  var inp=row.querySelector("input");
  function uebernehmen(){
   var v=Math.round(Number(inp.value));
   if(!(v>=eigene.min&&v<=eigene.max)) return;
   alle(); row.firstChild.classList.add("on"); onPick(v);
  }
  inp.addEventListener("input",uebernehmen);
  inp.addEventListener("focus",function(){ if(inp.value) uebernehmen(); });
  row.querySelector(".radio").addEventListener("click",function(){ inp.focus(); });
  l.appendChild(row);
 }
 openSheet("#s-pick");
}
$("#k-back").addEventListener("click",function(){closeSheet("#s-pick")});
function vibeBars(it){
 if(it.v==="Aus")return"";
 var pat={"Herzschlag":[14,6,14,4],"Kurz":[8,4],"Stakkato":[6,6,6,6,6],"Welle":[4,8,14,8,4]}[it.v]||[6];
 return '<span class="bars">'+pat.map(function(h){return '<i style="height:'+h+'px"></i>'}).join("")+'</span>';
}
function playTone(name){ if(A)try{A.tonVorschau(name)}catch(e){} }
$("#e-cat").addEventListener("click",function(){
 openPick("Kategorie",S.cats.map(function(k){return{n:k.n,v:k.id}}),draft.cat,
  function(v){draft.cat=v;syncEditRows();},
  function(it){var k=kat(it.v);return '<span class="catdot" style="background:'+k.c+'22">'+bild(k.bild,26)+'</span>'});
});
$("#e-tone").addEventListener("click",function(){
 openPick("Weckton",TONES,draft.tone||"",function(v){draft.tone=v;syncEditRows();playTone(v)});
});
$("#e-vibe").addEventListener("click",function(){
 openPick("Vibration",VIBES.map(function(t){return{n:t,v:t}}),draft.vibe,function(v){draft.vibe=v;syncEditRows();if(A&&v!=="Aus")A.vibrationVorschau(v)},vibeBars);
});
var EIGENE_ZEIT={n:"Eigene Zeit",einheit:"Min",min:1,max:180,platzhalter:"z. B. 12"};
function snoozeItems(){ var items=SNOOZE.map(function(s){return{n:s+" Minuten",v:s}}); items.push({n:"Aus",v:0}); return items; }
$("#e-snooze").addEventListener("click",function(){
 openPick("Schlummern",snoozeItems(),draft.snooze,function(v){draft.snooze=v;syncEditRows()},null,EIGENE_ZEIT);
});
$("#p-tone").addEventListener("click",function(){
 $("#s-pick").style.setProperty("--accent","#74B4FF");
 openPick("Standardton",TONES,S.defTone||"",
  function(v){S.defTone=v;save(false);renderSettings();playTone(v)});
});
$("#p-snooze").addEventListener("click",function(){
 $("#s-pick").style.setProperty("--accent","#74B4FF");
 openPick("Schlummerdauer",snoozeItems(),S.defSnooze,function(v){S.defSnooze=v;save(false);renderSettings()},null,EIGENE_ZEIT);
});
$("#p-prewarn").addEventListener("click",function(){
 $("#s-pick").style.setProperty("--accent","#74B4FF");
 var items=VORWARN.map(function(s){return{n:s+" Minuten vorher",v:s}}); items.push({n:"Aus",v:0});
 openPick("Vorwarnung",items,S.prewarn,function(v){S.prewarn=v;save();renderSettings()});
});

/* ===================== Home Assistant ===================== */
$("#p-api").addEventListener("click",function(){
 $("#s-api").style.setProperty("--accent","#74B4FF");
 $("#api-url").value=S.api.url||"";
 $("#api-id").value=S.api.id||"";
 $("#api-on").setAttribute("aria-checked",String(S.api.on!==false));
 $("#api-status").textContent=""; $("#api-status").className="apistatus";
 apiLetzter(); apiPruefen(false); openSheet("#s-api");
});
function apiLetzter(){ $("#api-last").textContent=S.api.letzter?("Letzter Push: "+S.api.letzter):""; }
/* Testen erst freigeben, wenn die ID da ist; Eingaben sofort sichern (ohne Push) */
function apiPruefen(sichern){
 var u=$("#api-url").value.trim(), i=$("#api-id").value.trim(), on=$("#api-on").getAttribute("aria-checked")==="true";
 $("#api-test").disabled=!i;
 S.api.url=u; S.api.id=i; S.api.on=on;
 if(sichern!==false&&A)try{A.apiSpeichern(u,i,on)}catch(e){}
}
$("#api-url").addEventListener("input",apiPruefen);
$("#api-id").addEventListener("input",apiPruefen);
$("#api-id").addEventListener("blur",function(){ try{ var n=JSON.parse(A.zustand()); S.api=n.api; $("#api-url").value=S.api.url; $("#api-id").value=S.api.id; }catch(e){} });
$("#api-on").addEventListener("click",function(){ this.setAttribute("aria-checked",String(this.getAttribute("aria-checked")!=="true")); apiPruefen(); });
$("#api-test").addEventListener("click",function(){
 apiPruefen();
 var st=$("#api-status"); st.className="apistatus"; st.textContent="Verbindung wird geprüft …";
 if(A)A.apiTesten();
});
window.apiErgebnis=function(ok,text){
 var st=$("#api-status"); st.className="apistatus "+(ok?"gut":"schlecht"); st.textContent=text;
 try{ var n=JSON.parse(A.zustand()); S.api.letzter=n.api.letzter; }catch(e){}
 apiLetzter();
};
$("#api-back").addEventListener("click",function(){closeSheet("#s-api");renderSettings()});

/* ===================== Schlafenszeit ===================== */
function renderSleep(){
 $("#sl-on").setAttribute("aria-checked",String(!!S.sleep.on));
 $("#sl-notify").setAttribute("aria-checked",String(S.sleep.notify!==false));
 $("#sl-start-v").textContent=S.sleep.start+" ›";
 $("#sl-end-v").textContent=S.sleep.end+" ›";
}
$("#p-sleep").addEventListener("click",function(){
 $("#s-sleep").style.setProperty("--accent","#74B4FF");
 renderSleep(); openSheet("#s-sleep");
});
$("#sl-back").addEventListener("click",function(){closeSheet("#s-sleep");renderSettings()});
$("#sl-on").addEventListener("click",function(){S.sleep.on=!S.sleep.on;save();renderSleep()});
$("#sl-notify").addEventListener("click",function(){S.sleep.notify=!(S.sleep.notify!==false);save();renderSleep()});

var rad2H=new Rad($("#rad2-h"),23), rad2M=new Rad($("#rad2-m"),59), zeitZiel=null;
rad2M.aufUeberlauf=function(d){ rad2H.huepfen(d); };
function openTime(title,wert,onSave){
 $("#t-title").textContent=title;
 var p=(wert||"06:30").split(":");
 rad2H.setzen(Number(p[0])||0); rad2M.setzen(Number(p[1])||0);
 $("#s-time").style.setProperty("--accent","#74B4FF");
 zeitZiel=onSave; openSheet("#s-time");
}
$("#t-cancel").addEventListener("click",function(){closeSheet("#s-time")});
$("#t-save").addEventListener("click",function(){
 if(zeitZiel)zeitZiel(fmt(rad2H.wert,rad2M.wert));
 closeSheet("#s-time");
});
$("#sl-start").addEventListener("click",function(){openTime("Beginn",S.sleep.start,function(v){S.sleep.start=v;save();renderSleep()})});
$("#sl-end").addEventListener("click",function(){openTime("Ende",S.sleep.end,function(v){S.sleep.end=v;save();renderSleep()})});

/* ===================== Kategorien ===================== */
$("#p-cats").addEventListener("click",function(){renderCatList();openSheet("#s-cats")});
$("#c-back").addEventListener("click",function(){closeSheet("#s-cats");renderSettings()});
function anzahlMit(id){return S.alarms.filter(function(a){return a.cat===id}).length}
function renderCatList(){
 var l=$("#catList"); l.innerHTML="";
 S.cats.forEach(function(k){
  var b=document.createElement("button"); b.className="catrow";
  var n=anzahlMit(k.id), bi=BILDER[k.bild]||BILDER.sonne;
  b.innerHTML='<span class="bildbox" style="background:'+k.c+'22">'+bild(k.bild,34)+'</span>'+
   '<span class="cn"><b>'+esc(k.n)+'</b><span>'+bi.n+' · '+(n===1?"1 Wecker":n+" Wecker")+'</span></span>'+
   '<span class="pfeil">›</span>';
  b.addEventListener("click",function(){openCatEdit(k.id)});
  l.appendChild(b);
 });
}
$("#catAdd").addEventListener("click",function(){openCatEdit(null)});

var catDraft=null, catEditId=null;
function openCatEdit(id){
 var k=id?kat(id):null;
 catEditId=id||null;
 catDraft=k?JSON.parse(JSON.stringify(k)):{id:"",n:"",bild:"mond",c:BILDER.mond.c};
 if(!BILDER[catDraft.bild]) catDraft.bild="sonne";
 catDraft.c=BILDER[catDraft.bild].c;   /* feste Farbe des Bildes */
 $("#ce-title").textContent=k?"Kategorie bearbeiten":"Neue Kategorie";
 $("#ce-name").value=catDraft.n;
 $("#ce-delete").hidden=!k||S.cats.length<2;
 buildBildGitter(); syncCatPreview(); openSheet("#s-cat");
}
function syncCatPreview(){
 $("#s-cat").style.setProperty("--accent",catDraft.c);
 var name=$("#ce-name").value.trim()||catDraft.n||"Neue Kategorie";
 $("#ce-preview").innerHTML='<span class="bildbox" style="background:'+catDraft.c+'22">'+bild(catDraft.bild,54)+'</span>'+
  '<span><b>'+esc(name)+'</b><span>'+BILDER[catDraft.bild].n+' · Farbe gehört zum Bild</span></span>';
}
$("#ce-name").addEventListener("input",syncCatPreview);
function buildBildGitter(){
 var g=$("#ce-bilder"); g.innerHTML="";
 Object.keys(BILDER).forEach(function(id){
  var b=document.createElement("button");
  b.innerHTML=bild(id,36); b.title=BILDER[id].n;
  b.style.background=BILDER[id].c+(id===catDraft.bild?"33":"14");
  b.setAttribute("aria-pressed",String(id===catDraft.bild));
  b.addEventListener("click",function(){
   catDraft.bild=id; catDraft.c=BILDER[id].c;   /* jedes Bild hat seine feste Farbe */
   buildBildGitter(); syncCatPreview();
  });
  g.appendChild(b);
 });
}
$("#ce-cancel").addEventListener("click",function(){closeSheet("#s-cat")});
$("#ce-save").addEventListener("click",function(){
 catDraft.n=$("#ce-name").value.trim()||BILDER[catDraft.bild].n;
 catDraft.c=BILDER[catDraft.bild].c;
 if(catEditId){ for(var i=0;i<S.cats.length;i++) if(S.cats[i].id===catEditId) S.cats[i]=catDraft; }
 else { catDraft.id=""; S.cats.push(catDraft); }
 save(); renderCatList(); renderAlarms(); closeSheet("#s-cat");
});
$("#ce-delete").addEventListener("click",function(){
 if(S.cats.length<2)return;
 S.cats=S.cats.filter(function(k){return k.id!==catEditId});
 var ersatz=S.cats[0].id;
 S.alarms.forEach(function(a){if(a.cat===catEditId)a.cat=ersatz});
 save(); renderCatList(); renderAlarms(); closeSheet("#s-cat");
});

/* ===================== Klick des Zeitrads ===================== */
var AC=null;
function klickTon(){
 if(A)try{A.radTick()}catch(e){}
 try{
  AC=AC||new (window.AudioContext||window.webkitAudioContext)();
  if(AC.state==="suspended")AC.resume();
  var o=AC.createOscillator(), g=AC.createGain(), t=AC.currentTime;
  o.type="square"; o.frequency.setValueAtTime(1500,t);
  g.gain.setValueAtTime(0.045,t); g.gain.exponentialRampToValueAtTime(0.0001,t+.035);
  o.connect(g); g.connect(AC.destination); o.start(t); o.stop(t+.04);
 }catch(e){}
}

/* ===================== Takt und Android-Rueckrufe ===================== */
var zuletztGeladen=Date.now();
function tick(){
 var n=new Date(), up=upcoming();
 var cd=$("#heroCd");
 if(cd&&up.length) cd.textContent=heroRest(up[0].d);
 if(n.getSeconds()===0){
  /* jede Minute den Stand aus dem Backend holen (Schlummern, Ueberspringen, Rechte) */
  if(!$$(".sheet.on").length) window.aktualisieren(true); else renderAlarms();
 }
}
/* Stand aus dem Backend holen. Neu gezeichnet wird nur, wenn sich etwas
   geaendert hat - sonst wuerde die Hero-Animation nach einem Schalten sofort
   wieder abgebrochen, weil das Backend die Aenderung ein zweites Mal meldet. */
window.aktualisieren=function(erzwingen){
 var vorher=JSON.stringify([S.alarms,S.cats,S.perms,S.sleep]);
 laden();
 var nachher=JSON.stringify([S.alarms,S.cats,S.perms,S.sleep]);
 if(erzwingen||vorher!==nachher) renderAlarms();
 if($("#v-settings").classList.contains("on")) renderSettings();
};
window.setInsets=function(t,r,b,l){
 var s=document.documentElement.style;
 s.setProperty("--sat",t+"px"); s.setProperty("--sar",r+"px"); s.setProperty("--sab",b+"px"); s.setProperty("--sal",l+"px");
};

setInterval(tick,1000);
renderAlarms(); renderSettings(); tick();
})();
