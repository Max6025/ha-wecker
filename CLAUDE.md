# HA Wecker – Hinweise fuer die Arbeit am Repo

Drei Teile, eine Integration: `custom_components/ha_wecker` (Home Assistant),
`app/` (Android-Wecker-App), `firmware/signalsaeule/` (Arduino UNO R4 WiFi an
einer Rittal-Signalsaeule). Die Relaisbox (ESP32-S3) ist am 14.11.2026 ganz
entfernt worden - Integration, Firmware, Blueprint und Tests.
Die README beschreibt alles fuer Nutzer; hier stehen nur die Fallstricke.

## Regeln

- **Oberflaeche der App ist das Mockup.** `app/app/src/main/assets/ui/` (style.css,
  bilder.js 1:1 aus dem Artefakt „Hora Wecker", app.js/app.html/ring.html mit
  Bruecke `window.Android`). Keine XML-Layouts mehr anlegen; Aenderungen am
  Aussehen passieren dort. Safe-Area kommt von Android als `--sat/--sab/...`.
  Textauswahl ist absichtlich aus (sonst dreht ein langes Druecken das Zeitrad).
  Vorschau am Rechner: `python3 -m http.server 8765` im ui-Ordner.
- **Kein MQTT, kein Hintergrunddienst in der App.** Die App meldet sich per
  Webhook, wenn sich etwas aendert, sonst nichts. Einen lokalen Server gab es
  bis 1.4; er ist bewusst entfernt und kommt nicht zurueck.
- **Geheimnisse bleiben draussen.** Die WLAN-Zugangsdaten der Saeule stehen in
  `firmware/signalsaeule/signalsaeule/arduino_secrets.h` und sind in
  `.gitignore`. Webhook-IDs einer echten HA-Instanz nie in Beispiele schreiben,
  Platzhalter `DEINE_WEBHOOK_ID` verwenden.
- **Signalsaeule-Pins:** MOSFET-Module, aktiv **HIGH**. D2 = H5 Blitz-Warnleuchte
  (1-Kanal-Modul K1), D3-D6 = H1 gruen, H2 orange, H3 rot, H4 Hinweis
  (K2 IN1-IN4), D7 = Tongeber (1-Kanal-Relais K3, seit 16.11.2026), wie im
  Stromlaufplan SIG-R4-E. Die Nummern 1-4 (Stufen), 5 (Warnleuchte) und 6
  (Ton) in `/api/state` nie umsortieren, die HA-Entitaeten haengen daran -
  eine geaenderte Verdrahtung nur ueber den Pin in `LEUCHTEN` richten.
  Stromlaufplan: `SIG-R4-E`. Die Klemmenbelegung an der Saeule steht in der
  README (Abschnitt 6) und im Kopf des Sketches.
- **Saeule: ein Ausgang hat eine Rolle**, nicht ein `bool warn`. `R_STUFE`
  folgt dem Status, `R_WARN` ist die Blitzleuchte, `R_TON` der Tongeber; die
  Kennung steht als `rolle` in `/api/state` und die Integration filtert
  danach (`coordinator.leuchten(ROLLE_TON)`). Ein Ausgang ohne gemeldete
  Rolle gilt als Stufe, damit eine aeltere Firmware nicht alle Schalter
  verliert.
- **Saeule: der Tongeber bleibt still, wo er nur kann.** Kein Status, kein
  Testmodus (`testStellen` setzt ihn ausdruecklich aus) und kein Startablauf
  nehmen ihn mit, und er liegt **nicht** im Flash-Gedaechtnis: nach einem
  Stromausfall ist er aus. Die Saeule bekommt um 4:45 Strom - ein gemerkter
  Ton wuerde beim Booten das halbe Haus wecken. In `sollAn()` steht er
  deshalb **vor** `if (testAn) return true;`.
