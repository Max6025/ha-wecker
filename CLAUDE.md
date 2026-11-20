# HA Wecker – Hinweise fuer die Arbeit am Repo

Drei Teile, eine Integration: `custom_components/ha_wecker` (Home Assistant),
`app/` (Android-Wecker-App), `firmware/signalsaeule/` (Arduino UNO R4 WiFi an
einer Rittal-Signalsaeule). Die Relaisbox (ESP32-S3) ist am 14.11.2026 ganz
entfernt worden - Integration, Firmware, Blueprint und Tests. Seit 2.5.0
(17.11.2026) haengt als drittes Geraet die **Garage** dran: der Garagen-ESP des
Peugeot 206 (`garage.py`); seine Firmware liegt nicht hier, sondern im Repo
`van206` unter `firmware/ls` (Max6025/van206).
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
  Dasselbe gilt fuer die Farbe: die Saeule meldet seit 1.3.0 bei jedem
  Ausgang `farbe` (`gruen`, `orange`, `rot`, `hinweis`, `warn`, `ton`), und
  `nummer_farbe("rot")` fragt danach. Wer eine bestimmte Farbe braucht - die
  Garagenampel tut das -, fragt nach der Farbe, nie nach Nummer drei.
- **Der kurze Hinweiston kommt aus der Saeule, nicht aus Home Assistant.**
  `POST /api/piep` (1.3.0) gibt die Folge selbst, nicht zwei Schaltbefehle
  mit einer Pause dazwischen: so ist der Ton wirklich kurz, auch wenn das Netz
  gerade langsam ist. Die Folge laeuft im Zeitgeber, nicht in `loop()` - die
  steht beim Ausliefern einer Seite ueber eine Sekunde, und dann waere aus dem
  Piep ein Ton geworden. `piepAn` teilt sich den Ausgang mit `tonAn`
  (`setzen(IDX_TON, tonAn || piepAn)`), steht aber **nicht** im JSON: ein
  Piep ist kein Zustand. Der stille Start und `/api/alarm/stop` raeumen eine
  laufende Folge ab.
- **Die Laenge eines Tons nicht raten, sondern einstellbar machen.** Am
  17.11. ging das dreimal schief: 70 ms waren nicht zu hoeren, 200 ms „viel
  viel zu kurz", ein geratener Rhythmus war der falsche - jedes Mal ein
  Flash-Zyklus und eine Rueckfrage. Seit 1.5.0 nimmt `/api/piep` darum ein
  freies `muster=400,500,800`: Dauern in ms, abwechselnd Ton und Pause, die
  erste Zahl ist ein Ton. Damit laesst sich jeder Rhythmus am laufenden Geraet
  vorspielen, und erst der bestaetigte wird als `PIEP_MUSTER` eingebaut. Die
  Integration ruft `/api/piep` **ohne** Angabe - gehoert wird der Ton am
  Geraet, also steht das Muster dort und nicht in Python.
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
- **Eine unbekannte Uhrzeit darf nicht dauerhaft still bedeuten.** Der
  schwerste Fehler nach dem Serverstart: `zeitHolen()` lief **einmal**,
  direkt nach `wlanVerbinden()`. Liefert `WiFi.getTime()` da noch nichts -
  der Koprozessor holt seine NTP-Zeit erst Sekunden nach dem Verbinden -,
  bleibt `zeitStunde` auf -1, `nachtruhe()` sagt still, und die Phase ist
  durch: die Saeule stand am 20.11.2026 um halb sechs am Abend auf
  "manuell", stockdunkel, mit `"nachtruhe": true` im JSON. Max hat es
  gemerkt, nicht die Technik. Seit 1.14.0 drei Dinge: `zeitHolen()` wird
  sechsmal mit 1,5 s Abstand versucht; **jede Antwort von Home Assistant
  liefert die Zeit im `Date:`-Kopf** (`zeitAusDate()` in `haSchritt`, zweite
  Quelle im eigenen Netz, unabhaengig von NTP); und `nachholenPruefen()`
  holt die Vorfuehrung nach, sobald die Zeit doch kommt - aber nur solange
  `unberuehrt` gilt (jeder POST loescht es) und es dann wirklich nicht
  Nachtruhe ist. Nie wieder einen Dauerzustand an einen einzigen Versuch
  haengen, eine Zeit zu bekommen.
