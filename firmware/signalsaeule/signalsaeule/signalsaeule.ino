/*
  Signalsaeule - Arduino UNO R4 WiFi
  ---------------------------------------------------------------------------
  Rittal Signalsaeule SZ 2372.02.0 mit vier Leuchtelementen und einer
  Blitz-Warnleuchte, geschaltet ueber MOSFET-Leistungsstufen (aktiv HIGH).
  Die Saeule haengt im WLAN, zeigt ein eigenes Web-Dashboard und bietet
  dieselbe HTTP-Schnittstelle, die die Home-Assistant-Integration
  "HA Wecker" schon fuer die Relaisbox spricht (Geraetetyp "saeule").

  Ausgaenge (Stromlaufplan SIG-R4-E, Blatt 9)

    D2  K1 : IN       H5  Blitz-Warnleuchte   Ader weiss   braucht Dauerspannung
    D3  K2 : IN3      H3  rot     Stufe 3     Ader gelb
    D4  K2 : IN2      H2  orange  Stufe 2     Ader weiss
    D5  K2 : IN1      H1  gruen   Stufe 1     Ader gelb
    D6  K2 : IN4      H4  Hinweis Stufe 4     Ader rot

  D3 und D5 sind gegenueber dem Stromlaufplan vertauscht: die beiden gelben
  Adern sind beim Anklemmen verwechselt worden und bleiben so. Die Tabelle
  LEUCHTEN weiter unten dreht das wieder gerade.
                      Reserve (Ader schwarz) bleibt ungeschaltet

  Die Module ziehen bei HIGH durch (F5305S, P-Kanal, schaltet im Pluspfad).
  Kein Oeffner, kein Ruhestromprinzip - fehlt die Steuerung, ist alles dunkel.

  Betriebsart

    auto     ein Status treibt die Saeule. Jeder Wechsel wird angesagt
             (Aufbau, Abbau, Einrasten), danach steht das Bild des Status.
    manuell  jede Leuchte wird einzeln geschaltet und bleibt so stehen.

  Die Warnleuchte haengt an keiner Choreografie: sie hat einen eigenen
  Schalter und gilt in beiden Betriebsarten. Mitgenommen wird sie von zweierlei:
  vom Testmodus und vom Status Alarm. Beim Alarm geht sie erst an, wenn das
  Alarmbild wirklich laeuft - also wenn Rot und Hinweisleuchte im Wechsel
  blinken, nicht schon waehrend der Ansage - und bleibt dann dauerhaft an.
  Verlaesst die Saeule den Alarm, bekommt sie wieder den Stand von vorher.

  HTTP (Port 80)
    GET  /                          Dashboard
    GET  /api/state                 Zustand als JSON
    GET  /api/ping                  {"ok":true}
    GET  :8081/api/events           Ereignisstrom (SSE), bei jeder Aenderung
    POST /api/relais/<nr>?an=1|0    eine Leuchte schalten (Stufe -> manuell)
    POST /api/modus?modus=auto|manuell
    POST /api/status?status=ruhe|hinweis|achtung|stoerung|alarm  (-> auto)
    POST /api/test?an=1|0           Testmodus
    POST /api/diagnose              Selbstdiagnose starten
    POST /api/alarm/stop            alles aus, Betriebsart manuell
*/

#include "ArduinoGraphics.h"
#include "Arduino_LED_Matrix.h"
#include <WiFiS3.h>
#include <Preferences.h>
#include "FspTimer.h"
#include "arduino_secrets.h"
#include "seite.h"

static const char* VERSION  = "1.0.0";
static const char* HOSTNAME = "signalsaeule";
static const uint16_t SSE_PORT = 8081;

// Alle Typen stehen vor der ersten Funktion: arduino-cli setzt seine erzeugten
// Prototypen vor die erste Funktionsdefinition, und die muessen Status,
// Leuchte, DiagPunkt und Phase schon kennen.
enum Status { RUHE = 0, HINWEIS, ACHTUNG, STOERUNG, ALARM, STATUS_ANZAHL };

static const char* STATUS_ID[]   = {"ruhe", "hinweis", "achtung", "stoerung", "alarm"};
static const char* STATUS_NAME[] = {"Ruhe", "Hinweis", "Achtung", "St\xc3\xb6rung", "Alarm"};

struct Leuchte {
  uint8_t nr;            // Nummer bleibt stabil, HA haengt daran
  uint8_t pin;
  const char* name;
  bool warn;             // true = Blitz-Warnleuchte, laeuft ausserhalb der Status
};

struct DiagPunkt {
  const char* name;
  int8_t ok;             // 1 in Ordnung, 0 Fehler, -1 nur ein Hinweis
  char text[52];
};

enum Phase { PH_START, PH_WLAN, PH_BETRIEB };

// Die Betriebsphase liest auch die Zeitgeber-Unterbrechung, darum steht sie
// hier oben bei den uebrigen Grundgroessen.
static Phase phase = PH_START;
static uint32_t schleifeBegann = 0;
static uint16_t schleifeMax = 0;        // laengster Schleifendurchlauf in ms

ArduinoLEDMatrix matrix;
WiFiServer server(80);
WiFiServer sseServer(SSE_PORT);

// --------------------------------------------------------------- Leuchten

// Gruen und Rot haengen vertauscht an der Leistungsstufe: beim Anklemmen sind
// am 14.11. die beiden gelben Adern verwechselt worden. Gerichtet wird das
// hier, nicht am Draht - Gruen liegt an D5, Rot an D3. Die Nummern 1 bis 5
// bleiben dabei unberuehrt, die Entitaeten in Home Assistant haengen daran.
static Leuchte LEUCHTEN[] = {
  {1, 5, "Gruen",       false},
  {2, 4, "Orange",      false},
  {3, 3, "Rot",         false},
  {4, 6, "Hinweis",     false},
  {5, 2, "Warnleuchte", true },
};
static const uint8_t ANZAHL = sizeof(LEUCHTEN) / sizeof(LEUCHTEN[0]);
static const uint8_t STUFEN = 4;        // Index 0..3 sind die Stufen der Saeule
static const uint8_t IDX_WARN = 4;      // Index der Warnleuchte

