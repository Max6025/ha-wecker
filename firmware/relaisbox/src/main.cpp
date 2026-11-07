// Relaisbox fuer HA Wecker - ESP32-S3-DevKitC-1 (zwei USB-C, RGB-LED)
//
// Die Box haengt im WLAN und bietet eine kleine HTTP-Schnittstelle, ueber die
// die Home-Assistant-Integration "HA Wecker" die Relais schaltet und
// Alarmmuster (Blinken, Doppelblitz ...) startet. Die Muster laufen auf dem
// ESP selbst, Home Assistant sagt nur "Muster X auf Relais Y, so lange".
//
// Pins
//   GPIO 42: dauerhaft HIGH, geht vor den Relais an
//   GPIO 38, 36, 35: Relais 1, 3, 4 (IN der Relaisplatine, aktiv HIGH)
//   GPIO 37: Relais 2, DEFEKT - bleibt dauerhaft LOW
//   GPIO 48: RGB-LED (Status: blau = WLAN sucht, gruen = verbunden, amber = Alarm)
//
// HTTP (Port 80)
//   GET  /                         Statusseite
//   GET  /api/state                Zustand als JSON
//   GET  /api/ping                 {"ok":true}
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

static const char* VERSION   = "1.0.1";
static const char* HOSTNAME  = "relaisbox";

static const int PIN_VERSORGUNG = 42;
static const bool RELAIS_AKTIV_LOW = false;   // Platine zieht bei HIGH an

struct Relais {
  int gpio;
  bool defekt;
};
// Nummern 1-4 wie auf der Platine; Relais 2 (GPIO 37) ist kaputt.
static Relais RELAIS[] = {
  {38, false},
  {37, true},
  {36, false},
  {35, false},
};
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

static void ausgang(size_t i, bool an) {
  if (RELAIS[i].defekt) an = false;
  lauf[i].an = an;
  digitalWrite(RELAIS[i].gpio, (an != RELAIS_AKTIV_LOW) ? HIGH : LOW);
}

static void musterStarten(size_t i, int m, uint32_t dauerS) {
  if (RELAIS[i].defekt) return;
  lauf[i].muster = m;
  lauf[i].pos = 0;
  lauf[i].schrittSeit = millis();
  lauf[i].endeMs = dauerS ? millis() + dauerS * 1000UL : 0;
  if (m == MUSTER_AUS) ausgang(i, false);
  else if (m == MUSTER_DAUER) ausgang(i, true);
  else ausgang(i, true);   // Muster beginnt mit "an"
}

