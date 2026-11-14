# HA Wecker

Zwei Geraete fuer Home Assistant in einer Integration, kein MQTT:

1. **Wecker** - eine eigene Android-Wecker-App (wie die Samsung-Uhr), die ihre
   **komplette Weckerliste** - auch die ausgeschalteten Wecker - per Webhook an
   Home Assistant meldet. Die App laeuft dafuer **nicht im Hintergrund**: kein
   Dienst, kein Intervall, kein Wakelock. Sie sendet nur, wenn sich etwas
   aendert, und schlaeft sonst. An ihm haengt der **Weckablauf**: was rund um
   den Weckruf passiert - Hauptlicht hochdimmen, Saeule schalten - steht in
   einer Ablaufdatei mit Zeitbloecken.
2. **Signalsaeule** - ein Arduino UNO R4 WiFi an einer Rittal-Signalsaeule mit
   vier Leuchtelementen und einer Blitz-Warnleuchte. Oben ein Umschalter
   **Auto / Manuell**: in Auto treibt ein **Status** die Saeule (Ruhe, Hinweis,
   Achtung, Stoerung, Alarm, Kreuzwechsel, Blinker), jeder Wechsel wird
   angesagt und bleibt dann stehen; in Manuell schaltet man die Leuchten
   einzeln. Die Blitz-Warnleuchte hat ihren eigenen Schalter. Die Saeule bringt
   ein **eigenes Web-Dashboard** mit (Live-Bild, Testmodus, Selbstdiagnose) und
   merkt sich ihren Status ueber einen Stromausfall hinweg.

Bis November 2026 gab es eine dritte: die **Relaisbox** (ESP32-S3). Sie ist
draussen; die Signalsaeule hat ihre Aufgabe uebernommen, und der Weckablauf
haengt nicht mehr an ihr, sondern am Wecker.

```
ha-wecker/
├── custom_components/ha_wecker/   Home-Assistant-Integration (HACS-faehig)
├── app/                           Android-App (Kotlin, nur androidx.core)
├── firmware/signalsaeule/         Arduino-Sketch fuer den UNO R4 WiFi
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
   Webhook-ID beim Anlegen, im Diagnose-Sensor „Webhook" und in den Optionen; die kommt
   in der App unter dem Zahnrad in das Feld Webhook-ID. App-APK aus `app/` bauen
   (Abschnitt 2) und installieren.
3. **Signalsaeule hinzufuegen:** Sketch aus `firmware/signalsaeule/` flashen
   (Abschnitt 6), WLAN-Zugang in `arduino_secrets.h` eintragen. Dann
   HA Wecker -> *Signalsaeule* -> Adresse der Saeule.
4. **Weckablauf einstellen:** beim Geraet „Wecker" auf Konfigurieren, dort das
   **Hauptlicht** waehlen und die **Ablaufdatei** anpassen (Abschnitt 6a).
   Danach den Knopf **Probelauf** druecken - er spielt alles sofort durch.

---

## 1. Was die App kann

**Oberflaeche (seit 2.0)**
- Aussehen und Bedienung 1:1 nach dem Mockup „Hora Wecker" (08.11.2026): die
  Seite liegt als HTML/CSS/JS in `app/app/src/main/assets/ui/` und laeuft in
  einer WebView; Wecker, Planung, Klingeln und Push bleiben nativ (Kotlin).
  Bruecke: `UiBridge.kt` (Seite -> App) und `window.aktualisieren()` (App -> Seite).
- Hero-Box „Naechster Weckruf", Kachelraster mit Kategoriebild und Farbe,
  kurz tippen = an/aus, lange druecken = bearbeiten, Zeitrad mit Uebertrag,
  Kategorien mit 30 Bildern (Farbe gehoert zum Bild), Vollbild-Weckruf mit
  Schieberegler. Schriften Archivo und Manrope liegen in den Assets.
- Vorschau am Rechner ohne Handy: `cd app/app/src/main/assets/ui && python3 -m
  http.server 8765`, dann `http://127.0.0.1:8765/app.html` (Beispieldaten,
  nichts wird gespeichert).