static bool istAn[ANZAHL];              // was gerade wirklich gesetzt ist
static bool manuell[ANZAHL];            // Wunsch in der Betriebsart "manuell"

static int8_t leuchteIndex(int nr) {
  for (uint8_t i = 0; i < ANZAHL; i++) if (LEUCHTEN[i].nr == nr) return (int8_t)i;
  return -1;
}

static void setzen(uint8_t i, bool an) {
  istAn[i] = an;
  digitalWrite(LEUCHTEN[i].pin, an ? HIGH : LOW);
}

// --------------------------------------------------------------- Zustaende

// Auf welcher Stufe steht die Moduslampe? (0 gruen, 1 orange, 2 rot)
static uint8_t modusStufe(Status s) {
  switch (s) {
    case ACHTUNG:  return 1;
    case STOERUNG: return 2;
    case ALARM:    return 2;
    default:       return 0;
  }
}

static const unsigned long AUFBAU_MS = 180;    // je Stufe beim Hochlaufen
static const unsigned long ABBAU_MS  = 180;    // je Stufe beim Abraeumen
static const unsigned long RUHE_MS   = 1400;   // Moduslampe steht still

static Status status = RUHE;
static bool autoModus = true;
static bool warnAn = false;
// Der Alarm nimmt die Warnleuchte mit - aber erst, wenn das Alarmbild wirklich
// laeuft, nicht schon waehrend der Ansage. Beim Verlassen des Alarms bekommt
// sie wieder den Stand, den sie vorher von Hand hatte.
static bool warnVomAlarm = false;
static bool warnVorAlarm = false;
static bool testAn = false;

static unsigned long statusSeit = 0;
static bool wechselAktiv = false;
static bool pfeilHoch = true;
static bool bildSteht = false;
static bool pfeilSteht = false;

static uint8_t abbauFolge[STUFEN];
static uint8_t abbauSchritte = 0;

static void abbauFolgeBauen(uint8_t modus) {
  abbauSchritte = 0;
  for (int s = STUFEN - 1; s >= 0; s--)
    if ((uint8_t)s != modus) abbauFolge[abbauSchritte++] = (uint8_t)s;
}

static unsigned long wechselZeit()  { return millis() - statusSeit; }
static unsigned long aufbauDauer()  { return STUFEN * AUFBAU_MS; }
static unsigned long wechselDauer() { return aufbauDauer() + abbauSchritte * ABBAU_MS; }
static bool imWechsel()   { return wechselAktiv && wechselZeit() < wechselDauer(); }
static bool imAufbau()    { return wechselZeit() < aufbauDauer(); }
static bool inRuhephase() { return wechselAktiv && !imWechsel(); }

static void sseSenden();   // vorab

static void statusSetzen(Status neu, bool ansage = true, bool erzwingen = false) {
  if (neu == status && ansage && !erzwingen) return;
  pfeilHoch = (neu >= status);
  abbauFolgeBauen(modusStufe(neu));
  status = neu;
  statusSeit = millis();
  wechselAktiv = ansage;
  bildSteht = false;
  pfeilSteht = false;
}

static bool takt(unsigned long periode) { return (millis() % periode) < (periode / 2); }

// ------------------------------------------------------------- Testmodus

// Lauflicht ueber die vier Stufen, die Warnleuchte blitzt in Schueben -
// so sieht man jede Leuchte einmal, ohne die Blitzroehre zu quaelen.
static const unsigned long TEST_SCHRITT_MS = 300;
static const unsigned long TEST_WARN_AN_MS = 2000;
static const unsigned long TEST_WARN_AUS_MS = 3000;

static void testStellen() {
  unsigned long t = millis();
  uint8_t i = (uint8_t)((t / TEST_SCHRITT_MS) % (STUFEN * 2 - 2));   // hin und zurueck
  if (i >= STUFEN) i = (uint8_t)(STUFEN * 2 - 2 - i);
  for (uint8_t s = 0; s < STUFEN; s++) setzen(s, s == i);
  unsigned long p = t % (TEST_WARN_AN_MS + TEST_WARN_AUS_MS);
  setzen(IDX_WARN, p < TEST_WARN_AN_MS);
}

// --------------------------------------------------------- Selbstdiagnose

static const uint8_t DIAG_PUNKTE = 4 + ANZAHL;    // WLAN, USB, Rueckmeldung, Speicher
static DiagPunkt diag[DIAG_PUNKTE];
static uint8_t diagAnzahl = 0;
static int8_t diagSchritt = -1;          // -1 = laeuft nicht
static unsigned long diagSeit = 0;
static bool diagFertig = false;
static bool diagRueckmeldung = false;    // liest der Pin seinen Pegel zurueck?
static unsigned long diagEnde = 0;

static void diagEintrag(const char* name, int8_t ok, const char* text) {
  if (diagAnzahl >= DIAG_PUNKTE) return;
  diag[diagAnzahl].name = name;
  diag[diagAnzahl].ok = ok;
  strncpy(diag[diagAnzahl].text, text, sizeof(diag[0].text) - 1);
  diag[diagAnzahl].text[sizeof(diag[0].text) - 1] = 0;
  diagAnzahl++;
}

extern "C" char* sbrk(int incr);
static int freierRam() {
  char oben;
  return &oben - reinterpret_cast<char*>(sbrk(0));
}

// USB-Erkennung gibt es hier bewusst nicht. Am 14.11. gemessen: INTSTS0 des
// RA4M1 liest aus dem Sketch durchweg 0 (VBSTS und DVSQ also auch), und das
// gilt auch, nachdem man VDCEN selbst setzt - der Core laesst die
// VBUS-Erkennung aus, aber das allein ist es nicht. tud_cdc_connected() hinter
// (bool)Serial bleibt umgekehrt dauerhaft true, auch ohne offenen Port. Damit
// laesst sich weder "Spannung da" noch "Rechner dran" ehrlich anzeigen.

// Zustand vor der Diagnose, um ihn danach wiederherzustellen
static bool diagVorherAuto = true;
static Status diagVorherStatus = RUHE;
static bool diagVorherWarn = false;

