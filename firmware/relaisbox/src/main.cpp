// Relaisbox fuer HA Wecker - ESP32-S3-DevKitC-1 (zwei USB-C, RGB-LED)
//
// Die Box haengt im WLAN und bietet eine kleine HTTP-Schnittstelle, ueber die
// die Home-Assistant-Integration "HA Wecker" die Relais schaltet und
// Alarmmuster (Blinken, Doppelblitz ...) startet. Die Muster laufen auf dem
// ESP selbst, Home Assistant sagt nur "Muster X auf Relais Y, so lange".
//
// Bauweise "Lampen" (env esp32s3-lampe, -DNUR_LAMPE): drei Ausgaenge fuer
// MOSFET-Module (F5305S, Plusleitung einer 12/24-V-Lampe), kein Taster, kein
// GPIO 42. Die HTTP-Schnittstelle bleibt dieselbe; die Relais heissen
// 1 Lampe (GPIO 1, die gruene LED haengt mit daran), 3 Rot (GPIO 40),
// 4 Warnleuchte (GPIO 41, blitzt von selbst, braucht Dauer). Nummer 2 ist
// seit 11.11. frei (Gruen war kurz an GPIO 2); die Nummern bleiben stabil,
// weil der Lampenplan in Home Assistant daran haengt. Die Namen stehen in
// /api/state als "name", Home Assistant benennt die Schalter danach.
//
// Pins
//   GPIO 42: dauerhaft HIGH, geht vor den Relais an
//   GPIO 4, 5, 6: Relais 1-3 (IN der Module, aktiv HIGH, VCC 3,3 V).
//            Linker Stecker, direkt hinter den beiden 3V3-Pins. Reine GPIOs:
//            keine Strapping-, PSRAM-, JTAG- oder USB-Funktion, beim Start still.
//   GPIO 7:  Eingang fuer einen Taster/Kontakt nach GND (INPUT_PULLUP,
//            LOW = gedrueckt), gleich daneben. Fuer ein 3,3-V-Signal
//            EINGANG_AKTIV_LOW auf false setzen. 30 ms entprellt.
//
//   NIE GPIO 33-37 benutzen: beim N16R8-Modul haengen die intern am
//   PSRAM-Chip. Relais daran klicken nur leise, statt zu schalten, und ein
//   Eingang dort liest ohne Taster HIGH. Das war am 07./08.11. der Grund fuer
//   das vermeintlich defekte Relais 2 (GPIO 37) und die schwachen Relais an
//   GPIO 35/36.
//   GPIO 48: RGB-LED (Status: blau = WLAN sucht, gruen = verbunden, amber = Alarm)
//
// HTTP (Port 80)
//   GET  /                         Statusseite
//   GET  /api/state                Zustand als JSON
//   GET  /api/ping                 {"ok":true}
//   GET  :8081/api/events          Ereignisstrom (Server-Sent Events): bei jeder
//                                  Aenderung sofort der komplette Zustand als JSON
//   POST /api/relais/<nr>?an=1|0   Relais schalten (beendet ein laufendes Muster)
//   POST /api/alarm?relais=1,3&muster=doppelblitz&dauer=0
//                                  Muster starten; dauer in Sekunden, 0 = bis Stopp
//                                  relais=alle fuer alle brauchbaren Relais
//   POST /api/alarm/stop?relais=   Muster beenden, Relais aus (ohne relais = alle)
//   POST /api/wifi?ssid=&pass=     WLAN-Zugang speichern und neu starten
//
// Muster: aus, dauer, blinken (1 s/1 s), langsam (2 s/2 s), schnell (250 ms),
//         doppelblitz (100/120/100/680 ms wie eine Brandmeldezentrale), sos

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include <Preferences.h>
#include <driver/gpio.h>
#include <esp_system.h>
#include <vector>

#ifndef WIFI_SSID
#define WIFI_SSID ""
#endif
#ifndef WIFI_PASS
#define WIFI_PASS ""
#endif
#ifndef RGB_BUILTIN
#define RGB_BUILTIN 48
#endif

static const char* VERSION   = "1.7.0";
static const char* HOSTNAME  = "relaisbox";

static const int PIN_VERSORGUNG = 42;
static const int PIN_EINGANG    = 7;
static const bool EINGANG_AKTIV_LOW = true;   // Taster nach GND: LOW = gedrueckt
static const uint32_t ENTPRELL_MS = 30;
static const uint16_t SSE_PORT = 8081;
// Ansteuerung der Relaismodule - zwei Bauweisen, Auswahl ueber platformio.ini:
//
//  Standard (env esp32s3): Modul auf HIGH-Trigger, VCC 3,3 V, Pin schaltet
//    aktiv HIGH/LOW (Gegentakt).
//  -DRELAIS_LOW_OPEN_DRAIN (env esp32s3-lowtrigger): Modul auf LOW-Trigger
//    mit VCC 5 V. Der Pin ist Open-Drain: "an" = Pin zieht nach GND,
//    "aus" = Pin hochohmig, das Modul zieht IN selbst auf seine 5 V. So sieht
//    ein 5-V-Modul sauberen 5-V-Pegel, obwohl der ESP nur 3,3 V kann.
#ifdef RELAIS_LOW_OPEN_DRAIN
static const bool RELAIS_AKTIV_LOW = true;
static const bool RELAIS_OPEN_DRAIN = true;
#else
static const bool RELAIS_AKTIV_LOW = false;   // Platine zieht bei HIGH an
static const bool RELAIS_OPEN_DRAIN = false;
#endif

