"""Konstanten der HA-Wecker-Integration."""

DOMAIN = "ha_wecker"

# Geraetetyp eines Konfigurationseintrags
CONF_TYP = "typ"
TYP_WECKER = "wecker"
TYP_SAEULE = "saeule"
TYP_GARAGE = "garage"      # Garagen-ESP "VAN206 LS" an der Lichtschranke, siehe garage.py

# Signalsaeule (Arduino UNO R4 WiFi). Sie schiebt jede Aenderung ueber den
# Ereignisstrom, die Abfrage ist nur die Rueckfallebene.
CONF_HOST = "host"
SAEULE_ABFRAGE_S = 15
MODUS_AUTO = "auto"
MODUS_MANUELL = "manuell"
# Dritte Betriebsart, die es nur in Home Assistant gibt: die Saeule zeichnet
# die Ampel der Garage nach (siehe ampel.py). Am Geraet selbst steht sie
# dabei auf "manuell" - die Stufen werden einzeln gestellt.
MODUS_AMPEL = "ampel"
# Vierte Betriebsart, ebenfalls nur hier: die Saeule als Werkstattanzeige des
# 3D-Druckers (siehe drucker.py). Am Geraet steht sie dabei auf "manuell".
MODUS_DRUCKER = "drucker"
STATUS_STANDARD = "ruhe"
# Rolle eines Ausgangs in /api/state: "stufe" gehoert zur Saeule und folgt dem
# Status, "warn" ist die Blitz-Warnleuchte, "ton" der Tongeber - die beiden
# letzten haengen an keiner Choreografie und haben eigene Schalter.
ROLLE_STUFE = "stufe"
ROLLE_WARN = "warn"
ROLLE_TON = "ton"
# Farbe eines Ausgangs, wie die Saeule sie ab Firmware 1.3.0 meldet. Damit
# findet die Integration "rot", ohne die Relaisnummer zu kennen.
FARBE_GRUEN = "gruen"
FARBE_ORANGE = "orange"
FARBE_ROT = "rot"
FARBE_HINWEIS = "hinweis"

# Betriebsart "Ampel" (siehe ampel.py). Zeiten in Millisekunden, je Periode
# (halb an, halb aus).
# Die Zwischenphasen einer deutschen Ampel (Wechsellichtzeichen nach StVO),
# Zeiten nach RiLSA fuer 50 km/h: gruen -> gelb -> rot, rot -> rot+gelb ->
# gruen. Rot und Gelb zugleich ist das, was die deutsche Ampel von den
# meisten anderen unterscheidet.
AMPEL_GELB_MS = 3000             # Gelbzeit
AMPEL_ROT_GELB_MS = 1000         # Rot und Gelb zusammen
AMPEL_STEHT_MS = 1000            # so lange steht ein Vollbild beim Vorfahren

# Betriebsart "Drucker" (siehe drucker.py)
DRUCKER_VORLAUF_MS = 250         # je Lampe beim Selbsttest zur Eroeffnung
DRUCKER_ENDSPURT_MIN = 5.0       # ab hier ist der Druck im Endspurt
DRUCKER_ENDSPURT_PROZENT = 98    # ... oder ab diesem Fortschritt
DRUCKER_FERTIG_MAX_S = 900       # so lange ruft die Saeule zum Abholen
DRUCKER_WEG_MAX_S = 1800         # so lange gilt ein verschwundener Druck als Stoerung
DRUCKER_FEUCHT_AB = 4           # Feuchtigkeitsindex des AMS, ab dem es im Attribut steht
# Die Takte der Bildsprache (Periode in ms, halb an, halb aus). Getaktet wird
# in der Saeule (Firmware 1.15.0), hier stehen nur die Zahlen.
DRUCKER_WELLE_MS = 1800          # eine Welle hinauf (heizt) oder hinunter (kuehlt)
DRUCKER_WECHSEL_MS = 700         # zwei Lampen im Wechsel: die Maschine fahert hin und her
DRUCKER_EILIG_MS = 400           # schnelles Blinken: gleich soweit, oder Material laeuft
DRUCKER_RUF_MS = 600             # die Hinweisleuchte ruft: komm jetzt
DRUCKER_FEHLER_MS = 500          # rot blinkt: etwas stimmt nicht
DRUCKER_TUER_MS = 300            # rot hektisch: es laeuft, aber es steht offen
DRUCKER_STILL_MS = 1500          # langsamer Wechsel: keine Auskunft

# Garagen-ESP: schiebt jede Aenderung ueber den Ereignisstrom, Abfrage ist Rueckfallebene
GARAGE_ABFRAGE_S = 15

# Quittungston beim Umschalten auf die Betriebsart "Ampel". Das Muster steht
# in der Firmware der Saeule (ab 1.5.0: 400 ms Ton, 500 ms Pause, 800 ms Ton),
# nicht hier - Home Assistant ruft /api/piep ohne Angabe und bekommt damit,
# was am Geraet eingestellt ist.

SIGNAL_UPDATE = DOMAIN + "_update_{}"
SIGNAL_WECKER_ALLE = DOMAIN + "_wecker_alle"     # irgendein Wecker hat sich gemeldet
SIGNAL_ABLAUF = DOMAIN + "_ablauf_{}"            # Weckablauf eines Weckers

STORAGE_VERSION = 1

# Weckablauf (siehe ablauf.py): haengt am Wecker, steuert Hauptlicht und Saeule
CONF_HAUPTLICHT = "hauptlicht"          # dimmbare light-Entitaet; leer = keines
CONF_ABLAUF = "ablauf"                  # JSON mit Zeitbloecken; leer = Standardablauf

# Strom fuer die Saeule (siehe strom.py): schaltbare Steckdose, die kurz vor
# dem Weckruf angeht und abends wieder aus
CONF_STROM = "strom"                    # switch-Entitaet; leer = kein Schalten
CONF_STROMPLAN = "stromplan"            # JSON mit Vorlauf und Ausschaltzeiten
PROTOKOLL_MAX = 40                      # so viele Schritte bleiben sichtbar
PROBELAUF_VORLAUF_S = 60                # Probelauf: so lange bis zum "Klingeln"
PROBELAUF_KLINGELT_S = 30               # ... und so lange, bis er "beendet" wird
ABLAUF_MAX_S = 7200                     # Sicherheitsnetz: so lange wartet ein
                                        # Lauf hoechstens auf das Beenden