static void diagnoseStarten() {
  diagVorherAuto = autoModus;
  diagVorherStatus = status;
  diagVorherWarn = warnAn;
  diagAnzahl = 0;
  diagSchritt = 0;
  diagFertig = false;
  diagSeit = millis();
}

static void diagnoseSchritt() {
  char zeile[52];
  unsigned long seit = millis() - diagSeit;

  // 0 WLAN, 1 USB, 2 Rueckmeldung: sofort. Danach je Leuchte 400 ms.
  if (diagSchritt == 0) {
    long r = WiFi.RSSI();
    snprintf(zeile, sizeof(zeile), "%s, %ld dBm, %s",
             WiFi.SSID(), r, WiFi.localIP().toString().c_str());
    diagEintrag("WLAN", WiFi.status() == WL_CONNECTED ? 1 : 0, zeile);
    diagSchritt = 1;
    return;
  }
  if (diagSchritt == 1) {
    snprintf(zeile, sizeof(zeile), "%s, Firmware %s", HOSTNAME, VERSION);
    diagEintrag("Geraet", 1, zeile);
    diagSchritt = 2;
    return;
  }
  if (diagSchritt == 2) {
    // Pruefen, ob digitalRead einem Ausgang ueberhaupt folgt
    uint8_t pin = LEUCHTEN[0].pin;
    digitalWrite(pin, HIGH);
    delayMicroseconds(50);
    int hoch = digitalRead(pin);
    digitalWrite(pin, LOW);
    delayMicroseconds(50);
    int tief = digitalRead(pin);
    setzen(0, false);
    diagRueckmeldung = (hoch == HIGH && tief == LOW);
    diagEintrag("Pinrueckmeldung", diagRueckmeldung ? 1 : -1,
                diagRueckmeldung ? "Ausgaenge lesen ihren Pegel zurueck"
                                 : "nicht lesbar - Leuchten nur gesetzt");
    diagSchritt = 3;
    diagSeit = millis();
    return;
  }
  if (diagSchritt >= 3 && diagSchritt < (int8_t)(3 + ANZAHL)) {
    uint8_t i = (uint8_t)(diagSchritt - 3);
    if (seit == 0 || !istAn[i]) {
      for (uint8_t k = 0; k < ANZAHL; k++) setzen(k, k == i);
    }
    if (seit < 400) return;
    int pegel = digitalRead(LEUCHTEN[i].pin);
    bool ok = !diagRueckmeldung || pegel == HIGH;
    if (diagRueckmeldung)
      snprintf(zeile, sizeof(zeile), "Pin D%u liest %d", LEUCHTEN[i].pin, pegel);
    else
      snprintf(zeile, sizeof(zeile), "Pin D%u gesetzt", LEUCHTEN[i].pin);
    diagEintrag(LEUCHTEN[i].name, ok ? 1 : 0, zeile);
    setzen(i, false);
    diagSchritt++;
    diagSeit = millis();
    return;
  }
  // Letzter Punkt: Speicher und Laufzeit
  snprintf(zeile, sizeof(zeile), "%d Byte RAM frei, %lu s Laufzeit",
           freierRam(), millis() / 1000);
  diagEintrag("Speicher", freierRam() > 2000 ? 1 : 0, zeile);

  diagSchritt = -1;
  diagFertig = true;
  diagEnde = millis();
  autoModus = diagVorherAuto;
  warnAn = diagVorherWarn;
  warnVomAlarm = false;       // der Alarm darf sie gleich wieder uebernehmen
  statusSetzen(diagVorherStatus, false);
  sseSenden();
}

static bool diagLaeuft() { return diagSchritt >= 0; }

static bool diagAllesOk() {
  for (uint8_t i = 0; i < diagAnzahl; i++) if (diag[i].ok == 0) return false;
  return diagAnzahl > 0;
}

// ------------------------------------------------------------- Leuchtbild

// Alarm und Warnleuchte zusammenbringen. Eingerastet heisst: die Ansage ist
// durch und die Ruhephase auch - genau der Augenblick, in dem Rot und
// Hinweisleuchte im Wechsel zu blinken anfangen.
static void alarmWarnPflegen() {
  bool soll = autoModus && !testAn && status == ALARM && !wechselAktiv;
  if (soll && !warnVomAlarm) {
    warnVorAlarm = warnAn;
    warnAn = true;
    warnVomAlarm = true;
  } else if (!soll && warnVomAlarm) {
    warnAn = warnVorAlarm;
    warnVomAlarm = false;
  }
}

static void lampenStellen() {
  if (diagLaeuft()) return;            // die Diagnose stellt selbst
  if (testAn) { testStellen(); return; }

  // Warnleuchte: eigener Schalter, unabhaengig von der Betriebsart
  setzen(IDX_WARN, warnAn);

  if (!autoModus) {
    for (uint8_t s = 0; s < STUFEN; s++) setzen(s, manuell[s]);
    return;
  }

  uint8_t modus = modusStufe(status);

  if (imWechsel()) {
    if (imAufbau()) {
      uint8_t i = (uint8_t)(wechselZeit() / AUFBAU_MS);
      for (uint8_t s = 0; s < STUFEN; s++)
        setzen(s, pfeilHoch ? (s <= i) : (s >= STUFEN - 1 - i));
    } else {
      uint8_t j = (uint8_t)((wechselZeit() - aufbauDauer()) / ABBAU_MS);
      if (abbauSchritte && j >= abbauSchritte) j = abbauSchritte - 1;
      uint8_t aus = 0;
      for (uint8_t k = 0; k <= j && k < abbauSchritte; k++) aus |= (uint8_t)(1 << abbauFolge[k]);
      for (uint8_t s = 0; s < STUFEN; s++) setzen(s, s == modus || !(aus & (1 << s)));
    }
    return;
  }

  if (inRuhephase()) {
    for (uint8_t s = 0; s < STUFEN; s++) setzen(s, s == modus);
    return;
  }

  switch (status) {
    case RUHE:
      setzen(0, true);  setzen(1, false); setzen(2, false); setzen(3, false);
      break;
    case HINWEIS:
      setzen(0, true);  setzen(1, false); setzen(2, false); setzen(3, takt(2000));
      break;
    case ACHTUNG:
      setzen(0, false); setzen(1, true);  setzen(2, false); setzen(3, takt(800));
      break;
    case STOERUNG:
      setzen(0, false); setzen(1, false); setzen(2, true);  setzen(3, takt(400));
      break;
    case ALARM:
      setzen(0, false); setzen(1, false); setzen(2, takt(500)); setzen(3, !takt(500));
      break;
    default: break;
  }
}