struct Relais {
  int nr;      // Nummer wie auf der Platine (bleibt stabil, auch wenn eins fehlt)
  int gpio;
  bool defekt;
  const char* name;   // nullptr = "Relais <nr>"
};
#ifdef NUR_LAMPE
// GPIO 40/41 sind JTAG-Pins (MTDO/MTDI); frei, weil die Box ueber USB-JTAG
// laeuft. Keine PSRAM-Pins (33-37).
static Relais RELAIS[] = {
  {1, 1,  false, "Lampe"},        // plus gruene LED am selben Ausgang
  {3, 40, false, "Rot"},
  {4, 41, false, "Warnleuchte"},
};
#else
static Relais RELAIS[] = {
  {1, 4, false, nullptr},
  {2, 5, false, nullptr},
  {3, 6, false, nullptr},
};
#endif

// Index zu einer Platinennummer, -1 wenn es die nicht gibt
static int relaisIndex(int nr) {
  for (size_t i = 0; i < sizeof(RELAIS) / sizeof(RELAIS[0]); i++)
    if (RELAIS[i].nr == nr) return (int)i;
  return -1;
}
static const size_t RELAIS_ANZAHL = sizeof(RELAIS) / sizeof(RELAIS[0]);

// --- Muster ----------------------------------------------------------------

struct Muster {
  const char* name;
  const uint32_t* schritte;   // an, aus, an, aus ... in ms; leer = statisch
  size_t anzahl;
};

static const uint32_t M_BLINKEN[]     = {1000, 1000};
static const uint32_t M_LANGSAM[]     = {2000, 2000};
static const uint32_t M_SCHNELL[]     = {250, 250};
static const uint32_t M_DOPPELBLITZ[] = {100, 120, 100, 680};
static const uint32_t M_DREIFACHBLITZ[] = {60, 70, 60, 70, 60, 480};   // drei kurze Blitze wie ein Stroboskop, 0,8 s Takt
static const uint32_t M_INTERVALL[]     = {10000, 2000};   // 10 s an, 2 s wirklich aus (Blitzleuchte im Test schonen)
static const uint32_t M_TAKT5[]         = {100, 120, 100, 4680};   // Doppelblitz alle 5 s (Nachlauf der Weckerlampe)
static const uint32_t M_SOS[] = {200, 200, 200, 200, 200, 600,
                                 600, 200, 600, 200, 600, 600,
                                 200, 200, 200, 200, 200, 1400};

static const Muster MUSTER[] = {
  {"aus",         nullptr,       0},
  {"dauer",       nullptr,       0},
  {"blinken",     M_BLINKEN,     2},
  {"langsam",     M_LANGSAM,     2},
  {"schnell",     M_SCHNELL,     2},
  {"doppelblitz", M_DOPPELBLITZ, 4},
  {"dreifachblitz", M_DREIFACHBLITZ, 6},
  {"intervall",   M_INTERVALL,   2},
  {"takt5",       M_TAKT5,       4},
  {"sos",         M_SOS,         18},
};
static const size_t MUSTER_ANZAHL = sizeof(MUSTER) / sizeof(MUSTER[0]);
enum { MUSTER_AUS = 0, MUSTER_DAUER = 1 };

static int musterIndex(const String& name) {
  for (size_t i = 0; i < MUSTER_ANZAHL; i++)
    if (name.equalsIgnoreCase(MUSTER[i].name)) return (int)i;
  return -1;
}

// Laufzustand je Relais
struct Lauf {
  int muster = MUSTER_AUS;
  size_t pos = 0;
  uint32_t schrittSeit = 0;
  uint32_t endeMs = 0;        // 0 = ohne Ende
  bool an = false;            // aktueller Ausgangszustand
};
static Lauf lauf[RELAIS_ANZAHL];

static bool zustandGeaendert = false;   // fuer den Ereignisstrom

static void ausgang(size_t i, bool an) {
  if (RELAIS[i].defekt) an = false;
  if (lauf[i].an != an) zustandGeaendert = true;
  lauf[i].an = an;
  digitalWrite(RELAIS[i].gpio, (an != RELAIS_AKTIV_LOW) ? HIGH : LOW);
}

static void musterStarten(size_t i, int m, uint32_t dauerS) {
  if (RELAIS[i].defekt) return;
  if (lauf[i].muster != m) zustandGeaendert = true;
  lauf[i].muster = m;
  lauf[i].pos = 0;
  lauf[i].schrittSeit = millis();
  lauf[i].endeMs = dauerS ? millis() + dauerS * 1000UL : 0;
  if (m == MUSTER_AUS) ausgang(i, false);
  else if (m == MUSTER_DAUER) ausgang(i, true);
  else ausgang(i, true);   // Muster beginnt mit "an"
}

