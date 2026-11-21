# HA Wecker

Drei Geraete fuer Home Assistant in einer Integration, kein MQTT:

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

3. **Garage** - der Garagen-ESP des Peugeot 206 (ESP32 an der Lichtschranke,
   Firmware `ls` im Repo `van206`). Er liest, ob das Auto weit genug drin steht,
   schaltet die rote Lampe und hoert per Funk den ESP im Auto. In Home Assistant
   stehen die **Ampel** (Stopp, Frei, kein Strom, aus - dieselbe wie im Tacho),
   Tor, Auto in der Garage, **Auto-ESP verbunden**, verriegelt, Zuendung,
   Rueckwaertsgang, Strom der Lichtschranke, Lampe. **Er meldet sich selbst
   an** - in Home Assistant muss niemand etwas einrichten (Abschnitt 8).

Bis November 2026 gab es daneben die **Relaisbox** (ESP32-S3). Sie ist
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
   Haengt die Saeule an einer schaltbaren Steckdose, hier auch die
   **Steckdose der Saeule** eintragen (Abschnitt 6b). Danach den Knopf
   **Probelauf** druecken - er spielt alles sofort durch.

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
| D7      | K3 : IN  | Tongeber (1-Kanal-Relais) | orange |

Die Zuordnung stimmt mit dem Stromlaufplan `SIG-R4-E` ueberein.

Klemmleiste an der Saeule (Stand 16.11.2026, Cat-Kabel):

| Klemme | Funktion | Draht |
|---|---|---|
| 0 | Minus | weiss (gruenes Paar) |
| 1 | LED gruen | gruen (gruenes Paar) |
| 2 | LED orange | braun (braunes Paar) |
| 3 | LED rot | weiss (braunes Paar) |
| 4 | Hinweisleuchte | blau |
| 5 | Ton | orange |

Die Nummern in `/api/state` (1 gruen bis 4 Hinweis, 5 Warnleuchte, 6 Ton)
bleiben stabil - die Entitaeten in Home Assistant haengen daran. Ab Firmware
**1.3.0** steht bei jedem Ausgang zusaetzlich seine `farbe` (`gruen`, `orange`,
`rot`, `hinweis`, `warn`, `ton`). Wer eine bestimmte Farbe will, fragt danach
und nicht nach der Nummer - die Garagenampel in Abschnitt 6c tut genau das.

**Betriebsarten.** Vier: **Auto**, **Manuell**, **Ampel** und **Drucker**. Die
ersten zwei kennt die Saeule selbst, die anderen nur Home Assistant - sie
stehen weiter unten in Abschnitt 6c (Ampel) und 6d (Drucker).

In **Auto** treibt der Status die Saeule. Ein Wechsel wird
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

Der **Tongeber** (seit Firmware 1.1.0, Nr. 6 an D7) haengt an gar nichts: er
piept, solange Strom drauf ist, und wird nur ueber seinen eigenen Schalter
geschaltet. Im Standardablauf des Weckers steht er **nicht** - wer ihn dort
haben will, schreibt `"ton": true` in einen Schritt (Abschnitt 6a). Kein
Status, kein Testmodus und kein Startablauf nehmen ihn mit, und gemerkt wird
er auch nicht: **nach einem Stromausfall ist er aus.** Eine Saeule, die beim
Booten um Viertel vor fuenf losschreit, weckt das halbe Haus. Nur die
Selbstdiagnose laesst ihn kurz piepen - sie schaltet jeden Ausgang der Reihe
nach fuer 0,4 Sekunden ein.

**Hinweiston (seit Firmware 1.3.0, Muster seit 1.5.0).** `POST /api/piep`
gibt einen Quittungston und laesst den Schalter darueber unberuehrt - eine
Quittung, kein Alarm. Das Muster ist frei: `muster=400,500,800` sind Dauern in
Millisekunden, **abwechselnd Ton und Pause**, die erste Zahl ist immer ein
Ton. Also 0,4 s Ton, 0,5 s Pause, 0,8 s Ton - und genau das ist auch der
Standard, wenn man nichts mitgibt. Bis zu sechzehn Werte, jeder hoechstens
drei Sekunden; eine Pause am Ende wird weggelassen, die hoert ohnehin niemand.
Damit ist jeder Rhythmus einstellbar, ohne die Firmware neu zu bauen - was
sich beim Einstellen des Tons als das Entscheidende erwiesen hat. Die Folge
laeuft im Zeitgeber (alle 10 ms), nicht in der Schleife: die steht beim
Ausliefern einer Seite auch mal eine Sekunde, und dann waere aus dem kurzen
Piep ein Ton geworden. Im JSON steht ein laufender Piep nicht - er ist kein
Zustand. Home Assistant gibt diesen Ton beim Umschalten auf die Betriebsart
**Ampel** (Abschnitt 6c), und auf der Seite der Saeule gibt es den Knopf
„Kurz piepen".

**Selbstanmeldung (seit Firmware 1.12.0).** Die Saeule traegt sich selbst in
Home Assistant ein - wie der Garagen-ESP (Abschnitt 8). Sie ruft nach jedem
Start und danach einmal taeglich den Einrichtungsablauf der Integration auf
und meldet ihre Adresse; ein zweiter Anlauf legt kein zweites Geraet an,
sondern zieht nur die Adresse nach. Grund: Die Adresse kommt vom Router und
hat schon zweimal gewechselt - stand in Home Assistant die alte, war die
Saeule dort nicht erreichbar, und das faellt erst auf, wenn der Weckruf ohne
sie laeuft. `POST /api/anmelden` stoesst es von Hand an, `ha_anmeldung` in
`/api/state` sagt, wie es ausging.

Zugang: `HA_HOST`, `HA_PORT` und `HA_TOKEN` in `arduino_secrets.h` (Vorlage
daneben). Die **lokale** Adresse, nicht die oeffentliche - der Sketch spricht
nur HTTP. Der Token braucht Verwalterrechte.

