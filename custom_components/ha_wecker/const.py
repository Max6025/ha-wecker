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
MUSTER_LISTE = ["dauer", "blinken", "langsam", "schnell", "doppelblitz", "dreifachblitz", "intervall", "takt5", "sos"]

# Weckerlampe: fester Ablauf ueber die Relais der Box und ein dimmbares
# Hauptlicht (siehe lampe.py). Relais-Nummern wie in der Bauweise "Lampen".
LAMPE_RELAIS_LAMPE = 1          # Lampe an GPIO 1 (mit gruener LED)
LAMPE_RELAIS_ROT = 3            # rote Leuchte
LAMPE_RELAIS_WARN = 4           # Blitz-Warnleuchte, braucht nur Dauer
CONF_HAUPTLICHT = "hauptlicht"              # light.<...>, dimmbar; leer = kein Hauptlicht
CONF_HAUPTLICHT_VON = "hauptlicht_von"      # Zeitfenster, in dem das Hauptlicht mitmacht
CONF_HAUPTLICHT_BIS = "hauptlicht_bis"
HAUPTLICHT_VON_STANDARD = "03:00:00"
HAUPTLICHT_BIS_STANDARD = "10:00:00"
LED_NACHT_VON = "20:00:00"       # RGB-LED der Box in Ruhe aus (Nachtruhe) ...
LED_NACHT_BIS = "08:00:00"       # ... bis dahin; die Integration setzt /api/led
TEST_LICHTBILD = {               # Schalter "Testmodus": Relais -> Muster, bis Stopp
    1: "dreifachblitz",
    3: "langsam",
    4: "intervall",
}
LAMPE_VORLAUF_S = 60          # so lange vor dem Weckruf geht es los
LAMPE_NACHLAUF_WARN_S = 5         # Warnleuchte nach dem Beenden
LAMPE_NACHLAUF_ROT_S = 300        # Rot schnell nach dem Beenden
LAMPE_NACHLAUF_LAMPE_S = 600      # Lampe blinkt nach dem Beenden; so lange auch Hauptlicht 50 %
LAMPE_NACHLAUF_LICHT_AUS_S = 30   # danach dimmt das Hauptlicht in dieser Zeit auf 0
LAMPE_NACHLAUF_WARN_NOCHMAL_S = 10  # ist das Hauptlicht aus, blitzt die Warnleuchte noch so lange
LAMPE_NACHLAUF_S = LAMPE_NACHLAUF_LAMPE_S + LAMPE_NACHLAUF_LICHT_AUS_S + LAMPE_NACHLAUF_WARN_NOCHMAL_S   # 640 s
LAMPE_KLINGELN_MAX_S = 600    # Hoechstdauer, falls die App nichts mehr meldet
