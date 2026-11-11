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
MUSTER_LISTE = ["dauer", "blinken", "langsam", "schnell", "doppelblitz", "dreifachblitz", "intervall", "sos"]

# Weckerlampe: die Relais der Box folgen dem Wecker der App (siehe lampe.py).
# Je Relais ein Muster fuer "aktiv" (Vorlauf und Klingeln) und "nachlauf"
# (nach dem Beenden); "aus" heisst: dieses Relais macht in der Phase nichts.
CONF_LAMPE_PLAN = "lampe_plan"       # {"1": {"aktiv": "dreifachblitz", "nachlauf": "doppelblitz"}, ...}
LAMPE_AKTIV = "aktiv"
LAMPE_NACHLAUF = "nachlauf"
LAMPE_MUSTER_LISTE = ["aus", *MUSTER_LISTE]
LAMPE_PLAN_STANDARD: dict[int, dict[str, str]] = {
    1: {LAMPE_AKTIV: "dreifachblitz", LAMPE_NACHLAUF: "doppelblitz"},   # Lampe
    2: {LAMPE_AKTIV: "langsam", LAMPE_NACHLAUF: "aus"},                 # Gruen
    3: {LAMPE_AKTIV: "langsam", LAMPE_NACHLAUF: "aus"},                 # Rot
    4: {LAMPE_AKTIV: "dauer", LAMPE_NACHLAUF: "aus"},                   # Warnleuchte (blinkt selbst)
}
LAMPE_PLAN_SONST = {LAMPE_AKTIV: "aus", LAMPE_NACHLAUF: "aus"}           # weitere Relais
LAMPE_PLAN_FELDER = 4                # so viele Relais zeigt der Optionsdialog hoechstens
LAMPE_VORLAUF_S = 60          # so lange vor dem Weckruf geht es los
LAMPE_NACHLAUF_S = 300        # so lange nach dem Beenden laeuft der Nachlauf
LAMPE_KLINGELN_MAX_S = 600    # Hoechstdauer, falls die App nichts mehr meldet