static void musterStoppen(size_t i) {
  if (lauf[i].muster != MUSTER_AUS) zustandGeaendert = true;
  lauf[i].muster = MUSTER_AUS;
  lauf[i].endeMs = 0;
  ausgang(i, false);
}

static bool alarmAktiv() {
  for (size_t i = 0; i < RELAIS_ANZAHL; i++)
    if (lauf[i].muster >= 2) return true;
  return false;
}

static void musterTakt() {
  uint32_t jetzt = millis();
  for (size_t i = 0; i < RELAIS_ANZAHL; i++) {
    Lauf& l = lauf[i];
    if (l.muster == MUSTER_AUS) continue;
    if (l.endeMs && (int32_t)(jetzt - l.endeMs) >= 0) {
      musterStoppen(i);
      Serial.printf("Relais %d: Dauer abgelaufen, aus\n", RELAIS[i].nr);
      continue;
    }
    if (l.muster == MUSTER_DAUER) continue;
    const Muster& m = MUSTER[l.muster];
    if (jetzt - l.schrittSeit >= m.schritte[l.pos]) {
      l.schrittSeit = jetzt;
      l.pos = (l.pos + 1) % m.anzahl;
      ausgang(i, (l.pos % 2) == 0);
    }
  }
}

// --- Startdiagnose -------------------------------------------------------------
//
// Zaehlt Starts und Brownouts (Versorgung eingebrochen) im Flash. Bricht der
// 3,3-V-Regler beim Anziehen mehrerer Relais ein, steht es hier.

static uint32_t startZaehler = 0;
static uint32_t brownoutZaehler = 0;
static const char* startGrund = "unbekannt";

static const char* resetGrundText(esp_reset_reason_t r) {
  switch (r) {
    case ESP_RST_POWERON:   return "Einschalten";
    case ESP_RST_SW:        return "Software";
    case ESP_RST_PANIC:     return "Absturz";
    case ESP_RST_INT_WDT:
    case ESP_RST_TASK_WDT:
    case ESP_RST_WDT:       return "Watchdog";
    case ESP_RST_BROWNOUT:  return "BROWNOUT (Versorgung eingebrochen)";
    case ESP_RST_DEEPSLEEP: return "Tiefschlaf";
    case ESP_RST_EXT:       return "Reset-Taste/USB";
    default:                return "unbekannt";
  }
}

// --- Eingang ------------------------------------------------------------------

static bool eingangAktiv = false;        // entprellter Zustand
static uint32_t eingangSeit = 0;         // millis() der letzten Aenderung
static uint32_t eingangZaehler = 0;      // wie oft "an" seit dem Start

static void eingangTakt() {
#ifndef NUR_LAMPE
  static bool rohAlt = false;
  static uint32_t rohSeit = 0;
  bool roh = (digitalRead(PIN_EINGANG) == HIGH) != EINGANG_AKTIV_LOW;
  uint32_t jetzt = millis();
  if (roh != rohAlt) {
    rohAlt = roh;
    rohSeit = jetzt;
  } else if (roh != eingangAktiv && jetzt - rohSeit >= ENTPRELL_MS) {
    eingangAktiv = roh;
    eingangSeit = jetzt;
    zustandGeaendert = true;
    if (eingangAktiv) eingangZaehler++;
    Serial.printf("Eingang GPIO %d: %s\n", PIN_EINGANG, eingangAktiv ? "AN" : "aus");
  }
#endif
}

// --- LED --------------------------------------------------------------------

static void led(uint8_t r, uint8_t g, uint8_t b) { neopixelWrite(RGB_BUILTIN, r, g, b); }

// Nachtruhe: Home Assistant setzt /api/led?dunkel=1 (etwa 20-8 Uhr), dann
// bleibt die RGB-LED aus, solange kein Muster laeuft. Die rote Betriebs-LED
// des DevKits haengt fest an 3,3 V, die kann keine Software ausschalten.
static bool ledDunkel = false;

static void ledTakt() {
  static uint32_t zuletzt = 0;
  static bool phase = false;
  uint32_t jetzt = millis();
  if (jetzt - zuletzt < 500) return;
  zuletzt = jetzt;
  phase = !phase;
  if (ledDunkel && !alarmAktiv())        led(0, 0, 0);                                // Nachtruhe
  else if (alarmAktiv())                 led(phase ? 60 : 10, phase ? 30 : 5, 0);   // amber pulsierend
  else if (WiFi.status() == WL_CONNECTED) led(0, 8, 0);                              // gruen leise
  else if (WiFi.getMode() & WIFI_AP)      led(phase ? 0 : 20, 0, phase ? 30 : 0);    // lila/blau: Einrichtung
  else                                    led(0, 0, phase ? 30 : 0);                  // blau blinkend: sucht
}