- **Der stille Start gilt nur zwischen 3 und 7 Uhr** (1.13.0, Max am
  18.11.2026). Ausserhalb fuehrt die Saeule beim Einschalten normal vor und
  steht danach auf **Auto** - das ist der Zustand, in dem Weckablauf und
  Betriebsart sie erwarten. Die Uhrzeit kommt per NTP (`WiFi.getTime()`,
  MEZ/MESZ selbst gerechnet). Ohne Zeit gilt **still**: lieber einmal zu oft
  dunkel als einmal um Viertel vor fuenf hell. Darum entscheidet die Phase
  `PH_WLAN` erst nach `wlanVerbinden()` und `zeitHolen()`, ob `PH_VORFUEHREN`
  kommt - vorher bleibt alles aus.
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
- **Die Betriebsart „Ampel" gibt es nur in Home Assistant** (`ampel.py`, seit
  17.11.2026). Die Saeule kennt die Garage nicht; am Geraet steht sie dabei
  auf `manuell` und die Stufen werden einzeln gestellt - ein stehendes Bild,
  keine Choreografie. Nicht ueber den Status gehen: `stoerung` waere rot,
  liesse aber die Hinweisleuchte mitblinken, und eine Ampel soll ruhig sein.
  Vier Dinge beenden sie: ein anderer Platz im Schalter, ein Status oder eine
  **Stufe** von Hand (Warnleuchte und Tongeber nicht - die gehoeren zu keinem
  Bild), der Knopf „Alles aus" und jeder Neustart. „Alles aus" gehoert dazu,
  weil sonst das naechste Wort aus der Garage die Saeule gleich wieder
  anschaltete und der Knopf wirkungslos waere.
- **Der Ampelmodus endet, sobald die Saeule nicht mehr antwortet** - und wird
  nicht gemerkt (kein `RestoreEntity`, kein Store). Beides zielt auf dasselbe:
  die Saeule geht abends um 21 Uhr vom Netz und kommt um 4:55 still wieder
  hoch. Wuerde der Ampelmodus das ueberdauern, schriebe er sein Bild einfach
  weiter und sie stuende auf Rot, lange bevor der Wecker klingelt - genau das,
  was der stille Start verhindern soll. Darum haengt `_saeule_gemeldet` am
  Saeulen-Coordinator und beendet die Betriebsart bei
  `not last_update_success`. Lieber einmal zu oft aus: ein Griff an den
  Schalter stellt sie wieder an, ein rotes Zimmer um Viertel vor fuenf nicht.
- **Der Weckruf hat Vorrang vor der Ampel.** `_saeule()` ruft
  `ampel.pausieren()`, sobald ein Schritt die Saeule anfasst; `_fertig()` und
  `async_abbrechen()` geben sie mit `_ampel_weiter()` wieder frei, und dann
  zieht sie ihr Bild nach (`_bild = None`, weil der Ablauf die Saeule
  umgestellt hat). Nicht an `laeuft` haengen: das ist auch wahr, waehrend nur
  der Vorlauf steht, und dann waere die Ampel den ganzen Tag stumm.
- **Die Saeule meldet sich selbst in Home Assistant an** (1.12.0, wie der
  Garagen-ESP). Drei Fallen, alle am Geraet gemessen: drei einzelne
  Verbindungen hintereinander scheitern beim dritten Mal (Socket wird nicht
  schnell genug frei) - also keep-alive ueber eine Verbindung; `connected()`
  meldet schon „zu", waehrend Daten unterwegs sind - also am Stueck lesen und
  danach an `\r\n\r\n` trennen; und der Einrichtungsablauf fragt die Saeule ab,
  waehrend sie auf seine Antwort wartet - also die Wartezeit mit
  `httpBedienen()` fuellen (`warten()`), sonst laeuft genau diese Anfrage auf.
  `anmeldungLaeuft` schuetzt dabei vor Rekursion.
- **Die Server MUESSEN starten, sobald das WLAN steht - egal wann.** Der
  schwerste Fehler dieses Projekts: `wlanVerbinden()` startete `server` und
  `sseServer` nur, wenn die Verbindung in seinen zehn Wartesekunden zustande
  kam, und kehrte bei bestehender Verbindung oben gleich um. Kam die
  Verbindung kurz nach dem Warten von selbst, lief die Saeule mit IP, aber
  ohne Server - stumm, bis zum Stromausfall. Am 18.11. lief der Weckruf
  deshalb ohne Saeule. Seit 1.8.0 zieht `serverSicherstellen()` das aus der
  Schleife nach. Nie wieder einen Serverstart an den Erfolg eines einzelnen
  Verbindungsversuchs haengen.