static void musterStoppen(size_t i) {
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
      Serial.printf("Relais %u: Dauer abgelaufen, aus\n", (unsigned)(i + 1));
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

// --- LED --------------------------------------------------------------------

static void led(uint8_t r, uint8_t g, uint8_t b) { neopixelWrite(RGB_BUILTIN, r, g, b); }

static void ledTakt() {
  static uint32_t zuletzt = 0;
  static bool phase = false;
  uint32_t jetzt = millis();
  if (jetzt - zuletzt < 500) return;
  zuletzt = jetzt;
  phase = !phase;
  if (alarmAktiv())                      led(phase ? 60 : 10, phase ? 30 : 5, 0);   // amber pulsierend
  else if (WiFi.status() == WL_CONNECTED) led(0, 8, 0);                              // gruen leise
  else if (WiFi.getMode() & WIFI_AP)      led(phase ? 0 : 20, 0, phase ? 30 : 0);    // lila/blau: Einrichtung
  else                                    led(0, 0, phase ? 30 : 0);                  // blau blinkend: sucht
}

// --- WLAN -------------------------------------------------------------------

static Preferences prefs;
static WebServer server(80);
static String wifiSsid, wifiPass;
static bool apModus = false;
static uint32_t wifiVersuchSeit = 0;

static void wifiLaden() {
  prefs.begin("relaisbox", false);
  wifiSsid = prefs.getString("ssid", "");
  wifiPass = prefs.getString("pass", "");
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
  s += ",\"alarm\":" + String(alarmAktiv() ? "true" : "false");
  s += ",\"muster\":[";
  for (size_t i = 0; i < MUSTER_ANZAHL; i++) {
    if (i) s += ",";
    s += "\"" + String(MUSTER[i].name) + "\"";
  }
  s += "],\"relais\":[";
  uint32_t jetzt = millis();
  for (size_t i = 0; i < RELAIS_ANZAHL; i++) {
    if (i) s += ",";
    s += "{\"nr\":" + String(i + 1);
    s += ",\"gpio\":" + String(RELAIS[i].gpio);
    s += ",\"defekt\":" + String(RELAIS[i].defekt ? "true" : "false");
    s += ",\"an\":" + String(lauf[i].an ? "true" : "false");
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
      int nr = teil.toInt();
      if (nr < 1 || nr > (int)RELAIS_ANZAHL) return false;
      out.push_back(nr - 1);
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
  if (nr < 1 || nr > (int)RELAIS_ANZAHL) return sendeFehler(404, "unbekanntes Relais");
  size_t i = nr - 1;
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

static void handleAlarm() {
  std::vector<size_t> liste;
  if (!relaisListe(server.arg("relais"), true, liste)) return sendeFehler(400, "relais ungueltig");
  String mName = server.hasArg("muster") ? server.arg("muster") : "doppelblitz";
  int m = musterIndex(mName);
  if (m < 0) return sendeFehler(400, "muster unbekannt");
  uint32_t dauer = server.hasArg("dauer") ? (uint32_t)server.arg("dauer").toInt() : 0;
  for (size_t i : liste) musterStarten(i, m, dauer);
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
    h += "<tr><td>" + String(i + 1) + "</td><td>" + String(RELAIS[i].gpio) + "</td>";
    if (RELAIS[i].defekt) { h += "<td class=aus colspan=3>defekt, nicht benutzt</td></tr>"; continue; }
    h += "<td>" + String(lauf[i].an ? "AN" : "aus") + "</td><td>" + String(MUSTER[lauf[i].muster].name) + "</td><td>";
    h += "<button onclick=\"f('/api/relais/" + String(i + 1) + "?an=1')\">an</button>";
    h += "<button onclick=\"f('/api/relais/" + String(i + 1) + "?an=0')\">aus</button>";
    h += "<button onclick=\"f('/api/alarm?relais=" + String(i + 1) + "&muster=doppelblitz')\">Doppelblitz</button></td></tr>";
  }
  h += "</table><p><button onclick=\"f('/api/alarm?relais=alle&muster=blinken')\">alle blinken</button>"
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
  server.on("/api/wifi", HTTP_POST, handleWifi);
  server.onNotFound([]() {
    if (server.uri().startsWith("/api/relais/")) return handleRelais();
    sendeFehler(404, "nicht gefunden");
  });
  server.begin();
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
    pinMode(RELAIS[i].gpio, OUTPUT);
    ausgang(i, false);
  }
  pinMode(PIN_VERSORGUNG, OUTPUT);
  gpio_set_drive_capability((gpio_num_t)PIN_VERSORGUNG, GPIO_DRIVE_CAP_3);
  digitalWrite(PIN_VERSORGUNG, HIGH);

  Serial.begin(115200);
  delay(300);
  Serial.println();
  Serial.printf("Relaisbox %s bereit\n", VERSION);
  Serial.printf("GPIO %d dauerhaft AN; Relais an GPIO", PIN_VERSORGUNG);
  for (size_t i = 0; i < RELAIS_ANZAHL; i++)
    Serial.printf(" %d%s", RELAIS[i].gpio, RELAIS[i].defekt ? "(defekt)" : "");
  Serial.println();

  led(0, 0, 30);
  wifiLaden();
  wifiVerbinden();
  httpStarten();
}

void loop() {
  wifiTakt();
  server.handleClient();
  musterTakt();
  ledTakt();
  seriellTakt();
  delay(2);
}
