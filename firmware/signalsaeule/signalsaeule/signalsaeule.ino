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
    D3  K2 : IN1      H1  gruen   Stufe 1     Ader gelb
    D4  K2 : IN2      H2  orange  Stufe 2     Ader weiss
    D5  K2 : IN3      H3  rot     Stufe 3     Ader gelb
    D6  K2 : IN4      H4  Hinweis Stufe 4     Ader rot
                      Reserve (Ader schwarz) bleibt ungeschaltet

  Die Module ziehen bei HIGH durch (F5305S, P-Kanal, schaltet im Pluspfad).
  Kein Oeffner, kein Ruhestromprinzip - fehlt die Steuerung, ist alles dunkel.

  Betriebsart

    auto     ein Status treibt die Saeule. Jeder Wechsel wird angesagt
             (Aufbau, Abbau, Einrasten), danach steht das Bild des Status.
    manuell  jede Leuchte wird einzeln geschaltet und bleibt so stehen.

  Die Warnleuchte haengt an keiner Choreografie: sie hat einen eigenen
  Schalter und gilt in beiden Betriebsarten. Nur der Testmodus nimmt sie mit.

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

ArduinoLEDMatrix matrix;
WiFiServer server(80);
WiFiServer sseServer(SSE_PORT);

// --------------------------------------------------------------- Leuchten

