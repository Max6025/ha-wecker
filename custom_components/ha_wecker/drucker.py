"""Betriebsart "Drucker": die Signalsaeule als Werkstattanzeige des 3D-Druckers.

Ein vierter Platz im Schalter "Betriebsart", neben Auto, Manuell und Ampel.
Steht er auf Drucker, sagt die Saeule mit einem Blick, wie es dem Bambu Lab
im Zimmer geht - und zwar **nicht**, indem sie die Meldungen des Herstellers
weiterreicht. Die Integration urteilt selbst.

Das ist der ganze Zweck dieser Betriebsart. Die Bambu-Integration liefert
rund 70 Entitaeten je Drucker, und ihre Zustaende sind Maschinenbegriffe:
`print_status` kennt elf Werte, `stage` ueber achtzig - von
`heatbed_underside_foreign_object_detection` bis `paused_skipped_step`.
Davon ist fast nichts eine Information, auf die man aufsteht. Hier werden
daraus **neun Lagen**, und jede beantwortet eine einzige Frage: muss ich hin?

    ruht      nichts zu tun                            Hinweis
    ruestet   heizt, kalibriert, laedt Filament        orange
    druckt    laeuft                                   gruen
    endspurt  weniger als fuenf Minuten                gruen + orange
    fertig    liegt auf dem Bett und will geholt       gruen + Hinweis
    pause     von Hand angehalten                      orange + Hinweis
    eingriff  Material fehlt, Hand gebraucht           orange + rot
    fehler    abgebrochen, Duesenproblem, Fehldruck    rot
    weg       mitten im Druck verschwunden             rot + Hinweis
    tuer      Tuer offen, waehrend gedruckt wird       gruen + rot

Die Bilder folgen derselben Lesart wie die Garagenampel (siehe ampel.py):
die Farbe sagt, wie es steht, die **Hinweisleuchte oben heisst "es wartet
etwas auf dich"** - beim Abholen, in der Pause, und bei `weg`, wo niemand
mehr weiss, wie es dem Druck geht. Rot und Hinweis zusammen bedeutet hier
dasselbe wie dort: keine Auskunft. Jedes Bild ist eindeutig; kein Bild
blinkt.

**Nicht geblinkt wird mit Absicht.** Blinken koennte nur die Saeule selbst,
und das ist am 18.11.2026 aus ihrer Firmware heraus - zusammen mit einem
Fehler, der sie zeitweise nicht mehr starten liess. Ein Takt aus Home
Assistant ueber HTTP waere ein Zufallstakt (dieselbe Begruendung wie in
ampel.py). Neun stehende Bilder reichen, weil vier Lampen fuenfzehn davon
hergeben.

**Was die Integration selbst entscheidet**, statt es durchzureichen:

- `print_status: pause` ist nicht gleich Pause. Ist der Grund in `stage` ein
  Materialproblem (`paused_filament_runout`, `paused_ams_lost`, warten auf
  Material), ist das `eingriff` - da hilft nur hingehen. Ist es ein
  Maschinenproblem (verstopfte Duese, erste Schicht misslungen,
  Temperaturfehler), ist das `fehler`. Hat sie der Nutzer selbst angehalten,
  ist es `pause`. Drei Lagen aus einem Wort.
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

**Gehoert wird es einmal.** Der Tongeber gibt den Quittungston beim
Umschalten auf die Betriebsart, und danach genau einmal je Lage, wenn aus dem
Nichtstun `fertig` oder `fehler` wird - dafuer ist eine Werkstattanzeige da.
Nicht bei `eingriff`: eine offene Tuer waehrend des Drucks ist Alltag. Und
nie nachts: zwischen 21 und 8 Uhr bleibt sie stumm
(`DRUCKER_TON_VON_UHR`), denn sie steht in einem Schlafzimmer. Die
Blitz-Warnleuchte bleibt immer aus - die gehoert zum Alarm, nicht zum Druck.

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
    DRUCKER_ENDSPURT_MIN,
    DRUCKER_ENDSPURT_PROZENT,
    DRUCKER_FERTIG_MAX_S,
    DRUCKER_FEUCHT_AB,
    DRUCKER_TON_BIS_UHR,
    DRUCKER_TON_VON_UHR,
    DRUCKER_VORLAUF_MS,
    DRUCKER_WEG_MAX_S,
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
LAGE_DRUCKT = "druckt"
LAGE_ENDSPURT = "endspurt"
LAGE_FERTIG = "fertig"
LAGE_PAUSE = "pause"
LAGE_EINGRIFF = "eingriff"
LAGE_FEHLER = "fehler"
LAGE_WEG = "weg"
LAGE_TUER = "tuer"

LAGE_ALLE = (
    LAGE_RUHT,
    LAGE_RUESTET,
    LAGE_DRUCKT,
    LAGE_ENDSPURT,
    LAGE_FERTIG,
    LAGE_PAUSE,
    LAGE_EINGRIFF,
    LAGE_FEHLER,
    LAGE_WEG,
    LAGE_TUER,
)

# Das Bild je Lage, als Menge der Farben. Die Farbe sagt, wie es steht; die
# Hinweisleuchte oben heisst "es wartet etwas auf dich". Jedes Bild ist
# eindeutig, keines blinkt.
DRUCKER_BILD: dict[str, frozenset[str]] = {
    LAGE_RUHT: frozenset({FARBE_HINWEIS}),
    LAGE_RUESTET: frozenset({FARBE_ORANGE}),
    LAGE_DRUCKT: frozenset({FARBE_GRUEN}),
    LAGE_ENDSPURT: frozenset({FARBE_GRUEN, FARBE_ORANGE}),
    LAGE_FERTIG: frozenset({FARBE_GRUEN, FARBE_HINWEIS}),
    LAGE_PAUSE: frozenset({FARBE_ORANGE, FARBE_HINWEIS}),
    LAGE_EINGRIFF: frozenset({FARBE_ORANGE, FARBE_ROT}),
    LAGE_FEHLER: frozenset({FARBE_ROT}),
    LAGE_WEG: frozenset({FARBE_ROT, FARBE_HINWEIS}),
    # Tuer offen, waehrend gedruckt wird: gruen bleibt, weil der Druck laeuft,
    # rot dazu, weil etwas offen steht. Ein Bild, das es sonst nicht gibt -
    # man sieht beides auf einmal (Max, 20.11.2026).
    LAGE_TUER: frozenset({FARBE_GRUEN, FARBE_ROT}),
}

LAGE_TEXT: dict[str, str] = {
    LAGE_RUHT: "Drucker ruht",
    LAGE_RUESTET: "Drucker rüstet",
    LAGE_DRUCKT: "Druck läuft",
    LAGE_ENDSPURT: "Druck fast fertig",
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
    LAGE_DRUCKT,
    LAGE_ENDSPURT,
    LAGE_PAUSE,
    LAGE_EINGRIFF,
    LAGE_TUER,
)
# Dafuer gibt der Tongeber einmal kurz Laut, sobald die Lage eintritt
LAGE_TON = (LAGE_FERTIG, LAGE_FEHLER, LAGE_TUER)

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
# Ueber achtzig Werte gibt es; nach Anfang zu pruefen ist kuerzer und faengt
# auch die, die Bambu erst morgen dazunimmt.
STUFE_RUESTEN_ANFANG = (
    "heat",
    "cool",
    "calibrat",
    "bed_level",
    "filament_",
    "changing_filament",
    "preparing",
    "prepar",
    "homing",
    "scanning",
    "inspecting",
    "identifying",
    "measuring",
    "moving",
    "sweeping",
    "purifying",
    "build_plate",
    "thermal",
    "hotend",
    "absolute_accuracy",
    "laser",
    "active_arc",
    "waiting",
    "cleaning",
    "print_calibration",
    "pre_extrusion",
    "check_absolute",
    "check_birdeye",
    "motor_noise",
)


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
        self._bild: frozenset[str] | None = None   # was zuletzt gestellt wurde
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
        self._ton_fuer: str | None = None  # fuer diese Lage hat es schon getont

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
            # und bei einem geschlossenen Drucker auch Temperatur. Gruen und
            # rot zusammen, dazu einmal kurz der Tongeber (Max, 20.11.2026).
            if self._ja(TK_TUER):
                return LAGE_TUER
            # Der Endspurt geht vor dem Ruesten - sonst wird aus dem Nachlauf
            # am Ende eines Drucks (die Kammerluft wird gereinigt, die Duese
            # kuehlt) wieder "ruestet", und die Saeule faellt bei 100 % von
            # gruen auf orange zurueck. Am 20.11.2026 am laufenden Druck
            # gesehen: stage `purifying_chamber_air` bei 465/465 Schichten.
            if self._endspurt():
                return LAGE_ENDSPURT
            if stufe and stufe != "printing" and self._ruestet(stufe):
                return LAGE_RUESTET
            return LAGE_DRUCKT

        if status in STATUS_RUESTET:
            return LAGE_RUESTET
        if self._ruestet(stufe):
            return LAGE_RUESTET
        return LAGE_RUHT

    @staticmethod
    def _ruestet(stufe: str) -> bool:
        """Arbeitet der Drucker, ohne schon zu drucken?"""
        if not stufe or stufe in ("idle", "printing", "unknown", "offline"):
            return False
        return stufe.startswith(STUFE_RUESTEN_ANFANG)

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
        self._ton_fuer = None
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
                (frozenset({farbe}), DRUCKER_VORLAUF_MS)
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
        self._ton_fuer = None
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
    def _folge_starten(self, schritte: tuple[tuple[frozenset[str], int], ...]) -> None:
        self._folge_abbrechen()
        self._folge = self.hass.async_create_task(self._folge_fahren(schritte))

    async def _folge_fahren(
        self, schritte: tuple[tuple[frozenset[str], int], ...]
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

    def _bild_fuer(self, lage: str) -> tuple[frozenset[str], str]:
        bild = DRUCKER_BILD.get(lage, frozenset())
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
        vorher, self._lage = self._lage, lage
        self._bild = ziel
        self.fehler = None
        await self._tonen(vorher, lage)
        self.melden()
        _LOGGER.debug("Betriebsart Drucker: %s -> %s", warum, ziel or "aus")

    async def _tonen(self, vorher: str | None, lage: str) -> None:
        """Einmal Laut geben, wenn aus dem Lauf etwas Wartendes geworden ist.

        `fertig`, `fehler` und die offene Tuer beim Drucken, je einmal beim
        Eintreten, und nie nachts - die Saeule steht in einem Schlafzimmer.
        `eingriff` tont nicht: wer das Filament wechselt, steht sowieso davor.
        Geht die Tuer zu und wieder auf, tont es erneut - `_ton_fuer` haelt nur
        die laufende Lage fest, und die ist dazwischen eine andere.
        """
        if lage not in LAGE_TON or vorher is None or self._ton_fuer == lage:
            self._ton_fuer = lage if lage in LAGE_TON else None
            return
        self._ton_fuer = lage
        stunde = dt_util.now().hour
        if not DRUCKER_TON_VON_UHR <= stunde < DRUCKER_TON_BIS_UHR:
            _LOGGER.debug("Betriebsart Drucker: %s, aber Nachtruhe - still", lage)
            return
        try:
            await self.saeule.async_piep()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Ton zu \"%s\" ging nicht: %s", lage, err)

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
