// Dashboard der Signalsaeule - eine Seite, liegt im Flash des RA4M1.
// Die Seite fragt /api/live zwei Mal pro Sekunde ab (kurze Antwort, damit die
// Leuchten live mitlaufen) und /api/state fuer alles Uebrige.
#pragma once

static const char SEITE[] = R"HTML(<!doctype html>
<html lang="de"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Signalsäule</title>
<style>
*{box-sizing:border-box}
:root{
  --bg:#0e1116; --karte:#171c24; --rand:#242c38; --text:#e7edf3; --matt:#8b98a8;
  --gruen:#35d07f; --orange:#ff9f1c; --rot:#ff4d4d; --hinweis:#dbe6ef; --blitz:#ffe066;
}
body{margin:0;background:var(--bg);color:var(--text);
  font:15px/1.5 -apple-system,"Segoe UI",Roboto,sans-serif;padding:16px}
h1{font-size:20px;margin:0}
.kopf{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:4px}
.kopf .v{color:var(--matt);font-size:13px}
.punkt{width:9px;height:9px;border-radius:50%;background:#444;display:inline-block}
.punkt.ok{background:var(--gruen);box-shadow:0 0 8px var(--gruen)}
.gitter{display:grid;grid-template-columns:200px 1fr;gap:16px;margin-top:16px;align-items:start}
@media(max-width:620px){.gitter{grid-template-columns:1fr}}
.karte{background:var(--karte);border:1px solid var(--rand);border-radius:14px;padding:14px}
.karte h2{font-size:13px;text-transform:uppercase;letter-spacing:.08em;
  color:var(--matt);margin:0 0 10px;font-weight:600}
.saeule{display:flex;justify-content:center;padding:6px 0}
svg .aus{opacity:.13}
svg .an{opacity:1}
.schalter{display:grid;gap:8px}
button{font:inherit;color:var(--text);background:#1f2733;border:1px solid var(--rand);
  border-radius:10px;padding:11px 13px;cursor:pointer;text-align:left;
  display:flex;align-items:center;gap:10px;transition:.12s}
button:hover{border-color:#3a4555}
button:active{transform:translateY(1px)}
button .led{width:12px;height:12px;border-radius:50%;background:#2c3542;flex:0 0 auto}
button.an{background:#223042;border-color:#3e5f86}
button.an .led{background:currentColor}
.l1.an{color:var(--gruen)} .l2.an{color:var(--orange)} .l3.an{color:var(--rot)}
.l4.an{color:var(--hinweis)} .l5.an{color:var(--blitz)}
button.an .led{box-shadow:0 0 10px currentColor}
.reihe{display:flex;gap:8px}
.reihe button{flex:1;justify-content:center;text-align:center}
.reihe button.aktiv{background:#2a3a50;border-color:#4a6c96;font-weight:600}
select{width:100%;font:inherit;color:var(--text);background:#1f2733;
  border:1px solid var(--rand);border-radius:10px;padding:11px 12px}
.matt{color:var(--matt)}
.hinweis{font-size:13px;color:var(--matt);margin-top:8px}
.warn button.an{background:#3a2a1c;border-color:#7a5a2a}
table{width:100%;border-collapse:collapse;font-size:13px}
td{padding:5px 0;border-bottom:1px solid var(--rand);vertical-align:top}
td.z{width:18px} td.n{width:34%}
.ok{color:var(--gruen)} .fehl{color:var(--rot)} .info{color:var(--matt)}
.werte{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:10px;font-size:13px}
.werte div span{display:block;color:var(--matt);font-size:11px;text-transform:uppercase;letter-spacing:.06em}
.band{background:#2a3a50;border:1px solid #4a6c96;border-radius:10px;padding:8px 12px;
  font-size:13px;margin-top:10px;display:none}
</style></head><body>

<div class="kopf">
  <h1>Signalsäule</h1>
  <span class="punkt" id="pkt"></span>
  <span class="v" id="kopfinfo">verbinde …</span>
</div>

<div class="gitter">
  <div class="karte saeulekarte">
    <div class="saeule">
      <svg width="150" height="320" viewBox="0 0 120 320">
        <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stop-color="#000" stop-opacity=".35"/>
          <stop offset=".45" stop-color="#fff" stop-opacity=".12"/>
          <stop offset="1" stop-color="#000" stop-opacity=".4"/>
        </linearGradient></defs>
        <!-- Blitzleuchte oben -->
        <g id="lampe5">
          <path d="M34 62 A26 26 0 0 1 86 62 L86 70 L34 70 Z" fill="#ffe066"/>
          <path d="M34 62 A26 26 0 0 1 86 62 L86 70 L34 70 Z" fill="url(#g)"/>
        </g>
        <rect x="32" y="70" width="56" height="7" rx="2" fill="#2b333f"/>
        <!-- Stufen von oben nach unten: Hinweis, rot, orange, gruen -->
        <g id="lampe4"><rect x="30" y="79" width="60" height="44" rx="5" fill="#dbe6ef"/>
          <rect x="30" y="79" width="60" height="44" rx="5" fill="url(#g)"/></g>
        <rect x="28" y="123" width="64" height="6" rx="2" fill="#2b333f"/>
        <g id="lampe3"><rect x="30" y="129" width="60" height="44" rx="5" fill="#ff4d4d"/>
          <rect x="30" y="129" width="60" height="44" rx="5" fill="url(#g)"/></g>
        <rect x="28" y="173" width="64" height="6" rx="2" fill="#2b333f"/>
        <g id="lampe2"><rect x="30" y="179" width="60" height="44" rx="5" fill="#ff9f1c"/>
          <rect x="30" y="179" width="60" height="44" rx="5" fill="url(#g)"/></g>
        <rect x="28" y="223" width="64" height="6" rx="2" fill="#2b333f"/>
        <g id="lampe1"><rect x="30" y="229" width="60" height="44" rx="5" fill="#35d07f"/>
          <rect x="30" y="229" width="60" height="44" rx="5" fill="url(#g)"/></g>
        <rect x="24" y="273" width="72" height="12" rx="3" fill="#2b333f"/>
        <rect x="16" y="285" width="88" height="10" rx="4" fill="#232a35"/>
      </svg>
    </div>
    <div class="hinweis" id="saeuleinfo">&nbsp;</div>
  </div>

  <div style="display:grid;gap:16px">
    <div class="karte">
      <h2>Betriebsart</h2>
      <div class="reihe">
        <button id="mauto" onclick="modus('auto')">Auto</button>
        <button id="mman" onclick="modus('manuell')">Manuell</button>
      </div>
      <div id="band" class="band"></div>
      <div style="margin-top:12px">
        <h2>Status</h2>
        <select id="status" onchange="statusWahl(this.value)"></select>
        <div class="hinweis" id="statushinweis">Ein Status wird angesagt und bleibt dann stehen.</div>
      </div>
    </div>

    <div class="karte">
      <h2>Leuchten einzeln</h2>
      <div class="schalter" id="lampen"></div>
      <div class="warn schalter" style="margin-top:8px" id="warnschalter"></div>
      <div class="hinweis">Eine Stufe von Hand zu schalten stellt auf Manuell. Die
        Warnleuchte hat ihren eigenen Schalter und gilt in beiden Betriebsarten.</div>
    </div>

    <div class="karte">
      <h2>Prüfen</h2>
      <div class="schalter">
        <button id="test" onclick="test()"><span class="led"></span>Testmodus</button>
        <button id="diag" onclick="diagnose()"><span class="led"></span>Selbstdiagnose starten</button>
      </div>
      <table id="diagtab" style="margin-top:10px"></table>
      <div class="hinweis">Die Diagnose prüft, was der Arduino selbst wissen kann:
        WLAN, USB, Speicher und ob jeder Ausgang seinen Pegel annimmt. Ob eine
        Leuchte wirklich brennt, sieht er nicht. Die Blitzleuchte blitzt dabei kurz.</div>
    </div>

    <div class="karte">
      <h2>Gerät</h2>
      <div class="werte" id="werte"></div>
    </div>
  </div>
</div>

<script>
const E = id => document.getElementById(id);
const NAMEN = ["Grün (Stufe 1)","Orange (Stufe 2)","Rot (Stufe 3)","Hinweis (Stufe 4)"];
let z = {}, bereit = false;

async function hol(p, m) {
  const r = await fetch(p, m ? {method:'POST'} : undefined);
  if (!r.ok) throw new Error(r.status);
  return r.json();
}
async function tu(p) { try { z = await hol(p, true); voll(); } catch(e) { fehler(); } }

function fehler() { E('pkt').classList.remove('ok'); E('kopfinfo').textContent = 'keine Verbindung'; }

function modus(m) { tu('/api/modus?modus=' + m); }
function statusWahl(s) { tu('/api/status?status=' + s); }
function schalte(nr, an) { tu('/api/relais/' + nr + '?an=' + (an ? 1 : 0)); }
function test() { tu('/api/test?an=' + (z.test ? 0 : 1)); }
function diagnose() { tu('/api/diagnose'); }

function bauen() {
  const w = E('status');
  w.innerHTML = '';
  (z.status_liste || []).forEach(s => {
    const o = document.createElement('option');
    o.value = s.id; o.textContent = s.name;
    w.appendChild(o);
  });
  const lampen = E('lampen'); lampen.innerHTML = '';
  (z.relais || []).filter(r => r.rolle !== 'warn').forEach((r, i) => {
    const b = document.createElement('button');
    b.className = 'l' + r.nr; b.id = 'sw' + r.nr;
    b.innerHTML = '<span class="led"></span>' + (NAMEN[i] || r.name);
    b.onclick = () => schalte(r.nr, !b.classList.contains('an'));
    lampen.appendChild(b);
  });
  const ws = E('warnschalter'); ws.innerHTML = '';
  (z.relais || []).filter(r => r.rolle === 'warn').forEach(r => {
    const b = document.createElement('button');
    b.className = 'l' + r.nr; b.id = 'sw' + r.nr;
    b.innerHTML = '<span class="led"></span>Blitz-Warnleuchte';
    b.onclick = () => schalte(r.nr, !b.classList.contains('an'));
    ws.appendChild(b);
  });
  bereit = true;
}

function voll() {
  if (!bereit || (z.status_liste || []).length !== E('status').options.length) bauen();
  E('pkt').classList.add('ok');
  E('kopfinfo').textContent = 'Version ' + z.version + ' · ' + z.ip;
  const d = z.diagnose || {}, t = E('diagtab');
  t.innerHTML = '';
  (d.punkte || []).forEach(p => {
    const zeichen = p.ok === 1 ? '✓' : (p.ok === 0 ? '✕' : 'i');
    const kl = p.ok === 1 ? 'ok' : (p.ok === 0 ? 'fehl' : 'info');
    t.insertAdjacentHTML('beforeend',
      '<tr><td class="z ' + kl + '">' + zeichen + '</td><td class="n">' + p.name +
      '</td><td class="matt">' + p.text + '</td></tr>');
  });
  const u = z.usb || {};
  const usbtext = !u.spannung ? 'kein USB' : (!u.rechner ? 'nur Spannung'
    : (u.monitor ? 'Rechner, Port offen' : 'Rechner angesteckt'));
  E('werte').innerHTML =
    feld('WLAN', z.rssi + ' dBm') + feld('Adresse', z.ip) +
    feld('Laufzeit', dauer(z.uptime_s)) + feld('Speicher', (z.ram_frei || 0) + ' B frei') +
    feld('USB', usbtext) + feld('Version', z.version);
  anwenden(z);
}
function feld(n, w) { return '<div><span>' + n + '</span>' + w + '</div>'; }
function dauer(s) {
  s = s || 0;
  const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60);
  return h ? h + ' h ' + m + ' min' : (m ? m + ' min' : s + ' s');
}

function anwenden(l) {
  const auto = l.modus === 'auto';
  E('mauto').classList.toggle('aktiv', auto);
  E('mman').classList.toggle('aktiv', !auto);
  const w = E('status');
  if (document.activeElement !== w && l.status) w.value = l.status;
  w.disabled = false;
  E('statushinweis').textContent = auto
    ? (l.wechsel ? 'Wechsel läuft – die Säule sagt den neuen Status an.' : 'Status steht.')
    : 'In Manuell gilt der Status nicht. Ein Status schaltet zurück auf Auto.';
  const band = E('band');
  if (l.phase !== 'betrieb') { band.style.display = 'block'; band.textContent = 'Startablauf läuft …'; }
  else if (l.diag) { band.style.display = 'block'; band.textContent = 'Selbstdiagnose läuft …'; }
  else if (l.test) { band.style.display = 'block'; band.textContent = 'Testmodus läuft – alle Leuchten der Reihe nach.'; }
  else band.style.display = 'none';
  E('test').classList.toggle('an', !!l.test);
  E('test').classList.toggle('l5', !!l.test);

  const live = l.live || (z.relais || []).map(r => r.live ? 1 : 0);
  const soll = l.soll || (z.relais || []).map(r => r.an ? 1 : 0);
  (z.relais || []).forEach((r, i) => {
    const g = E('lampe' + r.nr), b = E('sw' + r.nr);
    if (g) { g.classList.toggle('an', !!live[i]); g.classList.toggle('aus', !live[i]);
             g.style.filter = live[i] ? 'drop-shadow(0 0 14px ' + farbe(r.nr) + ')' : 'none'; }
    if (b) b.classList.toggle('an', !!soll[i]);
  });
  E('saeuleinfo').textContent = auto ? (z.status_name || '') : 'Manuell';
}
function farbe(nr) {
  return {1:'#35d07f',2:'#ff9f1c',3:'#ff4d4d',4:'#dbe6ef',5:'#ffe066'}[nr] || '#fff';
}

async function live() {
  try {
    const l = await hol('/api/live');
    E('pkt').classList.add('ok');
    if (!bereit) { z = await hol('/api/state'); voll(); return; }
    anwenden(l);
    if (l.diag || (z.diagnose && z.diagnose.laeuft)) { z = await hol('/api/state'); voll(); }
  } catch(e) { fehler(); }
}

(async () => { try { z = await hol('/api/state'); voll(); } catch(e) { fehler(); } })();
setInterval(live, 450);
setInterval(async () => { try { z = await hol('/api/state'); voll(); } catch(e) {} }, 8000);
</script>
</body></html>)HTML";
