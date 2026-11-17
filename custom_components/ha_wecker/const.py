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
STATUS_STANDARD = "ruhe"
# Rolle eines Ausgangs in /api/state: "stufe" gehoert zur Saeule und folgt dem
# Status, "warn" ist die Blitz-Warnleuchte, "ton" der Tongeber - die beiden
# letzten haengen an keiner Choreografie und haben eigene Schalter.
ROLLE_STUFE = "stufe"
ROLLE_WARN = "warn"
ROLLE_TON = "ton"

# Garagen-ESP: schiebt jede Aenderung ueber den Ereignisstrom, Abfrage ist Rueckfallebene
GARAGE_ABFRAGE_S = 15

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