// --- WLAN -------------------------------------------------------------------

static Preferences prefs;
static WebServer server(80);
static WiFiServer sseServer(SSE_PORT);   // Ereignisstrom, siehe unten
static String wifiSsid, wifiPass;
static bool apModus = false;
static uint32_t wifiVersuchSeit = 0;

static void wifiLaden() {
  prefs.begin("relaisbox", false);
  wifiSsid = prefs.getString("ssid", "");
  wifiPass = prefs.getString("pass", "");
  ledDunkel = prefs.getBool("leddunkel", false);
  if (wifiSsid.isEmpty() && strlen(WIFI_SSID) > 0) {
    wifiSsid = WIFI_SSID;
    wifiPass = WIFI_PASS;
    prefs.putString("ssid", wifiSsid);
    prefs.putString("pass", wifiPass);
    Serial.println("WLAN-Zugang aus dem Build uebernommen");
  }
}

static void wifiSpeichern(const String& ssid, const String& pass) {
  prefs.putString("ssid", ssid);
  prefs.putString("pass", pass);
}

static void apStarten() {
  apModus = true;
  // Keine weiteren Verbindungsversuche: die wechseln den Kanal und lassen
  // den Zugangspunkt immer wieder verschwinden. Neuer Versuch erst nach
  // dem Speichern neuer Zugangsdaten (Neustart).
  WiFi.setAutoReconnect(false);
  WiFi.disconnect(false, false);
  delay(100);
  WiFi.mode(WIFI_AP);
  bool ok = WiFi.softAP("Relaisbox-Setup", nullptr, 1, 0, 4);
  delay(100);
  Serial.printf("Einrichtungs-WLAN 'Relaisbox-Setup' %s, Kanal 1, Seite: http://%s/\n",
                ok ? "offen" : "FEHLGESCHLAGEN", WiFi.softAPIP().toString().c_str());
}

static void wifiScan() {
  int n = WiFi.scanNetworks();
  Serial.printf("WLAN-Scan: %d Netze\n", n);
  for (int i = 0; i < n && i < 20; i++)
    Serial.printf("  %-24s %4d dBm  Kanal %2d  %s\n", WiFi.SSID(i).c_str(), WiFi.RSSI(i),
                  WiFi.channel(i), WiFi.encryptionType(i) == WIFI_AUTH_OPEN ? "offen" : "gesichert");
  WiFi.scanDelete();
}

static void wifiEreignis(WiFiEvent_t ev, WiFiEventInfo_t info) {
  if (ev == ARDUINO_EVENT_WIFI_STA_DISCONNECTED)
    Serial.printf("WLAN getrennt, Grund %d\n", (int)info.wifi_sta_disconnected.reason);
}

static void wifiVerbinden() {
  static bool ereignisDa = false;
  if (!ereignisDa) { WiFi.onEvent(wifiEreignis); ereignisDa = true; }
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(HOSTNAME);
  WiFi.setSleep(false);
  if (wifiSsid.isEmpty()) {
    Serial.println("Kein WLAN-Zugang gespeichert");
    if (!apModus) apStarten();
    return;
  }
  Serial.printf("WLAN %s ...\n", wifiSsid.c_str());
  WiFi.begin(wifiSsid.c_str(), wifiPass.c_str());
  wifiVersuchSeit = millis();
}

static void wifiTakt() {
  static bool warVerbunden = false;
  bool verbunden = WiFi.status() == WL_CONNECTED;
  if (verbunden && !warVerbunden) {
    Serial.printf("WLAN verbunden: %s  (http://%s.local/)\n",
                  WiFi.localIP().toString().c_str(), HOSTNAME);
    MDNS.end();
    if (MDNS.begin(HOSTNAME)) {
      MDNS.addService("http", "tcp", 80);
      MDNS.addService("ha-wecker", "tcp", 80);
      MDNS.addServiceTxt("ha-wecker", "tcp", "typ", "relaisbox");
      MDNS.addServiceTxt("ha-wecker", "tcp", "version", VERSION);
      MDNS.addServiceTxt("ha-wecker", "tcp", "events", String(SSE_PORT).c_str());
    }
  }
  if (!verbunden && warVerbunden) {
    Serial.println("WLAN getrennt");
    wifiVersuchSeit = millis();
  }
  warVerbunden = verbunden;

  static bool scanGemacht = false;
  if (!verbunden && !scanGemacht && millis() - wifiVersuchSeit > 12000) {
    scanGemacht = true;
    wifiScan();
    WiFi.begin(wifiSsid.c_str(), wifiPass.c_str());
  }
  // Nach 30 s ohne Verbindung auf das Einrichtungs-WLAN umschalten
  if (!verbunden && !apModus && !wifiSsid.isEmpty() && millis() - wifiVersuchSeit > 30000) {
    Serial.println("WLAN nicht erreichbar - Einrichtungs-WLAN wird geoeffnet");
    apStarten();
  }
  // Im AP-Modus alle 15 s melden, ob jemand verbunden ist
  static uint32_t apMeldung = 0;
  if (apModus && millis() - apMeldung > 15000) {
    apMeldung = millis();
    Serial.printf("Einrichtungs-WLAN: %d Gerät(e) verbunden, IP %s\n",
                  WiFi.softAPgetStationNum(), WiFi.softAPIP().toString().c_str());
  }
}