- **Die Nummer eines Ausgangs nicht hartkodieren.** `async_rolle_schalten`
  sucht sie ueber `nummer_fuer(rolle)`; fehlt der Ausgang (aeltere Firmware
  ohne Tongeber), gibt es einen Fehler im Protokoll statt eines Schaltbefehls
  an eine geratene Nummer. Vorher stand im Ablauf `async_schalten(5, ...)`.
- **Kommt nie ein Beenden, raeumt das Sicherheitsnetz auf.** `_fertig()`
  erkennt am noch leeren `beendet_um`, dass der Weckruf-Teil ohne Beenden
  ausgelaufen ist, und ruft `_aufraeumen()` (Ton aus, Saeule auf Ruhe, Licht
  aus). Ohne das piepte der Tongeber die vollen `ABLAUF_MAX_S`.
- **Saeule: die Ausgaenge stellt der Zeitgeber, nicht `loop()`.** Ein GPT
  laeuft mit 100 Hz und ruft `lampenStellen()` aus der Unterbrechung. Grund:
  jede Socket-Operation geht beim R4 WiFi ueber den ESP32-S3, eine Anfrage
  haelt `loop()` ~200 ms auf, eine ganze Seite ueber eine Sekunde - das war
  das Ruckeln. In der Unterbrechung nie Strings, Matrix oder Netz anfassen;
  `alarmWarnPflegen()` und `matrixSpiegeln()` bleiben in der Schleife.
  `takt_max_us` in `/api/state` misst das nach (Soll 10 000).
- **Saeule: Antworten in einem Stueck schreiben.** Jedes einzelne `print` auf
  einen WiFiClient ist eine eigene Uebertragung an den ESP32-S3. Kopf und
  Rumpf werden darum erst zusammengebaut und mit einem `write` geschickt, die
  Seite in Happen von 1460 Byte.
- **Saeule: das Bild eines Status ist eine Maske, keine einzelne Lampe.**
  `ruheMaske()` sagt, was in der Ruhephase steht (Blinker: alle vier,
  Kreuzwechsel: orange+Hinweis), `sollMaske()` was Home Assistant als "an"
  sieht. Der Abbau raeumt nur, was nicht in `ruheMaske` steht - beim Blinker
  also nichts. Steht beim Wechsel schon die ganze Saeule (`ruheMaske` des
  alten Status ist 0b1111), faellt der Aufbau weg und es wird nur kurz
  gehalten (`mitAufbau`), sonst sieht es aus wie ein Stolperer.
- **Saeule: Stufe 4 ("Hinweis") ist orange**, nicht klar - im Dashboard
  entsprechend gezeichnet.
- **Saeule: der Blinktakt zaehlt ab dem Einrasten**, nicht ab `millis()` null
  (`blinkAb`, in `statusSetzen` gesetzt). Sonst ist der erste Impuls
  angeschnitten und beim Alarm faellt Rot im Einrastmoment aus, statt aus der
  Ruhephase weiterzuleuchten. Gleiches gilt fuer den Testmodus (`testSeit`).
- **Saeule: die Phasen der Ansage haengen allein an der Zeit.** Frueher endete
  die Ruhephase erst, wenn die Schleife `wechselAktiv` loeschte - bei einer
  blockierten Schleife stand die Moduslampe sekundenlang zu lange still.
  `eingerastet()` rechnet das aus `statusSeit` aus.
- **Saeule: Animationen nie behaupten, immer messen.** `POST /api/spur?an=1`,
  Vorgang ausloesen, `GET /api/spur` - jede Pegelaenderung mit Zeitstempel im
  10-ms-Takt. Eine HTTP-Abfrage dauert laenger als ein Blinkimpuls, mit
  Pollen laesst sich gar nichts pruefen.
- **Saeule: `an` und `live` sind zwei Dinge.** `an` ist der logische Zustand
  (bleibt stehen, waehrend die Leuchte blinkt), `live` der Pegel im Augenblick.
  HA nimmt `an`, das Dashboard `live`. Der Ereignisstrom pusht nur bei
  Aenderung der logischen Lage - sonst flattert HA im Sekundentakt.
