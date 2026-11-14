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

"zeit" zaehlt in Sekunden ab dem Klingeln, negativ heisst vorher. Es gewinnt
der erste Block, dessen Wochentag und Zeitfenster zur Weckzeit passen.
Jeder Schritt landet mit Zeit und Ergebnis im Protokoll, das am Schalter haengt.
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
    TYP_SAEULE,
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
                {"zeit": -60, "saeule": {"status": "hinweis"}},
                {"zeit": -60, "licht": {"prozent": 3, "dauer": 60}},
                {"zeit": 0, "saeule": {"status": "alarm"}},
                {"zeit": 0, "licht": {"prozent": 90, "dauer": 20}},
                {"zeit": 540, "licht": {"prozent": 5, "dauer": 30}},
                {"zeit": 840, "licht": {"aus": True}},
                {"zeit": 840, "saeule": {"status": "ruhe"}},
            ],
        }
    ],
}


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
        self.nullpunkt: datetime | None = None  # Zeitpunkt, auf den sich "zeit" bezieht
        self.protokoll: list[dict[str, Any]] = []
        self._klingelt_alt = False
        self._timer: list[CALLBACK_TYPE] = []
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
        self._klingelt_alt = klingelt

        if not self.aktiv or self.probelauf:
            self._melden()
            return

        if flanke_an:
            # Es klingelt wirklich: ab hier zaehlt die Zeit, alles ab 0 kommt neu
            self._starten(dt_util.utcnow(), nur_ab_null=True)
        elif schlummert and self.laeuft:
            self._timer_weg()
            self._notiz("Schlummern", "Ablauf angehalten", "ok")
            self.laeuft = False
        elif not self.laeuft and naechster is not None:
            self._starten(naechster, nur_ab_null=False)
        self._melden()

    def _starten(self, nullpunkt: datetime, nur_ab_null: bool) -> None:
        """Schritte des passenden Blocks auf absolute Zeitpunkte legen."""
        ablauf, fehler = self.ablauf
        if fehler:
            self._notiz("Ablaufdatei", fehler, "fehler")
        block = block_waehlen(ablauf, nullpunkt)
        if block is None:
            self._timer_weg()
            self.laeuft = False
            self.block = None
            self._notiz("Kein Block", "Weckzeit passt in keinen Zeitblock", "uebersprungen")
            return
        self._timer_weg()
        self.block = str(block.get("name") or "ohne Namen")
        self.nullpunkt = nullpunkt
        self.laeuft = True
        jetzt = dt_util.utcnow()
        geplant = 0
        for schritt in block.get("schritte", []):
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
        self._notiz(
            "Geplant",
            f"Block \"{self.block}\", {geplant} Schritte ab {dt_util.as_local(nullpunkt):%H:%M:%S}",
            "ok",
        )

    def _faellig(self, schritt: dict[str, Any]):
        @callback
        def _ausloesen(_jetzt: datetime) -> None:
            self.hass.async_create_task(self._ausfuehren(schritt))
        return _ausloesen

    # --- Probelauf ----------------------------------------------------

    async def async_probelauf(self, vorlauf_s: int = 60) -> None:
        """Ablauf sofort starten, als klingelte es in `vorlauf_s` Sekunden."""
        self._timer_weg()
        self.protokoll = []
        self.probelauf = True
        self._notiz("Probelauf", f"gestartet, Klingeln in {vorlauf_s} s", "ok")
        self._starten(dt_util.utcnow() + timedelta(seconds=vorlauf_s), nur_ab_null=False)
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

    def _melden(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_ABLAUF.format(self.entry.entry_id))
