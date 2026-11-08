# HA Wecker

Zwei Geraete fuer Home Assistant in einer Integration, kein MQTT:

1. **Wecker** - eine eigene Android-Wecker-App (wie die Samsung-Uhr), die ihre
   **komplette Weckerliste** - auch die ausgeschalteten Wecker - per Webhook an
   Home Assistant meldet. Die App laeuft dafuer **nicht im Hintergrund**: kein
   Dienst, kein Intervall, kein Wakelock. Sie sendet nur, wenn sich etwas
   aendert, und schlaeft sonst.
2. **Relaisbox** - ein ESP32-S3 im WLAN mit Relaisplatine. Jedes Relais ist ein
   Schalter in HA, und die Integration bringt fertige Aktionen mit: `Alarm
   starten` laesst ein Relais ein Muster laufen (Doppelblitz, Blinken, SOS ...),
   `Alarm stoppen` beendet es. Ein Blueprint verbindet beides: solange der
   Wecker klingelt, blinkt das Relais.

```
ha-wecker/
├── custom_components/ha_wecker/   Home-Assistant-Integration (HACS-faehig)
├── blueprints/automation/         Blueprint "Relais blinkt, solange Wecker klingelt"
├── app/                           Android-App (Kotlin, nur androidx.core)
├── firmware/relaisbox/            PlatformIO-Firmware fuer den ESP32-S3
├── homeassistant/                 YAML-Alternative ohne Integration, Lovelace-Karte
└── tests/                         pytest mit pytest-homeassistant-custom-component
```

---

## 0. Schnellstart

1. **Integration installieren:** Ordner `custom_components/ha_wecker` in den
   HA-Konfigurationsordner kopieren (oder dieses Repo in HACS als eigenes
   Repository eintragen), HA neu starten.
2. **Wecker hinzufuegen:** Einstellungen -> Geraete & Dienste -> Integration
   hinzufuegen -> HA Wecker -> *Wecker (Android-App)*. Danach steht die
   Webhook-Adresse im Diagnose-Sensor „Webhook" und in den Optionen; die kommt
   in der App unter **API** in das Feld Webhook. App-APK aus `app/` bauen
   (Abschnitt 2) und installieren.
3. **Relaisbox hinzufuegen:** Firmware aus `firmware/relaisbox/` flashen
   (Abschnitt 6), WLAN-Zugang eintragen. Die Box meldet sich per mDNS, HA
   bietet sie unter „Entdeckt" an - oder von Hand: HA Wecker -> *Relaisbox
   (ESP32)* -> Adresse `relaisbox.local`.
4. **Verbinden:** Blueprint `blueprints/automation/ha_wecker/wecker_alarm_relais.yaml`
   importieren, Wecker-Sensor „Klingelt" und die gewuenschten Relais waehlen.

---

## 1. Was die App kann

**Wecker**
- Exakte Alarme ueber `AlarmManager.setAlarmClock()` – erscheint auch im
  Android-Statusbalken wie jeder andere Wecker
- Vollbild-Weckruf ueber dem Sperrbildschirm, Bildschirm geht an
- Alarm-Stream, Loop, sanft lauter werdend, Vibrationsmuster
- Eigener Weckton pro Wecker (Systempicker)
- Wiederholung pro Wochentag, Presets Mo-Fr / Taeglich / Einmalig
- Schlummern (Minuten pro Wecker einstellbar), Lautstaerketaste = Schlummern
- "Naechsten Termin ueberspringen" – Wecker bleibt an, faellt einmal aus
- Ueberlebt Neustart (BOOT_COMPLETED), Zeit- und Zeitzonenwechsel

**Home Assistant**
- Meldet **alle** Wecker per Webhook, mit `enabled: true/false` – also auch die
  deaktivierten, getrennt nach `active_alarms` / `inactive_alarms`
- Rein ereignisgesteuert: kein Dienst, kein Intervall, kein Server in der App

Keine externen Bibliotheken ausser `androidx.core`. Release-APK ca. 90 KB.

---

## 2. Bauen (App)

Android-Projekt liegt in `app/` (AGP 8.7.2, Kotlin 2.0.21, Gradle 8.9-8.11).