- **Saeule: Typen vor die erste Funktion.** `arduino-cli` setzt seine erzeugten
  Prototypen vor die erste Funktionsdefinition im .ino. Stehen `enum Status`,
  `struct Leuchte` & Co. weiter unten, bricht der Build mit "'Status' was not
  declared in this scope" ab. Darum stehen alle Typen ganz oben.
- **Saeule: die Warnleuchte gehoert im Alarm dem Alarm.** Sie geht erst an,
  wenn `wechselAktiv` abgelaufen ist (Ansage *und* Ruhephase durch), also
  genau wenn Rot und Hinweis im Wechsel blinken - nicht waehrend der Ansage.
  `warnVomAlarm` merkt sich das, `warnVorAlarm` den Stand davor; beim
  Verlassen wird der wiederhergestellt. Von Hand schalten setzt
  `warnVomAlarm = false` und nimmt sie dem Alarm ab. Ins Gedaechtnis kommt
  immer der Handstand, nie der vom Alarm erzwungene.
- **Saeule: keine USB-Erkennung, nicht nochmal versuchen.** Am 14.11. auf dem
  Geraet gemessen: `R_USB_FS0->INTSTS0` liest aus dem Sketch 0 (also auch
  `VBSTS` und `DVSQ`), selbst nachdem man `USBMC_b.VDCEN = 1` setzt - der Core
  laesst das hinter `VUSB_LDO_ENABLE` aus, aber das allein ist nicht der Grund.
  `(bool)Serial` (`tud_cdc_connected()`) bleibt dauerhaft true, auch ohne
  offenen Port. Darum gibt es in `/api/state` kein `usb` mehr.
- **Saeule: stiller Start, und darum kein Gedaechtnis mehr.** Seit 1.2.0
  kommt die Saeule dunkel hoch: keine Startanimation, keine Matrix, Betriebsart
  manuell, alle Ausgaenge aus. Grund ist die Steckdose, die um 4:45 angeht -
  bis der Vorlauf kommt, darf in einem Schlafzimmer nichts leuchten. Damit war
  das Flash-Gedaechtnis (`Preferences`, Status/Modus/Warnleuchte) nicht nur
  nutzlos, es beschrieb den Daten-Flash umsonst; es ist ganz raus, samt
  `geaendert`/`merkenBald`. `START_ANIMATION = true` dreht die Animation
  zurueck. Dass die Saeule auf Befehl wieder aufwacht, ist am Geraet geprueft:
  `POST /api/status?status=hinweis` stellt auf Auto und leuchtet.
- **Der Tongeber steht nicht im Standardablauf.** Max will ihn als eigenen
  Knopf, nicht am Weckruf (16.11.2026). Die Moeglichkeit bleibt
  (`"ton": true` in einem Schritt), und dann raeumt der Ablauf ihn beim
  Schlummern und im Sicherheitsnetz auch wieder ab - aber nur, wenn er ihn
  selbst angestellt hat (`_ton_von_uns`). Sonst schaltete ein Weckruf den von
  Hand gedrueckten Knopf aus.
- **Eine geaenderte Weckzeit muss den Vorlauf nachziehen.** Stand der Vorlauf
  schon, blieb `laeuft` gesetzt und `_wecker_geaendert` plante nicht neu: am
  16.11. stellte Max abends 05:00 auf 04:50 um, der Stromplan zog mit (die
  Dose ging um 04:45 an), der Ablauf nicht. Um 04:50 klingelte es, die alten
  Timer auf 04:59 wurden abgeraeumt, und Hinweis und die 5 % Licht fielen
  ganz aus. Jetzt wird neu geplant, sobald `naechster != nullpunkt` - aber
  nur solange nichts klingelt und kein Nachlauf laeuft.
- **Weckablauf haengt am Wecker, nicht an einem Leuchtmittel** (`ablauf.py`).
  Vorher stand er in `lampe.py` und wurde nur in `_setup_relais` angelegt: ohne
  Relaisbox lief gar nichts, und die Hauptlicht-Option steckte in deren
  Optionsdialog. Der Ablauf greift ueber `hass.data[DOMAIN]` auf Geraete aus
  anderen Eintraegen zu (die Saeule), das ist Absicht.