// --- HTTP -------------------------------------------------------------------

static String stateJson() {
  String s;
  s.reserve(600);
  s += "{\"name\":\"Relaisbox\",\"version\":\"" + String(VERSION) + "\"";
  s += ",\"mac\":\"" + WiFi.macAddress() + "\"";
  s += ",\"ip\":\"" + WiFi.localIP().toString() + "\"";
  s += ",\"rssi\":" + String(WiFi.RSSI());
  s += ",\"uptime_s\":" + String(millis() / 1000);
  s += ",\"events_port\":" + String(SSE_PORT);
  s += ",\"ansteuerung\":\"" + String(RELAIS_OPEN_DRAIN ? "low-trigger-open-drain" : "high-trigger") + "\"";
  s += ",\"start\":{\"grund\":\"" + String(startGrund) + "\"";
  s += ",\"starts\":" + String(startZaehler);
  s += ",\"brownouts\":" + String(brownoutZaehler) + "}";
  s += ",\"alarm\":" + String(alarmAktiv() ? "true" : "false");
  s += ",\"led_dunkel\":" + String(ledDunkel ? "true" : "false");
#ifndef NUR_LAMPE
  s += ",\"eingang\":{\"gpio\":" + String(PIN_EINGANG);
  s += ",\"aktiv\":" + String(eingangAktiv ? "true" : "false");
  s += ",\"seit_s\":" + String((millis() - eingangSeit) / 1000);
  s += ",\"zaehler\":" + String(eingangZaehler) + "}";
#endif
  s += ",\"muster\":[";
  for (size_t i = 0; i < MUSTER_ANZAHL; i++) {
    if (i) s += ",";
    s += "\"" + String(MUSTER[i].name) + "\"";
  }
  s += "],\"relais\":[";
  uint32_t jetzt = millis();
  for (size_t i = 0; i < RELAIS_ANZAHL; i++) {
    if (i) s += ",";
    s += "{\"nr\":" + String(RELAIS[i].nr);
    s += ",\"gpio\":" + String(RELAIS[i].gpio);
    if (RELAIS[i].name) s += ",\"name\":\"" + String(RELAIS[i].name) + "\"";
    s += ",\"defekt\":" + String(RELAIS[i].defekt ? "true" : "false");
    s += ",\"an\":" + String(lauf[i].an ? "true" : "false");
    s += ",\"pegel\":" + String(digitalRead(RELAIS[i].gpio));   // tatsaechlicher Pin, zur Fehlersuche
    s += ",\"muster\":\"" + String(MUSTER[lauf[i].muster].name) + "\"";
    long rest = lauf[i].endeMs ? (long)((int32_t)(lauf[i].endeMs - jetzt)) / 1000 : -1;
    if (rest < -1) rest = 0;
    s += ",\"rest_s\":" + String(rest);
    s += "}";
  }
  s += "]}";
  return s;
}

static void sendeJson(int code, const String& body) {
  server.sendHeader("Cache-Control", "no-store");
  server.send(code, "application/json", body);
}

static void sendeFehler(int code, const char* text) {
  sendeJson(code, String("{\"ok\":false,\"fehler\":\"") + text + "\"}");
}

// "1,3" oder "alle" -> Liste von Indizes (0-basiert), nur brauchbare Relais
static bool relaisListe(const String& arg, bool leerIstAlle, std::vector<size_t>& out) {
  out.clear();
  if (arg.isEmpty() ? leerIstAlle : arg.equalsIgnoreCase("alle")) {
    for (size_t i = 0; i < RELAIS_ANZAHL; i++) if (!RELAIS[i].defekt) out.push_back(i);
    return true;
  }
  if (arg.isEmpty()) return false;
  int start = 0;
  while (start <= (int)arg.length()) {
    int ende = arg.indexOf(',', start);
    if (ende < 0) ende = arg.length();
    String teil = arg.substring(start, ende);
    teil.trim();
    if (!teil.isEmpty()) {
      int idx = relaisIndex(teil.toInt());
      if (idx < 0) return false;
      out.push_back((size_t)idx);
    }
    start = ende + 1;
  }
  return !out.empty();
}

static bool wahr(const String& v) {
  return v == "1" || v.equalsIgnoreCase("true") || v.equalsIgnoreCase("on") || v.equalsIgnoreCase("an");
}