// -------------------------------------------------------------- LED-Matrix

// Die Matrix zeigt die Saeule im Kleinen: vier Balken von unten nach oben,
// genau die, die gerade brennen. Blinkt die Hinweisleuchte, blinkt der oberste
// Balken mit; die Blitz-Warnleuchte legt zwei Striche an die Seiten.
// Buchstaben auf zwoelf mal acht Punkten waren nicht zu entziffern, ein
// Abbild der Saeule schon - und es sagt mehr.

static void matrixZahl(const char* text) {
  matrix.beginDraw();
  matrix.clear();
  matrix.stroke(0xFFFFFFFF);
  matrix.textFont(Font_5x7);
  matrix.beginText(text[1] ? 1 : 4, 1, 0xFFFFFF);
  matrix.println(text);
  matrix.endText();
  matrix.endDraw();
}

// Letztes Glied der Adresse, Ziffer fuer Ziffer - drei Stellen passen nicht
// nebeneinander auf zwoelf Punkte, nacheinander sind sie gut lesbar.
static void matrixAdresse(uint8_t letztes) {
  char ziffern[4];
  snprintf(ziffern, sizeof(ziffern), "%u", (unsigned)letztes);
  for (uint8_t runde = 0; runde < 2; runde++) {
    for (char* z = ziffern; *z; z++) {
      char eine[2] = {*z, 0};
      matrixZahl(eine);
      delay(600);
    }
    matrix.beginDraw(); matrix.clear(); matrix.endDraw();
    delay(250);
  }
}

static uint8_t matrixBild = 0xFF;      // Signatur des zuletzt gezeichneten Bildes

static void matrixSpiegeln() {
  uint8_t sig = 0;
  for (uint8_t i = 0; i < ANZAHL; i++) if (istAn[i]) sig |= (uint8_t)(1 << i);
  if (sig == matrixBild) return;       // nur zeichnen, wenn sich etwas aendert
  matrixBild = sig;

  static const uint8_t ZEILE[STUFEN] = {7, 5, 3, 1};   // Stufe 1 unten
  matrix.beginDraw();
  matrix.clear();
  matrix.noStroke();
  matrix.fill(0xFFFFFF);
  for (uint8_t s = 0; s < STUFEN; s++)
    if (istAn[s]) matrix.rect(3, ZEILE[s], 6, 1);
  if (istAn[IDX_WARN]) {
    matrix.rect(0, 0, 1, 8);
    matrix.rect(11, 0, 1, 8);
  }
  matrix.endDraw();
}

// Ein Takt fuer die Schleife: Alarmkopplung und Matrix. Die Leuchten selbst
// stellt der Zeitgeber unten, nicht die Schleife.
static void takten() {
  alarmWarnPflegen();
  matrixSpiegeln();
}

// --------------------------------------------------------- Taktgeber (GPT)
//
// Das Blinken darf nicht davon abhaengen, was das Netz gerade tut. Beim
// UNO R4 WiFi laeuft jede Socket-Operation ueber eine Uebertragung an den
// ESP32-S3, der das WLAN macht - eine einzelne Anfrage haelt die Schleife
// dadurch leicht 200 ms auf, und genau so sah das Blinken auch aus.
// Darum stellt ein Hardware-Zeitgeber die Ausgaenge hundert Mal je Sekunde,
// voellig unabhaengig von loop(). In der Unterbrechung wird nur geschaltet:
// keine Strings, keine Matrix, kein Netz.

FspTimer taktgeber;

// Abstand zweier Takte: soll 10 000 us sein. Der groesste Abstand seit der
// letzten Abfrage sagt, ob das Licht wirklich unabhaengig vom Netz laeuft.
static volatile uint32_t taktLetzter = 0;
static volatile uint32_t taktMaxUs = 0;
static volatile uint32_t taktZaehler = 0;

static void taktISR(timer_callback_args_t*) {
  uint32_t jetzt = micros();
  if (taktLetzter) {
    uint32_t ab = jetzt - taktLetzter;
    if (ab > taktMaxUs) taktMaxUs = ab;
  }
  taktLetzter = jetzt;
  taktZaehler++;

  if (phase != PH_BETRIEB) return;     // Startablauf stellt selbst
  if (diagLaeuft()) return;            // die Diagnose auch
  lampenStellen();
}

static bool taktgeberStarten() {
  uint8_t typ;
  int8_t kanal = FspTimer::get_available_timer(typ);
  if (kanal < 0) {
    FspTimer::force_use_of_pwm_reserved_timer();
    kanal = FspTimer::get_available_timer(typ, true);
  }
  if (kanal < 0) return false;
  if (!taktgeber.begin(TIMER_MODE_PERIODIC, typ, (uint8_t)kanal, 100.0f, 0.0f, taktISR, nullptr))
    return false;
  if (!taktgeber.setup_overflow_irq()) return false;
  if (!taktgeber.open()) return false;
  return taktgeber.start();
}

// ------------------------------------------------------- Gedaechtnis (Flash)
//
// Status, Betriebsart und Warnleuchte liegen im Daten-Flash des RA4M1
// (Preferences). Nach einem Stromausfall steht die Saeule wieder so da wie
// vorher. Geschrieben wird verzoegert und nur bei echter Aenderung - der
// Daten-Flash haelt keine beliebige Zahl von Schreibzyklen aus.

Preferences merker;
static const unsigned long MERKEN_VERZUG_MS = 3000;
static unsigned long merkenFaellig = 0;
static uint8_t gemerktStatus = 255;
static uint8_t gemerktModus = 255;
static uint8_t gemerktWarn = 255;

