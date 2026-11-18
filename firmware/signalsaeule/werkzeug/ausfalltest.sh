#!/bin/bash
# Nimmt die Saeule laenger vom Netz (1200-Baud-Touch -> Bootloader) und prueft,
# ob die Betriebsart "Ampel" von selbst endet. Danach wird sie zurueckgeholt.
SP=/tmp
LOG=$SP/ausfalltest.log
: > $LOG
zustand() { $SP/ha.sh states/select.og_zimmer_max_signalsaule_betriebsart \
  | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["state"])' 2>/dev/null; }

echo "vorher: $(zustand)" >> $LOG
# Bootloader: die Saeule verschwindet aus dem Netz, bis wieder geflasht wird
stty -F /dev/ttyACM0 1200 2>/dev/null; sleep 1
echo "Saeule in den Bootloader geschickt" >> $LOG
for i in $(seq 1 14); do
  z=$(zustand)
  echo "  +$((i*5))s: $z" >> $LOG
  [ "$z" != "Ampel" ] && break
  sleep 5
done
echo "nach dem Ausfall: $(zustand)" >> $LOG
# zurueckholen
arduino-cli upload -b arduino:renesas_uno:unor4wifi \
  /home/max/projekte/ha-wecker/firmware/signalsaeule/signalsaeule -p /dev/ttyACM0 >>$LOG 2>&1
for i in $(seq 1 20); do
  r=$(curl -s --max-time 3 http://192.168.1.81/api/state 2>/dev/null)
  case "$r" in *version*) echo "Saeule wieder da: $(echo "$r" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["version"],d["modus"],"Pegel",sum(x["pegel"] for x in d["relais"]))')" >> $LOG; break;; esac
  sleep 4
done
echo "Betriebsart danach: $(zustand)" >> $LOG
