"""Konstanten der HA-Wecker-Integration."""

DOMAIN = "ha_wecker"

# Geraetetyp eines Konfigurationseintrags
CONF_TYP = "typ"
TYP_WECKER = "wecker"
TYP_RELAIS = "relais"

# Relaisbox (ESP32)
CONF_HOST = "host"
RELAIS_ABFRAGE_S = 10

SIGNAL_UPDATE = DOMAIN + "_update_{}"

STORAGE_VERSION = 1

# Aktionen
SERVICE_ALARM_STARTEN = "alarm_starten"
SERVICE_ALARM_STOPPEN = "alarm_stoppen"
ATTR_MUSTER = "muster"
ATTR_DAUER = "dauer"

MUSTER_STANDARD = "doppelblitz"
MUSTER_LISTE = ["dauer", "blinken", "langsam", "schnell", "doppelblitz", "sos"]