static void merkenBald() { merkenFaellig = millis() + MERKEN_VERZUG_MS; }

static void merkenJetzt() {
  merkenFaellig = 0;
  uint8_t s = (uint8_t)status, m = autoModus ? 1 : 0;
  // den Stand von Hand merken, nicht den vom Alarm erzwungenen
  uint8_t w = (warnVomAlarm ? warnVorAlarm : warnAn) ? 1 : 0;
  if (s == gemerktStatus && m == gemerktModus && w == gemerktWarn) return;
  merker.putUChar("status", s);
  merker.putUChar("modus", m);
  merker.putUChar("warn", w);
  gemerktStatus = s; gemerktModus = m; gemerktWarn = w;
}

static void gedaechtnisLaden() {
  merker.begin("saeule", false);
  gemerktStatus = merker.getUChar("status", (uint8_t)RUHE);
  gemerktModus  = merker.getUChar("modus", 1);
  gemerktWarn   = merker.getUChar("warn", 0);
  if (gemerktStatus >= STATUS_ANZAHL) gemerktStatus = RUHE;
  status = (Status)gemerktStatus;
  autoModus = (gemerktModus != 0);
  warnAn = (gemerktWarn != 0);
}

// ------------------------------------------------------------ Startablauf
//
// Sobald Strom da ist, laeuft die Saeule einmal sichtbar durch: von unten
// nach oben dazu, alle zusammen mit einem Blitz, dann von oben nach unten
// wieder aus. Danach zeigt die Matrix Version und Adresse, und die Saeule
// nimmt den Status wieder auf, der vor dem Stromausfall stand.

static unsigned long startSeit = 0;

static const unsigned long ST_AUF_MS   = 300;                 // je Stufe dazu
static const unsigned long ST_HALT_MS  = 600;                 // alle zusammen
static const unsigned long ST_AB_MS    = 225;                 // je Stufe weg
static const unsigned long ST_AUF_ENDE = STUFEN * ST_AUF_MS;             // 1200
static const unsigned long ST_HALT_ENDE = ST_AUF_ENDE + ST_HALT_MS;      // 1800
static const unsigned long ST_ENDE = ST_HALT_ENDE + STUFEN * ST_AB_MS;   // 2700
static const bool START_MIT_BLITZ = true;     // ein Impuls der Warnleuchte

static void startStellen() {
  unsigned long t = millis() - startSeit;

  if (t < ST_AUF_ENDE) {
    uint8_t i = (uint8_t)(t / ST_AUF_MS);
    for (uint8_t s = 0; s < STUFEN; s++) setzen(s, s <= i);
    setzen(IDX_WARN, false);
  } else if (t < ST_HALT_ENDE) {
    for (uint8_t s = 0; s < STUFEN; s++) setzen(s, true);
    // kurzer Impuls, damit man auch die Blitzleuchte einmal sieht
    setzen(IDX_WARN, START_MIT_BLITZ && t > ST_AUF_ENDE + 100 && t < ST_AUF_ENDE + 400);
  } else {
    // von oben nach unten wieder aus
    int grenze = (int)STUFEN - 1 - (int)((t - ST_HALT_ENDE) / ST_AB_MS);
    for (uint8_t s = 0; s < STUFEN; s++) setzen(s, (int)s < grenze);
    setzen(IDX_WARN, false);
  }

  // Balken auf der Matrix waechst mit dem Ablauf
  static unsigned long letzterBalken = 0;
  if (millis() - letzterBalken > 120) {
    letzterBalken = millis();
    int breite = (int)((t * 12) / ST_ENDE);
    if (breite > 12) breite = 12;
    matrix.beginDraw();
    matrix.clear();
    matrix.noStroke();
    matrix.fill(0xFFFFFF);
    if (breite > 0) matrix.rect(0, 3, breite, 2);
    matrix.endDraw();
  }
}

// ------------------------------------------------------------------- WLAN

static void wlanVerbinden() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.print("WLAN ");
  Serial.print(WLAN_SSID);
  WiFi.setHostname(HOSTNAME);
  WiFi.begin(WLAN_SSID, WLAN_PASS);
  for (int i = 0; i < 20 && WiFi.status() != WL_CONNECTED; i++) {
    delay(500);
    Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print(" verbunden, IP ");
    Serial.println(WiFi.localIP());
    server.begin();
    sseServer.begin();
  } else {
    Serial.println(" nicht erreichbar");
  }
}

// ------------------------------------------------------------------- JSON

static String jsonText(const char* s) {
  String out = "\"";
  for (const char* p = s; *p; p++) {
    if (*p == '"' || *p == '\\') out += '\\';
    out += *p;
  }
  out += '"';
  return out;
}

static bool sollAn(uint8_t i) {
  if (testAn) return true;
  if (i == IDX_WARN) return warnAn;
  if (!autoModus) return manuell[i];
  uint8_t m = modusStufe(status);
  if (i == m) return true;
  if (i == 3) return status != RUHE;      // Hinweisleuchte blinkt ausser in Ruhe
  return false;
}