- **Ein Schritt haengt entweder am Weckruf oder am Beenden** (`ab`:
  "weckruf" oder "ende"). Beide Haelften werden getrennt geplant; ein neuer
  Lauf raeumt nur die Timer seiner eigenen Haelfte ab. Der Nachlauf faengt
  genau dann an, wenn die App "ringing" auf false setzt - nicht nach Uhrzeit.
  Der Probelauf simuliert das Beenden nach 30 s, sonst liefe die zweite
  Haelfte nie an.
- **Das Ablauffeld im Optionsdialog nie mit dem Standardablauf
  vorausfuellen.** Genau das war am 14.11. die Ursache, warum der Nachlauf bei
  Max nicht lief: er hatte den Dialog geoeffnet und gespeichert, damit lag der
  damalige Standard fest in den Optionen und spaetere Verbesserungen kamen nie
  an. Leeres Feld heisst "nimm den aktuellen Standard".
- **Beim Schlummern aufraeumen.** Die Schritte des Weckrufs sind durch, der
  Nachlauf gilt noch nicht - ohne `_schlummern()` bliebe die Saeule im Alarm
  und das Licht an, bis es wieder klingelt.
- **Jeder Lauf braucht ein Ende.** Nach dem letzten Schritt setzt `_fertig()`
  `laeuft` und `probelauf` zurueck und plant gleich den naechsten Vorlauf.
  Ohne das blieb `laeuft` stehen: kein Vorlauf mehr, und waehrend `probelauf`
  stand, wurden echte Weckrufe stillschweigend ignoriert. `_fertig()` raeumt
  bewusst keine Timer ab - werden mehrere Zeitpunkte gleichzeitig faellig, ist
  die Reihenfolge nicht garantiert und der letzte Schritt fiele aus.
  Kommt nie ein Beenden (App stumm), greift `ABLAUF_MAX_S`.
- **Die naechste Weckzeit wird selbst gerechnet**, aus `hour`, `minute`,
  `days_mask` und `skip_next` der App-Nutzlast (`_termin_rechnen`).
  `next_trigger` ist nur Rueckfallebene: die App meldet sich nur bei
  Aenderungen, der Zeitstempel kann von gestern sein - daran scheiterte der
  Vorlauf.
- **Jeder Schritt kommt ins Protokoll**, auch der gescheiterte. Vorher wurden
  Fehler beim Lichtbefehl gefangen und nur geloggt; von aussen sah es aus, als
  passiere nichts. Das Protokoll haengt als Attribut am Schalter.
- **Kein festes Zeitfenster mehr.** Frueher entschied `_hauptlicht_erlaubt()`
  nach einem Fenster (Vorgabe 3-10 Uhr), ob das Hauptlicht ueberhaupt
  mitspielt; ausserhalb wurden die Lichtschritte gar nicht erst eingeplant.
  Jetzt bestimmen die Zeitbloecke der Ablaufdatei, welcher Ablauf gilt.
- **Kann eine Leuchte kein `transition`**, wird der Dienst ohne wiederholt,
  statt den Schritt verfallen zu lassen.
- **Der Strom der Saeule ist kein Ablaufschritt** (`strom.py`). Die Steckdose
  soll fuenf Minuten vor dem Weckruf an und erst abends wieder aus - ein
  Schritt im Weckablauf ginge nicht, dessen Lauf endet nach `ABLAUF_MAX_S`.
  Eigene Einheit, eigene Timer, aber dieselbe Weckzeit
  (`ablauf.naechste_weckzeit`) und dasselbe Protokoll.