- **Nie Speicher anfordern, waehrend die Unterbrechungen gesperrt sind.**
  `/api/stufen` rief `argWert()` viermal innerhalb von `noInterrupts()` - und
  jeder Aufruf baut drei Arduino-`String`s auf dem Heap. Der 100-Hz-Zeitgeber
  faellt dabei aus, und malloc mit gesperrten Unterbrechungen kann haengen.
  Seit 1.9.0 liest der Endpunkt alle Werte erst in ein `bool[STUFEN]` und
  sperrt dann nur fuer vier Zuweisungen. So gehoert es ueberall gemacht.
- **Das Blinken je Stufe ist am 18.11. heraus** (Max: die Saeule startete
  zeitweise nicht mehr, erst muss das sitzen). Die Betriebsart „Ampel" zeigt
  Stoerungen seither ohne Blinken - Farbe plus Hinweisleuchte. Auf Zuruf kann
  es zurueck; es war nicht die Fehlerursache.
- **Das Stufenbild gleichzeitig setzen, nicht Stufe fuer Stufe.** Mit vier
  einzelnen `/api/relais`-Anfragen steht die Saeule entweder 570 ms dunkel
  (erst aus, dann an) oder es brennen kurz drei Farben (erst an, dann aus) -
  beides am Geraet gemessen. Fuer eine Ampel ist beides nichts, darum
  `/api/stufen`.
- **Beim Startverhalten nichts behaupten, was nicht gemessen ist.**
  `scratchpad/starttest.sh` faehrt acht Neustarts und prueft jedes Mal
  Erreichbarkeit, Fassung und ob sie still hochkam. Nach jeder
  Firmware-Aenderung neu fahren - der Nachweis gilt nur fuer die Fassung, mit
  der er gefahren wurde.
- **Die Ampel schaltet deutsch: gruen -> gelb -> rot, rot -> rot+gelb ->
  gruen.** Nicht nur bei der Eroeffnung, sondern bei jedem Wechsel
  (`uebergang()`); Rot und Gelb zugleich ist das Kennzeichen der deutschen
  Ampel. Zeiten nach RiLSA fuer 50 km/h: Gelb 3 s, Rot-Gelb 1 s. Zu einer
  Stoerung und aus einer heraus wird nicht ueberblendet - es gibt keine Phase,
  die dazu passt, und eine Stoerung soll sofort zu sehen sein.
- **Phasenfolgen laufen nebenher, nicht im Dienstruf.** Sekundenlang einen
  `select.select_option` haengen zu lassen geht nicht, darum eine Task
  (`_folge_fahren`). Waehrend sie laeuft (`schaltet`) schreibt der Ampelmodus
  kein Bild - sonst funkte ein Wort aus der Garage mitten hinein; am Ende
  zieht die Folge selbst nach. Der Weckablauf bricht sie ab (`pausieren`).
  Im Test die Zeiten verkuerzen (Fixture `schnelle_phasen`), sonst dauert
  jeder Ampeltest ueber zehn Sekunden.
- **Was der Ampelmodus aendert, muss er selbst melden.** `melden()` ruft
  `async_update_listeners()` am Saeulen-Coordinator. Ohne das stand der
  Schalter auf dem Stand vom Augenblick des Dienstrufs - ein Fehler, der
  danach auffiel (die Eroeffnung und jedes Wort aus der Garage passieren
  ausserhalb eines Dienstrufs).
- **Das Blinken macht die Saeule, nicht Home Assistant.** Seit 1.6.0 nimmt
  `POST /api/relais/<nr>?an=1&blinken=1000` eine Periode in ms (halb an, halb
  aus) - nur fuer die Stufen und nur in „manuell", denn „auto" hat seine
  eigenen Bilder. Gebraucht wird es fuer die gestoerte Garagenampel: gelb
  blinkt mit einem Hertz wie an einer Kreuzung, die Hinweisleuchte sehr
  schnell dazu. Ueber HTTP im Sekundentakt zu schalten waere ein Zufallstakt.
  `blinkenLoeschen()` raeumt es beim Wechsel auf Auto, bei einem Status, bei
  „Alles aus" und beim stillen Start ab.