Drei Dinge waren dabei zu loesen, alle am Geraet gemessen:

- **Eine Verbindung fuer alle drei Schritte.** Drei einzelne hintereinander
  scheiterten reproduzierbar beim dritten Mal; das WLAN-Modul gibt den Socket
  nicht schnell genug frei, und laengere Pausen halfen nicht.
- **Die Antwort am Stueck lesen.** `connected()` meldet beim R4 schon „zu",
  waehrend die Antwort noch unterwegs ist - zeilenweises Lesen lieferte einen
  leeren Rumpf, und eine saubere Antwort galt als abgelehnt.
- **Beim Warten weiter bedienen.** Der Einrichtungsablauf prueft, ob unter der
  gemeldeten Adresse wirklich eine Signalsaeule antwortet - und fragt dazu die
  Saeule, waehrend die auf seine Antwort wartet. Mit `delay()` lief genau diese
  Anfrage auf und das Formular kam mit einem Fehler zurueck. Die Wartezeit
  wird deshalb mit `httpBedienen()` gefuellt.

**Der Fehler, der die Saeule stumm im Netz stehen liess (behoben in 1.8.0).**
`wlanVerbinden()` wartet nach `WiFi.begin()` zehn Sekunden auf die Verbindung
und startete die Server nur, wenn sie in dieser Zeit zustande kam. Kam sie
kurz danach von selbst, sah die Schleife „verbunden" und rief die Funktion
nie wieder - die Saeule hatte eine IP und antwortete auf nichts, bis man ihr
den Strom nahm. Am 18.11.2026 genau so passiert: der Weckruf lief ohne
Saeule, jeder Schritt mit „nicht erreichbar" im Protokoll. Jetzt zieht
`serverSicherstellen()` den Start der Server nach, aus der Schleife heraus,
sobald eine Verbindung steht.

**Stiller Start nur nachts (seit Firmware 1.13.0).** Zwischen **3 und 7 Uhr**
kommt die Saeule still hoch: keine Leuchte, keine Matrix, Betriebsart Manuell.
Ausserhalb dieses Fensters fuehrt sie beim Einschalten normal vor (Lauflicht,
Adresse auf der Matrix) und steht danach auf **Auto** mit Status Ruhe - von
Hand laesst sich das jederzeit umstellen. Die Uhrzeit holt sie sich per NTP
ueber das WLAN-Modul und rechnet MEZ/MESZ selbst dazu; `stunde` und
`nachtruhe` in `/api/state` sagen, womit sie rechnet.

Bekommt sie keine Zeit (kein WLAN, NTP stumm), gilt **still**. Lieber einmal
zu oft dunkel als einmal um Viertel vor fuenf hell: die Steckdose geht um 4:55
an, der Wecker klingelt um fuenf. Darum ist auch die Reihenfolge so herum -
erst WLAN und Uhrzeit, dann die Entscheidung, ob vorgefuehrt wird.

**Und sie bleibt nicht still, wenn die Zeit nur spaet kommt (seit 1.14.0).**
Das WLAN-Modul liefert seine NTP-Zeit erst einige Sekunden nach der
Verbindung, manchmal gar nicht - am 20.11.2026 stand die Saeule darum um
halb sechs am Abend dunkel und auf Manuell, mit `"nachtruhe": true` im JSON.
Jetzt wird die Zeit sechsmal versucht, **jede Antwort von Home Assistant
liefert sie im `Date:`-Kopf mit** (zweite Quelle im eigenen Netz, ohne NTP),
und kommt sie erst danach, holt die Saeule die Vorfuehrung nach - aber nur,
solange niemand etwas gestellt hat und es dann wirklich nicht zwischen 3 und
7 Uhr ist.

**Und ohne WLAN steht sie nicht mehr dunkel da (seit 1.16.0).** Das war der
schlimmere Fall derselben Falle: ohne Netz gibt es keine Uhrzeit, eine
unbekannte Uhrzeit galt als Nachtruhe - also keine Leuchte, keine Matrix,
Betriebsart manuell. Die Saeule sah damit aus wie ein Geraet **ohne Strom**,
und zwar fuer immer. Am 21.11.2026 genau so: von 11:23 bis 15:07 war sie weg
und kam erst am USB-Kabel wieder.