static void handleRelais() {
  // Pfad /api/relais/<nr>
  String pfad = server.uri();
  int nr = pfad.substring(pfad.lastIndexOf('/') + 1).toInt();
  int idx = relaisIndex(nr);
  if (idx < 0) return sendeFehler(404, "unbekanntes Relais");
  size_t i = (size_t)idx;
  if (server.method() == HTTP_GET) {
    return sendeJson(200, stateJson());
  }
  if (RELAIS[i].defekt) return sendeFehler(409, "Relais ist als defekt markiert");
  if (!server.hasArg("an")) return sendeFehler(400, "Parameter an fehlt");
  bool an = wahr(server.arg("an"));
  musterStarten(i, an ? MUSTER_DAUER : MUSTER_AUS, 0);
  Serial.printf("Relais %d: %s\n", nr, an ? "AN" : "aus");
  sendeJson(200, stateJson());
}

// POST /api/led?dunkel=1|0 - RGB-LED in Ruhe aus (Nachtruhe), bleibt gespeichert
static void handleLed() {
  if (!server.hasArg("dunkel")) return sendeFehler(400, "dunkel fehlt");
  bool neu = server.arg("dunkel") == "1" || server.arg("dunkel") == "true";
  if (neu != ledDunkel) {
    ledDunkel = neu;
    prefs.putBool("leddunkel", ledDunkel);
    zustandGeaendert = true;
    if (ledDunkel && !alarmAktiv()) led(0, 0, 0);
  }
  sendeJson(200, stateJson());
}

static void handleAlarm() {
  std::vector<size_t> liste;
  if (!relaisListe(server.arg("relais"), true, liste)) return sendeFehler(400, "relais ungueltig");
  String mName = server.hasArg("muster") ? server.arg("muster") : "doppelblitz";
  int m = musterIndex(mName);
  if (m < 0) return sendeFehler(400, "muster unbekannt");
  uint32_t dauer = server.hasArg("dauer") ? (uint32_t)server.arg("dauer").toInt() : 0;
  // Nacheinander statt gleichzeitig: drei Spulen auf einmal reissen den
  // 3,3-V-Regler eher in die Knie als drei im Abstand von 40 ms.
  bool erstes = true;
  for (size_t i : liste) {
    if (!erstes) delay(40);
    erstes = false;
    musterStarten(i, m, dauer);
  }
  Serial.printf("Alarm: Muster %s auf %u Relais, Dauer %lu s\n",
                MUSTER[m].name, (unsigned)liste.size(), (unsigned long)dauer);
  sendeJson(200, stateJson());
}

static void handleAlarmStop() {
  std::vector<size_t> liste;
  if (!relaisListe(server.arg("relais"), true, liste)) return sendeFehler(400, "relais ungueltig");
  for (size_t i : liste) musterStoppen(i);
  Serial.printf("Alarm gestoppt (%u Relais)\n", (unsigned)liste.size());
  sendeJson(200, stateJson());
}

static void handleWifi() {
  if (!server.hasArg("ssid")) return sendeFehler(400, "ssid fehlt");
  wifiSpeichern(server.arg("ssid"), server.arg("pass"));
  sendeJson(200, "{\"ok\":true,\"neustart\":true}");
  Serial.println("WLAN-Zugang gespeichert, Neustart");
  delay(300);
  ESP.restart();
}

static void handleStatusseite() {
  String h;
  h.reserve(2500);
  h += "<!doctype html><html lang=de><meta charset=utf-8><meta name=viewport content='width=device-width'>";
  h += "<title>Relaisbox</title><style>body{font-family:sans-serif;background:#0b0e13;color:#eee;margin:2em}"
       "h1{font-weight:300;color:#ffb23f}table{border-collapse:collapse}td,th{padding:.4em 1em;text-align:left;border-bottom:1px solid #333}"
       "button{background:#ffb23f;border:0;padding:.4em 1em;border-radius:4px;margin:.2em;cursor:pointer}"
       "input{padding:.4em;background:#1a1f28;color:#eee;border:1px solid #444}.aus{color:#888}</style>";
  h += "<h1>Relaisbox</h1>";
  h += "<p>Version " + String(VERSION) + " &middot; " + WiFi.localIP().toString() + " &middot; RSSI " + String(WiFi.RSSI()) + " dBm</p>";
  h += "<table><tr><th>Relais</th><th>GPIO</th><th>Zustand</th><th>Muster</th><th></th></tr>";
  for (size_t i = 0; i < RELAIS_ANZAHL; i++) {
    h += "<tr><td>" + String(RELAIS[i].nr);
    if (RELAIS[i].name) h += " " + String(RELAIS[i].name);
    h += "</td><td>" + String(RELAIS[i].gpio) + "</td>";
    if (RELAIS[i].defekt) { h += "<td class=aus colspan=3>defekt, nicht benutzt</td></tr>"; continue; }
    h += "<td>" + String(lauf[i].an ? "AN" : "aus") + "</td><td>" + String(MUSTER[lauf[i].muster].name) + "</td><td>";
    h += "<button onclick=\"f('/api/relais/" + String(RELAIS[i].nr) + "?an=1')\">an</button>";
    h += "<button onclick=\"f('/api/relais/" + String(RELAIS[i].nr) + "?an=0')\">aus</button>";
    h += "<button onclick=\"f('/api/alarm?relais=" + String(RELAIS[i].nr) + "&muster=doppelblitz')\">Doppelblitz</button></td></tr>";
  }
#ifndef NUR_LAMPE
  h += "</table><p>Eingang GPIO " + String(PIN_EINGANG) + ": <b>" + String(eingangAktiv ? "AN" : "aus") + "</b></p>";
#else
  h += "</table>";
#endif
  h += "<p>Start " + String(startZaehler) + " (" + String(startGrund) + "), Brownouts: <b>" + String(brownoutZaehler) + "</b></p>";
  h += "<p><button onclick=\"f('/api/alarm?relais=alle&muster=blinken')\">alle blinken</button>"
       "<button onclick=\"f('/api/alarm/stop')\">alles stopp</button></p>";
  if (apModus) h += "<p style='color:#ffb23f'>Einrichtungsmodus: WLAN-Zugang unten eintragen, die Box startet dann neu.</p>";
  h += "<h3>WLAN</h3><form method=post action='/api/wifi'>SSID <input name=ssid value='" + wifiSsid + "'> "
       "Kennwort <input name=pass type=password> <button>speichern &amp; neu starten</button></form>";
  h += "<p><a style='color:#ffb23f' href='/api/state'>/api/state</a></p>";
  h += "<script>function f(u){fetch(u,{method:'POST'}).then(()=>location.reload())}</script></html>";
  server.send(200, "text/html; charset=utf-8", h);
}