**Wecker**
- Exakte Alarme ueber `AlarmManager.setAlarmClock()` – erscheint auch im
  Android-Statusbalken wie jeder andere Wecker
- Vollbild-Weckruf ueber dem Sperrbildschirm, Bildschirm geht an
- Wecktoene aus dem Handy (Alarm- und Klingeltoene des Systems) in der eigenen
  Auswahlseite, kein Systemdialog; Alarm-Kanal, sanft lauter werdend,
  Vibrationsmuster Herzschlag / Kurz / Stakkato / Welle
- Wiederholung pro Wochentag, Kategorie, Schlummern 5 / 7 / 9 Minuten oder
  eigene Zeit, Lautstaerketaste = Schlummern
- Vorwarnung als Live-Benachrichtigung mit Balken oben (Android 16), 5 Minuten
  vorher oder sofort, wenn der Weckruf naeher ist; nur in diesem Fenster laeuft
  ein kurzer Dienst, davor nichts. Schlafenszeit, „heute ueberspringen"
- Ueberlebt Neustart (BOOT_COMPLETED), Zeit- und Zeitzonenwechsel

**Home Assistant**
- Meldet **alle** Wecker per Webhook, mit `enabled: true/false` – also auch die
  deaktivierten, getrennt nach `active_alarms` / `inactive_alarms`; seit 2.0
  je Wecker `kategorie`, `ton`, `vibration` und oben `kategorien` (api_version 3)
- Rein ereignisgesteuert: kein Dienst, kein Intervall, kein Server in der App

Keine externen Bibliotheken ausser `androidx.core`. Release-APK ca. 470 KB
(davon die zwei Schriften).

---

## 2. Bauen (App)

Android-Projekt liegt in `app/` (AGP 8.9.3, Kotlin 2.0.21, Gradle 8.11.1, compileSdk 36).

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
2. Dem Warnbanner folgen: **Vollbild-Weckruf**, **Ueber anderen Apps
   anzeigen**, **exakte Alarme** und **Akku-Optimierung** freigeben (jeweils
   ein Tipp fuehrt in die richtige Systemeinstellung). Vollbild-Weckruf gilt
   fuer den ausgeschalteten Bildschirm, „Ueber anderen Apps anzeigen" fuer
   das eingeschaltete, entsperrte Handy - erst mit beidem oeffnet sich die
   Weckruf-Seite immer.
3. Einstellungen -> **Home Assistant** -> **Webhook-ID** aus Home Assistant eintragen (zeigt die
   Integration beim Hinzufuegen des Geraets „Wecker" an, spaeter im
   Diagnose-Sensor „Webhook" und unter „Konfigurieren"). Die
   Home-Assistant-Adresse ist vorausgefuellt (`Prefs.HA_ADRESSE_STANDARD`,
   ohne Port, da HA hinter HTTPS haengt) und laesst sich aendern.
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

Die Integration legt je Eintrag **ein Geraet** an - „Wecker" oder „Signalsäule" -
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
2. In der App unter Einstellungen -> Home Assistant die **Webhook-ID** eintragen; die
   Home-Assistant-Adresse steht schon da. Eine ganze Adresse
   `https://DEINE-HA-ADRESSE/api/webhook/DEINE_WEBHOOK_ID` im ID-Feld wird
   automatisch aufgeteilt.
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

## 6. Signalsaeule (Arduino UNO R4 WiFi)

Hardware: Rittal Signalsaeule SZ 2372.02.0 mit vier Leuchtelementen, dazu eine
Blitz-Warnleuchte. Geschaltet wird ueber MOSFET-Leistungsstufen (F5305S,
P-Kanal, also im Pluspfad) - eine mit einem Kanal fuer die Warnleuchte, eine
mit vier Kanaelen fuer die Saeule. Die Module ziehen bei **HIGH** durch.
Der komplette Aufbau steht im Stromlaufplan `SIG-R4-E`.