Jetzt geht sie auch ohne Uhrzeit in Betrieb und zeigt in zwei Stufen, dass
sie lebt: nach **20 s** einen Punkt unten links auf der Matrix („ich laufe,
mir fehlt das Netz"), nach **90 s** dazu das gruene Grundbild - ohne
Vorfuehrung, denn es koennte Viertel vor fuenf sein. Die Abwaegung: die
Steckdose ist nachts aus, wer also Strom hat und keine Uhr kennt, steht fast
immer im Tag. Kommt die Zeit spaeter doch und es ist wirklich Nacht, geht
beides sofort wieder aus.

Dazu wird das WLAN **beharrlich** versucht: alle 20 s, und nach drei
Fehlversuchen wird der WLAN-Koprozessor des R4 ganz abgeschaltet und neu
angefangen (`WiFi.end()`), weil er sonst in seinem halben Zustand haengt und
auch dann weiter scheitert, wenn das Netz laengst wieder da ist. Die Zaehler
stehen in `/api/state`: `wlan_versuche`, `wlan_neustarts`, `ohne_netz` und
`ohne_netz_s`. Am Geraet gemessen (SSID absichtlich falsch): Versuch 1-3
scheitern, dann der Neustart des Koprozessors, nach 90 s das Grundbild.

**Wie die Funklage am Standort wirklich ist (gemessen am 21.11.2026).**
`POST /api/funk` laesst die Saeule selbst scannen - nur dort, wo sie steht,
hat die Messung Wert. Ergebnis, drei Mal gleich: sieben Netze in Reichweite,
das **eigene Netz aber nur einmal** und mit **-81 bis -83 dBm** auf
**Kanal 1**; im Betrieb stehen -73 dBm an. Es gibt also keinen zweiten
Zugangspunkt des Hausnetzes in Reichweite, auf den sie ausweichen koennte.
Auf demselben Kanal 1 funkt ein Fremdnetz mit **-71 dBm** - zehn Dezibel
**stuerker** als das eigene. Kanal 6 ist frei, auf Kanal 11 liegen vier
weitere Netze. Zum Vergleich: der 3D-Drucker im selben Zimmer hat -57 dBm,
die Leiterbahnantenne des R4 hoert also deutlich schlechter als er.

**Was die Firmware daraus macht (1.18.0).** Am Funk selbst aendert die Saeule
nichts - der Kanal ist Sache des Routers. Sie haelt aber durch:

- **Stille-Wachhund.** Verbunden zu sein heisst nicht, erreichbar zu sein (am
  18.11.2026 stand sie mit IP im Netz und antwortete auf nichts). Home
  Assistant fragt alle 15 s ab und haelt den Ereignisstrom offen; bleibt es
  **drei Minuten** ganz still, wird die Verbindung von Grund auf neu gemacht
  (`WiFi.end()`), hoechstens aber alle fuenf Minuten. Zaehler:
  `stille_neustarts`, `stille_s`.
- **Erst die Adresse, dann der Rest.** Nach einem Neuverbinden steht
  `WL_CONNECTED`, bevor DHCP fertig ist. Wer dann den Server startet, bindet
  ihn an **0.0.0.0** und meldet sich bei Home Assistant mit einer Adresse, die
  es nicht gibt - genau so am 21.11.2026 beim ersten Testlauf des Wachhunds
  gesehen. Jetzt wartet die Saeule auf die Adresse (bis 5 s) und prueft sie
  vor jedem Schritt (`adresseDa()`).
- **Nachsicht mit der jungen Verbindung.** In den ersten 90 s nach dem
  Verbinden gehen ausgehende Verbindungen noch ins Leere. Ein Fehlschlag ohne
  Antwort ist dann kein Befund, sondern nur zu frueh: es wird still neu
  versucht, statt einen guten Anmeldestand mit einem Fehler zu
  ueberschreiben.

Gemessen (Testfassung mit 20-30 s Schwelle und abgeklemmten Lebenszeichen):
der Wachhund schlaegt genau nach der Frist an, verbindet neu, bekommt die
Adresse und meldet sich wieder an; im Dauerlauf mit echtem Verkehr sieben
Minuten lang `stille_neustarts: 0`. Einen Schalter fuer den Stromsparbetrieb
hat WiFiS3 nicht - da ist nichts abzuschalten.

**Stiller Start (die Technik dahinter, seit Firmware 1.2.0).** Die Saeule haengt an einer
schaltbaren Steckdose, die kurz vor dem Weckruf angeht (Abschnitt 6b). Darum
bleibt beim Einschalten **alles dunkel**: keine Startanimation, keine Matrix,
kein gemerkter Status. Die Saeule kommt in der Betriebsart *Manuell* mit allen
Ausgaengen aus hoch und wartet. Erst was Home Assistant schickt - der Vorlauf
eine Minute vor dem Weckruf - laesst etwas leuchten. In einem Schlafzimmer
darf vorher nichts angehen.

Damit ist auch das **Flash-Gedaechtnis entfallen**: bis 1.1.0 lagen Status,
Betriebsart und Warnleuchte in `Preferences`, damit die Saeule nach einem
Stromausfall wieder so dastand wie vorher. Das widerspricht dem stillen Start
und hat den Daten-Flash nur umsonst beschrieben. Wer die Startanimation
zurueckwill (Lauflicht, zwei Blitze, Adresse auf der Matrix), setzt
`START_ANIMATION` im Sketch auf `true`.

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
POST /api/stufen?gruen=1&rot=1  alle vier Stufen gleichzeitig (-> Manuell);
                                was nicht dabeisteht, geht aus. Statt 1 darf
                                eine Blinkperiode in ms stehen, dahinter nach
                                einem Doppelpunkt der Versatz darin
                                ("orange=900:300") - damit blinken zwei Lampen
                                im Wechsel und drei laufen als Welle
                                (ab Firmware 1.15.0)
POST /api/relais/<nr>?an=1|0    eine Leuchte schalten (Stufe -> Manuell)
POST /api/modus?modus=auto|manuell
POST /api/status?status=ruhe|hinweis|achtung|stoerung|alarm   (-> Auto)
POST /api/piep?muster=400,500,800   Hinweiston: Dauern in ms, abwechselnd
                                Ton und Pause (erste Zahl ist ein Ton)
POST /api/test?an=1|0           Testmodus
POST /api/funk                  Funklage am Standort messen (ab 1.17.0).
                                Die Antwort kommt sofort, der Scan laeuft
                                danach - er nimmt dem Koprozessor die
                                Verbindung, und damit waere die offene
                                Anfrage weg. Die Liste der Netze kommt
                                seriell, die Zahlen stehen danach in
                                /api/state unter "funk"; danach verbindet
                                sich die Saeule selbst wieder
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
die Schalter *Warnleuchte*, *Ton*, *Testmodus*, die Knoepfe *Selbstdiagnose* und
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
| Steckdose der Saeule | eine `switch`-Entitaet; leer = nicht schalten (Abschnitt 6b) |
| Stromplan | JSON mit Vorlauf und Ausschaltzeiten; leer = Standardplan |

**Entitaeten**

| Entity | Inhalt |
|---|---|
| `switch.ha_wecker_weckablauf` | an = der Ablauf laeuft mit. Attribute: Block, naechster Wecker, Nullpunkt, Fehler der Ablaufdatei und das **Protokoll** jedes Schritts mit Ergebnis |
| `button.ha_wecker_probelauf` | spielt den Ablauf sofort durch: eine Minute Vorlauf, dann „klingelt" es, 30 s später gilt der Weckruf als beendet |
| `button.ha_wecker_ablauf_abbrechen` | stoppt einen laufenden Ablauf und räumt auf: Licht aus, Säule auf Ruhe |

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
        { "zeit": -60, "licht":  { "prozent": 5, "dauer": 60 } },
        { "zeit":   0, "saeule": { "status": "alarm", "ton": true } },

        { "zeit":   0, "ab": "ende", "saeule": { "status": "kreuz", "ton": false } },
        { "zeit":   0, "ab": "ende", "licht":  { "prozent": 70, "dauer": 10 } },
        { "zeit": 420, "ab": "ende", "licht":  { "aus": true, "dauer": 30 } },
        { "zeit": 420, "ab": "ende", "saeule": { "status": "alarm" } },
        { "zeit": 480, "ab": "ende", "saeule": { "status": "ruhe" } },

        { "zeit":    0, "ab": "schlummern", "saeule": { "status": "ruhe" } },
        { "zeit":    0, "ab": "schlummern", "licht":  { "prozent": 5, "dauer": 10 } },
        { "zeit": 1140, "ab": "schlummern", "licht":  { "aus": true, "dauer": 30 } }
      ]
    }
  ]
}
```

Das ist zugleich der **Standardablauf**, wenn das Feld leer bleibt: In der
letzten Minute vor dem Weckruf steigt das Licht auf 5 %, die Saeule zeigt
Hinweis. Beim Klingeln geht sie in den Alarm, nimmt ihre Blitz-Warnleuchte mit
und der **Tongeber faengt an zu piepen**. Sobald du den Weckruf **beendest**,
hoert der Ton sofort auf, die Warnleuchte faellt mit dem Alarm weg, die Saeule
geht in den Kreuzwechsel und das Licht auf 70 %. Sieben
Minuten spaeter dimmt das Licht aus und die Saeule schlaegt noch einmal Alarm,
eine Minute danach steht sie auf Gruen und nimmt wieder Befehle an.

- `zeit` zaehlt in **Sekunden**, `ab` sagt wovon: `weckruf` (Vorgabe) rechnet
  ab dem Klingeln, negativ heisst vorher; `ende` rechnet ab dem Moment, in dem
  du den Weckruf beendest; `schlummern` ab dem Moment, in dem du ihn vertagst.
  Nachlauf und Schlummern haengen also an dir, nicht an der Uhr.
- Es gilt der **erste Block**, dessen Wochentag und Zeitfenster zur Weckzeit
  passen. `von` gleich `bis` heisst: immer.
- `licht`: `prozent` (0-100), `dauer` in Sekunden fuer den Uebergang, `aus`.
  Kann die Leuchte kein `transition`, wird der Befehl ohne wiederholt.
- `saeule`: `status` (eine Kennung aus der Statusliste der Saeule), `warn`
  fuer die Blitz-Warnleuchte und `ton` fuer den Tongeber. Die Nummer des
  Ausgangs wird aus seiner Rolle gesucht, nicht geraten: hat die Saeule keinen
  Tongeber, steht das als Fehler im Protokoll, statt irgendetwas zu schalten.
- **Kommt nie ein Beenden** (App stumm, Handy aus), greift nach `ABLAUF_MAX_S`
  das Sicherheitsnetz und stellt Ton, Saeule und Licht zurueck. Sonst piepte
  es zwei Stunden in ein leeres Zimmer.
- Unsinn in der Datei wird beim Speichern abgelehnt, mit Angabe von Block und
  Schritt. Bis dahin gilt der Standardablauf.
- **Leeres Feld heisst: der eingebaute Standardablauf gilt** - und waechst mit
  jeder neuen Fassung mit. Wer einen eigenen Ablauf eintraegt, bleibt dabei,
  bis er ihn wieder loescht.
- Wird **geschlummert**, laufen die Schritte mit `"ab": "schlummern"`: im
  Standardablauf geht die Saeule zurueck auf Ruhe und das Licht auf 5 % - es
  soll nicht stockdunkel werden, aber auch nicht hell bleiben. Kommt danach
  **19 Minuten** lang nichts mehr, kein neues Klingeln und kein Beenden, geht
  das Licht aus. Klingelt es vorher wieder (Max' Wecker schlummert zwei
  Minuten), gilt wieder der Weckruf und der Schlummer-Timer ist vom Tisch.

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

## 6b. Strom fuer die Saeule (Steckdose nach dem Weckplan)

Die Saeule haengt an einer schaltbaren Steckdose (bei Max ein Shelly Plug im
Zimmer). Sie soll **kurz vor dem Weckruf** Strom bekommen - sonst ist der
Arduino noch nicht im Netz, wenn der Vorlauf ihn ansprechen will - und abends
wieder aus. Das steht in `strom.py` und haengt am selben Wecker wie der
Weckablauf; die Weckzeit kommt aus demselben Rechenweg
(`ablauf.naechste_weckzeit`), es gibt keine zweite Wahrheit darueber, wann
geweckt wird.

**Einstellen:** dieselben Optionen wie der Weckablauf, Felder *Steckdose der
Saeule* und *Stromplan*. Was der Stromplan schaltet, steht im **Protokoll des
Weckablaufs** - eine Stelle zum Hinschauen - und die Zeitpunkte stehen im
Attribut `strom` von `switch.ha_wecker_weckablauf`.

```json
{
  "version": 1,
  "vorlauf": 300,
  "aus": [
    { "wochentage": ["mo", "di", "mi", "do", "fr"], "zeit": "21:00" },
    { "wochentage": ["sa", "so"], "zeit": "22:00" }
  ]
}
```

Das ist zugleich der **Standardplan**, wenn das Feld leer bleibt: fuenf
Minuten vor dem Weckruf an, werktags um 21 Uhr aus, am Wochenende um 22 Uhr.
Dazwischen schaltet nichts - die Steckdose bleibt den ganzen Tag an.

- `vorlauf` sind **Sekunden** vor dem Weckruf, `aus` eine Liste aus
  `wochentage` und `zeit`. Ohne `wochentage` gilt der Eintrag an jedem Tag.
- **Ausgeschaltet wird nur zum Zeitpunkt selbst, nie nachtraeglich.** War Home
  Assistant um 21 Uhr aus, bleibt die Steckdose an, bis die naechste
  Ausschaltzeit kommt. Eine Steckdose, die zu lange an ist, kostet nichts -
  eine, die zur falschen Zeit ausgeht, nimmt der Saeule mitten im Betrieb den
  Strom.
- **Eingeschaltet wird auch nachtraeglich**, aber nur einmal je An-Phase:
  liegt das naechste Ausschalten vor dem naechsten Einschalten, laeuft gerade
  eine An-Phase, und eine ausgeschaltete Steckdose wird angedreht. Wer sie von
  Hand ausschaltet, bekommt sie nicht bei der naechsten Meldung der App wieder
  angedreht - erst in der naechsten Phase.
- Der **Probelauf** schaltet die Steckdose vorher ein, sonst antwortet die
  Saeule nicht und das halbe Protokoll steht auf „Fehler".
- Ohne eingetragene Entitaet bleibt der Stromplan still.

**Fallstrick, der hier schon zugebissen hat:** `hass.async_create_task` startet
die Aufgabe sofort und laesst sie bis zum ersten echten Warten durchlaufen.
Als `_schalten` am Ende noch neu plante, lief das synchron in die Planung
zurueck - einmal im Kreis fuer jeden Schaltvorgang, bis der Stapel voll war.
Deshalb plant jetzt nur der Timer-Rueckruf, nie das Schalten selbst.

---

## 6c. Betriebsart „Ampel" (die Saeule zeigt die Garagenampel)

Ein dritter Platz im Schalter **Betriebsart** neben Auto und Manuell. Steht er
auf **Ampel**, zeigt die Signalsaeule, wie der Stellplatz in der Garage steht
(Abschnitt 8) - im Zimmer sieht man also, ob der 206 drinsteht:

| Lage in der Garage             | Saeule     |
|--------------------------------|------------|
| Auto steht drin                | rot        |
| frei                           | gruen      |
| kein Strom an der Lichtschranke | gelb und die Hinweisleuchte oben |
| ESP antwortet nicht            | rot und die Hinweisleuchte oben |

**Nicht** die Ampel des ESP.** Das Feld `ampel` in dessen `/api/state` gehoert
zur Lampe in der Garage und ist zum Einparken gedacht: es geht auf `aus`,
sobald das Tor zu ist und das Auto nicht mehr per Funk zu hoeren ist. Der 206
steht dann immer noch drin, nur muss ihn niemand mehr anleuchten. Eine
Statusanzeige im Zimmer will das Gegenteil - sie soll gerade dann sagen, dass
der Platz belegt ist. Darum urteilt die Betriebsart selbst, aus `auto_drin`
und `strom`. (Am 17.11.2026 stand genau das im Weg: Auto drin, Lichtschranke
durchtrennt, und die Saeule blieb dunkel, weil der ESP `ampel: aus` meldete.)
Weiss der ESP nichts ueber den Platz, blinkt es gelb - lieber eine Stoerung
zeigen als faelschlich gruen. Ein Bild fuer „nichts leuchtet" gibt es nicht:
eine Statusanzeige, die dunkel ist, sagt nichts.

Die **Stoerung an der Lichtschranke** ist nachgebaut, wie eine Ampel es an der Kreuzung
macht: gelb blinkt mit einem Hertz. Die Hinweisleuchte blinkt sehr schnell
dazu (160 ms), damit man es nicht mit dem Status „Achtung" verwechselt.

**Antwortet der ESP gar nicht**, fehlen ihm die 5 V, mit denen er selbst
betrieben wird. Dann steht nicht einmal fest, dass die Garage ueberwacht wird
- darum **rot** mit der Hinweisleuchte. Lebt er und meldet nur, dass der
Lichtschranke die 24 V fehlen, ist es **gelb** mit der Hinweisleuchte.

Gesetzt wird das Bild **gleichzeitig** (`POST /api/stufen`, ab Firmware
1.9.0), nicht Stufe fuer Stufe. Vier einzelne Anfragen sieht man: je nach
Reihenfolge steht die Saeule 570 ms dunkel oder es brennen kurz drei Farben
zugleich - beides am Geraet gemessen, und fuer eine Ampel beides nichts.

Der Endpunkt liest alle Werte **erst** und setzt sie **dann** unter einer
kurzen Interrupt-Sperre. Das ist nicht Geschmack: `argWert()` baut
Arduino-Strings auf dem Heap, und Speicher anzufordern, waehrend die
Unterbrechungen gesperrt sind, laesst den 100-Hz-Zeitgeber ausfallen und kann
haengen bleiben. Eine fruehere Fassung tat das und war mitschuldig daran,
dass die Saeule am 18.11.2026 zeitweise nicht mehr ansprach. Die Periode gilt nur fuer die Stufen in der
Betriebsart manuell und wird beim Wechsel auf Auto, bei „Alles aus" und beim
stillen Start geloescht.

**Still bleibt es.** Kein Ton, keine Blitz-Warnleuchte - auch bei der
Stoerung nicht. Den Tongeber gibt es genau einmal: beim Umschalten auf diese
Betriebsart.

**Geschaltet wird wie an einer deutschen Ampel.** Wechsellichtzeichen nach
StVO, Zeiten nach RiLSA fuer 50 km/h:

| Von   | ueber                        | nach  |
|-------|------------------------------|-------|
| gruen | **gelb**, 3 s                | rot   |
| rot   | **rot und gelb zusammen**, 1 s | gruen |

Rot und Gelb zugleich ist das, was die deutsche Ampel von den meisten anderen
unterscheidet. Ohne diese Zwischenphasen springt die Saeule unvermittelt um -
mit ihnen sieht man dem Bild an, wohin es geht. Zu einer **Stoerung** und aus
einer Stoerung heraus wird nicht ueberblendet: die soll sofort zu sehen sein.

**Beim Einschalten fahert sie einmal vor**, wie eine Ampel bei der
Inbetriebnahme: gelb, rot, rot+gelb, gruen - und danach das Bild, das
wirklich gilt, auch dorthin ueber die richtige Zwischenphase. Steht das Auto
in der Garage, kommt also noch gelb und rot; zusammen sind das rund neun
Sekunden. Ist in dem Moment eine **Stoerung**, entfaellt das ganz; kommt
sie mitten hinein, bricht die Folge ab. Meldet die Saeule keine Farben
(Firmware vor 1.3.0), faengt die Betriebsart gar nicht an und sagt das im
Attribut `ampel_fehler`.

Beim Umschalten gibt der Tongeber einmal den Quittungston (`/api/piep`, siehe
Abschnitt 6) - auch dann, wenn die Ampel gerade „aus" sagt und gar nichts zu
sehen ist. Gehoert hat man es trotzdem. Danach bleibt er stumm, was die Ampel
auch meldet.

**Nur in Home Assistant.** Die Saeule kennt die Garage nicht. Am Geraet steht
sie in dieser Betriebsart auf `manuell`, und die Stufen werden einzeln
gestellt - ein **stehendes Bild**, keine Choreografie. Genau das soll eine
Ampel sein: ruhig und auf einen Blick zu lesen. Darum auch nicht ueber den
Status: `stoerung` waere zwar rot, liesse aber die Hinweisleuchte im
Viertelsekundentakt mitblinken. Gefragt wird nach der **Farbe**, die die Saeule
ab Firmware 1.3.0 selbst meldet, nicht nach der Relaisnummer. Eine aeltere
Firmware meldet keine Farben; dann bleibt die Saeule dunkel und das Attribut
`ampel_fehler` sagt, warum. Der Platz „Ampel" steht ueberhaupt nur im Schalter,
wenn es den Garagen-ESP in Home Assistant wirklich gibt.

**Was die Betriebsart beendet.** Viererlei:

- ein anderer Platz im Schalter (Auto oder Manuell),
- der Knopf **Alles aus** - sonst schaltete das naechste Wort aus der Garage
  die Saeule gleich wieder an, und der Knopf waere wirkungslos,
- ein **Status** oder eine **Stufe** von Hand - wer selbst stellt, will selbst
  stellen. Dieselbe Regel gilt in der Firmware fuer Auto und Manuell. Die
  Warnleuchte und der Tongeber beenden sie **nicht**: die gehoeren zu keinem
  Bild,
- **die Saeule selbst, wenn sie nicht mehr antwortet.** Abends um 21 Uhr
  nimmt ihr der Stromplan den Strom (Abschnitt 6b), morgens um 4:55 bekommt
  sie ihn zurueck und kommt still hoch. Wuerde der Ampelmodus das
  ueberdauern, schriebe er sein Bild einfach weiter, und sie stuende auf Rot,
  lange bevor der Wecker klingelt - genau das, was der stille Start
  verhindern soll. Ein **Neustart** von Home Assistant beendet ihn ohnehin:
  gemerkt wird er bewusst nicht. Wer die Ampel tagsueber will, stellt sie also
  einmal am Tag ein.

**Der Weckruf hat Vorrang.** Fasst der Weckablauf die Saeule an, ruht die
Betriebsart bis zum Ende des Laufs und zieht danach das Ampelbild nach. Beides
steht im Protokoll des Weckablaufs („ruht bis zum Ende des Laufs", „laeuft
wieder"). Waehrend sie ruht, schaltet auch ein Wort aus der Garage nichts.

Die Attribute am Schalter **Betriebsart** sagen, was los ist: `lage` und
`lage_text` (was die Saeule zeigt: `besetzt`, `frei`, `kein_strom`,
`kein_esp`), `ampel` (was der ESP seiner eigenen Lampe sagt - nur zur
Information), `ampel_pausiert`, `ampel_schaltet` (eine Phasenfolge laeuft), `ampel_fehler`, `garage`
und `geraet` (worauf die Saeule selbst steht, also `auto` oder `manuell`).

Code: `custom_components/ha_wecker/ampel.py`.

---

## 6d. Betriebsart „Drucker" (die Saeule zeigt den 3D-Drucker)

Der vierte Platz im Schalter **Betriebsart**. Er steht nur da, wenn die
**Bambu-Lab-Integration** in Home Assistant eingerichtet ist; einzurichten
ist sonst nichts, die Entitaeten des Druckers werden selbst gefunden.

Diese Betriebsart reicht **keine Herstellermeldungen weiter**. Die
Bambu-Integration liefert rund siebzig Entitaeten je Drucker, und ihre Werte
sind Maschinenbegriffe: `print_status` kennt elf, `stage` ueber achtzig - von
`heatbed_underside_foreign_object_detection` bis `paused_skipped_step`. Davon
ist fast nichts eine Information, auf die man aufsteht. Die Integration
urteilt selbst.

### Die Bildsprache ist eine Grammatik, keine Liste

Vierzehn Bilder auswendig zu lernen will niemand (Max, 20.11.2026). Darum
sagt nicht jedes Bild fuer sich etwas, sondern **sechs Regeln sagen alles**:

| Was man sieht | Was es heisst |
|---|---|
| Licht wandert **nach oben** | der Drucker fahert hoch - er wird warm |
| Licht wandert **nach unten** | er fahert runter - er kuehlt ab |
| **gruen** | der Druck laeuft; hektisch heisst gleich fertig |
| **orange** | er arbeitet daneben, es kommt noch kein Kunststoff |
| **weiss oben** | du bist gefragt; blinkt es, dann jetzt |
| **rot** | etwas stimmt nicht |

Daraus ergibt sich jede Lage von selbst, und am **eigenen Arbeitsschritt**
erkennt man, was gerade passiert:

| Lage | heisst | Saeule |
|---|---|---|
| `ruht` | nichts zu tun (auch: Drucker aus) | Hinweis, dauerhaft |
| `ruestet` | arbeitet vor, `stage` sagt nichts Naeheres | orange, dauerhaft |
| `heizt` | Bett und Duese werden warm | Welle nach oben (1,8 s) |
| `vermisst` | Bett antasten, kalibrieren, einmessen | gruen und orange im Wechsel (0,7 s) |
| `material` | Filament laden, spuelen, Duese putzen | orange, schnell (0,4 s) |
| `druckt` | laeuft | gruen, dauerhaft |
| `endspurt` | weniger als fuenf Minuten, oder ab 98 % | gruen, schnell (0,4 s) |
| `kuehlt` | Nachlauf: Kammerluft reinigen, abkuehlen | Welle nach unten (1,8 s) |
| `fertig` | liegt auf dem Bett und will geholt werden | gruen + Hinweis, dauerhaft |
| `pause` | von Hand angehalten | orange + Hinweis, dauerhaft |
| `eingriff` | Material fehlt, eine Hand ist gebraucht | orange, Hinweis blinkt (0,6 s) |
| `fehler` | abgebrochen, Duese verstopft, Fehldruck | rot, blinkt (0,5 s) |
| `tuer` | Tuer offen, waehrend gedruckt wird | gruen, rot blinkt hektisch (0,3 s) |
| `weg` | mitten im Druck verschwunden | rot und Hinweis langsam im Wechsel (1,5 s) |

**Heizen und Kuehlen sind dieselbe Welle, nur in die andere Richtung** - ein
Thermometer, das steigt oder faellt. Genau das war Max' Beispiel: man soll am
Ende eines Drucks sehen, dass nur noch zugemacht wird, ohne es zu lernen.
`pause` und `eingriff` tragen dieselben Farben und unterscheiden sich nur im
Takt oben: „es wartet etwas" gegen „komm jetzt". Kein Bild gleicht einem
anderen; der Test `test_drucker_jedes_bild_ist_eindeutig` haelt das fest.

**Geblinkt wird im Geraet.** `/api/stufen` nimmt ab Firmware **1.15.0** je
Lampe eine Periode und einen Versatz, und der Zeitgeber der Saeule (alle
10 ms) haelt sie ein. Ein Takt aus Home Assistant ueber HTTP waere ein
Zufallstakt. Der Versatz ist das eigentliche Mittel: eine halbe Periode
versetzt ergibt den Wechsel, je ein Drittel die Welle.

### Was die Integration selbst entscheidet

- **Eine Pause ist nicht eine Pause.** Steht der Druck, weil Material fehlt
  (`paused_filament_runout`, AMS verloren, warten auf Material), ist das
  `eingriff`. Steht er wegen der Maschine (verstopfte Duese, misslungene
  erste Schicht, Temperaturfehler), ist das `fehler`. Hat ihn der Nutzer
  selbst angehalten, ist es `pause`. Drei Lagen aus einem Wort.
- **Der Arbeitsschritt kommt aus `stage`, nach Wortanfang.** `heat`, `cool`,
  `calibrat`, `filament`, `purifying` - das traegt weiter als eine
  Aufzaehlung, die altert, denn Bambu nimmt laufend Werte dazu.
  `heatbed_preheating` ist damit auf immer richtig einsortiert.
- **Der Nachlauf ist kein Endspurt.** Am Ende steht der Fortschritt auf 100,
  waehrend `stage` auf `purifying_chamber_air` geht. Vorher wurde daraus
  `endspurt` oder sogar wieder `ruestet` - am 20.11.2026 am laufenden Druck
  gesehen. Jetzt faellt die Welle, und man sieht es.
- **HMS-Meldungen machen kein Bild.** Darunter melden die Drucker auch
  Bagatellen; eine Signalsaeule, die davon rot wird, ist nach einer Woche
  Tapete. Sie stehen im Attribut `hms`. Sichtbar wird nur, was den Druck
  wirklich anhaelt.
- **Fertig ist erst abgeholt.** Der Drucker bleibt nach dem letzten Layer
  stundenlang auf `finish`. Die Saeule ruft darum hoechstens eine
  Viertelstunde - und hoert sofort auf, wenn die Gehaeusetuer aufgeht: wer
  das Teil holt, hat es gesehen.
- **Offline ist meistens kein Fehler.** Ein ausgeschalteter Drucker `ruht`.
  Verschwindet er dagegen mitten im Druck, ist das `weg` - und auch das nur
  eine halbe Stunde, danach war es wohl doch der Netzschalter.
- **Die Restzeit hat eine Einheit.** Die Bambu-Integration meldet sie in
  **Stunden** (0,42), nicht in Minuten. Wer die Zahl ungelesen nimmt, haelt
  jeden Druck fuer fast fertig.

**Die offene Tuer beim Drucken ist eine Lage fuer sich.** Laeuft ein Druck und
die Gehaeusetuer steht offen, bleibt **gruen stehen** (der Druck laeuft) und
**rot blinkt hektisch** dazu: etwas steht offen - Zugluft, und beim
geschlossenen Drucker auch die Temperatur. Geht die Tuer zu, steht wieder
gruen allein. Steht der Drucker, ist eine offene Tuer dagegen nichts wert -
dann bleibt es bei `ruht`. Beim **fertigen** Druck hat dieselbe Tuer die
umgekehrte Bedeutung: sie quittiert das Abholen.

**Gehoert wird nichts.** Jeder Arbeitsschritt hat sein Licht, und damit ist
alles gesagt (Max, 20.11.2026). Der einzige Ton ist der Quittungston beim
**Umschalten** auf die Betriebsart - das ist eine Bedienung, keine Meldung
des Druckers. Die Blitz-Warnleuchte bleibt immer aus, die gehoert zum Alarm.

**Beim Umschalten laeuft ein Selbsttest**: gruen, orange, rot, Hinweis, je
250 ms von unten nach oben - wie eine Werkzeugmaschine beim Einschalten.
Danach steht, was gilt.

**Der Sensor `sensor.<saeule>_drucker` ist der eigentliche Kern.** Er gilt
unabhaengig davon, worauf die Saeule steht: eine Entitaet statt siebzig, mit
der Lage als Zustand und allem, was dazugehoert, als Attribut - `aufgabe`,
`fortschritt`, `rest_min`, `schicht` („306/465"), `filament`, `tuer_offen`,
`hms`, `feuchte_index` und `filament_feucht` (ab Index 4 ist das Filament im
AMS feucht), `online`, `abgeholt`, dazu `drucker` und `arbeitsschritt` als
das, was das Geraet selbst sagt. Ohne Drucker in Home Assistant ist er
`unavailable` - nicht „ruht", denn das waere eine Behauptung.

Beendet wird die Betriebsart von denselben vier Dingen wie die Ampel: ein
anderer Platz im Schalter (die beiden schliessen sich aus), ein Status oder
eine Stufe von Hand, der Knopf „Alles aus", und die Saeule selbst, wenn sie
abends vom Netz geht. Der Weckruf hat Vorrang.

Code: `custom_components/ha_wecker/drucker.py`.

---

## 8. Garage (ESP32 an der Lichtschranke des Peugeot 206)

Der Garagen-ESP gehoert zum Projekt `van206` (Ordner `firmware/ls`, Firmware
ab `ls-1.8`). Er hat nichts mit dem Wecker zu tun, aber dieselbe Integration
und dieselbe Bauart wie die Signalsaeule: `GET /api/state` liefert alles als
JSON, auf Port 8081 haelt `/api/events` einen Ereignisstrom offen, ueber den
jede Aenderung sofort kommt (Server-Sent Events, Lebenszeichen alle 15 s).

**Einrichten: nichts.** Der ESP kennt Adresse und Token von Home Assistant
schon (er liest damit das Garagentor). Sobald er Home Assistant erreicht,
startet er den Einrichtungsablauf dieser Integration ueber deren
REST-Schnittstelle selbst - genau die drei Schritte, die man sonst in der
Oberflaeche klickt: Integration HA Wecker, Garage, Adresse - und danach steht
das Geraet „Garage" da. Das wiederholt er nach jedem Start, einmal am Tag und
sobald sich seine IP aendert; ein zweiter Anlauf legt kein zweites Geraet an,
sondern zieht nur die Adresse nach. Der Token braucht dafuer Verwalterrechte
(der langlebige Token aus dem Profil hat sie). Steht die Integration noch
nicht oder noch in einer Version vor 2.5, meldet der ESP das in seiner
Konsole und versucht es stuendlich wieder; `a` in der Konsole versucht es
sofort. Von Hand geht es natuerlich auch: HA Wecker -> Garage -> Adresse.

**Entitaeten**

| Entity | Inhalt |
|---|---|
| `sensor.garage_ampel` | **Stopp** (Lichtschranke durchtrennt, Auto steht weit genug drin), **Frei**, **Kein Strom** (24 V der Schranke fehlen, kein Urteil), **Aus** (Tor zu, kein Auto zu hoeren). Attribut `grund` sagt es in Worten |
| `binary_sensor.garage_auto_in_der_garage` | Lichtschranke durchtrennt |
| `binary_sensor.garage_auto_esp_verbunden` | der ESP im Auto ist per Funk zu hoeren (Attribute: zuletzt vor, Pakete, aufgesperrt, Funkkanal) |
| `binary_sensor.garage_auto_verriegelt` | Verriegelung des Autos (nur solange das Auto zu hoeren ist) |
| `binary_sensor.garage_zundung_des_autos`, `..._ruckwartsgang` | was der Auto-ESP funkt, ebenfalls nur in Reichweite |
| `binary_sensor.garage_lichtschranke_strom` | 24 V der Lichtschranke liegen an |
| `binary_sensor.garage_rote_lampe` | die rote Lampe (Attribute: blinkt, Nachlauf) |
| `binary_sensor.garage_tor_laut_esp` | das Tor, wie der ESP es gelesen hat - danach richtet sich die Lampe (Diagnose) |
| `sensor.garage_auto_zuletzt_gehort` | Zeitstempel |
| `sensor.garage_pakete_vom_auto`, `_funkkanal`, `_wlan_signal`, `_laufzeit` | Diagnose |
| `binary_sensor.garage_ereignisstrom` | steht die Dauerverbindung (Diagnose) |
| `button.garage_lampe_testen` | rote Lampe zehn Sekunden an |
| `button.garage_neustart` | ESP neu starten |

Die alten, per REST gesetzten `binary_sensor.garage_*` der Firmware bis
`ls-1.7` schickt der ESP nicht mehr, sobald er angemeldet ist.

---

## 7. Warum nicht die Companion App

Die Home Assistant Companion App liest ueber den Sensor "Next Alarm" nur das
`AlarmClockInfo` des Systems. Android gibt dort ausschliesslich den naechsten
anstehenden Weckruf heraus – eine Liste aller eingetragenen Wecker samt
An/Aus-Zustand existiert in dieser System-API schlicht nicht, und die Samsung-Uhr
veroeffentlicht sie auch nirgends. Deshalb die eigene App mit eigener Quelle.