static void httpStarten() {
  server.on("/", HTTP_GET, handleStatusseite);
  server.on("/api/state", HTTP_GET, []() { sendeJson(200, stateJson()); });
  server.on("/api/ping", HTTP_GET, []() { sendeJson(200, "{\"ok\":true,\"name\":\"Relaisbox\"}"); });
  server.on("/api/alarm", HTTP_POST, handleAlarm);
  server.on("/api/alarm/stop", HTTP_POST, handleAlarmStop);
  server.on("/api/led", HTTP_POST, handleLed);
  server.on("/api/wifi", HTTP_POST, handleWifi);
  server.onNotFound([]() {
    if (server.uri().startsWith("/api/relais/")) return handleRelais();
    sendeFehler(404, "nicht gefunden");
  });
  server.begin();
  sseServer.begin();
  sseServer.setNoDelay(true);
}

// --- Ereignisstrom (Server-Sent Events) auf eigenem Port ---------------------
//
// Der normale WebServer kann keine Verbindung offen halten. Deshalb nimmt ein
// zweiter, einfacher Server Verbindungen an, antwortet mit einem SSE-Kopf und
// schickt bei jeder Aenderung sofort den kompletten Zustand. Alle 15 s ein
// Lebenszeichen, damit die Gegenseite einen Abbruch erkennt.

static const size_t SSE_MAX = 4;
static WiFiClient sseClients[SSE_MAX];
static uint32_t sseZuletzt = 0;

static void sseSenden(const String& daten) {
  String frame = "data: " + daten + "\n\n";
  for (size_t i = 0; i < SSE_MAX; i++) {
    if (!sseClients[i]) continue;
    if (!sseClients[i].connected()) { sseClients[i].stop(); continue; }
    sseClients[i].print(frame);
  }
  sseZuletzt = millis();
}

static void sseTakt() {
  // Neue Verbindungen annehmen
  WiFiClient neu = sseServer.accept();
  if (neu) {
    // Anfragezeile lesen (und verwerfen), hoechstens kurz warten
    uint32_t t0 = millis();
    while (neu.connected() && millis() - t0 < 500) {
      if (neu.available()) {
        String zeile = neu.readStringUntil('\n');
        if (zeile == "\r" || zeile.isEmpty()) break;
      } else {
        delay(1);
      }
    }
    size_t platz = SSE_MAX;
    for (size_t i = 0; i < SSE_MAX; i++)
      if (!sseClients[i] || !sseClients[i].connected()) { platz = i; break; }
    if (platz == SSE_MAX) {
      neu.print("HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\n\r\n");
      neu.stop();
    } else {
      neu.setNoDelay(true);
      neu.print("HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                "Cache-Control: no-store\r\nConnection: keep-alive\r\n"
                "Access-Control-Allow-Origin: *\r\n\r\n");
      neu.print("retry: 3000\n\n");
      neu.print("data: " + stateJson() + "\n\n");
      sseClients[platz] = neu;
      Serial.printf("Ereignisstrom: Abnehmer %u verbunden (%s)\n",
                    (unsigned)platz, neu.remoteIP().toString().c_str());
    }
  }

  if (zustandGeaendert) {
    zustandGeaendert = false;
    sseSenden(stateJson());
  } else if (millis() - sseZuletzt > 15000) {
    // Lebenszeichen (Kommentarzeile), haelt NAT und Gegenseite wach
    for (size_t i = 0; i < SSE_MAX; i++)
      if (sseClients[i] && sseClients[i].connected()) sseClients[i].print(": ping\n\n");
    sseZuletzt = millis();
  }
}

// --- Seriell: "wifi <ssid> <kennwort>", "state", "alarm", "stop" -----------