static Leuchte LEUCHTEN[] = {
  {1, 3, "Gruen",       false},
  {2, 4, "Orange",      false},
  {3, 5, "Rot",         false},
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

static void statusSetzen(Status neu, bool ansage = true) {
  if (neu == status && ansage) return;
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

// USB: liegt Spannung am Stecker an, und redet ein Rechner mit uns?
static bool usbSpannung() { return R_USB_FS0->INTSTS0_b.VBSTS; }
static uint8_t usbZustand() { return R_USB_FS0->INTSTS0_b.DVSQ; }   // 0 nur Strom, >=2 enumeriert
static bool usbRechner()  { return usbZustand() >= 2; }
static bool usbMonitor()  { return (bool)Serial; }

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
    if (!usbSpannung())      strncpy(zeile, "kein USB - laeuft am Netzteil", sizeof(zeile));
    else if (!usbRechner())  strncpy(zeile, "nur Spannung, kein Rechner", sizeof(zeile));
    else if (!usbMonitor())  strncpy(zeile, "Rechner angesteckt, Port zu", sizeof(zeile));
    else                     strncpy(zeile, "Rechner angesteckt, Port offen", sizeof(zeile));
    diagEintrag("USB", -1, zeile);
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
    snprintf(zeile, sizeof(zeile), diagRueckmeldung ? "Pin D%u liest %d" : "Pin D%u gesetzt",
             LEUCHTEN[i].pin, pegel);
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
  statusSetzen(diagVorherStatus, false);
  sseSenden();
}

static bool diagLaeuft() { return diagSchritt >= 0; }

static bool diagAllesOk() {
  for (uint8_t i = 0; i < diagAnzahl; i++) if (diag[i].ok == 0) return false;
  return diagAnzahl > 0;
}

// ------------------------------------------------------------- Leuchtbild

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

static void matrixText(const char* text) {
  matrix.beginDraw();
  matrix.stroke(0xFFFFFFFF);
  matrix.textFont(Font_5x7);
  matrix.beginText(4, 1, 0xFFFFFF);
  matrix.println(text);
  matrix.endText();
  matrix.endDraw();
}

static void matrixLeeren() {
  matrix.beginDraw();
  matrix.clear();
  matrix.endDraw();
}

static void matrixVoll() {
  matrix.beginDraw();
  matrix.clear();
  matrix.noStroke();
  matrix.fill(0xFFFFFF);
  matrix.rect(0, 0, 12, 8);
  matrix.endDraw();
}

static void pfeilZeichnen(bool hoch) {
  matrix.beginDraw();
  matrix.clear();
  matrix.stroke(0xFFFFFFFF);
  matrix.noFill();
  matrix.line(6, 0, 6, 7);
  if (hoch) { matrix.line(6, 0, 3, 3); matrix.line(6, 0, 9, 3); }
  else      { matrix.line(6, 7, 3, 4); matrix.line(6, 7, 9, 4); }
  matrix.endDraw();
}

// Die Matrix hat 12x8 Punkte - fuer die Adresse reicht das letzte Glied.
// (Laufschrift braucht in dieser Bibliothek einen Animationspuffer, das waere
// fuer zwei Zahlen zu viel Aufwand.)
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

static void zustandsbildZeichnen() {
  if (!autoModus) { matrixText("M"); return; }
  switch (status) {
    case RUHE:     matrixLeeren();  break;
    case HINWEIS:  matrixText("i"); break;
    case ACHTUNG:  matrixText("!"); break;
    case STOERUNG: matrixText("X"); break;
    case ALARM:    matrixVoll();    break;
    default: break;
  }
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
  uint8_t s = (uint8_t)status, m = autoModus ? 1 : 0, w = warnAn ? 1 : 0;
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

static Phase phase = PH_START;
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
  s += ",\"phase\":\"" + String(phase == PH_BETRIEB ? "betrieb" : "start") + "\"";
  s += ",\"modus\":\"" + String(autoModus ? "auto" : "manuell") + "\"";
  s += ",\"status\":\"" + String(STATUS_ID[status]) + "\"";
  s += ",\"status_name\":" + jsonText(STATUS_NAME[status]);
  s += ",\"wechsel\":" + String(imWechsel() || inRuhephase() ? "true" : "false");
  s += ",\"warn\":" + String(warnAn ? "true" : "false");
  s += ",\"test\":" + String(testAn ? "true" : "false");
  s += ",\"usb\":{\"spannung\":" + String(usbSpannung() ? "true" : "false");
  s += ",\"rechner\":" + String(usbRechner() ? "true" : "false");
  s += ",\"monitor\":" + String(usbMonitor() ? "true" : "false") + "}";

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
  s += "]}";
  return s;
}

// --------------------------------------------------------- Ereignisstrom

static const uint8_t SSE_MAX = 3;
static WiFiClient sseKlienten[SSE_MAX];
static unsigned long sseLeben = 0;
static String letzteSignatur;

static void sseSenden() {
  String daten = "data: " + stateJson() + "\n\n";
  for (uint8_t i = 0; i < SSE_MAX; i++) {
    if (sseKlienten[i] && sseKlienten[i].connected())
      sseKlienten[i].print(daten);
  }
}

// Nur der logische Zustand loest einen Push aus - das Blinken selbst nicht,
// sonst flattert Home Assistant im Sekundentakt.
static String signatur() {
  String s;
  s += autoModus ? "A" : "M";
  s += String((int)status);
  s += warnAn ? "W" : "-";
  s += testAn ? "T" : "-";
  s += diagLaeuft() ? "D" : (diagFertig ? "F" : "-");
  s += phase == PH_BETRIEB ? "B" : "S";
  for (uint8_t i = 0; i < ANZAHL; i++) s += sollAn(i) ? "1" : "0";
  return s;
}

static void sseAnnehmen() {
  WiFiClient neu = sseServer.available();
  if (!neu) return;
  while (neu.available()) {
    String zeile = neu.readStringUntil('\n');
    if (zeile.length() <= 1) break;          // Ende der Kopfzeilen
  }
  neu.println("HTTP/1.1 200 OK");
  neu.println("Content-Type: text/event-stream");
  neu.println("Cache-Control: no-store");
  neu.println("Access-Control-Allow-Origin: *");
  neu.println("Connection: keep-alive");
  neu.println("retry: 3000");
  neu.println();
  neu.print("data: " + stateJson() + "\n\n");

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
  sseAnnehmen();
  String jetzt = signatur();
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

static void sendeKopf(WiFiClient& c, int code, const char* typ, long laenge) {
  c.print("HTTP/1.1 ");
  c.print(code);
  c.println(code == 200 ? " OK" : (code == 404 ? " Not Found" : " Bad Request"));
  c.print("Content-Type: ");
  c.println(typ);
  if (laenge >= 0) {
    c.print("Content-Length: ");
    c.println(laenge);
  }
  c.println("Cache-Control: no-store");
  c.println("Access-Control-Allow-Origin: *");
  c.println("Connection: close");
  c.println();
}

static void sendeJson(WiFiClient& c, int code, const String& body) {
  sendeKopf(c, code, "application/json; charset=utf-8", body.length());
  c.print(body);
}

static void sendeSeite(WiFiClient& c) {
  size_t laenge = strlen(SEITE);
  sendeKopf(c, 200, "text/html; charset=utf-8", (long)laenge);
  const size_t HAPPEN = 512;
  for (size_t p = 0; p < laenge; p += HAPPEN) {
    size_t n = laenge - p;
    if (n > HAPPEN) n = HAPPEN;
    c.write((const uint8_t*)(SEITE + p), n);
  }
}

static void httpBedienen() {
  WiFiClient c = server.available();
  if (!c) return;

  String zeile1 = c.readStringUntil('\n');
  while (c.available()) {                      // Kopfzeilen verwerfen
    String z = c.readStringUntil('\n');
    if (z.length() <= 1) break;
  }
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
        autoModus = neu;
        if (neu) statusSetzen(status, false);
        else for (uint8_t s = 0; s < STUFEN; s++) manuell[s] = sollAn(s);
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
      autoModus = true;
      testAn = false;
      statusSetzen((Status)gefunden);
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
        warnAn = an;                      // Warnleuchte gilt in beiden Betriebsarten
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

  phase = PH_START;
  startSeit = millis();
  statusSeit = millis();
  wechselAktiv = false;
}

void loop() {
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
    if (WiFi.status() == WL_CONNECTED) {
      matrixZahl(String(WiFi.localIP()[3]).c_str());
    } else {
      matrixZahl("--");
    }
    delay(2000);
    // Jetzt den Status wieder aufnehmen, der vor dem Stromausfall stand
    phase = PH_BETRIEB;
    bildSteht = false;
    pfeilSteht = false;
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
  } else {
    if (imWechsel()) {
      if (!pfeilSteht) { pfeilZeichnen(pfeilHoch); pfeilSteht = true; }
    } else if (!bildSteht) {
      zustandsbildZeichnen();
      bildSteht = true;
    }
    if (wechselAktiv && wechselZeit() >= wechselDauer() + RUHE_MS) wechselAktiv = false;
  }

  lampenStellen();

  if (merkenFaellig && millis() >= merkenFaellig) merkenJetzt();
}