static String stateJson() {
  String s;
  s.reserve(2400);
  s += "{\"name\":\"Signals\xc3\xa4ule\",\"typ\":\"saeule\",\"version\":\"" + String(VERSION) + "\"";
  s += ",\"mac\":\"";
  uint8_t mac[6];
  WiFi.macAddress(mac);
  char puffer[20];
  snprintf(puffer, sizeof(puffer), "%02X:%02X:%02X:%02X:%02X:%02X",
           mac[5], mac[4], mac[3], mac[2], mac[1], mac[0]);
  s += puffer;
  s += "\",\"ip\":\"" + WiFi.localIP().toString() + "\"";
  s += ",\"rssi\":" + String(WiFi.RSSI());
  s += ",\"uptime_s\":" + String(millis() / 1000);
  s += ",\"events_port\":" + String(SSE_PORT);
  s += ",\"ram_frei\":" + String(freierRam());
  s += ",\"schleife_max_ms\":" + String(schleifeMax);
  s += ",\"takt_max_us\":" + String(taktMaxUs);
  s += ",\"takte\":" + String(taktZaehler);
  schleifeMax = 0;                      // nach dem Ablesen neu messen
  taktMaxUs = 0;
  s += ",\"phase\":\"" + String(phase == PH_BETRIEB ? "betrieb" : "start") + "\"";
  s += ",\"modus\":\"" + String(autoModus ? "auto" : "manuell") + "\"";
  s += ",\"status\":\"" + String(STATUS_ID[status]) + "\"";
  s += ",\"status_name\":" + jsonText(STATUS_NAME[status]);
  s += ",\"wechsel\":" + String(imWechsel() || inRuhephase() ? "true" : "false");
  s += ",\"warn\":" + String(warnAn ? "true" : "false");
  s += ",\"warn_vom_alarm\":" + String(warnVomAlarm ? "true" : "false");
  s += ",\"test\":" + String(testAn ? "true" : "false");

  s += ",\"status_liste\":[";
  for (uint8_t i = 0; i < STATUS_ANZAHL; i++) {
    if (i) s += ",";
    s += "{\"id\":\"" + String(STATUS_ID[i]) + "\",\"name\":" + jsonText(STATUS_NAME[i]) + "}";
  }
  s += "]";

  s += ",\"diagnose\":{\"laeuft\":" + String(diagLaeuft() ? "true" : "false");
  s += ",\"fertig\":" + String(diagFertig ? "true" : "false");
  s += ",\"ok\":" + String(diagAllesOk() ? "true" : "false");
  s += ",\"vor_s\":" + String(diagFertig ? (millis() - diagEnde) / 1000 : 0);
  s += ",\"punkte\":[";
  for (uint8_t i = 0; i < diagAnzahl; i++) {
    if (i) s += ",";
    s += "{\"name\":" + jsonText(diag[i].name);
    s += ",\"ok\":" + String(diag[i].ok);
    s += ",\"text\":" + jsonText(diag[i].text) + "}";
  }
  s += "]}";

  s += ",\"relais\":[";
  for (uint8_t i = 0; i < ANZAHL; i++) {
    if (i) s += ",";
    s += "{\"nr\":" + String(LEUCHTEN[i].nr);
    s += ",\"gpio\":" + String(LEUCHTEN[i].pin);
    s += ",\"name\":" + jsonText(LEUCHTEN[i].name);
    s += ",\"rolle\":\"" + String(LEUCHTEN[i].warn ? "warn" : "stufe") + "\"";
    s += ",\"defekt\":false";
    s += ",\"an\":" + String(sollAn(i) ? "true" : "false");       // logischer Zustand
    s += ",\"live\":" + String(istAn[i] ? "true" : "false");      // was gerade leuchtet
    s += ",\"pegel\":" + String(digitalRead(LEUCHTEN[i].pin));
    s += ",\"muster\":\"" + String(sollAn(i) ? "dauer" : "aus") + "\"";
    s += ",\"rest_s\":-1}";
  }
  s += "]}";
  return s;
}

// Kurzfassung fuer das Dashboard - wird zwei Mal pro Sekunde abgefragt
static String liveJson() {
  String s;
  s.reserve(300);
  s += "{\"modus\":\"" + String(autoModus ? "auto" : "manuell") + "\"";
  s += ",\"status\":\"" + String(STATUS_ID[status]) + "\"";
  s += ",\"wechsel\":" + String(imWechsel() || inRuhephase() ? "true" : "false");
  s += ",\"warn\":" + String(warnAn ? "true" : "false");
  s += ",\"warn_vom_alarm\":" + String(warnVomAlarm ? "true" : "false");
  s += ",\"test\":" + String(testAn ? "true" : "false");
  s += ",\"phase\":\"" + String(phase == PH_BETRIEB ? "betrieb" : "start") + "\"";
  s += ",\"diag\":" + String(diagLaeuft() ? "true" : "false");
  s += ",\"live\":[";
  for (uint8_t i = 0; i < ANZAHL; i++) {
    if (i) s += ",";
    s += istAn[i] ? "1" : "0";
  }
  s += "],\"soll\":[";
  for (uint8_t i = 0; i < ANZAHL; i++) {
    if (i) s += ",";
    s += sollAn(i) ? "1" : "0";
  }
  // zurueckgelesener Pin: zeigt auch ohne angeschlossenes Modul, ob der
  // Arduino wirklich geschaltet hat
  s += "],\"pegel\":[";
  for (uint8_t i = 0; i < ANZAHL; i++) {
    if (i) s += ",";
    s += String(digitalRead(LEUCHTEN[i].pin));
  }
  s += "]}";
  return s;
}

// --------------------------------------------------------- Ereignisstrom

static const uint8_t SSE_MAX = 3;
static WiFiClient sseKlienten[SSE_MAX];
static unsigned long sseLeben = 0;
static uint32_t letzteSignatur = 0xFFFFFFFFu;

static void sseSenden() {
  String daten = "data: " + stateJson() + "\n\n";
  for (uint8_t i = 0; i < SSE_MAX; i++) {
    if (sseKlienten[i] && sseKlienten[i].connected())
      sseKlienten[i].print(daten);
  }
}

// Nur der logische Zustand loest einen Push aus - das Blinken selbst nicht,
// sonst flattert Home Assistant im Sekundentakt. Als Zahl, nicht als String:
// die Signatur wird in jedem Schleifendurchlauf gebildet, und ein String waere
// dafuer hundert Mal in der Sekunde eine Speicheranforderung.
static uint32_t signatur() {
  uint32_t s = 0;
  s = (s << 1) | (autoModus ? 1u : 0u);
  s = (s << 3) | (uint32_t)status;
  s = (s << 1) | (warnAn ? 1u : 0u);
  s = (s << 1) | (warnVomAlarm ? 1u : 0u);
  s = (s << 1) | (testAn ? 1u : 0u);
  s = (s << 1) | (diagLaeuft() ? 1u : 0u);
  s = (s << 1) | (diagFertig ? 1u : 0u);
  s = (s << 1) | (phase == PH_BETRIEB ? 1u : 0u);
  for (uint8_t i = 0; i < ANZAHL; i++) s = (s << 1) | (sollAn(i) ? 1u : 0u);
  return s;
}