static void seriellTakt() {
  static String zeile;
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      zeile.trim();
      if (zeile.startsWith("wifi ")) {
        int sp = zeile.indexOf(' ', 5);
        String ssid = sp > 0 ? zeile.substring(5, sp) : zeile.substring(5);
        String pass = sp > 0 ? zeile.substring(sp + 1) : "";
        wifiSpeichern(ssid, pass);
        Serial.println("gespeichert, Neustart");
        delay(200);
        ESP.restart();
      } else if (zeile == "scan") {
        wifiScan();
      } else if (zeile == "state") {
        Serial.println(stateJson());
      } else if (zeile == "alarm") {
        for (size_t i = 0; i < RELAIS_ANZAHL; i++) musterStarten(i, musterIndex("doppelblitz"), 0);
      } else if (zeile == "stop") {
        for (size_t i = 0; i < RELAIS_ANZAHL; i++) musterStoppen(i);
      } else if (!zeile.isEmpty()) {
        Serial.println("Befehle: wifi <ssid> <kennwort> | scan | state | alarm | stop");
      }
      zeile = "";
    } else if (zeile.length() < 200) {
      zeile += c;
    }
  }
}

// --- Start ------------------------------------------------------------------

void setup() {
  for (size_t i = 0; i < RELAIS_ANZAHL; i++) {
    pinMode(RELAIS[i].gpio, RELAIS_OPEN_DRAIN ? OUTPUT_OPEN_DRAIN : OUTPUT);
    ausgang(i, false);
  }
#ifndef NUR_LAMPE
  pinMode(PIN_EINGANG, EINGANG_AKTIV_LOW ? INPUT_PULLUP : INPUT_PULLDOWN);
  pinMode(PIN_VERSORGUNG, OUTPUT);
  gpio_set_drive_capability((gpio_num_t)PIN_VERSORGUNG, GPIO_DRIVE_CAP_3);
  digitalWrite(PIN_VERSORGUNG, HIGH);
#endif

  Serial.begin(115200);
  delay(300);
  Serial.println();
  Serial.printf("Relaisbox %s bereit\n", VERSION);
  Serial.printf("Relais: %s-Trigger, %s\n", RELAIS_AKTIV_LOW ? "LOW" : "HIGH",
                RELAIS_OPEN_DRAIN ? "Open-Drain (5-V-Module)" : "Gegentakt 3,3 V");
#ifdef NUR_LAMPE
  Serial.print("Bauweise Lampen, kein Taster; Ausgaenge an GPIO");
#else
  Serial.printf("GPIO %d dauerhaft AN; Relais an GPIO", PIN_VERSORGUNG);
#endif
  for (size_t i = 0; i < RELAIS_ANZAHL; i++)
    Serial.printf(" %d%s", RELAIS[i].gpio, RELAIS[i].defekt ? "(defekt)" : "");
  Serial.println();
#ifndef NUR_LAMPE
  eingangAktiv = (digitalRead(PIN_EINGANG) == HIGH) != EINGANG_AKTIV_LOW;
  eingangSeit = millis();
  Serial.printf("Eingang GPIO %d beim Start: %s\n", PIN_EINGANG, eingangAktiv ? "AN" : "aus");
#endif

#ifdef LAMPEN_TEST
  // Test-Bauweise: das Weckruf-Lichtbild laeuft ab dem Einschalten dauernd,
  // auch ohne WLAN. Lampe (mit Gruen) Dreifachblitz, Rot langsam (2 s).
  // Die Warnleuchte bleibt hier aus (blendet beim Aufbauen); der Schalter
  // "Testmodus" in HA nimmt sie im Intervall mit.
  if (relaisIndex(1) >= 0) musterStarten(relaisIndex(1), musterIndex("dreifachblitz"), 0);
  if (relaisIndex(3) >= 0) musterStarten(relaisIndex(3), musterIndex("langsam"), 0);
  Serial.println("LAMPEN_TEST: Lichtbild laeuft dauernd");
#endif

  led(0, 0, 30);
  wifiLaden();   // oeffnet auch die Preferences
  {
    esp_reset_reason_t r = esp_reset_reason();
    startGrund = resetGrundText(r);
    startZaehler = prefs.getUInt("starts", 0) + 1;
    brownoutZaehler = prefs.getUInt("brownouts", 0) + (r == ESP_RST_BROWNOUT ? 1 : 0);
    prefs.putUInt("starts", startZaehler);
    prefs.putUInt("brownouts", brownoutZaehler);
    Serial.printf("Start %lu, Grund: %s, Brownouts bisher: %lu\n",
                  (unsigned long)startZaehler, startGrund, (unsigned long)brownoutZaehler);
  }
  wifiVerbinden();
  httpStarten();
}

void loop() {
  wifiTakt();
  server.handleClient();
  musterTakt();
  eingangTakt();
  if (WiFi.status() == WL_CONNECTED) sseTakt();
  ledTakt();
  seriellTakt();
  delay(2);
}
