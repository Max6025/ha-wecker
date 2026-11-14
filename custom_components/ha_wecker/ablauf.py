"""Weckablauf: Hauptlicht und Signalsaeule folgen dem Wecker der App.

Der Ablauf haengt am Wecker-Eintrag, nicht an einem Leuchtmittel. Er holt sich
die Weckzeiten aus dem, was die App gemeldet hat, und steuert damit Geraete,
die in ganz anderen Eintraegen derselben Integration stecken - die Saeule etwa.
Vorher hing er an der Relaisbox: ohne die lief gar nichts, und wo ein Schritt
scheiterte, sah man es nur im Protokoll.

Was wann passiert, steht in Zeitbloecken (JSON, in den Optionen des Weckers):

    {"version": 1, "bloecke": [{
       "name": "Werktags frueh",
       "wochentage": ["mo","di","mi","do","fr"],
       "von": "04:00", "bis": "10:00",
       "schritte": [
         {"zeit": -60, "saeule": {"status": "hinweis"}},
         {"zeit": -60, "licht":  {"prozent": 3, "dauer": 60}},
         {"zeit":   0, "saeule": {"status": "alarm"}},
         {"zeit":   0, "licht":  {"prozent": 90, "dauer": 20}},
         {"zeit": 540, "licht":  {"prozent": 5, "dauer": 30}},
         {"zeit": 840, "licht":  {"aus": true}},
         {"zeit": 840, "saeule": {"status": "ruhe"}}]}]}

"zeit" zaehlt in Sekunden, "ab" sagt wovon: "weckruf" (Vorgabe) rechnet ab dem
Klingeln, negativ heisst vorher; "ende" rechnet ab dem Moment, in dem der
Weckruf beendet wird. Der Nachlauf haengt also an dir, nicht an der Uhr.

Es gewinnt der erste Block, dessen Wochentag und Zeitfenster zur Weckzeit
passen. Jeder Schritt landet mit Zeit und Ergebnis im Protokoll am Schalter.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ABLAUF,
    CONF_HAUPTLICHT,
    DOMAIN,
    PROTOKOLL_MAX,
    SIGNAL_ABLAUF,
    SIGNAL_WECKER_ALLE,
    STATUS_STANDARD,
)

_LOGGER = logging.getLogger(__name__)

TAGE = ["mo", "di", "mi", "do", "fr", "sa", "so"]

# Ohne eigene Datei gilt das hier - genau der Ablauf, den Max beschrieben hat.
STANDARD_ABLAUF: dict[str, Any] = {
    "version": 1,
    "bloecke": [
        {
            "name": "Immer",
            "wochentage": TAGE,
            "von": "00:00",
            "bis": "00:00",
            "schritte": [
                # Vorlauf: in der letzten Minute vor dem Weckruf hoch auf 5 %
                {"zeit": -60, "saeule": {"status": "hinweis"}},
                {"zeit": -60, "licht": {"prozent": 5, "dauer": 60}},
                # Es klingelt: Saeule in den Alarm, sie nimmt die Warnleuchte mit
                {"zeit": 0, "saeule": {"status": "alarm"}},
                # Weckruf beendet: Warnleuchte faellt mit dem Alarm weg, die
                # Saeule geht in den Kreuzwechsel, das Licht auf 70 %
                {"zeit": 0, "ab": "ende", "saeule": {"status": "kreuz"}},
                {"zeit": 0, "ab": "ende", "licht": {"prozent": 70, "dauer": 10}},
                # Nach sieben Minuten Licht aus, dafuer noch einmal Alarm
                {"zeit": 420, "ab": "ende", "licht": {"aus": True, "dauer": 30}},
                {"zeit": 420, "ab": "ende", "saeule": {"status": "alarm"}},
                # Eine Minute spaeter zurueck auf Gruen und stehen bleiben
                {"zeit": 480, "ab": "ende", "saeule": {"status": "ruhe"}},
            ],
        }
    ],
}

AB_WECKRUF = "weckruf"
AB_ENDE = "ende"


def bezug(schritt: dict[str, Any]) -> str:
    wert = str(schritt.get("ab") or AB_WECKRUF).lower()
    return AB_ENDE if wert == AB_ENDE else AB_WECKRUF


def zeit_lesen(wert: Any, vorgabe: time) -> time:
    """'HH:MM' oder 'HH:MM:SS'; Unsinn faellt auf die Vorgabe zurueck."""
    if isinstance(wert, time):
        return wert
    t = dt_util.parse_time(str(wert)) if wert else None
    return t if t is not None else vorgabe


def im_fenster(jetzt: time, von: time, bis: time) -> bool:
    """von == bis heisst: immer. Ueber Mitternacht geht."""
    if von == bis:
        return True
    if von < bis:
        return von <= jetzt < bis
    return jetzt >= von or jetzt < bis


def ablauf_lesen(roh: Any) -> tuple[dict[str, Any], str | None]:
    """JSON pruefen. Gibt (Ablauf, Fehlertext) - bei Fehler den Standardablauf."""
    if not roh:
        return STANDARD_ABLAUF, None
    daten = roh
    if isinstance(roh, str):
        try:
            daten = json.loads(roh)
        except ValueError as err:
            return STANDARD_ABLAUF, f"JSON nicht lesbar: {err}"
    if not isinstance(daten, dict) or not isinstance(daten.get("bloecke"), list):
        return STANDARD_ABLAUF, "Es fehlt die Liste \"bloecke\""
    for i, block in enumerate(daten["bloecke"], 1):
        if not isinstance(block, dict):
            return STANDARD_ABLAUF, f"Block {i} ist kein Objekt"
        if not isinstance(block.get("schritte"), list):
            return STANDARD_ABLAUF, f"Block {i} hat keine Liste \"schritte\""
        for j, schritt in enumerate(block["schritte"], 1):
            if not isinstance(schritt, dict):
                return STANDARD_ABLAUF, f"Block {i}, Schritt {j} ist kein Objekt"
            if "zeit" not in schritt:
                return STANDARD_ABLAUF, f"Block {i}, Schritt {j} hat keine \"zeit\""
            try:
                int(schritt["zeit"])
            except (TypeError, ValueError):
                return STANDARD_ABLAUF, f"Block {i}, Schritt {j}: \"zeit\" ist keine Zahl"
            if not any(k in schritt for k in ("licht", "saeule")):
                return STANDARD_ABLAUF, f"Block {i}, Schritt {j} tut nichts"
            if "ab" in schritt and str(schritt["ab"]).lower() not in (AB_WECKRUF, AB_ENDE):
                return STANDARD_ABLAUF, (
                    f"Block {i}, Schritt {j}: \"ab\" kennt nur \"weckruf\" und \"ende\""
                )
    return daten, None


def block_waehlen(ablauf: dict[str, Any], weckzeit: datetime) -> dict[str, Any] | None:
    """Erster Block, dessen Wochentag und Fenster zur (lokalen) Weckzeit passen."""
    lokal = dt_util.as_local(weckzeit)
    tag = TAGE[lokal.weekday()]
    for block in ablauf.get("bloecke", []):
        tage = block.get("wochentage") or TAGE
        if tag not in [str(t).lower()[:2] for t in tage]:
            continue
        von = zeit_lesen(block.get("von"), time(0, 0))
        bis = zeit_lesen(block.get("bis"), time(0, 0))
        if im_fenster(lokal.time(), von, bis):
            return block
    return None


def naechste_weckzeit(hass: HomeAssistant) -> tuple[bool, bool, datetime | None]:
    """(klingelt, schlummert, naechster Weckruf) aus allen Wecker-Eintraegen.

    Die Weckzeit wird aus Stunde, Minute und Wochentagsmaske selbst gerechnet.
    "next_trigger" aus der App ist nur die Rueckfallebene: die App meldet sich
    nur bei Aenderungen, der Zeitstempel kann also von gestern sein.
    """
    from . import WeckerData  # Kreisimport vermeiden

    klingelt = schlummert = False
    naechster: datetime | None = None
    jetzt = dt_util.utcnow()
    for obj in hass.data.get(DOMAIN, {}).values():
        if not isinstance(obj, WeckerData) or not obj.payload:
            continue
        p = obj.payload
        klingelt = klingelt or bool(p.get("ringing"))
        schlummert = schlummert or bool(p.get("snoozed"))
        for a in (p.get("alarms") or []):
            if not isinstance(a, dict) or not a.get("enabled") or a.get("snoozed"):
                continue
            kandidat = _termin_rechnen(a, jetzt) or _termin_lesen(a.get("next_trigger"))
            if kandidat and kandidat > jetzt and (naechster is None or kandidat < naechster):
                naechster = kandidat
        if not p.get("alarms") and p.get("state"):
            kandidat = _termin_lesen(p.get("state"))
            if kandidat and kandidat > jetzt and (naechster is None or kandidat < naechster):
                naechster = kandidat
    return klingelt, schlummert, naechster


def _termin_lesen(wert: Any) -> datetime | None:
    if not wert:
        return None
    dt = dt_util.parse_datetime(str(wert))
    return dt_util.as_utc(dt) if dt else None


def _termin_rechnen(alarm: dict[str, Any], jetzt: datetime) -> datetime | None:
    """Naechster Termin aus Stunde, Minute und Wochentagsmaske der App.

    days_mask ist ein Bitfeld, Bit 0 ist Montag. Null heisst: einmalig, dann
    gilt der naechste Tag, an dem die Uhrzeit noch kommt. "skip_next"
    ueberspringt genau einen Termin.
    """
    try:
        stunde = int(alarm["hour"])
        minute = int(alarm["minute"])
    except (KeyError, TypeError, ValueError):
        return None
    try:
        maske = int(alarm.get("days_mask") or 0)
    except (TypeError, ValueError):
        maske = 0
    lokal = dt_util.as_local(jetzt)
    uebersprungen = bool(alarm.get("skip_next"))
    for tage_weiter in range(0, 9):
        kandidat = (lokal + timedelta(days=tage_weiter)).replace(
            hour=stunde, minute=minute, second=0, microsecond=0
        )
        if kandidat <= lokal:
            continue
        if maske and not (maske >> kandidat.weekday()) & 1:
            continue
        if uebersprungen:
            uebersprungen = False
            continue
        return dt_util.as_utc(kandidat)
    return None


class Weckablauf:
    """Faehrt die Schritte des passenden Blocks rund um den Weckruf."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.aktiv = True                       # Schalter "Weckablauf"
        self.laeuft = False
        self.probelauf = False
        self.block: str | None = None           # Name des gewaehlten Blocks
        self.naechster_wecker: datetime | None = None
        self.nullpunkt: datetime | None = None  # Weckruf, auf den sich "zeit" bezieht
        self.beendet_um: datetime | None = None # wann der Weckruf beendet wurde
        self.protokoll: list[dict[str, Any]] = []
        self._klingelt_alt = False
        self._timer: list[CALLBACK_TYPE] = []
        self._probe_timer: CALLBACK_TYPE | None = None
        self._unsub_signal: CALLBACK_TYPE | None = None

    # --- Einstellungen ------------------------------------------------

    @property
    def hauptlicht(self) -> str | None:
        wert = self.entry.options.get(CONF_HAUPTLICHT)
        return str(wert) if wert else None

    @property
    def ablauf(self) -> tuple[dict[str, Any], str | None]:
        return ablauf_lesen(self.entry.options.get(CONF_ABLAUF))

    def saeule(self) -> Any | None:
        """Die Signalsaeule aus einem anderen Eintrag derselben Integration."""
        from .saeule import SaeuleCoordinator

        for obj in self.hass.data.get(DOMAIN, {}).values():
            if isinstance(obj, SaeuleCoordinator):
                return obj
        return None

    def attribute(self) -> dict[str, Any]:
        _, fehler = self.ablauf
        saeule = self.saeule()
        return {
            "laeuft": self.laeuft,
            "probelauf": self.probelauf,
            "block": self.block,
            "hauptlicht": self.hauptlicht or "nicht eingestellt",
            "saeule": "verbunden" if saeule else "nicht eingerichtet",
            "naechster_wecker": self.naechster_wecker.isoformat() if self.naechster_wecker else None,
            "nullpunkt": self.nullpunkt.isoformat() if self.nullpunkt else None,
            "beendet_um": self.beendet_um.isoformat() if self.beendet_um else None,
            "ablauf_fehler": fehler,
            "protokoll": list(reversed(self.protokoll)),
        }

    # --- Lebenszyklus -------------------------------------------------

    @callback
    def async_start(self) -> None:
        self._unsub_signal = async_dispatcher_connect(
            self.hass, SIGNAL_WECKER_ALLE, self._wecker_geaendert
        )
        self._wecker_geaendert()

    @callback
    def async_stop(self) -> None:
        if self._unsub_signal:
            self._unsub_signal()
            self._unsub_signal = None
        self._timer_weg()

    async def async_setzen(self, an: bool) -> None:
        self.aktiv = an
        if an:
            self._wecker_geaendert()
            return
        self._timer_weg()
        self.laeuft = self.probelauf = False
        self._melden()

    # --- Reaktion auf den Wecker --------------------------------------

    @callback
    def _wecker_geaendert(self) -> None:
        klingelt, schlummert, naechster = naechste_weckzeit(self.hass)
        self.naechster_wecker = naechster
        flanke_an = klingelt and not self._klingelt_alt
        flanke_aus = not klingelt and self._klingelt_alt
        self._klingelt_alt = klingelt

        if not self.aktiv or self.probelauf:
            self._melden()
            return

        if flanke_an:
            # Es klingelt wirklich: ab hier zaehlt die Zeit, alles ab 0 kommt neu
            self._starten(dt_util.utcnow(), AB_WECKRUF, nur_ab_null=True)
        elif flanke_aus and schlummert:
            self._timer_weg()
            self._notiz("Schlummern", "Ablauf angehalten", "ok")
            self.laeuft = False
        elif flanke_aus:
            # Weckruf beendet: der Nachlauf haengt an diesem Moment
            self.beendet_um = dt_util.utcnow()
            self._starten(self.beendet_um, AB_ENDE)
        elif not self.laeuft and naechster is not None:
            self._starten(naechster, AB_WECKRUF)
        self._melden()

    def _starten(self, nullpunkt: datetime, art: str, nur_ab_null: bool = False) -> None:
        """Die Schritte des Blocks mit diesem Bezugspunkt auf Zeitpunkte legen.

        `art` trennt die beiden Haelften der Liste: die am Weckruf haengen und
        die, die erst nach dem Beenden gelten. Ein neuer Lauf raeumt die Timer
        der alten Haelfte ab, damit nichts aus dem Vorlauf hereinredet.
        """
        ablauf, fehler = self.ablauf
        if fehler:
            self._notiz("Ablaufdatei", fehler, "fehler")
        bezugszeit = self.nullpunkt if art == AB_ENDE and self.nullpunkt else nullpunkt
        block = block_waehlen(ablauf, bezugszeit)
        if block is None:
            self._timer_weg()
            self.laeuft = False
            self.block = None
            self._notiz("Kein Block", "Weckzeit passt in keinen Zeitblock", "uebersprungen")
            return
        self._timer_weg()
        self.block = str(block.get("name") or "ohne Namen")
        if art == AB_WECKRUF:
            self.nullpunkt = nullpunkt
            self.beendet_um = None
        self.laeuft = True
        jetzt = dt_util.utcnow()
        geplant = 0
        for schritt in block.get("schritte", []):
            if bezug(schritt) != art:
                continue
            versatz = int(schritt["zeit"])
            if nur_ab_null and versatz < 0:
                continue
            faellig = nullpunkt + timedelta(seconds=versatz)
            if faellig <= jetzt - timedelta(seconds=5):
                continue                      # laengst vorbei, nicht nachholen
            if faellig <= jetzt:
                self.hass.async_create_task(self._ausfuehren(schritt))
                geplant += 1
                continue
            self._timer.append(
                async_track_point_in_utc_time(self.hass, self._faellig(schritt), faellig)
            )
            geplant += 1
        woher = "ab dem Weckruf" if art == AB_WECKRUF else "ab dem Beenden"
        self._notiz(
            "Geplant",
            f"Block \"{self.block}\", {geplant} Schritte {woher} "
            f"{dt_util.as_local(nullpunkt):%H:%M:%S}",
            "ok",
        )

    def _faellig(self, schritt: dict[str, Any]):
        @callback
        def _ausloesen(_jetzt: datetime) -> None:
            self.hass.async_create_task(self._ausfuehren(schritt))
        return _ausloesen

    # --- Probelauf ----------------------------------------------------

    async def async_probelauf(self, vorlauf_s: int = 60, klingelt_s: int = 30) -> None:
        """Ablauf sofort durchspielen, ohne auf einen echten Weckruf zu warten.

        Nach `vorlauf_s` "klingelt" es, nach weiteren `klingelt_s` wird der
        Weckruf "beendet" - sonst liefe der Nachlauf nie an, der ja genau an
        diesem Moment haengt.
        """
        self._timer_weg()
        self.protokoll = []
        self.probelauf = True
        self.beendet_um = None
        weckruf = dt_util.utcnow() + timedelta(seconds=vorlauf_s)
        self._notiz(
            "Probelauf",
            f"Klingeln in {vorlauf_s} s, Beenden {klingelt_s} s spaeter",
            "ok",
        )
        self._starten(weckruf, AB_WECKRUF)
        self._probe_timer = async_track_point_in_utc_time(
            self.hass, self._probe_beenden, weckruf + timedelta(seconds=klingelt_s)
        )
        self._melden()

    @callback
    def _probe_beenden(self, _jetzt: datetime) -> None:
        self._probe_timer = None
        if not self.probelauf:
            return
        self.beendet_um = dt_util.utcnow()
        self._notiz("Probelauf", "Weckruf beendet", "ok")
        self._starten(self.beendet_um, AB_ENDE)
        self._melden()

    async def async_abbrechen(self) -> None:
        """Laufenden Ablauf stoppen und aufraeumen: Licht aus, Saeule auf Ruhe."""
        self._timer_weg()
        war = self.laeuft or self.probelauf
        self.laeuft = self.probelauf = False
        self.beendet_um = None
        self._notiz("Abbruch", "Ablauf gestoppt" if war else "nichts lief", "ok")
        if war:
            await self._licht({"aus": True})
            await self._saeule({"status": STATUS_STANDARD})
        self._melden()

    # --- Schritte ausfuehren ------------------------------------------

    async def _ausfuehren(self, schritt: dict[str, Any]) -> None:
        if "licht" in schritt:
            await self._licht(schritt["licht"])
        if "saeule" in schritt:
            await self._saeule(schritt["saeule"])
        self._melden()

    async def _licht(self, wunsch: dict[str, Any]) -> None:
        ziel = self.hauptlicht
        if not ziel:
            self._notiz("Hauptlicht", "keine Entitaet eingestellt", "fehler")
            return
        aus = bool(wunsch.get("aus"))
        daten: dict[str, Any] = {"entity_id": ziel}
        if not aus and wunsch.get("prozent") is not None:
            daten["brightness_pct"] = int(wunsch["prozent"])
        if wunsch.get("dauer"):
            daten["transition"] = int(wunsch["dauer"])
        dienst = "turn_off" if aus else "turn_on"
        beschreibung = "aus" if aus else f"{daten.get('brightness_pct', '?')} %"
        if wunsch.get("dauer"):
            beschreibung += f" in {int(wunsch['dauer'])} s"
        try:
            await self.hass.services.async_call("light", dienst, daten, blocking=True)
            self._notiz(f"Hauptlicht {ziel}", beschreibung, "ok")
        except Exception as err:  # noqa: BLE001
            # Viele Leuchten koennen kein "transition". Dann ohne, statt
            # den Schritt stillschweigend fallen zu lassen.
            if "transition" in daten:
                daten.pop("transition")
                try:
                    await self.hass.services.async_call("light", dienst, daten, blocking=True)
                    self._notiz(f"Hauptlicht {ziel}", beschreibung + " (ohne Uebergang)", "ok")
                    return
                except Exception as err2:  # noqa: BLE001
                    err = err2
            self._notiz(f"Hauptlicht {ziel}", f"{beschreibung}: {err}", "fehler")
            _LOGGER.warning("Weckablauf: Hauptlicht %s %s: %s", ziel, dienst, err)

    async def _saeule(self, wunsch: dict[str, Any]) -> None:
        coordinator = self.saeule()
        if coordinator is None:
            self._notiz("Signalsaeule", "nicht eingerichtet", "uebersprungen")
            return
        try:
            if "status" in wunsch:
                await coordinator.async_status(str(wunsch["status"]))
                self._notiz("Signalsaeule", f"Status {wunsch['status']}", "ok")
            if "warn" in wunsch:
                await coordinator.async_schalten(5, bool(wunsch["warn"]))
                self._notiz("Signalsaeule", f"Warnleuchte {'an' if wunsch['warn'] else 'aus'}", "ok")
        except Exception as err:  # noqa: BLE001
            self._notiz("Signalsaeule", str(err), "fehler")
            _LOGGER.warning("Weckablauf: Saeule %s: %s", wunsch, err)

    # --- Kleinkram ----------------------------------------------------

    def _notiz(self, was: str, text: str, ergebnis: str) -> None:
        self.protokoll.append(
            {
                "zeit": dt_util.as_local(dt_util.utcnow()).strftime("%d.%m. %H:%M:%S"),
                "was": was,
                "text": text,
                "ergebnis": ergebnis,
            }
        )
        del self.protokoll[:-PROTOKOLL_MAX]

    def _timer_weg(self) -> None:
        for t in self._timer:
            t()
        self._timer = []
        if self._probe_timer:
            self._probe_timer()
            self._probe_timer = None

    def _melden(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_ABLAUF.format(self.entry.entry_id))
