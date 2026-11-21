#!/bin/bash
# Startet die Saeule wiederholt neu und prueft, ob sie erreichbar wird.
# Reset per Upload (flasht dieselbe Fassung neu und loest dabei den Reset aus).
SK=/home/max/projekte/ha-wecker/firmware/signalsaeule
LOG=/tmp/starttest.log
: > $LOG
ok=0; fehl=0
for runde in $(seq 1 8); do
  # Neustart per /api/neustart (ab Firmware 1.20.0). Vorher lief das ueber
  # einen Upload - der braucht ein Kabel, und der Port wechselt nach jedem
  # Upload die Nummer: lief er ins Leere, meldete der Test "OK nach 0s", ohne
  # dass ueberhaupt neu gestartet wurde (am 21.11.2026 so passiert).
  curl -s -X POST --max-time 5 http://192.168.1.81/api/neustart >/dev/null 2>&1
  sleep 3
  start=$(date +%s)
  erreicht=""
  for versuch in $(seq 1 20); do
    for ip in 81 70; do
      r=$(curl -s --max-time 2 http://192.168.1.$ip/api/ping 2>/dev/null)
      case "$r" in *Signalsaeule*) erreicht="192.168.1.$ip"; break 2;; esac
    done
    sleep 3
  done
  dauer=$(( $(date +%s) - start ))
  if [ -n "$erreicht" ]; then
    v=$(curl -s --max-time 4 http://$erreicht/api/state | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['version'],d['modus'],sum(r['pegel'] for r in d['relais']))" 2>/dev/null)
    echo "Runde $runde: OK nach ${dauer}s auf $erreicht | $v" >> $LOG
    ok=$((ok+1))
  else
    echo "Runde $runde: NICHT ERREICHBAR nach ${dauer}s" >> $LOG
    fehl=$((fehl+1))
  fi
done
echo "--- $ok von 8 Starts erreichbar, $fehl Fehlversuche ---" >> $LOG
