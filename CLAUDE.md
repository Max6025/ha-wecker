# HA Wecker – Hinweise fuer die Arbeit am Repo

Vier Teile, eine Integration: `custom_components/ha_wecker` (Home Assistant),
`app/` (Android-Wecker-App), `firmware/relaisbox/` (ESP32-S3 mit Relais),
`firmware/signalsaeule/` (Arduino UNO R4 WiFi an einer Rittal-Signalsaeule).
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
- **Geheimnisse bleiben draussen.** `firmware/relaisbox/secrets.ini` (WLAN) ist
  in `.gitignore`. Webhook-IDs einer echten HA-Instanz nie in Beispiele
  schreiben, Platzhalter `DEINE_WEBHOOK_ID` verwenden.
- **Relaisbox-Pins:** Relaisplatine zieht bei **HIGH** an (`RELAIS_AKTIV_LOW =
  false`; die Module laufen bei Max an 3,3 V, das nicht anzweifeln). Relais 1-3
  an GPIO 4/5/6, Eingang GPIO 7 (Taster nach GND, Pullup, `EINGANG_AKTIV_LOW`),
  GPIO 42 geht beim Start dauerhaft HIGH. Freie Reserve: 15, 16, 17, 18, 1, 2.
  Bauweise „Lampen" (`-e esp32s3-lampe`, `-DNUR_LAMPE`): MOSFET-Module an
  GPIO 1 (Relais 1 Lampe + gruene LED), 40 (Relais 3 Rot), 41 (Relais 4
  Warnleuchte); Nummer 2 bewusst frei, Nummern nie umsortieren (Lampenplan in
  HA haengt daran), kein Taster; `-e
  esp32s3-lampe-test` laesst das Lichtbild ab dem Einschalten dauernd laufen.
  `pegel` in `/api/state` ist der zurueckgelesene Pin: zeigt er den Wechsel
  und die Lampe bleibt an, liegt es am Modul oder der Verdrahtung.
- **GPIO 33–37 nie benutzen und PSRAM nie einschalten.** Das N16R8-Modul legt
  sein Octal-PSRAM auf diese Pins; auch ohne PSRAM-Init sind sie belastet:
  Relais klicken nur leise, Eingaenge lesen HIGH. Hat am 7./8.11. ein „defektes
  Relais" vorgetaeuscht.
- Die HTTP-Schnittstelle der Box (`/api/state`, `/api/relais/<nr>`,
  `/api/alarm`, `/api/alarm/stop`, `/api/led`, Ereignisstrom `:8081/api/events`) ist der
  Vertrag zwischen Firmware und `relais.py`. Aenderungen immer auf beiden
  Seiten und im README. Der Ereignisstrom laeuft auf einem eigenen Port, weil
  der Arduino-WebServer keine Verbindung offen halten kann.

- **Signalsaeule-Pins:** MOSFET-Module, aktiv **HIGH**. D2 = H5 Blitz-Warnleuchte
  (1-Kanal-Modul K1), D3-D6 = H1 gruen, H2 orange, H3 rot, H4 Hinweis (K2 IN1-IN4).
  Die Nummern in `/api/state` (1-4 Stufen, 5 Warnleuchte) nie umsortieren, die
  HA-Entitaeten haengen daran. Stromlaufplan: `SIG-R4-E`.
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
- **Saeule: Gedaechtnis im Daten-Flash.** Status, Betriebsart und Warnleuchte
  liegen in `Preferences` ("saeule"), damit die Saeule nach einem Stromausfall
  ihren Status wieder aufnimmt. Verzoegert geschrieben (3 s) und nur bei echter
  Aenderung - der Daten-Flash haelt keine beliebige Zahl von Zyklen aus.
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

# Firmware Relaisbox
cd firmware/relaisbox && pio run -e esp32s3            # -t upload zum Flashen

# Firmware Signalsaeule
cd firmware/signalsaeule && arduino-cli compile -b arduino:renesas_uno:unor4wifi signalsaeule
arduino-cli upload -b arduino:renesas_uno:unor4wifi -p /dev/ttyACM0 signalsaeule

# App (Gradle 8.11.x, nicht 9; AGP 8.9.3, compileSdk 36)
cd app && echo "sdk.dir=$HOME/Android/Sdk" > local.properties && gradle assembleRelease
```

Beim Flashen oeffnet jedes Oeffnen des seriellen Ports einen Reset der Box;
mitlesen mit 115200 Baud. Grund 15 beim WLAN heisst falsches Kennwort.

`/dev/ttyACM0` des Arduino gehoert nach jedem Anstecken `root:uucp`, und max ist
nicht in `uucp`. Vor dem Upload darum einmal
`sudo chgrp wheel /dev/ttyACM0 && sudo chmod g+rw /dev/ttyACM0`.