- **Nie nachtraeglich ausschalten.** War Home Assistant um 21 Uhr aus, bleibt
  die Steckdose an. Eine zu lange angeschaltete Dose kostet nichts, eine zur
  falschen Zeit ausgeschaltete nimmt der Saeule mitten im Betrieb den Strom.
  Einschalten wird dagegen nachgeholt - aber nur einmal je An-Phase
  (`_phase_gesehen`), sonst dreht jede Meldung der App eine von Hand
  ausgeschaltete Dose wieder an.
- **`hass.async_create_task` startet die Aufgabe sofort** und laesst sie bis
  zum ersten echten Warten durchlaufen. Als `strom._schalten` am Ende neu
  plante, lief das synchron in die Planung zurueck - einmal im Kreis je
  Schaltvorgang, bis der Stapel voll war. Planen darf nur der Timer-Rueckruf.
- **Der Stromplan muss selbst melden.** Weckablauf und Stromplan haengen am
  selben Signal (`SIGNAL_WECKER_ALLE`), der Ablauf ist zuerst angemeldet und
  schreibt den Schalterzustand - ohne eigenes `_melden()` stehen die
  Zeitpunkte im Attribut `strom` noch auf dem Stand von vorher.
- **Dienstaufrufe auf `switch` im Test nicht mit `async_mock_service` fangen.**
  Die Integration richtet die Plattform `switch` selbst ein, deren echter
  Dienst ueberschreibt den Mock und die Aufrufe landen nirgends. Stattdessen
  `EVENT_CALL_SERVICE` am Bus mitschneiden (`_schaltrufe` in den Tests).
- **Weckruf:** Im Empfaenger nur PARTIAL_WAKE_LOCK. Schaltet man den Bildschirm
  vorher selbst ein, zeigt Android (ohne Sperre) statt der Weckruf-Seite nur den
  Hinweis oben. Bei eingeschaltetem, entsperrtem Handy kommt die Seite nur ueber
  den direkten startActivity aus `RingService`, und den laesst Android nur mit
  SYSTEM_ALERT_WINDOW („Ueber anderen Apps anzeigen", Zeile `overlay`) durch;
  ohne diese Freigabe bleibt es beim Hinweis oben (`RingState.seiteOffen`
  stoppt die Wiederholungen). Vorwarnung: Kanal `hawecker_prewarn_v3` mit IMPORTANCE_LOW (nie Ton;
  Live-Benachrichtigungen verlangen laut Google-Doku nur "nicht IMPORTANCE_MIN";
  mit DEFAULT klingelte Samsung trotz setSound(null)), wird sofort gezeigt, wenn der Weckruf
  naeher ist als die Vorwarnzeit. Den Live-Balken oben macht `VorwarnService`
  (Vordergrunddienst specialUse, nur in den Minuten vor dem Weckruf, Takt 20 s)
  mit `NotificationCompat.ProgressStyle` wie in der Kalender-App - braucht
  compileSdk 36, androidx.core 1.17 und AGP >= 8.9.1 (siehe Verlauf.kt).

## Pruefen

```bash
# Integration gegen einen echten HA-Testkern
python -m venv .venv && .venv/bin/pip install pytest-homeassistant-custom-component
.venv/bin/pytest tests/

# Firmware Signalsaeule
cd firmware/signalsaeule && arduino-cli compile -b arduino:renesas_uno:unor4wifi signalsaeule
arduino-cli upload -b arduino:renesas_uno:unor4wifi -p /dev/ttyACM0 signalsaeule

# App (Gradle 8.11.x, nicht 9; AGP 8.9.3, compileSdk 36)
cd app && echo "sdk.dir=$HOME/Android/Sdk" > local.properties && gradle assembleRelease
```

Beim Flashen oeffnet jedes Oeffnen des seriellen Ports einen Reset; mitlesen
mit 115200 Baud. Grund 15 beim WLAN heisst falsches Kennwort.

Die Portrechte sind seit dem 14.11.2026 geregelt: `/etc/udev/rules.d/99-arduino.rules`
gibt alle Boards mit Vendor 2341 an die Gruppe `wheel`, in der max ist. Kein
`sudo chgrp` mehr vor jedem Upload.