| Ausgang | Modul    | Betriebsmittel        | Ader    |
|---------|----------|-----------------------|---------|
| D2      | K1 : IN  | H5 Blitz-Warnleuchte  | weiss   |
| D3      | K2 : IN1 | H1 gruen, Stufe 1     | gelb    |
| D4      | K2 : IN2 | H2 orange, Stufe 2    | weiss   |
| D5      | K2 : IN3 | H3 rot, Stufe 3       | gelb    |
| D6      | K2 : IN4 | H4 Hinweis (orange), Stufe 4 | rot |

Die Zuordnung stimmt mit dem Stromlaufplan `SIG-R4-E` ueberein.

Die Nummern in `/api/state` (1 gruen bis 4 Hinweis, 5 Warnleuchte) bleiben
stabil - die Entitaeten in Home Assistant haengen daran.

**Betriebsarten.** In **Auto** treibt der Status die Saeule. Ein Wechsel wird
immer gleich angesagt: alle vier Stufen laufen von unten nach oben dazu (bei
einem Wechsel nach unten umgekehrt), dann raeumt die Saeule von oben nach unten
wieder ab und laesst nur die Lampe des neuen Status stehen, die erst eine
Weile ruhig dasteht, bevor die Hinweisleuchte zu blinken beginnt. Danach steht
das Bild des Status:

| Status        | Stehendes Bild                                         |
|---------------|--------------------------------------------------------|
| Ruhe          | gruen                                                   |
| Hinweis       | gruen, Hinweis blinkt ruhig (1 s)                       |
| Achtung       | orange, Hinweis blinkt (0,4 s)                          |
| Stoerung      | rot, Hinweis blinkt schnell (0,2 s)                     |
| Alarm         | rot und Hinweis im Wechsel (0,25 s), Warnleuchte dauernd |
| Kreuzwechsel  | orange+Hinweis und gruen+rot ueber Kreuz (0,3 s), ohne Warnleuchte |
| Blinker       | alle vier zusammen, schnell (0,15 s)                    |

Die Stufe 4 ("Hinweis") ist ebenfalls **orange**, nicht klar.

Beim **Blinker** bleiben alle vier stehen, darum gibt es nach dem Aufbau nichts
abzuraeumen: Stufe 1, 2, 3, 4 kommen nacheinander dazu und dann blinkt alles.
Und wer den Blinker verlaesst, bekommt keinen zweiten Aufbau - es steht ja
schon alles. Dann heisst es: alle kurz halten, dann Stufe 4 aus, 3 aus, 2 aus,
1 aus, wobei die Lampe des neuen Status uebersprungen wird und stehen bleibt.
In **Manuell** gilt der Status nicht, stattdessen schaltet man jede Leuchte
einzeln. Eine Stufe von Hand zu schalten stellt selbst auf Manuell um, und
einen Status zu waehlen stellt selbst auf Auto zurueck.

Die **Blitz-Warnleuchte** haengt an keiner Choreografie: eigener Schalter, gilt
in beiden Betriebsarten. Mitgenommen wird sie von zweierlei. Im **Testmodus**
blitzt sie in Schueben. Und im Status **Alarm** geht sie von selbst an - aber
erst, wenn das Alarmbild wirklich laeuft, also wenn Rot und Hinweisleuchte im
Wechsel zu blinken anfangen, nicht schon waehrend der Ansage. Dann bleibt sie
dauerhaft an. Verlaesst die Saeule den Alarm, bekommt die Warnleuchte wieder
den Stand, den sie vorher von Hand hatte; wer sie waehrend des Alarms selbst
schaltet, nimmt sie dem Alarm ab. In `/api/state` sagt `warn_vom_alarm`, wer
sie gerade in der Hand hat.

