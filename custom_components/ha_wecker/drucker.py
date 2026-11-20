"""Betriebsart "Drucker": die Signalsaeule als Werkstattanzeige des 3D-Druckers.

Ein vierter Platz im Schalter "Betriebsart", neben Auto, Manuell und Ampel.
Steht er auf Drucker, sagt die Saeule mit einem Blick, wie es dem Bambu Lab
im Zimmer geht - und zwar **nicht**, indem sie die Meldungen des Herstellers
weiterreicht. Die Integration urteilt selbst.

Das ist der ganze Zweck dieser Betriebsart. Die Bambu-Integration liefert
rund 70 Entitaeten je Drucker, und ihre Zustaende sind Maschinenbegriffe:
`print_status` kennt elf Werte, `stage` ueber achtzig - von
`heatbed_underside_foreign_object_detection` bis `paused_skipped_step`.
Davon ist fast nichts eine Information, auf die man aufsteht.

**Die Bildsprache ist eine Grammatik, keine Liste.** Max will nicht vierzehn
Bilder auswendig lernen, sondern hinsehen und es wissen (20.11.2026). Darum
sagt nicht jedes Bild fuer sich etwas, sondern vier Regeln sagen alles:

    Bewegung nach oben     der Drucker fahert hoch - er wird warm
    Bewegung nach unten    er fahert runter - er kuehlt ab
    gruen                  der Druck laeuft; hektisch heisst gleich fertig
    orange                 er arbeitet daneben, es kommt noch kein Kunststoff
    weiss oben             du bist gefragt; blinkt es, dann jetzt
    rot                    etwas stimmt nicht

Daraus ergeben sich die Bilder von selbst, und der eigene Arbeitsschritt ist
an der Art der Bewegung zu erkennen, nicht an einer Legende:

    ruht       nichts zu tun                      weiss oben, dauerhaft
    ruestet    arbeitet vor, ohne Naeheres        orange, dauerhaft
    heizt      Bett und Duese werden warm         Welle nach oben
    vermisst   Bett antasten, kalibrieren         gruen und orange im Wechsel
    material   Filament laden, spuelen, putzen    orange, schnell
    druckt     laeuft                             gruen, dauerhaft
    endspurt   gleich fertig                      gruen, schnell
    kuehlt     Nachlauf: Kammer und Duese kuehlen Welle nach unten
    fertig     liegt auf dem Bett, hol es         gruen und weiss, dauerhaft
    pause      von Hand angehalten                orange und weiss, dauerhaft
    eingriff   Material fehlt, Hand gebraucht     orange, weiss blinkt
    fehler     abgebrochen, Duese, Fehldruck      rot, blinkt
    tuer       Tuer offen, waehrend gedruckt wird gruen, rot blinkt hektisch
    weg        mitten im Druck verschwunden       rot und weiss, langsam im Wechsel

**Hier wird geblinkt, und zwar im Geraet.** Die Takte stehen in der Firmware
der Saeule: `/api/stufen` nimmt ab 1.15.0 je Lampe eine Periode und einen
Versatz, der Zeitgeber alle 10 ms haelt sie ein (siehe signalsaeule.ino). Ein
Takt aus Home Assistant ueber HTTP waere ein Zufallstakt - dieselbe
Begruendung wie in ampel.py, nur dass das Geraet es jetzt selbst kann. Der
Versatz ist das eigentliche Mittel: zwei Lampen um eine halbe Periode
versetzt blinken im Wechsel, drei um je ein Drittel laufen die Saeule hinauf
oder hinunter. Genau das macht aus "heizt" und "kuehlt" ein Bild, das man
nicht lernen muss - ein Thermometer, das steigt oder fahert.

**Ton gibt es nicht mehr.** Jeder Arbeitsschritt hat sein Licht, und damit ist
alles gesagt (Max, 20.11.2026). Nur das Umschalten auf die Betriebsart
quittiert der Tongeber einmal, wie bei der Ampel - das ist eine Bedienung,
keine Meldung des Druckers. Die Blitz-Warnleuchte bleibt immer aus: die
gehoert zum Alarm, nicht zum Druck.

**Was die Integration selbst entscheidet**, statt es durchzureichen:

- `print_status: pause` ist nicht gleich Pause. Ist der Grund in `stage` ein
  Materialproblem (`paused_filament_runout`, `paused_ams_lost`, warten auf
  Material), ist das `eingriff` - da hilft nur hingehen. Ist es ein
  Maschinenproblem (verstopfte Duese, erste Schicht misslungen,
  Temperaturfehler), ist das `fehler`. Hat sie der Nutzer selbst angehalten,
  ist es `pause`. Drei Lagen aus einem Wort.
- **Der Arbeitsschritt kommt aus `stage`,** nach Wortanfang sortiert statt
  nach Liste: ueber achtzig Werte gibt es, und Bambu nimmt morgen welche
  dazu. `heat`, `cool`, `calibrat`, `filament` - das traegt weiter als eine
  Aufzaehlung, die altert.
- **Der Nachlauf ist eigenes Licht, kein Endspurt.** Am Ende reinigt der
  Drucker die Kammerluft und kuehlt (`purifying_chamber_air`, `cooling`),
  waehrend der Fortschritt schon auf 100 steht. Vorher wurde daraus
  `endspurt` oder sogar wieder `ruestet` - am 20.11.2026 am laufenden Druck
  gesehen. Jetzt faehrt die Welle nach unten, und man sieht: er macht nur
  noch zu.
- **HMS-Meldungen machen kein Bild.** Der Drucker meldet darunter auch
  Bagatellen (ein offener AMS-Deckel, eine Kalibrierempfehlung); eine
  Signalsaeule, die davon rot wird, ist nach einer Woche Tapete. Sie stehen
  im Attribut `hms`, und sichtbar wird nur, was den Druck wirklich anhaelt:
  `print_error` oder ein abgebrochener Lauf.
- **Fertig ist erst abgeholt.** Der Drucker steht nach dem letzten Layer
  stundenlang auf `finish`. Die Saeule ruft darum hoechstens eine
  Viertelstunde (`DRUCKER_FERTIG_MAX_S`) - und hoert sofort auf, wenn die
  Gehaeusetuer aufgeht: wer das Teil holt, hat es gesehen. Danach `ruht`.
- **Offline ist meistens kein Fehler.** Ein ausgeschalteter Drucker ist
  `ruht`, kein Alarm. Verschwindet er dagegen, waehrend ein Druck lief, ist
  das `weg` - aber auch nur eine halbe Stunde (`DRUCKER_WEG_MAX_S`), danach
  war es wohl doch der Netzschalter.
- **Die Restzeit hat eine Einheit.** Die Bambu-Integration meldet sie in
  Stunden (0,58), nicht in Minuten. Hier wird `unit_of_measurement` gelesen
  und umgerechnet, statt eine Zahl zu glauben.

Beim Umschalten fahert die Saeule einmal von unten nach oben durch (gruen,
orange, rot, Hinweis, je 250 ms) - der Selbsttest einer Werkzeugmaschine beim
Einschalten. Danach steht, was gilt.

Die Entitaeten des Druckers werden **ueber den `translation_key` der
Bambu-Integration** gefunden (`print_status`, `stage`, ...), nicht ueber
Entitaets-IDs: die haengen an der Sprache von Home Assistant und am Namen,
den das Geraet gerade tragt. Die Lage wird neu bewertet, sobald sich eine
dieser Entitaeten aendert - kein Abfragetakt.

Beendet wird die Betriebsart von denselben vier Dingen wie die Ampel: ein
anderer Platz im Schalter, ein Status oder eine Stufe von Hand, der Knopf
"Alles aus", und die Saeule selbst, wenn sie abends vom Netz geht. Der
Weckruf hat Vorrang; waehrend er laeuft, ruht die Anzeige.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    DRUCKER_EILIG_MS,
    DRUCKER_ENDSPURT_MIN,
    DRUCKER_ENDSPURT_PROZENT,
    DRUCKER_FEHLER_MS,
    DRUCKER_FERTIG_MAX_S,
    DRUCKER_FEUCHT_AB,
    DRUCKER_RUF_MS,
    DRUCKER_STILL_MS,
    DRUCKER_TUER_MS,
    DRUCKER_VORLAUF_MS,
    DRUCKER_WECHSEL_MS,
    DRUCKER_WEG_MAX_S,
    DRUCKER_WELLE_MS,
    FARBE_GRUEN,
    FARBE_HINWEIS,
    FARBE_ORANGE,
    FARBE_ROT,
)

_LOGGER = logging.getLogger(__name__)

# Die Integration, deren Entitaeten gelesen werden
PLATTFORM = "bambu_lab"

# Was gebraucht wird, als translation_key der Bambu-Integration. Die
# Entitaets-IDs taugen nicht: die folgen der Sprache von Home Assistant und
# dem Namen, den das Geraet gerade trgt.
TK_STATUS = "print_status"
TK_STUFE = "stage"
TK_FORTSCHRITT = "print_progress"
TK_REST = "remaining_time"
TK_SCHICHT = "current_layer"
TK_SCHICHTEN = "total_layers"
TK_AUFGABE = "subtask_name"
TK_SLOT = "active_tray"
TK_ONLINE = "online"
TK_DRUCKFEHLER = "print_error"
TK_HMS = "hms_errors"
TK_TUER = "door_open"
TK_FILAMENT = "extruder_filament_state"
TK_FEUCHTE = "humidity_index"

# Ohne diese beiden ist keine Bewertung moeglich
TK_PFLICHT = (TK_STATUS,)
# Diese werden beobachtet (Aenderung = neu bewerten)
TK_ALLE = (
    TK_STATUS,
    TK_STUFE,
    TK_FORTSCHRITT,
    TK_REST,
    TK_SCHICHT,
    TK_SCHICHTEN,
    TK_AUFGABE,
    TK_SLOT,
    TK_ONLINE,
    TK_DRUCKFEHLER,
    TK_HMS,
    TK_TUER,
    TK_FILAMENT,
    TK_FEUCHTE,
)

# --- Die Lagen -------------------------------------------------------------

LAGE_RUHT = "ruht"
LAGE_RUESTET = "ruestet"
LAGE_HEIZT = "heizt"
LAGE_VERMISST = "vermisst"
LAGE_MATERIAL = "material"
LAGE_DRUCKT = "druckt"
LAGE_ENDSPURT = "endspurt"
LAGE_KUEHLT = "kuehlt"
LAGE_FERTIG = "fertig"
LAGE_PAUSE = "pause"
LAGE_EINGRIFF = "eingriff"
LAGE_FEHLER = "fehler"
LAGE_WEG = "weg"
LAGE_TUER = "tuer"

LAGE_ALLE = (
    LAGE_RUHT,
    LAGE_RUESTET,
    LAGE_HEIZT,
    LAGE_VERMISST,
    LAGE_MATERIAL,
    LAGE_DRUCKT,
    LAGE_ENDSPURT,
    LAGE_KUEHLT,
    LAGE_FERTIG,
    LAGE_PAUSE,
    LAGE_EINGRIFF,
    LAGE_FEHLER,
    LAGE_WEG,
    LAGE_TUER,
)

# Ein Bild ist je Lampe eine Periode und ein Versatz darin, beides in ms.
# Periode 0 heisst dauerhaft an. Getaktet wird in der Saeule (Firmware
# 1.15.0), hier steht nur, was sie tun soll.
Bild = dict[str, tuple[int, int]]


def dauer(*farben: str) -> Bild:
    """Diese Lampen brennen und stehen still."""
    return {farbe: (0, 0) for farbe in farben}


def blinkt(periode: int, *farben: str) -> Bild:
    """Diese Lampen blinken gemeinsam."""
    return {farbe: (periode, 0) for farbe in farben}


def wechsel(periode: int, erst: str, dann: str) -> Bild:
    """Zwei Lampen im Gegentakt - eine halbe Periode Versatz.

    Das liest sich als "hin und her", nicht als "Achtung": genau das, was eine
    Maschine tut, die etwas abtastet, und was eine Verbindung tut, die es
    nicht mehr gibt.
    """
    return {erst: (periode, 0), dann: (periode, periode // 2)}


def welle(periode: int, *farben: str) -> Bild:
    """Eine Bewegung durch die Saeule, in der Reihenfolge der Farben.

    Jede Lampe brennt eine halbe Periode, die naechste faengt ein Drittel
    spaeter an - zwei brennen also immer zugleich, und der Lichtschwerpunkt
    wandert. Die Saeule schaltet eine Lampe ein, solange
    `(t + versatz) % periode` in der ersten Haelfte liegt; sie faengt also bei
    `periode - versatz` an. Darum geht der Versatz nach hinten (`-i`): so
    leuchten die Farben in der Reihenfolge auf, in der sie hier stehen.
    """
    n = len(farben)
    return {
        farbe: (periode, (-i * periode // n) % periode)
        for i, farbe in enumerate(farben)
    }


# Die Bilder. Jedes ist eindeutig, und keines muss man lernen - die vier
# Regeln im Kopf dieser Datei geben sie her.
DRUCKER_BILD: dict[str, Bild] = {
    # Nichts zu tun. Die Hinweisleuchte allein ist das Grundbild der Saeule.
    LAGE_RUHT: dauer(FARBE_HINWEIS),
    # Er arbeitet vor, und `stage` sagt nicht, woran: orange, stehend.
    LAGE_RUESTET: dauer(FARBE_ORANGE),
    # Er wird warm: die Welle steigt wie ein Thermometer.
    LAGE_HEIZT: welle(DRUCKER_WELLE_MS, FARBE_GRUEN, FARBE_ORANGE, FARBE_ROT),
    # Er tastet das Bett ab und fahert hin und her - das Bild tut es auch.
    LAGE_VERMISST: wechsel(DRUCKER_WECHSEL_MS, FARBE_GRUEN, FARBE_ORANGE),
    # Material laeuft durch: orange, schnell.
    LAGE_MATERIAL: blinkt(DRUCKER_EILIG_MS, FARBE_ORANGE),
    # Es druckt.
    LAGE_DRUCKT: dauer(FARBE_GRUEN),
    # Gleich fertig: dasselbe Gruen, nur hektisch.
    LAGE_ENDSPURT: blinkt(DRUCKER_EILIG_MS, FARBE_GRUEN),
    # Nachlauf: dieselbe Welle wie beim Heizen, nur abwaerts.
    LAGE_KUEHLT: welle(DRUCKER_WELLE_MS, FARBE_ROT, FARBE_ORANGE, FARBE_GRUEN),
    # Fertig, hol es: gruen (gut gegangen) und weiss (du bist dran).
    LAGE_FERTIG: dauer(FARBE_GRUEN, FARBE_HINWEIS),
    # Von Hand angehalten: es steht, und es steht an dir.
    LAGE_PAUSE: dauer(FARBE_ORANGE, FARBE_HINWEIS),
    # Material fehlt: dieselben Farben wie die Pause, aber oben blinkt es -
    # "komm jetzt" statt "es wartet".
    LAGE_EINGRIFF: {**dauer(FARBE_ORANGE), **blinkt(DRUCKER_RUF_MS, FARBE_HINWEIS)},
    # Gestoert: rot, blinkend. Nichts sonst brennt dabei.
    LAGE_FEHLER: blinkt(DRUCKER_FEHLER_MS, FARBE_ROT),
    # Tuer offen beim Drucken: gruen bleibt stehen, weil der Druck laeuft, und
    # rot blinkt hektisch dazu (Max, 20.11.2026).
    LAGE_TUER: {**dauer(FARBE_GRUEN), **blinkt(DRUCKER_TUER_MS, FARBE_ROT)},
    # Keine Auskunft: rot und weiss im langsamen Wechsel - unruhig, aber ohne
    # Eile, so wie die Lage selbst.
    LAGE_WEG: wechsel(DRUCKER_STILL_MS, FARBE_ROT, FARBE_HINWEIS),
}

LAGE_TEXT: dict[str, str] = {
    LAGE_RUHT: "Drucker ruht",
    LAGE_RUESTET: "Drucker rüstet",
    LAGE_HEIZT: "heizt auf",
    LAGE_VERMISST: "vermisst das Bett",
    LAGE_MATERIAL: "Material läuft",
    LAGE_DRUCKT: "Druck läuft",
    LAGE_ENDSPURT: "Druck fast fertig",
    LAGE_KUEHLT: "kühlt ab",
    LAGE_FERTIG: "fertig, zum Abholen",
    LAGE_PAUSE: "von Hand angehalten",
    LAGE_EINGRIFF: "Eingriff nötig",
    LAGE_FEHLER: "Druck gestört",
    LAGE_WEG: "mitten im Druck verschwunden",
    LAGE_TUER: "Tür offen beim Drucken",
}

# Bei diesen Lagen ist ein Druck unterwegs - verschwindet der Drucker dabei,
# ist das `weg` und nicht einfach ein ausgeschaltetes Geraet.
LAGE_IM_LAUF = (
    LAGE_RUESTET,
    LAGE_HEIZT,
    LAGE_VERMISST,
    LAGE_MATERIAL,
    LAGE_DRUCKT,
    LAGE_ENDSPURT,
    LAGE_KUEHLT,
    LAGE_PAUSE,
    LAGE_EINGRIFF,
    LAGE_TUER,
)

# --- Wie aus den Begriffen des Druckers eine Lage wird ---------------------

# `print_status` der Bambu-Integration
STATUS_LAEUFT = "running"
STATUS_PAUSE = "pause"
STATUS_FERTIG = "finish"
STATUS_FEHLER = "failed"
STATUS_RUESTET = ("prepare", "slicing", "init")
STATUS_RUHT = ("idle",)
STATUS_WEG = ("offline", "unknown")

# `stage`: ein Maschinenproblem. Hier haelt der Druck, und zwar nicht, weil
# etwas fehlt, sondern weil etwas nicht stimmt - das ist `fehler`.
STUFE_FEHLER = frozenset(
    {
        "paused_nozzle_clog",
        "paused_first_layer_error",
        "paused_cutter_error",
        "paused_nozzle_temperature_malfunction",
        "paused_heat_bed_temperature_malfunction",
        "paused_chamber_temperature_control_error",
        "paused_front_cover_falling",
        "paused_low_fan_speed_heat_break",
        "paused_skipped_step",
        "paused_nozzle_filament_covered_detected",
    }
)

# `stage`: es fehlt Material oder eine Hand - `eingriff`
STUFE_EINGRIFF = frozenset(
    {
        "paused_filament_runout",
        "paused_ams_lost",
        "paused_user_gcode",
        "m400_pause",
        "check_material",
        "check_material_position",
        "check_door_and_cover",
        "check_quick_release",
        "check_plaform",          # so schreibt die Bambu-Integration es
    }
)

# `stage`: der Nutzer selbst
STUFE_PAUSE = frozenset({"paused_user"})

# `stage`: der Drucker arbeitet, aber es kommt noch kein Kunststoff aufs Bett.
# Ueber achtzig Werte gibt es; nach Wortanfang zu pruefen ist kuerzer und
# faengt auch die, die Bambu erst morgen dazunimmt. Die Reihenfolge der
# Gruppen ist die Rangfolge in `_arbeitsschritt`.

# Der Nachlauf am Ende eines Drucks: die Kammerluft wird gereinigt, Duese und
# Bett kuehlen. Das ist Max' Beispiel fuer einen Schritt, der sein eigenes
# Licht braucht - man soll sehen, dass nur noch zugemacht wird (20.11.2026).
STUFE_KUEHLEN_ANFANG = (
    "cool",
    "purifying",
    "chamber_air",
)

# Material in Bewegung: laden, entladen, spuelen, Duese putzen
STUFE_MATERIAL_ANFANG = (
    "filament",
    "changing_filament",
    "pre_extrusion",
    "purging",
    "purge",
    "extrud",
    "feeding",
    "cleaning",
    "cutting",
    "retract",
)

# Antasten und Nachmessen: das Bett, die Duese, die Mechanik
STUFE_VERMESSEN_ANFANG = (
    "calibrat",
    "bed_level",
    "auto_bed_level",
    "homing",
    "scanning",
    "inspecting",
    "identifying",
    "measuring",
    "sweeping",
    "vibration",
    "motor_noise",
    "absolute_accuracy",
    "laser",
    "build_plate",
    "print_calibration",
    "check_absolute",
    "check_birdeye",
    "nozzle_offset",
    "active_arc",
)

# Warm werden
STUFE_HEIZEN_ANFANG = (
    "heat",
    "preheat",
    "thermal",
    "hotend",
)

# Alles andere, was Arbeit ist, aber nicht Drucken - ohne Naeheres
STUFE_RUESTEN_ANFANG = (
    "prepar",
    "moving",
    "waiting",
    "slicing",
    "init",
)

# Ein `stage`, der gar kein Arbeitsschritt ist
STUFE_KEINE = frozenset({"", "idle", "printing", "unknown", "offline", "none"})


def zahl(wert: Any) -> float | None:
    """Einen Zustandswert als Zahl lesen; None bei unknown/unavailable/Text."""
    try:
        return float(wert)
    except (TypeError, ValueError):
        return None


def minuten(wert: Any, einheit: str | None) -> float | None:
    """Eine Dauer in Minuten, egal in welcher Einheit sie gemeldet wird.

    Die Bambu-Integration meldet die Restzeit in **Stunden** (`h`), nicht in
    Minuten - 0,58 heisst 35 Minuten. Wer die Zahl ungelesen nimmt, haelt
    jeden Druck fuer fast fertig.
    """
    z = zahl(wert)
    if z is None:
        return None
    if einheit in ("h", "hours"):
        return z * 60
    if einheit in ("s", "sec", "seconds"):
        return z / 60
    return z


class Druckermodus:
    """Haelt die Betriebsart "Drucker" fuer eine Signalsaeule."""

    def __init__(self, hass: HomeAssistant, coordinator: Any) -> None:
        self.hass = hass
        self.saeule = coordinator
        self.aktiv = False
        self.pausiert = False          # der Weckablauf hat die Saeule
        self.fehler: str | None = None
        self._bild: Bild | None = None             # was zuletzt gestellt wurde
        self._lage: str | None = None              # und zu welcher Lage
        self._folge: asyncio.Task | None = None    # laufender Selbsttest
        self._ab_zustand: Any = None               # Abmelder der Zustandswache
        self._ab_saeule: Any = None                # Abmelder des Saeulen-Listeners
        self._beobachtet: tuple[str, ...] = ()
        # Was die Saeule sich merken muss, weil der Drucker es nicht sagt
        self._fertig_seit: Any = None    # wann `finish` angefangen hat
        self._abgeholt = False           # Tuer war auf, oder die Zeit ist um
        self._tuer_war_zu = True
        self._lauf_seit: Any = None      # wann der Drucker zuletzt im Lauf war

    # --- Die Entitaeten des Druckers ----------------------------------

    def entitaeten(self) -> dict[str, list[str]]:
        """Die Entitaeten der Bambu-Integration, nach translation_key.

        Ueber die Registry, nicht ueber Entitaets-IDs: die haengen an der
        Sprache von Home Assistant und am Namen des Geraets. Mehrere Treffer
        je Schluessel sind normal (ein AMS je Fach meldet seine Feuchte).
        """
        registry = er.async_get(self.hass)
        gefunden: dict[str, list[str]] = {}
        for eintrag in registry.entities.values():
            if eintrag.platform != PLATTFORM or eintrag.disabled_by is not None:
                continue
            tk = eintrag.translation_key
            if tk in TK_ALLE:
                gefunden.setdefault(tk, []).append(eintrag.entity_id)
        return gefunden

    @property
    def vorhanden(self) -> bool:
        """Gibt es ueberhaupt einen Drucker in Home Assistant?"""
        gefunden = self.entitaeten()
        return all(gefunden.get(tk) for tk in TK_PFLICHT)

    def _wert(self, tk: str) -> str | None:
        """Der Zustand der ersten Entitaet zu diesem Schluessel."""
        for eid in self.entitaeten().get(tk, []):
            st = self.hass.states.get(eid)
            if st is None or st.state in ("unknown", "unavailable", ""):
                continue
            return str(st.state)
        return None

    def _einheit(self, tk: str) -> str | None:
        for eid in self.entitaeten().get(tk, []):
            st = self.hass.states.get(eid)
            if st is not None:
                return st.attributes.get("unit_of_measurement")
        return None

    def _ja(self, tk: str) -> bool | None:
        """Ein binaerer Wert: True/False, oder None wenn er nichts sagt."""
        wert = self._wert(tk)
        if wert is None:
            return None
        return wert == "on"

    def _hoechste(self, tk: str) -> float | None:
        """Der hoechste Zahlenwert ueber alle Entitaeten (mehrere AMS)."""
        werte = [
            zahl(st.state)
            for eid in self.entitaeten().get(tk, [])
            if (st := self.hass.states.get(eid)) is not None
        ]
        echte = [w for w in werte if w is not None]
        return max(echte) if echte else None

    # --- Das Urteil ---------------------------------------------------

    @property
    def rest_min(self) -> float | None:
        return minuten(self._wert(TK_REST), self._einheit(TK_REST))

    @property
    def lage(self) -> str:
        """Was die Saeule zeigen soll - aus eigener Bewertung.

        Die Reihenfolge ist die Rangfolge: ein Maschinenproblem schlaegt ein
        Materialproblem, das schlaegt eine Pause von Hand, und erst danach
        kommt der normale Lauf.
        """
        status = self._wert(TK_STATUS)
        stufe = (self._wert(TK_STUFE) or "").strip()
        online = self._ja(TK_ONLINE)

        # Ist der Drucker gar nicht da? Meistens steht er einfach aus. Nur
        # wenn gerade ein Druck lief, ist das eine Stoerung - und auch die
        # nur eine halbe Stunde lang, danach war es doch der Netzschalter.
        weg = online is False or status is None or status in STATUS_WEG
        if weg:
            return LAGE_WEG if self._im_lauf_verschwunden() else LAGE_RUHT

        # Ein Maschinenproblem: der Druck ist hin oder haengt an der Technik
        if status == STATUS_FEHLER or stufe in STUFE_FEHLER:
            return LAGE_FEHLER
        if self._ja(TK_DRUCKFEHLER):
            return LAGE_FEHLER

        # Es fehlt Material oder eine Hand
        if stufe in STUFE_EINGRIFF:
            return LAGE_EINGRIFF
        if status == STATUS_PAUSE:
            # Pause ohne genannten Grund: von Hand. Mit Grund hat ihn schon
            # eine der Mengen oben gefangen.
            if stufe in STUFE_PAUSE or not stufe or stufe == "unknown":
                return LAGE_PAUSE
            return LAGE_EINGRIFF
        # Laeuft der Druck und es ist kein Filament in der Duese, wartet er
        # auf Material - auch wenn der Drucker das noch nicht Pause nennt.
        if status == STATUS_LAEUFT and self._ja(TK_FILAMENT) is False:
            return LAGE_EINGRIFF

        # Fertig - aber nur, solange das Teil noch keiner geholt hat
        if status == STATUS_FERTIG:
            return LAGE_RUHT if self._abgeholt else LAGE_FERTIG

        if status == STATUS_LAEUFT:
            # Die offene Tuer geht vor allem anderen, was der Lauf zu melden
            # hat: der Druck geht weiter, aber es steht etwas offen - Zugluft,
            # und bei einem geschlossenen Drucker auch Temperatur.
            if self._ja(TK_TUER):
                return LAGE_TUER
            schritt = self._arbeitsschritt(stufe)
            # Der Nachlauf geht vor dem Endspurt, und der Endspurt vor allen
            # anderen Arbeitsschritten. Sonst wird aus dem Zumachen am Ende
            # eines Drucks wieder "ruestet", und die Saeule faellt bei 100 %
            # auf orange zurueck - am 20.11.2026 am laufenden Druck gesehen:
            # stage `purifying_chamber_air` bei 465/465 Schichten.
            if schritt == LAGE_KUEHLT:
                return LAGE_KUEHLT
            if self._endspurt():
                return LAGE_ENDSPURT
            if schritt is not None:
                return schritt
            return LAGE_DRUCKT

        if status in STATUS_RUESTET:
            return self._arbeitsschritt(stufe) or LAGE_RUESTET
        schritt = self._arbeitsschritt(stufe)
        if schritt is not None:
            return schritt
        return LAGE_RUHT

    @staticmethod
    def _arbeitsschritt(stufe: str) -> str | None:
        """Welcher Arbeitsschritt steckt in diesem `stage`? None = keiner.

        Nach Wortanfang, nicht nach Liste: `stage` hat ueber achtzig Werte und
        bekommt laufend neue. `heatbed_preheating` faengt mit "heat" an und ist
        damit auf immer richtig einsortiert, ohne dass es hier stehen muss.
        """
        stufe = (stufe or "").strip().lower()
        if stufe in STUFE_KEINE:
            return None
        if stufe.startswith(STUFE_KUEHLEN_ANFANG):
            return LAGE_KUEHLT
        if stufe.startswith(STUFE_MATERIAL_ANFANG):
            return LAGE_MATERIAL
        if stufe.startswith(STUFE_VERMESSEN_ANFANG):
            return LAGE_VERMISST
        if stufe.startswith(STUFE_HEIZEN_ANFANG):
            return LAGE_HEIZT
        if stufe.startswith(STUFE_RUESTEN_ANFANG):
            return LAGE_RUESTET
        return None

    def _endspurt(self) -> bool:
        """Ist der Druck so weit, dass es sich lohnt, hochzugehen?

        **Eine Restzeit von null ist kein Endspurt.** Beim Vorheizen steht sie
        oft auf null, weil der Drucker noch nichts zu rechnen hat - wer das
        glaubt, haelt jeden Druck vom ersten Augenblick an fuer fast fertig.
        Glaubwuerdig ist sie nur ueber null; was danach kommt (die Kammerluft
        wird gereinigt), faengt der Fortschritt.
        """
        fortschritt = zahl(self._wert(TK_FORTSCHRITT))
        if fortschritt is not None and fortschritt >= DRUCKER_ENDSPURT_PROZENT:
            return True
        rest = self.rest_min
        return rest is not None and 0 < rest <= DRUCKER_ENDSPURT_MIN

    def _im_lauf_verschwunden(self) -> bool:
        """War der Drucker gerade noch mitten in einem Druck?"""
        if self._lauf_seit is None:
            return False
        alter = (dt_util.utcnow() - self._lauf_seit).total_seconds()
        return alter <= DRUCKER_WEG_MAX_S

    @callback
    def _gedaechtnis_pflegen(self) -> None:
        """Was der Drucker selbst nicht sagt, hier nachhalten.

        Drei Dinge: wann ein Druck zuletzt wirklich lief (fuer `weg`), ob das
        fertige Teil schon geholt wurde (die Tuer sagt es), und wann `finish`
        angefangen hat (damit die Saeule nicht stundenlang ruft).
        """
        status = self._wert(TK_STATUS)
        jetzt = dt_util.utcnow()

        # Lief gerade ein Druck? Dann den Zeitpunkt festhalten.
        if status in (STATUS_LAEUFT, STATUS_PAUSE) or status in STATUS_RUESTET:
            self._lauf_seit = jetzt

        # Die Tuer: eine Oeffnung quittiert das fertige Teil. Nur die
        # Oeffnung, nicht der offene Zustand - sonst gilt eine Tuer, die
        # ohnehin offen stand, schon als Abholung.
        tuer_auf = self._ja(TK_TUER)
        if status == STATUS_FERTIG:
            if self._fertig_seit is None:
                self._fertig_seit = jetzt
                self._abgeholt = False
                self._tuer_war_zu = tuer_auf is not True
            if tuer_auf and self._tuer_war_zu:
                self._abgeholt = True
                _LOGGER.debug("Betriebsart Drucker: Tuer auf - Teil gilt als geholt")
            if tuer_auf is False:
                self._tuer_war_zu = True
            if (
                not self._abgeholt
                and (jetzt - self._fertig_seit).total_seconds() > DRUCKER_FERTIG_MAX_S
            ):
                self._abgeholt = True
        else:
            self._fertig_seit = None
            self._abgeholt = False
            self._tuer_war_zu = True

    # --- Ein und aus --------------------------------------------------

    async def async_an(self) -> None:
        """Betriebsart einschalten: Quittungston, Selbsttest, dann das Bild."""
        if not self.vorhanden:
            raise UpdateFailed(
                "Die Betriebsart \"Drucker\" braucht die Bambu-Lab-Integration - "
                "in Home Assistant ist kein Drucker eingerichtet"
            )
        self.aktiv = True
        self.pausiert = False
        self._bild = None
        self._lage = None
        self._horchen()
        self._saeule_beobachten()
        self._gedaechtnis_pflegen()
        try:
            await self.saeule.async_piep()
        except Exception as err:  # noqa: BLE001 - ein stummer Piep ist kein Grund
            _LOGGER.debug("Quittungston ging nicht: %s", err)
        try:
            self._bild_fuer(self.lage)
        except UpdateFailed as err:
            self.fehler = str(err)
            _LOGGER.warning("Betriebsart Drucker: %s", err)
            self.melden()
            return
        # Selbsttest wie an einer Werkzeugmaschine: von unten nach oben durch
        self._folge_starten(
            tuple(
                (dauer(farbe), DRUCKER_VORLAUF_MS)
                for farbe in (FARBE_GRUEN, FARBE_ORANGE, FARBE_ROT, FARBE_HINWEIS)
            )
        )

    @callback
    def verlassen(self) -> None:
        """Betriebsart beenden, ohne etwas zu schalten.

        Die Saeule bleibt stehen, wie sie steht - wer von Hand greift, will
        selbst stellen (dieselbe Regel wie in ampel.py). Die Wache auf den
        Drucker bleibt dabei an: der Sensor soll auch dann stimmen, wenn die
        Saeule auf Auto steht - er ist der eigentliche Zweck dieser Datei,
        die Betriebsart nur die Anzeige dazu.
        """
        self.aktiv = False
        self.pausiert = False
        self.fehler = None
        self._bild = None
        self._lage = None
        self._folge_abbrechen()
        self._saeule_loslassen()

    @callback
    def async_beobachten(self) -> None:
        """Von Anfang an auf den Drucker hoeren, ohne die Saeule zu stellen.

        Wird beim Einrichten gerufen (siehe __init__.py). Ohne das stuende
        der Drucker-Sensor erst still, bis jemand die Betriebsart waehlt.
        """
        self._horchen()
        self._gedaechtnis_pflegen()

    @callback
    def melden(self) -> None:
        """Die Entitaeten der Saeule auffrischen.

        Alles hier passiert ausserhalb eines Dienstrufs - eine Aenderung am
        Drucker, das Ende des Selbsttests. Ohne diesen Anruf bliebe der
        Schalter auf dem Stand von vorher (siehe ampel.py).
        """
        self.saeule.async_update_listeners()

    # --- Die Saeule geht abends vom Netz ------------------------------

    @callback
    def _saeule_beobachten(self) -> None:
        if self._ab_saeule is None:
            self._ab_saeule = self.saeule.async_add_listener(self._saeule_gemeldet)

    @callback
    def _saeule_loslassen(self) -> None:
        ab, self._ab_saeule = self._ab_saeule, None
        if ab is not None:
            ab()

    @callback
    def _saeule_gemeldet(self) -> None:
        """Antwortet die Saeule nicht mehr, endet die Betriebsart.

        Genau wie bei der Ampel: morgens um 4:55 kommt die Steckdose, und bis
        der Vorlauf kommt, darf im Schlafzimmer nichts leuchten.
        """
        if self.aktiv and not self.saeule.last_update_success:
            _LOGGER.debug("Betriebsart Drucker endet: die Saeule antwortet nicht mehr")
            self.verlassen()
            self.melden()

    # --- Der Weckruf hat Vorrang --------------------------------------

    @callback
    def pausieren(self) -> None:
        if self.aktiv:
            self.pausiert = True
            self._folge_abbrechen()

    async def async_weiter(self) -> None:
        if not self.aktiv or not self.pausiert:
            return
        self.pausiert = False
        self._bild = None           # der Weckablauf hat die Saeule umgestellt
        await self.async_nachziehen()

    # --- Folgen (Selbsttest) ------------------------------------------

    @property
    def schaltet(self) -> bool:
        return self._folge is not None and not self._folge.done()

    @callback
    def _folge_starten(self, schritte: tuple[tuple[Bild, int], ...]) -> None:
        self._folge_abbrechen()
        self._folge = self.hass.async_create_task(self._folge_fahren(schritte))

    async def _folge_fahren(
        self, schritte: tuple[tuple[Bild, int], ...]
    ) -> None:
        try:
            for bild, dauer_ms in schritte:
                if not self.aktiv or self.pausiert:
                    return
                await self.saeule.async_stufen_stellen(bild)
                self._bild = bild
                await asyncio.sleep(dauer_ms / 1000)
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            self.fehler = str(err)
            _LOGGER.warning("Betriebsart Drucker, Selbsttest: %s", err)
        finally:
            self._folge = None
            self._lage = None       # das Bild danach gilt wieder
            if self.aktiv and not self.pausiert:
                await self.async_nachziehen()
            self.melden()

    @callback
    def _folge_abbrechen(self) -> None:
        task, self._folge = self._folge, None
        if task is not None and not task.done():
            task.cancel()

    # --- Das Bild stellen ---------------------------------------------

    def _bild_fuer(self, lage: str) -> tuple[Bild, str]:
        bild = DRUCKER_BILD.get(lage, {})
        for farbe in bild:
            if self.saeule.nummer_farbe(farbe) is None:
                raise UpdateFailed(
                    f"Die Saeule meldet keine Leuchte \"{farbe}\" - "
                    "braucht Firmware 1.3.0 oder neuer"
                )
        return bild, LAGE_TEXT.get(lage, lage)

    async def async_nachziehen(self) -> None:
        """Das Bild stellen, wenn sich die Lage geaendert hat."""
        if not self.aktiv or self.pausiert or self.schaltet:
            return
        self._gedaechtnis_pflegen()
        lage = self.lage
        try:
            ziel, warum = self._bild_fuer(lage)
        except UpdateFailed as err:
            self.fehler = str(err)
            _LOGGER.warning("Betriebsart Drucker: %s", err)
            self.melden()
            return
        if ziel == self._bild and lage == self._lage:
            return

        try:
            await self.saeule.async_stufen_stellen(ziel)
        except Exception as err:  # noqa: BLE001
            self.fehler = str(err)
            _LOGGER.warning("Betriebsart Drucker: %s", err)
            self.melden()
            return
        self._lage = lage
        self._bild = ziel
        self.fehler = None
        self.melden()
        _LOGGER.debug("Betriebsart Drucker: %s -> %s", warum, ziel or "aus")

    # --- Auf den Drucker hoeren ---------------------------------------

    @callback
    def _horchen(self) -> None:
        """Auf jede Aenderung der Druckerentitaeten hoeren - kein Abfragetakt."""
        gefunden = self.entitaeten()
        ids = tuple(sorted({eid for liste in gefunden.values() for eid in liste}))
        if ids == self._beobachtet and self._ab_zustand is not None:
            return
        self._nicht_mehr_horchen()
        if not ids:
            return
        self._beobachtet = ids
        self._ab_zustand = async_track_state_change_event(
            self.hass, list(ids), self._drucker_gemeldet
        )

    @callback
    def _nicht_mehr_horchen(self) -> None:
        ab, self._ab_zustand = self._ab_zustand, None
        self._beobachtet = ()
        if ab is not None:
            ab()

    @callback
    def _drucker_gemeldet(self, event: Any) -> None:
        """Der Drucker hat etwas gemeldet.

        Das Gedaechtnis wird immer gepflegt und die Anzeige immer
        aufgefrischt - der Sensor gilt unabhaengig von der Betriebsart.
        Gestellt wird die Saeule nur, wenn sie wirklich auf Drucker steht.
        """
        self._gedaechtnis_pflegen()
        if self.aktiv and not self.pausiert and not self.schaltet:
            self.hass.async_create_task(self.async_nachziehen())
        else:
            self.melden()

    @callback
    def async_drucker_neu(self) -> None:
        """Die Bambu-Integration wurde neu geladen - die Wache nachziehen.

        Ihre Entitaeten sind danach andere Objekte; ohne das horchte die
        Wache ins Leere (dieselbe Falle wie bei der Garage, siehe ampel.py).
        """
        self._horchen()
        if self.aktiv:
            self.hass.async_create_task(self.async_nachziehen())
        else:
            self.melden()

    @callback
    def async_stop(self) -> None:
        self._folge_abbrechen()
        self._nicht_mehr_horchen()
        self._saeule_loslassen()

    # --- Anzeige ------------------------------------------------------

    def attribute(self) -> dict[str, Any]:
        """Alles, was zur Lage gehoert - an einer Stelle statt in 70 Entitaeten."""
        lage = self.lage if self.aktiv or self.vorhanden else LAGE_RUHT
        rest = self.rest_min
        feuchte = self._hoechste(TK_FEUCHTE)
        schicht = zahl(self._wert(TK_SCHICHT))
        schichten = zahl(self._wert(TK_SCHICHTEN))
        attr: dict[str, Any] = {
            "lage": lage,
            "lage_text": LAGE_TEXT.get(lage, lage),
            "aufgabe": self._wert(TK_AUFGABE),
            "fortschritt": zahl(self._wert(TK_FORTSCHRITT)),
            "rest_min": round(rest) if rest is not None else None,
            "schicht": (
                f"{int(schicht)}/{int(schichten)}"
                if schicht is not None and schichten
                else None
            ),
            "filament": self._wert(TK_SLOT),
            "drucker": self._wert(TK_STATUS),       # was das Geraet selbst sagt
            "arbeitsschritt": self._wert(TK_STUFE),
            "online": self._ja(TK_ONLINE),
            "tuer_offen": self._ja(TK_TUER),
            "hms": self._ja(TK_HMS),                # Meldung ohne Bild, siehe oben
            "abgeholt": self._abgeholt,
            "drucker_pausiert": self.pausiert,
            "drucker_schaltet": self.schaltet,
            "drucker_fehler": self.fehler,
        }
        if feuchte is not None:
            attr["feuchte_index"] = feuchte
            attr["filament_feucht"] = feuchte >= DRUCKER_FEUCHT_AB
        return attr