static void sseAnnehmen() {
  WiFiClient neu = sseServer.available();
  if (!neu) return;
  neu.setTimeout(40);
  while (neu.available()) {
    String zeile = neu.readStringUntil('\n');
    if (zeile.length() <= 1) break;          // Ende der Kopfzeilen
  }
  String antwort =
      "HTTP/1.1 200 OK\r\n"
      "Content-Type: text/event-stream\r\n"
      "Cache-Control: no-store\r\n"
      "Access-Control-Allow-Origin: *\r\n"
      "Connection: keep-alive\r\n\r\n"
      "retry: 3000\n\n"
      "data: ";
  antwort += stateJson();
  antwort += "\n\n";
  neu.write((const uint8_t*)antwort.c_str(), antwort.length());

  for (uint8_t i = 0; i < SSE_MAX; i++) {
    if (!sseKlienten[i] || !sseKlienten[i].connected()) {
      sseKlienten[i].stop();
      sseKlienten[i] = neu;
      return;
    }
  }
  neu.stop();     // alle Plaetze belegt
}

static void ssePflegen() {
  // Nicht in jedem Durchlauf nach neuen Klienten fragen: auch das ist jedes
  // Mal eine Uebertragung an den WLAN-Baustein.
  static uint32_t letzteAnnahme = 0;
  if (millis() - letzteAnnahme > 250) {
    letzteAnnahme = millis();
    sseAnnehmen();
  }
  uint32_t jetzt = signatur();
  if (jetzt != letzteSignatur) {
    letzteSignatur = jetzt;
    sseSenden();
  }
  if (millis() - sseLeben > 15000) {         // Lebenszeichen alle 15 s
    sseLeben = millis();
    for (uint8_t i = 0; i < SSE_MAX; i++)
      if (sseKlienten[i] && sseKlienten[i].connected()) sseKlienten[i].print(": ping\n\n");
  }
}

// ------------------------------------------------------------------- HTTP

static String argWert(const String& ziel, const char* name) {
  int fz = ziel.indexOf('?');
  if (fz < 0) return "";
  String such = String(name) + "=";
  int p = ziel.indexOf("?" + such);
  if (p < 0) p = ziel.indexOf("&" + such);
  if (p < 0) return "";
  p += such.length() + 1;
  int ende = ziel.indexOf('&', p);
  return ende < 0 ? ziel.substring(p) : ziel.substring(p, ende);
}

static bool wahr(const String& v) {
  return v == "1" || v.equalsIgnoreCase("true") || v.equalsIgnoreCase("on") || v.equalsIgnoreCase("an");
}

// Jede einzelne Schreiboperation auf einen WiFiClient ist beim UNO R4 eine
// eigene Uebertragung an den WLAN-Baustein. Sechs println fuer den Kopf haben
// die Schleife rund 150 ms gekostet und das Blinken sichtbar stolpern lassen.
// Darum wird alles vorher zusammengebaut und in einem Stueck geschrieben.
static String kopfBauen(int code, const char* typ, long laenge) {
  String k;
  k.reserve(180);
  k += "HTTP/1.1 ";
  k += code;
  k += (code == 200 ? " OK" : (code == 404 ? " Not Found" : " Bad Request"));
  k += "\r\nContent-Type: ";
  k += typ;
  if (laenge >= 0) {
    k += "\r\nContent-Length: ";
    k += laenge;
  }
  k += "\r\nCache-Control: no-store";
  k += "\r\nAccess-Control-Allow-Origin: *";
  k += "\r\nConnection: close\r\n\r\n";
  return k;
}

static void sendeJson(WiFiClient& c, int code, const String& body) {
  String alles = kopfBauen(code, "application/json; charset=utf-8", body.length());
  alles += body;
  c.write((const uint8_t*)alles.c_str(), alles.length());
}

static void sendeSeite(WiFiClient& c) {
  size_t laenge = strlen(SEITE);
  String kopf = kopfBauen(200, "text/html; charset=utf-8", (long)laenge);
  c.write((const uint8_t*)kopf.c_str(), kopf.length());
  const size_t HAPPEN = 1460;        // eine TCP-Nutzlast je Schreibvorgang
  for (size_t p = 0; p < laenge; p += HAPPEN) {
    size_t n = laenge - p;
    if (n > HAPPEN) n = HAPPEN;
    c.write((const uint8_t*)(SEITE + p), n);
    takten();          // zwoelf Kilobyte dauern - das Blinken laeuft weiter
  }
}