**Das Licht haengt nicht an der Schleife.** Beim UNO R4 WiFi laeuft jede
Socket-Operation ueber eine Uebertragung an den ESP32-S3, der das WLAN macht.
Eine einzelne Anfrage haelt `loop()` dadurch leicht 200 ms auf, das Ausliefern
der ganzen Seite ueber eine Sekunde - und genau so sah das Blinken auch aus:
Wackler, Aussetzer, mal zu langsam. Darum stellt ein **Hardware-Zeitgeber**
(GPT, 100 Hz) die Ausgaenge, voellig unabhaengig von `loop()`. In der
Unterbrechung wird nur geschaltet: keine Strings, keine Matrix, kein Netz.
Gemessen auf dem Geraet: der Taktabstand bleibt bei 10 003 us (Soll 10 000),
auch waehrend die Schleife 1,5 s mit einer Seite beschaeftigt ist.

**Die LED-Matrix zeigt die Saeule im Kleinen**: vier Balken von unten nach
oben, genau die, die gerade brennen, und bei eingeschalteter Blitzleuchte zwei
Striche an den Seiten. Das Blinken laeuft mit. Buchstaben waren auf zwoelf mal
acht Punkten nicht zu entziffern, ein Abbild schon - und es sagt mehr.

**Nach dem Einschalten** laeuft ein Punkt einmal die Saeule hoch und wieder
herunter (je Stufe 120 ms), dann blitzt sie zweimal komplett auf - beim ersten
Mal zuckt die Blitzleuchte mit. Nach zwei Sekunden ist der Ablauf vorbei und
die Saeule nimmt **sofort** den Status wieder auf, der vor dem Stromausfall
stand; erst danach verbindet sie sich mit dem WLAN und zeigt das letzte Glied
ihrer Adresse Ziffer fuer Ziffer auf der Matrix. Die Reihenfolge ist Absicht:
andersherum stand die Saeule dreizehn Sekunden dunkel da und sah aus wie tot,
so lange dauert das Verbinden.

**Mitschreiber zum Nachmessen.** `POST /api/spur?an=1` startet eine
Aufzeichnung, `GET /api/spur` gibt sie zurueck: jede Aenderung des
Leuchtbildes mit Zeitstempel, aufgenommen im Takt (10 ms). Damit laesst sich
jede Animation von aussen nachmessen - eine HTTP-Abfrage allein ist dafuer viel
zu langsam, die dauert laenger als ein Blinkimpuls. Der Startablauf wird
automatisch ab dem Einschalten mitgeschrieben.

Nachgemessene Zeiten (alle auf dem Geraet, nicht gerechnet):

| Vorgang                         | Soll        | Gemessen |
|---------------------------------|-------------|----------|
| Aufbau der Ansage, je Stufe     | 180 ms      | 180 ms   |
| Abbau der Ansage, je Stufe      | 180 ms      | 180 ms   |
| Ruhephase vor dem Blinken       | 1400 ms     | 1400 ms  |
| Hinweis blinkt                  | 1000 ms     | 1000 ms  |
| Achtung blinkt                  | 400 ms      | 400 ms   |
| Stoerung blinkt                 | 200 ms      | 200 ms   |
| Alarm, Rot und Hinweis wechseln | 250 ms      | 250 ms   |
| Testmodus, je Stufe             | 300 ms      | 300 ms   |
| Warnleuchte im Test             | 2000/3000 ms| 2000/3000|
| Startablauf gesamt              | 2000 ms     | 2000 ms  |

Unter Last gemessen: waehrend acht Abrufe der ganzen Dashboard-Seite die
Schleife bis zu 1,26 s blockierten, waren **alle 53 Blinkimpulse exakt
200 ms** lang. Status, Betriebsart und Warnleuchte liegen dafuer im
Daten-Flash des RA4M1 (`Preferences`); geschrieben wird verzoegert und nur bei
echter Aenderung.

**Dashboard.** Unter `http://<adresse>/` liefert die Saeule ihre eigene Seite:
eine gezeichnete Signalsaeule, die live mitleuchtet (auch das Blinken),
Umschalter Auto/Manuell, Testmodus, Selbstdiagnose mit Ergebnisliste und die
Werte des Geraets. Was gerade nichts tut, wird ausgeblendet: in **Auto** steht
das Status-Auswahlfeld da und die Einzelschalter sind weg, in **Manuell**
umgekehrt. Die Blitz-Warnleuchte hat ihren Schalter in beiden Betriebsarten. Die Seite liegt im Flash des Arduino, es braucht keinen Server.

