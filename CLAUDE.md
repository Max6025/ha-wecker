# HA Wecker – Hinweise fuer die Arbeit am Repo

Drei Teile, eine Integration: `custom_components/ha_wecker` (Home Assistant),
`app/` (Android-Wecker-App), `firmware/relaisbox/` (ESP32-S3 mit Relais).
Die README beschreibt alles fuer Nutzer; hier stehen nur die Fallstricke.

## Regeln

- **Kein MQTT, kein Hintergrunddienst in der App.** Die App meldet sich per
  Webhook, wenn sich etwas aendert, sonst nichts. Einen lokalen Server gab es
  bis 1.4; er ist bewusst entfernt und kommt nicht zurueck.
- **Geheimnisse bleiben draussen.** `firmware/relaisbox/secrets.ini` (WLAN) ist
  in `.gitignore`. Webhook-IDs einer echten HA-Instanz nie in Beispiele
  schreiben, Platzhalter `DEINE_WEBHOOK_ID` verwenden.
- **Relaisbox-Pins:** Relaisplatine zieht bei **HIGH** an (`RELAIS_AKTIV_LOW =
  false`). Relais 1/3/4 an GPIO 38/36/35; Relais 2 der Platine ist defekt und
  nicht angeschlossen, die Nummern bleiben trotzdem 1, 3, 4 (`Relais.nr`).
  GPIO 37 ist der Eingang, GPIO 42 geht beim Start dauerhaft HIGH.
- **PSRAM nie einschalten** (`-DBOARD_HAS_PSRAM`): das N16R8-Modul legt sein
  Octal-PSRAM auf GPIO 33–37, dann sind die Relais-Pins blockiert.
- Die HTTP-Schnittstelle der Box (`/api/state`, `/api/relais/<nr>`,
  `/api/alarm`, `/api/alarm/stop`) ist der Vertrag zwischen Firmware und
  `relais.py`. Aenderungen immer auf beiden Seiten und im README.

## Pruefen

```bash
# Integration gegen einen echten HA-Testkern
python -m venv .venv && .venv/bin/pip install pytest-homeassistant-custom-component
.venv/bin/pytest tests/

# Firmware
cd firmware/relaisbox && pio run -e esp32s3            # -t upload zum Flashen

# App (Gradle 8.x, nicht 9)
cd app && echo "sdk.dir=$HOME/Android/Sdk" > local.properties && gradle assembleRelease
```

Beim Flashen oeffnet jedes Oeffnen des seriellen Ports einen Reset der Box;
mitlesen mit 115200 Baud. Grund 15 beim WLAN heisst falsches Kennwort.