static void httpBedienen() {
  WiFiClient c = server.available();
  if (!c) return;

  // Kurze Frist: ohne sie wartet readStringUntil bis zu einer vollen Sekunde
  // auf einen Klienten, der nichts mehr schickt - und so lange stuende das
  // Blinken still.
  c.setTimeout(40);
  String zeile1 = c.readStringUntil('\n');
  takten();
  while (c.available()) {                      // Kopfzeilen verwerfen
    String z = c.readStringUntil('\n');
    if (z.length() <= 1) break;
  }
  takten();
  zeile1.trim();
  int l1 = zeile1.indexOf(' ');
  int l2 = zeile1.indexOf(' ', l1 + 1);
  if (l1 < 0 || l2 < 0) { c.stop(); return; }
  String methode = zeile1.substring(0, l1);
  String ziel = zeile1.substring(l1 + 1, l2);
  String pfad = ziel;
  int fz = pfad.indexOf('?');
  if (fz >= 0) pfad = pfad.substring(0, fz);

  bool geaendert = false;

  if (pfad == "/" || pfad == "/index.html") {
    sendeSeite(c);
  } else if (pfad == "/api/state") {
    sendeJson(c, 200, stateJson());
  } else if (pfad == "/api/live") {
    sendeJson(c, 200, liveJson());
  } else if (pfad == "/api/ping") {
    sendeJson(c, 200, "{\"ok\":true,\"name\":\"Signalsaeule\",\"typ\":\"saeule\"}");
  } else if (pfad == "/api/modus") {
    String m = argWert(ziel, "modus");
    if (m == "auto" || m == "manuell") {
      bool neu = (m == "auto");
      if (neu != autoModus) {
        if (neu) {
          autoModus = true;
          statusSetzen(status, true, true);     // Status noch einmal ansagen
        } else {
          // das laufende Bild einfrieren: sollAn() noch in Auto auswerten
          for (uint8_t s = 0; s < STUFEN; s++) manuell[s] = sollAn(s);
          autoModus = false;
        }
        bildSteht = false;
        geaendert = true;
      }
      sendeJson(c, 200, stateJson());
    } else {
      sendeJson(c, 400, "{\"ok\":false,\"fehler\":\"modus\"}");
    }
  } else if (pfad == "/api/status") {
    String id = argWert(ziel, "status");
    int8_t gefunden = -1;
    for (uint8_t i = 0; i < STATUS_ANZAHL; i++) if (id == STATUS_ID[i]) gefunden = (int8_t)i;
    if (gefunden < 0) {
      sendeJson(c, 400, "{\"ok\":false,\"fehler\":\"status\"}");
    } else {
      // Einen Status zu waehlen heisst, die Saeule soll ihn fahren
      bool warManuell = !autoModus || testAn;
      autoModus = true;
      testAn = false;
      statusSetzen((Status)gefunden, true, warManuell);
      geaendert = true;
      sendeJson(c, 200, stateJson());
    }
  } else if (pfad.startsWith("/api/relais/")) {
    int nr = pfad.substring(pfad.lastIndexOf('/') + 1).toInt();
    int8_t i = leuchteIndex(nr);
    if (i < 0) {
      sendeJson(c, 404, "{\"ok\":false,\"fehler\":\"nummer\"}");
    } else {
      bool an = wahr(argWert(ziel, "an"));
      if (LEUCHTEN[i].warn) {
        // Warnleuchte gilt in beiden Betriebsarten. Von Hand geschaltet gilt
        // das auch waehrend eines Alarms - der Alarm hat sie dann abgegeben.
        warnAn = an;
        warnVomAlarm = false;
      } else {
        if (autoModus) {                  // von Hand schalten heisst manuell
          for (uint8_t s = 0; s < STUFEN; s++) manuell[s] = sollAn(s);
          autoModus = false;
          bildSteht = false;
        }
        manuell[i] = an;
        testAn = false;
      }
      geaendert = true;
      sendeJson(c, 200, stateJson());
    }
  } else if (pfad == "/api/test") {
    bool an = wahr(argWert(ziel, "an"));
    if (an != testAn) {
      testAn = an;
      if (!an) { bildSteht = false; statusSetzen(status, false); }
      geaendert = true;
    }
    sendeJson(c, 200, stateJson());
  } else if (pfad == "/api/diagnose") {
    if (!diagLaeuft()) diagnoseStarten();
    sendeJson(c, 200, stateJson());
  } else if (pfad == "/api/alarm/stop") {
    testAn = false;
    warnAn = false;
    warnVomAlarm = false;
    autoModus = false;
    for (uint8_t s = 0; s < STUFEN; s++) manuell[s] = false;
    geaendert = true;
    sendeJson(c, 200, stateJson());
  } else {
    sendeJson(c, 404, "{\"ok\":false,\"fehler\":\"unbekannt\"}");
  }

  c.flush();
  c.stop();
  if (geaendert) merkenBald();
  (void)methode;
}

// ----------------------------------------------------------------- Ablauf

void setup() {
  // Erst den Ruhepegel schreiben, dann auf Ausgang stellen - sonst zucken die
  // Leuchten beim Booten einmal durch.
  for (uint8_t i = 0; i < ANZAHL; i++) {
    digitalWrite(LEUCHTEN[i].pin, LOW);
    pinMode(LEUCHTEN[i].pin, OUTPUT);
    digitalWrite(LEUCHTEN[i].pin, LOW);
    istAn[i] = false;
    manuell[i] = false;
  }

  Serial.begin(115200);
  matrix.begin();
  gedaechtnisLaden();            // Status von vor dem Stromausfall

  if (!taktgeberStarten()) Serial.println("Taktgeber laesst sich nicht starten");

  phase = PH_START;
  startSeit = millis();
  statusSeit = millis();
  wechselAktiv = false;
}

void loop() {
  schleifeBegann = millis();

  if (phase == PH_START) {
    startStellen();
    if (millis() - startSeit >= ST_ENDE) {
      for (uint8_t i = 0; i < ANZAHL; i++) setzen(i, false);
      phase = PH_WLAN;
    }
    return;
  }

  if (phase == PH_WLAN) {
    wlanVerbinden();
    // Startbild: das letzte Glied der Adresse, damit man sie am Geraet sieht
    if (WiFi.status() == WL_CONNECTED) matrixAdresse(WiFi.localIP()[3]);
    else                               matrixZahl("--");
    // Jetzt den Status wieder aufnehmen, der vor dem Stromausfall stand
    phase = PH_BETRIEB;
    matrixBild = 0xFF;
    statusSetzen(status, true);
    merkenJetzt();
    return;
  }

  if (WiFi.status() == WL_CONNECTED) {
    httpBedienen();
    ssePflegen();
  } else {
    static unsigned long letzterVersuch = 0;
    if (millis() - letzterVersuch > 20000) {
      letzterVersuch = millis();
      wlanVerbinden();
    }
  }

  if (diagLaeuft()) {
    diagnoseSchritt();
    matrixSpiegeln();
  } else {
    if (wechselAktiv && wechselZeit() >= wechselDauer() + RUHE_MS) wechselAktiv = false;
    takten();           // Alarmkopplung und Matrix; die Leuchten macht der Zeitgeber
  }

  if (merkenFaellig && millis() >= merkenFaellig) merkenJetzt();

  // laengster Durchlauf seit der letzten Abfrage - zeigt, ob etwas bremst
  uint32_t dauer = millis() - schleifeBegann;
  if (dauer > schleifeMax) schleifeMax = (uint16_t)dauer;
}