**Selbstdiagnose.** Sie prueft, was der Arduino selbst wissen kann: WLAN
(Verbindung, Feldstaerke, Adresse), Geraet und Firmware, ob `digitalRead` einem
Ausgang ueberhaupt folgt, dann jeden Ausgang einzeln fuer 400 ms, und zuletzt
freien Speicher und Laufzeit. Ob eine Leuchte wirklich brennt, sieht er nicht -
dafuer fehlt eine Rueckmeldung aus der Saeule. Die Blitzleuchte blitzt dabei
kurz.

**Keine USB-Erkennung.** Am 14.11. gemessen und wieder ausgebaut: `INTSTS0` des
RA4M1 liest aus dem Sketch durchweg 0, `VBSTS` und `DVSQ` damit auch - auch
dann, wenn man `VDCEN` selbst setzt (der Core laesst die VBUS-Erkennung hinter
`VUSB_LDO_ENABLE` aus). Umgekehrt bleibt `(bool)Serial` alias
`tud_cdc_connected()` dauerhaft **true**, auch ohne offenen Port. Weder
"Spannung da" noch "Rechner dran" laesst sich damit ehrlich anzeigen, darum
gibt es die Anzeige nicht.

**Ohne Leistungsstufe.** Solange ein Modul noch fehlt, steht rechts neben jeder
Leuchte der zurueckgelesene Pin (`D3 · high`). So sieht man am Dashboard, dass
der Arduino wirklich schaltet, obwohl nichts leuchtet. Derselbe Wert steht in
`/api/state` als `pegel` und in Home Assistant im Attribut `pegel` des
Schalters.

**HTTP-Schnittstelle** (Vertrag zwischen Firmware und `saeule.py`)

```
GET  /                          Dashboard
GET  /api/state                 kompletter Zustand als JSON
GET  /api/live                  Kurzfassung fuer das Dashboard
GET  /api/ping                  {"ok":true,"typ":"saeule"}
GET  :8081/api/events           Ereignisstrom (SSE), bei jeder Aenderung
POST /api/relais/<nr>?an=1|0    eine Leuchte schalten (Stufe -> Manuell)
POST /api/modus?modus=auto|manuell
POST /api/status?status=ruhe|hinweis|achtung|stoerung|alarm   (-> Auto)
POST /api/test?an=1|0           Testmodus
POST /api/diagnose              Selbstdiagnose starten
POST /api/alarm/stop            alles aus, Betriebsart Manuell
```

In `/api/state` ist `an` der **logische** Zustand einer Leuchte - er bleibt
stehen, waehrend sie blinkt - und `live` der Pegel in diesem Augenblick. Home
Assistant nimmt `an`, das Dashboard `live`; sonst wuerden die Schalter in HA im
Sekundentakt flattern.

**Flashen**

```bash
cp firmware/signalsaeule/signalsaeule/arduino_secrets.h.beispiel \
   firmware/signalsaeule/signalsaeule/arduino_secrets.h   # WLAN eintragen
cd firmware/signalsaeule
arduino-cli compile -b arduino:renesas_uno:unor4wifi signalsaeule
arduino-cli upload -b arduino:renesas_uno:unor4wifi -p /dev/ttyACM0 signalsaeule
```

**In Home Assistant hinzufuegen:** Einstellungen -> Geraete & Dienste -> HA
Wecker -> *Signalsäule (Arduino UNO R4 WiFi)*, dann die Adresse eintragen. Es
entstehen zwei Auswahlfelder (Betriebsart, Status), ein Schalter je Leuchte,
der Schalter *Warnleuchte*, *Testmodus*, die Knoepfe *Selbstdiagnose* und
*Alles aus* sowie Sensoren fuer Anzeige, Selbstdiagnose, Feldstaerke und
Laufzeit.

---

