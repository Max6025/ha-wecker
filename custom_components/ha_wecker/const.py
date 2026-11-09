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
SIGNAL_WECKER_ALLE = DOMAIN + "_wecker_alle"     # irgendein Wecker hat sich gemeldet
SIGNAL_LAMPE = DOMAIN + "_lampe_{}"              # Weckerlampe einer Relaisbox

STORAGE_VERSION = 1

# Aktionen
SERVICE_ALARM_STARTEN = "alarm_starten"
SERVICE_ALARM_STOPPEN = "alarm_stoppen"
ATTR_MUSTER = "muster"
ATTR_DAUER = "dauer"

MUSTER_STANDARD = "doppelblitz"
MUSTER_LISTE = ["dauer", "blinken", "langsam", "schnell", "doppelblitz", "sos"]

# Weckerlampe: ein Relais der Box folgt dem Wecker der App (siehe lampe.py)
CONF_LAMPE_RELAIS = "lampe_relais"
CONF_LAMPE_MUSTER_VORLAUF = "lampe_muster_vorlauf"
CONF_LAMPE_MUSTER_NACHLAUF = "lampe_muster_nachlauf"
LAMPE_RELAIS_STANDARD = 1
LAMPE_MUSTER_VORLAUF_STANDARD = "blinken"
LAMPE_MUSTER_NACHLAUF_STANDARD = "doppelblitz"
LAMPE_VORLAUF_S = 60          # so lange vor dem Weckruf geht es los
LAMPE_NACHLAUF_S = 300        # so lange nach dem Beenden laeuft der Nachlauf
LAMPE_KLINGELN_MAX_S = 600    # Hoechstdauer, falls die App nichts mehr meldet
