# HA Wecker – Hinweise fuer die Arbeit am Repo

Drei Teile, eine Integration: `custom_components/ha_wecker` (Home Assistant),
`app/` (Android-Wecker-App), `firmware/relaisbox/` (ESP32-S3 mit Relais).
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
  `/api/alarm`, `/api/alarm/stop`, Ereignisstrom `:8081/api/events`) ist der
  Vertrag zwischen Firmware und `relais.py`. Aenderungen immer auf beiden
  Seiten und im README. Der Ereignisstrom laeuft auf einem eigenen Port, weil
  der Arduino-WebServer keine Verbindung offen halten kann.

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

# Firmware
cd firmware/relaisbox && pio run -e esp32s3            # -t upload zum Flashen

# App (Gradle 8.11.x, nicht 9; AGP 8.9.3, compileSdk 36)
cd app && echo "sdk.dir=$HOME/Android/Sdk" > local.properties && gradle assembleRelease
```

Beim Flashen oeffnet jedes Oeffnen des seriellen Ports einen Reset der Box;
mitlesen mit 115200 Baud. Grund 15 beim WLAN heisst falsches Kennwort.