- **Die Ampel bleibt still.** Kein Ton und keine Warnleuchte im Bild, auch
  nicht bei der Stoerung (Max, 17.11.2026). Der Tongeber kommt genau einmal
  beim Umschalten auf die Betriebsart.
- **Die Betriebsart „Ampel" folgt dem Stellplatz, nicht der Lampe des ESP.**
  Das Feld `ampel` in dessen `/api/state` gehoert zur Lampe in der Garage und
  geht auf `aus`, sobald das Tor zu ist und das Auto nicht mehr zu hoeren ist -
  dann steht der 206 immer noch drin. Am 17.11. blieb die Saeule darum dunkel,
  obwohl das Auto drinstand und die Lichtschranke durchtrennt war. Die
  Betriebsart urteilt jetzt selbst, aus `auto_drin` und `strom`
  (`Ampelmodus.lage`); `ampel` steht nur noch als Attribut daneben. Weiss der
  ESP nichts ueber den Platz, blinkt es gelb - nie faelschlich gruen. Und es
  gibt kein Bild fuer „nichts leuchtet": eine dunkle Statusanzeige sagt nichts.
- **Die zwei Stoerungen der Ampel nicht zusammenwerfen.** `kein_strom` heisst:
  der ESP lebt und `strom` ist falsch, der Lichtschranke fehlen die 24 V - gelb blinkt
  mit einem Hertz, Hinweisleuchte sehr schnell dazu. Antwortet er gar nicht,
  fehlen ihm selbst die 5 V, und dann steht nicht einmal fest, dass die Garage
  ueberwacht wird: rot blinkt, allein, im Takt der gelben und ohne
  Hinweisleuchte (Max, 17.11.2026). Erst waren beide Faelle gleich gebaut,
  das war falsch.
- **Blinken und Ampelbilder gelten nur im Ampelmodus.** Ausserhalb bleibt die
  Saeule, wie sie war: `LeuchteSwitch` gibt kein `blinken` mit, und in „auto"
  wirkt es ohnehin nicht.
- **Nach einem Reload der Garage muss der Listener nachgezogen werden.** Der
  Ampelmodus haengt mit `async_add_listener` am Garagen-Coordinator; wird der
  Eintrag neu geladen, ist der ein neues Objekt, und die Saeule bliebe auf dem
  letzten Bild stehen. Darum ruft `_setup_garage` am Ende
  `ampel.async_garage_neu()` bei jeder Saeule. Am 17.11. beim Pruefen am Geraet
  aufgefallen.
- **Der Ampelmodus schreibt nur bei Aenderung.** `_bild` haelt, was zuletzt
  gestellt wurde; meldet die Garage denselben Wert noch einmal (sie schiebt
  jede Kleinigkeit ueber den Ereignisstrom), geht kein Befehl ans Geraet.
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
- **Ein Schritt haengt am Weckruf, am Beenden oder am Schlummern** (`ab`:
  "weckruf", "ende", "schlummern"). Die Teile werden getrennt geplant; ein
  neuer Lauf raeumt die Timer des alten ab. Der Nachlauf faengt genau dann an,
  wenn die App "ringing" auf false setzt - nicht nach Uhrzeit. Der Probelauf
  simuliert das Beenden nach 30 s, sonst liefe die zweite Haelfte nie an.
- **Schlummern ist ein eigener Teil des Ablaufs**, kein hartkodiertes
  Aufraeumen (bis 2.3.0 war es `_schlummern()`). Im Standardablauf: Saeule auf
  Ruhe, Licht auf 5 %, und nach 1140 s (19 min) Licht aus - Max' Vorgabe vom
  16.11., nachdem "ganz aus" eine Stunde vorher noch richtig schien. Mit zwei
  Minuten Schlummerzeit klingelt es vorher wieder, dann raeumt der
  Weckruf-Teil die Schlummer-Timer ab. `AB_SPAETER` fasst "ende" und
  "schlummern" zusammen: beide waehlen den Block ueber den alten Nullpunkt
  und enden mit ihrem letzten Schritt, statt auf `ABLAUF_MAX_S` zu warten.
  `_letzte_art` haelt fest, welcher Teil lief - sonst meldete `_fertig()`
  nach jedem Schlummern faelschlich das Sicherheitsnetz.
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
- **Garage: der Schritt `garage` im Config-Flow ist eine Schnittstelle, kein
  Formular.** Der Garagen-ESP ruft ihn selbst ueber REST auf (`POST
  /api/config/config_entries/flow` mit `handler: ha_wecker`, dann
  `next_step_id: garage`, dann `name` und `host`). Feldnamen, Schrittname und
  das `updates={CONF_HOST: host}` beim Abbruch `already_configured` (so zieht
  eine neue IP nach) duerfen sich nicht aendern, ohne die Firmware
  mitzuziehen. Der Test `test_garage_config_flow_wie_der_esp` geht genau
  diesen Weg.