```bash
cd app
echo "sdk.dir=$HOME/Android/Sdk" > local.properties
gradle assembleRelease      # Gradle 8.x, nicht 9
# -> app/build/outputs/apk/release/app-release.apk
```

Die Release-APK wird mit dem Debug-Key signiert und ist direkt installierbar.

---

## 3. Einrichten auf dem Handy

1. APK installieren, App oeffnen, Benachrichtigungen erlauben
2. Dem Warnbanner folgen: **Vollbild-Weckruf**, **exakte Alarme** und
   **Akku-Optimierung** freigeben (jeweils ein Tipp fuehrt in die richtige
   Systemeinstellung)
3. Zahnrad -> **Webhook-Adresse** aus Home Assistant eintragen (steht dort beim
   Geraet „Wecker" im Diagnose-Sensor „Webhook" und unter „Konfigurieren"),
   **Push aktiv** einschalten, **JETZT SENDEN UND TESTEN**

---

## 4. Was die App an Home Assistant schickt (Webhook-Rumpf)

```json
{
  "state": "2026-11-08T06:30:00+01:00",
  "next_alarm": {
    "id": 1, "name": "Arbeit", "time": "06:30", "enabled": true,
    "days_label": "Mo-Fr", "next_trigger": "2026-11-08T06:30:00+01:00",
    "next_trigger_ts": 1762580000, "next_trigger_in": "12 Std 13 Min"
  },
  "next_alarm_time": "06:30",
  "next_alarm_in": "12 Std 13 Min",
  "total_count": 4,
  "active_count": 2,
  "inactive_count": 2,
  "ringing": false,
  "snoozed": false,
  "alarms":          [ ... alle, mit "enabled": true/false ... ],
  "active_alarms":   [ ... nur eingeschaltete ... ],
  "inactive_alarms": [ ... nur ausgeschaltete ... ],
  "summary": "AN   06:30  Mo-Fr  (Arbeit)\nAUS  08:00  Sa+So",
  "device_time": "2026-11-07T18:17:00+01:00",
  "timezone": "Europe/Berlin"
}
```

Dazu seit App 1.6 (`api_version` 2) ein Block `sleep` mit `enabled`, `active`,
`start`, `end`, `days_mask`, `next_start`, `next_end`, `remaining_minutes`, sowie
`sleep_active` und `prewarn_minutes` auf oberster Ebene.

Jeder Eintrag in `alarms` hat: `id`, `name`, `label`, `time`, `hour`, `minute`,
`enabled`, `repeating`, `days_mask`, `days_label`, `days`, `vibrate`,
`snooze_minutes`, `skip_next`, `snoozed`, `snoozed_until`, `ringing`,
`next_trigger`, `next_trigger_ts`, `next_trigger_in`, `next_trigger_in_minutes`.

---

## 5. Home Assistant - Integration (empfohlen)

Die Integration legt je Eintrag **ein Geraet** an - „Wecker" oder „Relaisbox" -
unter dem alle Entitaeten haengen. Beim Wecker erzeugt sie die Webhook-Adresse
selbst.

**Installieren**

1. Ordner `custom_components/ha_wecker` in den HA-Konfigurationsordner
   kopieren (dort liegt auch `configuration.yaml`), HA neu starten.
   Alternativ ueber HACS als eigenes Repository (`hacs.json` liegt bei).
2. Einstellungen -> Geraete & Dienste -> Integration hinzufuegen -> **HA Wecker**
   -> **Wecker (Android-App)**.
3. Beim Geraet den Diagnose-Sensor **Webhook** oeffnen: das Attribut
   `adresse_fuer_die_app` ist die Adresse, die in der App unter **API** als
   Webhook eingetragen wird. Die Adresse steht auch in den Optionen der
   Integration (Zahnrad "Konfigurieren").
4. In der App **Push aktiv** einschalten und **JETZT SENDEN UND TESTEN**
   druecken - oder einfach die App oeffnen, sie meldet sich dann von selbst.
   Mehr braucht es nicht: die App laeuft nicht im Hintergrund, und HA fragt sie
   nie ab.
5. Falls vorher der YAML-Block in `verlinkungen/template.yaml` eingebaut war:
   **wieder entfernen**, sonst gibt es die Entitaeten doppelt.

**Entitaeten**

| Entity | Inhalt |
|---|---|
| `sensor.ha_wecker_naechster_wecker` | Zeitstempel des naechsten Weckers (Attribute: Name, Uhrzeit, in) |
| `sensor.ha_wecker_naechster_wecker_in` | "12 Std 13 Min" |
| `sensor.ha_wecker_aktive_wecker` | Anzahl aktiver Wecker, Attribut `alarms` mit **allen** |
| `binary_sensor.ha_wecker_klingelt` | klingelt gerade |
| `binary_sensor.ha_wecker_schlafenszeit` | Schlafenszeit laeuft (Attribute von, bis, rest_minuten) |
| `binary_sensor.ha_wecker_06_30_arbeit` ... | **je Wecker eine Entitaet**: an = eingeschaltet, Attribute Uhrzeit, Tage, naechster Termin, heute uebersprungen, geschlummert |
| `sensor.ha_wecker_letzte_meldung` | wann sich das Handy zuletzt gemeldet hat (Diagnose) |
| `sensor.ha_wecker_webhook` | Webhook-ID, Attribut mit der Adresse fuer die App (Diagnose) |

Die Wecker-Entitaeten entstehen automatisch, sobald ein Wecker zum ersten Mal
gemeldet wird, und verschwinden wieder, wenn er in der App geloescht wurde.
Die `entity_id` wird nur beim Anlegen aus Uhrzeit und Name gebildet und bleibt
danach stabil - der angezeigte Name folgt der aktuellen Uhrzeit.

Der zuletzt gemeldete Stand wird gespeichert und ueberlebt einen HA-Neustart.

---

## 5a. Alternative ohne Integration: YAML

Wer keine Integration will, bekommt die Entitaeten auch per YAML:

- `homeassistant/webhook-push.yaml` – Push per Webhook als Template-Entitaeten
- `homeassistant/verlinkungen-template-anhaengen.yaml` – dasselbe als Listeneintrag fuer eine bestehende Template-Datei
- `homeassistant/lovelace-card.yaml` – Markdown-Karte mit allen Weckern
- `homeassistant/automation-beispiel.yaml` – Rollo, Licht, Fernschaltung

Du bekommst damit:

| Entity | Inhalt |
|---|---|
| `sensor.wecker_naechster` | Zeitstempel des naechsten Weckers |
| `sensor.wecker_aktiv` | Anzahl aktiver Wecker, Attribut `alarms` mit **allen** |
| `binary_sensor.wecker_klingelt` | klingelt gerade |
| `sensor.wecker_naechster_in` | "12 Std 13 Min" |

Damit siehst du – anders als beim HA-eigenen `sensor.next_alarm` der Companion
App – jeden einzelnen Wecker und ob er an oder aus ist.

---

## 5b. Push per Webhook (gilt fuer Integration und YAML)

Abfragen von aussen geht nicht: im Mobilfunknetz hat das Handy keine
erreichbare Adresse (CGNAT, wechselnde IP). Deshalb sendet die App von sich
aus - und zwar **ereignisgesteuert**, nicht im Intervall.

Gesendet wird bei:

- Wecker angelegt, geaendert, geloescht, ein- oder ausgeschaltet
- Weckruf beginnt, wird geschlummert oder gestoppt
- "Nur heute aus" / "Ausschalten" aus der Vorwarnung
- nach dem Neustart des Handys
- beim Oeffnen der App (hoechstens einmal pro Minute)

Dazwischen laeuft **nichts**: kein Dienst, kein Timer, kein Wakelock. Die App
wacht nur fuer die Wecker-Alarme auf, die der AlarmManager ohnehin ausloest.
Schlaegt ein Versand fehl (kein Netz), plant die App genau einen
Wiederholungsversuch in fuenf Minuten und schlaeft weiter.

**Einrichten**

1. Integration einrichten (Abschnitt 5) - oder ohne Integration
   `homeassistant/webhook-push.yaml` in die `configuration.yaml` uebernehmen,
   `webhook_id` durch eine eigene lange Zeichenfolge ersetzen, HA neu starten
2. In der App unter **API** die Webhook-Adresse eintragen:
   `https://DEINE-HA-ADRESSE/api/webhook/DEINE_WEBHOOK_ID`
3. **Push aktiv** einschalten, **JETZT SENDEN UND TESTEN** druecken

Kein Token noetig - die webhook_id ist das Geheimnis, also lang waehlen.

Die Entitaeten sind trigger-basierte Template-Entitaeten. Die stellen ihren
letzten Zustand nach einem HA-Neustart selbst wieder her, deshalb braucht es
kein regelmaessiges Nachsenden.

Einen lokalen Server gibt es in der App seit Version 1.5 nicht mehr: nichts
laeuft dauerhaft, nichts wird abgefragt.

---

## 5c. Benachrichtigungen

Im Normalbetrieb zeigt die App nichts an und hat keine Daueranzeige. Ausnahmen:

- **Vorwarnung als Live-Benachrichtigung** (seit 1.6): standardmaessig 5 Minuten
  vor dem Weckruf erscheint oben eine laufende Benachrichtigung mit Countdown
  („Klingelt in 04:59"). Auf Android 16 wird sie als *Live Update* angefordert
  (Statusleisten-Chip, Sperrbildschirm, Samsung Now Bar), darunter ist sie eine
  normale laufende Benachrichtigung mit Countdown. Knoepfe: **Nur heute aus**
  (wiederkehrender Wecker) und **Ausschalten**. Antippen oeffnet einen kleinen
  Dialog mit denselben Wahlmoeglichkeiten plus „Klingeln lassen", auch ueber dem
  Sperrbildschirm. Minuten einstellbar, 0 schaltet sie ab.
- **Schlafenszeit** (seit 1.6): in den Einstellungen ein taegliches Fenster
  „von - bis" (Ende darf nach Mitternacht liegen). Waehrend des Fensters zeigt
  die App eine stille Live-Anzeige mit Countdown bis zum Ende bzw. bis zum
  Wecker, und Home Assistant bekommt Beginn und Ende gemeldet
  (`binary_sensor ... schlafenszeit`) - z. B. fuer Licht aus, Rollos, Nicht
  stoeren. Die Anzeige laesst sich abschalten, die Meldung an HA bleibt.

- **Vorwarnung**: standardmaessig 10 Minuten vor dem Weckruf eine stumme
  Benachrichtigung mit einem Knopf. Bei einem wiederkehrenden Wecker heisst er
  **Nur heute aus** (der Wecker bleibt aktiv, faellt einmal aus), bei einem
  einmaligen **Ausschalten**. Minuten einstellbar, 0 schaltet sie ab.
- **Weckruf**: Vollbild plus Benachrichtigung, solange er laeuft.

---

## 6. Relaisbox (ESP32-S3)

Hardware: ESP32-S3-DevKitC-1 (zwei USB-C, RGB-LED, N16R8) mit einer
4-fach-Relaisplatine am 3V3-Pin. Relais 1-4 an GPIO 38, 39, 40, 41 (aktiv HIGH,
nebeneinander am rechten Stecker). GPIO 42 geht beim Start dauerhaft auf HIGH.
GPIO 2 ist ein **Eingang** fuer einen Taster oder Kontakt nach GND (interner
Pullup, gedrueckt = an, 30 ms entprellt). Fuer ein 3,3-V-Signal
`EINGANG_AKTIV_LOW` in `main.cpp` auf false setzen.

**Nie GPIO 33-37 benutzen.** Beim N16R8-Modul haengen diese Pins intern am
PSRAM-Chip. Relais daran klicken nur leise statt zu schalten, ein Eingang liest
ohne Taster HIGH - das sah aus wie ein defektes Relais, war aber der Pin. Pins und Polaritaet stehen oben in
`firmware/relaisbox/src/main.cpp`.

**Flashen**

```bash
cd firmware/relaisbox
cp secrets.ini.beispiel secrets.ini     # WLAN eintragen
pio run -e esp32s3 -t upload
```

Ohne `secrets.ini` oder bei falschem Kennwort oeffnet die Box nach 30 s das
Einrichtungs-WLAN **Relaisbox-Setup**; unter `http://192.168.4.1/` laesst sich
der Zugang eintragen. Seriell (115200) geht es auch: `wifi <ssid> <kennwort>`,
`scan`, `state`, `alarm`, `stop`. Die RGB-LED zeigt den Zustand: blau blinkend
= sucht WLAN, lila = Einrichtungs-WLAN offen, gruen = verbunden, amber
pulsierend = Alarmmuster laeuft.

**HTTP-Schnittstelle** (Port 80, `http://relaisbox.local/` zeigt eine Statusseite)

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/state` | Zustand aller Relais und des Eingangs als JSON |
| GET | `/api/ping` | Erreichbarkeitstest |
| GET | `:8081/api/events` | **Ereignisstrom** (Server-Sent Events): bei jeder Aenderung sofort der komplette Zustand, alle 15 s ein Lebenszeichen |
| POST | `/api/relais/<nr>?an=1` | Relais schalten (beendet ein Muster) |
| POST | `/api/alarm?relais=1,3&muster=doppelblitz&dauer=0` | Muster starten; `relais=alle`, `dauer` in s, 0 = bis Stopp |
| POST | `/api/alarm/stop?relais=1` | Muster beenden, Relais aus (ohne `relais` = alle) |
| POST | `/api/wifi?ssid=&pass=` | WLAN speichern, Neustart |

Muster: `dauer`, `blinken` (1 s/1 s), `langsam` (2 s/2 s), `schnell` (¼ s),
`doppelblitz` (100/120/100/680 ms wie eine Brandmeldezentrale), `sos`. Die
Muster laufen auf dem ESP, HA sagt nur, welches wie lange.

Die Integration haelt den Ereignisstrom dauerhaft offen, dadurch erscheinen
Eingang und Relaiszustand in HA ohne Verzoegerung. Reisst die Verbindung ab,
verbindet sie sich neu und fragt dazwischen alle 10 s ab. Ob der Strom steht,
zeigt das Attribut `ereignisstrom` am Diagnose-Sensor „Laufzeit".

**Entitaeten in HA**

| Entity | Inhalt |
|---|---|
| `switch.relaisbox_relais_1` ... `_4` | je Relais ein Schalter; Attribute `muster`, `rest_s` |
| `binary_sensor.relaisbox_alarm` | laeuft gerade ein Muster |
| `binary_sensor.relaisbox_eingang` | Taster an GPIO 2; Attribute `seit_s`, `zaehler` |
| `button.relaisbox_alarm_stoppen` | alles aus |
| `sensor.relaisbox_wlan_signal`, `sensor.relaisbox_laufzeit` | Diagnose, standardmaessig deaktiviert |

**Aktionen**

```yaml
action: ha_wecker.alarm_starten
target:
  entity_id: switch.relaisbox_relais_1     # oder device_id der Relaisbox
data:
  muster: doppelblitz
  dauer: 900          # Sekunden, 0 = bis "Alarm stoppen"
```

```yaml
action: ha_wecker.alarm_stoppen
target:
  device_id: <relaisbox>
```

Ohne Ziel gelten beide Aktionen fuer alle Relaisboxen. Der Blueprint in
`blueprints/automation/ha_wecker/` startet den Alarm, wenn `binary_sensor
... klingelt` auf *an* geht, und stoppt ihn beim Zurueckfallen auf *aus*; die
Hoechstdauer (Standard 15 Minuten) faengt den Fall ab, dass das Ende nicht
ankommt.

---

## 7. Warum nicht die Companion App

Die Home Assistant Companion App liest ueber den Sensor "Next Alarm" nur das
`AlarmClockInfo` des Systems. Android gibt dort ausschliesslich den naechsten
anstehenden Weckruf heraus – eine Liste aller eingetragenen Wecker samt
An/Aus-Zustand existiert in dieser System-API schlicht nicht, und die Samsung-Uhr
veroeffentlicht sie auch nirgends. Deshalb die eigene App mit eigener Quelle.