## 6a. Weckablauf (Hauptlicht und Saeule folgen dem Wecker)

Der Weckablauf haengt am **Wecker**, nicht an einem Leuchtmittel. Er holt sich
die Weckzeiten aus dem, was die App gemeldet hat, und steuert damit Geraete aus
anderen Eintraegen derselben Integration - die Signalsaeule etwa. Bis November
2026 hing er an der Relaisbox: ohne die lief gar nichts.

**Einstellen:** Optionen des Geraets „Wecker" (Zahnrad „Konfigurieren").

| Feld | Inhalt |
|---|---|
| Hauptlicht | eine dimmbare `light`-Entitaet; leer = kein Hauptlicht |
| Ablaufdatei | JSON mit Zeitbloecken (siehe unten); leer = Standardablauf |

**Entitaeten**

| Entity | Inhalt |
|---|---|
| `switch.ha_wecker_weckablauf` | an = der Ablauf laeuft mit. Attribute: Block, naechster Wecker, Nullpunkt, Fehler der Ablaufdatei und das **Protokoll** jedes Schritts mit Ergebnis |
| `button.ha_wecker_probelauf` | spielt den Ablauf sofort durch: eine Minute Vorlauf, dann „klingelt" es |

**Ablaufdatei**

```json
{
  "version": 1,
  "bloecke": [
    {
      "name": "Werktags frueh",
      "wochentage": ["mo", "di", "mi", "do", "fr"],
      "von": "04:00",
      "bis": "10:00",
      "schritte": [
        { "zeit": -60, "saeule": { "status": "hinweis" } },
        { "zeit": -60, "licht":  { "prozent": 3, "dauer": 60 } },
        { "zeit":   0, "saeule": { "status": "alarm" } },
        { "zeit":   0, "licht":  { "prozent": 90, "dauer": 20 } },
        { "zeit": 540, "licht":  { "prozent": 5, "dauer": 30 } },
        { "zeit": 840, "licht":  { "aus": true } },
        { "zeit": 840, "saeule": { "status": "ruhe" } }
      ]
    }
  ]
}
```

- `zeit` zaehlt in **Sekunden ab dem Klingeln**, negativ heisst vorher.
- Es gilt der **erste Block**, dessen Wochentag und Zeitfenster zur Weckzeit
  passen. `von` gleich `bis` heisst: immer.
- `licht`: `prozent` (0-100), `dauer` in Sekunden fuer den Uebergang, `aus`.
  Kann die Leuchte kein `transition`, wird der Befehl ohne wiederholt.
- `saeule`: `status` (eine Kennung aus der Statusliste der Saeule) und `warn`
  fuer die Blitz-Warnleuchte.
- Unsinn in der Datei wird beim Speichern abgelehnt, mit Angabe von Block und
  Schritt. Bis dahin gilt der Standardablauf.

**Die Weckzeit rechnet die Integration selbst** aus Stunde, Minute und
Wochentagsmaske, die die App mitschickt, inklusive „naechsten ueberspringen".
`next_trigger` aus der Nutzlast ist nur die Rueckfallebene: die App meldet sich
nur bei Aenderungen, der Zeitstempel kann also alt sein. Genau daran scheiterte
vorher der Vorlauf.

**Wenn nichts passiert:** Das Protokoll am Schalter `switch.ha_wecker_weckablauf`
zeigt jeden Schritt mit Zeit, Ziel und Ergebnis - auch die gescheiterten. Fuer
einen schnellen Versuch den Knopf **Probelauf** druecken, statt bis zum
naechsten Morgen zu warten.

---

## 7. Warum nicht die Companion App

Die Home Assistant Companion App liest ueber den Sensor "Next Alarm" nur das
`AlarmClockInfo` des Systems. Android gibt dort ausschliesslich den naechsten
anstehenden Weckruf heraus – eine Liste aller eingetragenen Wecker samt
An/Aus-Zustand existiert in dieser System-API schlicht nicht, und die Samsung-Uhr
veroeffentlicht sie auch nirgends. Deshalb die eigene App mit eigener Quelle.