- **Die Betriebsart „Drucker" urteilt selbst** (`drucker.py`, seit
  20.11.2026). Sie reicht nichts von Bambu weiter: aus `print_status` (elf
  Werte) und `stage` (ueber achtzig) werden neun Lagen, und eine Pause wird
  nach ihrem Grund auf drei davon verteilt - Material fehlt ist `eingriff`,
  Maschine ist `fehler`, von Hand ist `pause`. HMS-Meldungen machen bewusst
  **kein** Bild (darunter kommen Bagatellen, und eine Saeule, die davon rot
  wird, ist nach einer Woche Tapete), nur `print_error` und ein abgebrochener
  Lauf. Max' Vorgabe: „die eingebauten meldungen wie störung etc nicht
  einfach anzeigen was eigenes bauen."
- **Drucker: die Entitaeten ueber den `translation_key` finden**, nie ueber
  Entitaets-IDs. Die IDs folgen der Sprache von Home Assistant und dem Namen
  des Geraets (`sensor.og_zimmer_max_bambulab_drucker_druckstatus`); der
  Schluessel (`print_status`) ist stabil. Gelesen wird die Registry
  (`platform == "bambu_lab"`), und `async_track_state_change_event` horcht -
  kein Abfragetakt.
- **Drucker: die Restzeit kommt in Stunden.** `remaining_time` hat
  `unit_of_measurement: h` (0,42 = 25 Minuten). Wer die Zahl ungelesen nimmt,
  haelt jeden Druck fuer fast fertig - darum `minuten()` mit der Einheit.
  Dasselbe gilt fuer alles andere, was eine Einheit traegt.
- **Drucker: `finish` ist kein Ereignis, sondern ein Dauerzustand.** Der
  Drucker steht nach dem letzten Layer stundenlang darauf. Darum merkt sich
  `_gedaechtnis_pflegen()` drei Dinge, die das Geraet nicht sagt: wann
  `finish` anfing (nach `DRUCKER_FERTIG_MAX_S` ist es gut), ob die
  Gehaeusetuer seither **aufgegangen** ist (das quittiert das Abholen - nur
  die Oeffnung, nicht der offene Zustand), und wann zuletzt wirklich ein
  Druck lief (sonst waere jeder ausgeschaltete Drucker eine Stoerung statt
  `ruht`).
- **Drucker: der Sensor ist der Zweck, die Betriebsart die Zugabe.** Darum
  horcht `Druckermodus` ab dem Einrichten (`async_beobachten()` in
  `_setup_saeule`) und `verlassen()` raeumt die Wache **nicht** ab - nur
  `async_stop`. Sonst stuende `sensor.<saeule>_drucker` still, solange die
  Saeule auf Auto steht.
- **Drucker: Ton nur tagsueber und nur einmal je Lage.** Quittung beim
  Umschalten, dann je einmal bei `fertig` und `fehler`
  (`_ton_fuer`), nichts bei `eingriff` (eine offene Tuer im Druck ist
  Alltag), und zwischen 21 und 8 Uhr gar nichts - die Saeule steht in einem
  Schlafzimmer. Keine Blitz-Warnleuchte, die gehoert dem Alarm.
- **Die beiden Betriebsarten aus Home Assistant schliessen sich aus.**
  `coordinator.betriebsarten` / `betriebsart_verlassen()` fassen sie
  zusammen; Schalter, Stufe von Hand, Status und „Alles aus" gehen ueber
  diese eine Stelle, nicht ueber `coordinator.ampel`. Wer eine dritte
  dazubaut, haengt sie dort ein und sonst nirgends.
- **Garage: Werte vom Auto sind dreiwertig.** `auto_verriegelt`, `auto_zuendung`,
  `auto_rueckwaerts` sind `null`, solange der Auto-ESP nicht zu hoeren ist, und
  die Entitaeten dann `unavailable` - nicht "aus". Ein verriegeltes Auto, das
  gerade ausser Reichweite ist, wuerde sonst als entriegelt angezeigt.

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
