"""Weckerlampe: Leuchten an der Relaisbox und ein Hauptlicht folgen dem Wecker.

Fester Ablauf (Relais-Nummern wie in der Bauweise "Lampen": 1 Lampe mit
gruener LED, 3 Rot, 4 Warnleuchte; das Hauptlicht ist eine dimmbare
light-Entitaet aus den Optionen), solange der Schalter "Weckerlampe" an ist:

Vorlauf (eine Minute vor dem Weckruf)
  Rot dauerhaft an; Hauptlicht auf 3 % und innerhalb der Minute auf 10 %.
Klingeln
  Rot blinkt, Lampe Doppelblitz, Warnleuchte an; Hauptlicht auf 100 %.
  Fehlte der Vorlauf (Schlummern, HA gerade gestartet), geht es direkt los.
Schlummern
  Alle Leuchten aus, Hauptlicht zurueck auf 10 %; klingelt es wieder, wie Klingeln.
Nachlauf (Wecker beendet)
  Warnleuchte noch 5 s; Rot blinkt schnell 5 min; Lampe blinkt 10 min (1 s);
  Hauptlicht 50 % fuer 10 min, dann in 30 s auf 0; ist es aus, blitzt die
  Warnleuchte noch 10 s. Danach ist Ruhe (nach 640 s).

Das Hauptlicht macht nur im Zeitfenster der Optionen mit (Vorgabe 3 bis 10
Uhr), entschieden beim Start eines Ablaufs. Alle Muster auf der Box bekommen
eine Hoechstdauer: bleibt die App stumm, gehen die Leuchten trotzdem aus.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .const import (
    CONF_HAUPTLICHT,
    CONF_HAUPTLICHT_BIS,
    CONF_HAUPTLICHT_VON,
    DOMAIN,
    HAUPTLICHT_BIS_STANDARD,
    HAUPTLICHT_VON_STANDARD,
    LAMPE_KLINGELN_MAX_S,
    LAMPE_NACHLAUF_LAMPE_S,
    LAMPE_NACHLAUF_LICHT_AUS_S,
    LAMPE_NACHLAUF_ROT_S,
    LAMPE_NACHLAUF_S,
    LAMPE_NACHLAUF_WARN_NOCHMAL_S,
    LAMPE_NACHLAUF_WARN_S,
    LAMPE_RELAIS_LAMPE,
    LAMPE_RELAIS_ROT,
    LAMPE_RELAIS_WARN,
    LAMPE_VORLAUF_S,
    SIGNAL_LAMPE,
    SIGNAL_WECKER_ALLE,
)

if TYPE_CHECKING:
    from .relais import RelaisCoordinator

_LOGGER = logging.getLogger(__name__)

PHASE_AUS = "aus"
PHASE_VORLAUF = "vorlauf"
PHASE_KLINGELN = "klingeln"
PHASE_SCHLUMMER = "schlummer"
PHASE_NACHLAUF = "nachlauf"

# Relais-Schritte je Phase: (Verzoegerung s, Relais, Muster, Hoechstdauer s)
RELAIS_ABLAUF: dict[str, list[tuple[int, int, str, int]]] = {
    PHASE_VORLAUF: [
        (0, LAMPE_RELAIS_ROT, "dauer", LAMPE_VORLAUF_S + LAMPE_KLINGELN_MAX_S),
    ],
    PHASE_KLINGELN: [
        (0, LAMPE_RELAIS_ROT, "blinken", LAMPE_KLINGELN_MAX_S),
        (0, LAMPE_RELAIS_LAMPE, "doppelblitz", LAMPE_KLINGELN_MAX_S),
        (0, LAMPE_RELAIS_WARN, "dauer", LAMPE_KLINGELN_MAX_S),
    ],
    PHASE_NACHLAUF: [
        (0, LAMPE_RELAIS_WARN, "dauer", LAMPE_NACHLAUF_WARN_S),
        (0, LAMPE_RELAIS_ROT, "schnell", LAMPE_NACHLAUF_ROT_S),
        (0, LAMPE_RELAIS_LAMPE, "blinken", LAMPE_NACHLAUF_LAMPE_S),
        (LAMPE_NACHLAUF_LAMPE_S + LAMPE_NACHLAUF_LICHT_AUS_S, LAMPE_RELAIS_WARN, "dauer", LAMPE_NACHLAUF_WARN_NOCHMAL_S),
    ],
}

# Hauptlicht-Schritte je Phase: (Verzoegerung s, Dienst, Daten)
LICHT_ABLAUF: dict[str, list[tuple[int, str, dict[str, Any]]]] = {
    PHASE_VORLAUF: [
        (0, "turn_on", {"brightness_pct": 3}),
        (2, "turn_on", {"brightness_pct": 10, "transition": LAMPE_VORLAUF_S - 2}),
    ],
    PHASE_KLINGELN: [
        (0, "turn_on", {"brightness_pct": 100, "transition": 20}),
    ],
    PHASE_SCHLUMMER: [
        (0, "turn_on", {"brightness_pct": 10}),
    ],
    PHASE_NACHLAUF: [
        (0, "turn_on", {"brightness_pct": 50}),
        (LAMPE_NACHLAUF_LAMPE_S, "turn_off", {"transition": LAMPE_NACHLAUF_LICHT_AUS_S}),
    ],
}
ALLE_RELAIS = sorted({LAMPE_RELAIS_LAMPE, LAMPE_RELAIS_ROT, LAMPE_RELAIS_WARN})


def _wecker_stand(hass: HomeAssistant) -> tuple[bool, bool, datetime | None]:
    """Alle Wecker-Eintraege zusammen: klingelt, schlummert, naechster Weckruf.

    Der naechste Weckruf kommt aus den einzelnen Weckern (eingeschaltet, nicht
    geschlummert, mit Termin); aeltere App-Versionen ohne Weckerliste liefern
    nur "state".
    """
    from . import WeckerData  # Kreisimport vermeiden

    klingelt = False
    schlummert = False
    naechster: datetime | None = None
    for obj in hass.data.get(DOMAIN, {}).values():
        if not isinstance(obj, WeckerData) or not obj.payload:
            continue
        p = obj.payload
        klingelt = klingelt or bool(p.get("ringing"))
        schlummert = schlummert or bool(p.get("snoozed"))
        kandidaten: list[datetime] = []
        alarms = [a for a in (p.get("alarms") or []) if isinstance(a, dict)]
        if alarms:
            for a in alarms:
                if not a.get("enabled") or a.get("snoozed") or not a.get("next_trigger"):
                    continue
                dt = dt_util.parse_datetime(str(a["next_trigger"]))
                if dt is not None:
                    kandidaten.append(dt_util.as_utc(dt))
        elif p.get("state"):
            dt = dt_util.parse_datetime(str(p["state"]))
            if dt is not None:
                kandidaten.append(dt_util.as_utc(dt))
        for dt in kandidaten:
            if naechster is None or dt < naechster:
                naechster = dt
    return klingelt, schlummert, naechster


def zeit_lesen(wert: Any, vorgabe: str) -> time:
    """'HH:MM' oder 'HH:MM:SS' aus den Optionen; Unsinn faellt auf die Vorgabe zurueck."""
    for kandidat in (wert, vorgabe):
        if isinstance(kandidat, time):
            return kandidat
        t = dt_util.parse_time(str(kandidat)) if kandidat else None
        if t is not None:
            return t
    return time(0, 0)


def im_fenster(jetzt: time, von: time, bis: time) -> bool:
    """Liegt `jetzt` im Fenster von..bis? von == bis heisst: immer; ueber Mitternacht geht."""
    if von == bis:
        return True
    if von < bis:
        return von <= jetzt < bis
    return jetzt >= von or jetzt < bis


class WeckerLampe:
    """Faehrt den Ablauf auf der Box und am Hauptlicht nach dem Stand der Wecker-App."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: RelaisCoordinator) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self.aktiv = True                 # Schalter "Weckerlampe"; wird wiederhergestellt
        self.phase = PHASE_AUS
        self.naechster_wecker: datetime | None = None
        self.fehler: str | None = None
        self.hauptlicht_dabei = False     # Entscheidung fuer den laufenden Ablauf
        self._klingelt_alt = False
        self._timer_vorlauf: CALLBACK_TYPE | None = None
        self._timer_phase: list[CALLBACK_TYPE] = []   # Schritte und Ende der laufenden Phase
        self._unsub_signal: CALLBACK_TYPE | None = None

    # --- Einstellungen ------------------------------------------------

    @property
    def hauptlicht(self) -> str | None:
        wert = self.entry.options.get(CONF_HAUPTLICHT)
        return str(wert) if wert else None

    @property
    def fenster(self) -> tuple[time, time]:
        return (
            zeit_lesen(self.entry.options.get(CONF_HAUPTLICHT_VON), HAUPTLICHT_VON_STANDARD),
            zeit_lesen(self.entry.options.get(CONF_HAUPTLICHT_BIS), HAUPTLICHT_BIS_STANDARD),
        )

    def relais_der_box(self) -> set[int]:
        """Relais, die die Box meldet (ohne defekte); vor der ersten Antwort alle."""
        nrn = {int(r["nr"]) for r in self.coordinator.brauchbare_relais() if "nr" in r}
        return nrn or set(ALLE_RELAIS)

    @property
    def vorlauf_ab(self) -> datetime | None:
        if self.naechster_wecker is None:
            return None
        return self.naechster_wecker - timedelta(seconds=LAMPE_VORLAUF_S)

    def attribute(self) -> dict[str, Any]:
        von, bis = self.fenster
        return {
            "phase": self.phase,
            "relais": sorted(self.relais_der_box() & set(ALLE_RELAIS)),
            "hauptlicht": self.hauptlicht,
            "hauptlicht_fenster": f"{von.strftime('%H:%M')}-{bis.strftime('%H:%M')}",
            "hauptlicht_dabei": self.hauptlicht_dabei,
            "naechster_wecker": self.naechster_wecker.isoformat() if self.naechster_wecker else None,
            "vorlauf_ab": self.vorlauf_ab.isoformat() if self.vorlauf_ab else None,
            "fehler": self.fehler,
        }

    # --- Lebenszyklus -------------------------------------------------

    @callback
    def async_start(self) -> None:
        self._unsub_signal = async_dispatcher_connect(self.hass, SIGNAL_WECKER_ALLE, self._wecker_geaendert)
        self._wecker_geaendert()

    @callback
    def async_stop(self) -> None:
        if self._unsub_signal:
            self._unsub_signal()
            self._unsub_signal = None
        self._timer_vorlauf_weg()
        self._timer_phase_weg()

    async def async_setzen(self, an: bool, befehl: bool = True) -> None:
        """Schalter umlegen. Aus: alles sofort aus, keine Timer mehr."""
        self.aktiv = an
        if an:
            self._wecker_geaendert()
            return
        self._timer_vorlauf_weg()
        self._timer_phase_weg()
        if befehl and self.phase != PHASE_AUS:
            await self._alles_aus()
        self.phase = PHASE_AUS
        self.hauptlicht_dabei = False
        self._melden()

    # --- Reaktion auf den Wecker --------------------------------------

    @callback
    def _wecker_geaendert(self) -> None:
        klingelt, schlummert, naechster = _wecker_stand(self.hass)
        self.naechster_wecker = naechster
        flanke_an = klingelt and not self._klingelt_alt
        flanke_aus = not klingelt and self._klingelt_alt
        self._klingelt_alt = klingelt

        if not self.aktiv:
            self._melden()
            return

        if flanke_an:
            self._phase_starten(PHASE_KLINGELN)
        elif flanke_aus:
            self._phase_starten(PHASE_SCHLUMMER if schlummert else PHASE_NACHLAUF)
        elif klingelt and self.phase != PHASE_KLINGELN:
            # HA hat das Klingeln erst jetzt gesehen (Start, Neuladen)
            self._phase_starten(PHASE_KLINGELN)
        elif self.phase == PHASE_VORLAUF and not klingelt:
            # Vorlauf laeuft, aber der Weckruf ist weg (abgeschaltet, uebersprungen)
            jetzt = dt_util.utcnow()
            if naechster is None or naechster - jetzt > timedelta(seconds=LAMPE_VORLAUF_S + 30):
                self._abbrechen()

        self._vorlauf_planen(klingelt)
        self._melden()

    def _vorlauf_planen(self, klingelt: bool) -> None:
        """Timer auf "eine Minute vor dem naechsten Weckruf" stellen."""
        self._timer_vorlauf_weg()
        ab = self.vorlauf_ab
        if ab is None or klingelt or self.phase not in (PHASE_AUS, PHASE_NACHLAUF, PHASE_SCHLUMMER):
            return
        jetzt = dt_util.utcnow()
        if ab <= jetzt:
            # Schon im Vorlauffenster (z. B. HA gerade gestartet); nur, wenn
            # der Weckruf noch nicht lange vorbei ist
            if self.naechster_wecker and jetzt < self.naechster_wecker + timedelta(seconds=30):
                self._phase_starten(PHASE_VORLAUF)
            return
        self._timer_vorlauf = async_track_point_in_utc_time(self.hass, self._vorlauf_faellig, ab)

    @callback
    def _vorlauf_faellig(self, _jetzt: datetime) -> None:
        self._timer_vorlauf = None
        if self.aktiv and self.phase in (PHASE_AUS, PHASE_NACHLAUF, PHASE_SCHLUMMER):
            self._phase_starten(PHASE_VORLAUF)
            self._melden()

    # --- Phasen -------------------------------------------------------

    def _phase_starten(self, phase: str) -> None:
        """Phase wechseln: Timer der alten Phase weg, Schritte der neuen setzen."""
        self._timer_phase_weg()
        vorher = self.phase
        self.phase = phase
        self.coordinator.test_aktiv = False     # ein Ablauf verdraengt den Testmodus
        if vorher in (PHASE_AUS, PHASE_NACHLAUF) and phase in (PHASE_VORLAUF, PHASE_KLINGELN):
            # neuer Ablauf: jetzt faellt die Entscheidung ueber das Hauptlicht
            self.hauptlicht_dabei = self._hauptlicht_erlaubt()
        schritte: list[tuple[int, Callable[[], Awaitable[None]]]] = []
        for verz, nr, muster, dauer in RELAIS_ABLAUF.get(phase, []):
            if nr in self.relais_der_box():
                schritte.append((verz, self._relais_befehl(nr, muster, dauer)))
        if phase == PHASE_SCHLUMMER:
            schritte.append((0, self._relais_stopp()))
        if self.hauptlicht_dabei and self.hauptlicht:
            for verz, dienst, daten in LICHT_ABLAUF.get(phase, []):
                schritte.append((verz, self._licht_befehl(dienst, daten)))
        self._schritte_setzen(schritte)
        if phase == PHASE_NACHLAUF:
            self._timer_phase.append(async_call_later(self.hass, LAMPE_NACHLAUF_S, self._nachlauf_vorbei))

    def _schritte_setzen(self, schritte: list[tuple[int, Callable[[], Awaitable[None]]]]) -> None:
        """Schritte ohne Verzoegerung sofort (in Reihenfolge), die anderen per Timer."""
        sofort = [s for v, s in schritte if v <= 0]
        if sofort:
            self.hass.async_create_task(self._nacheinander(sofort))
        for verz, schritt in schritte:
            if verz > 0:
                self._timer_phase.append(
                    async_call_later(self.hass, verz, self._schritt_faellig(schritt))
                )

    def _schritt_faellig(self, schritt: Callable[[], Awaitable[None]]) -> Callable[[datetime], None]:
        @callback
        def _ausfuehren(_jetzt: datetime) -> None:
            self.hass.async_create_task(self._nacheinander([schritt]))
        return _ausfuehren

    async def _nacheinander(self, schritte: list[Callable[[], Awaitable[None]]]) -> None:
        for schritt in schritte:
            await schritt()
        self._melden()

    @callback
    def _nachlauf_vorbei(self, _jetzt: datetime) -> None:
        if self.phase == PHASE_NACHLAUF:
            self.phase = PHASE_AUS      # die Box hat die Muster selbst beendet
            self.hauptlicht_dabei = False
            self._timer_phase = []
            self._vorlauf_planen(False)
            self._melden()

    def _abbrechen(self) -> None:
        """Vorlauf ohne Weckruf: alles aus."""
        self._timer_phase_weg()
        self.phase = PHASE_AUS
        self.hass.async_create_task(self._alles_aus())

    def _hauptlicht_erlaubt(self) -> bool:
        if not self.hauptlicht:
            return False
        von, bis = self.fenster
        return im_fenster(dt_util.now().time().replace(tzinfo=None), von, bis)

    # --- Befehle ------------------------------------------------------

    def _relais_befehl(self, nr: int, muster: str, dauer_s: int) -> Callable[[], Awaitable[None]]:
        async def _senden() -> None:
            try:
                await self.coordinator.async_alarm_starten([nr], muster, dauer_s)
                self.fehler = None
            except Exception as err:  # noqa: BLE001
                self.fehler = str(err)
                _LOGGER.warning("Weckerlampe: Relais %s %s nicht gestartet: %s", nr, muster, err)
        return _senden

    def _relais_stopp(self) -> Callable[[], Awaitable[None]]:
        async def _senden() -> None:
            relais = sorted(self.relais_der_box() & set(ALLE_RELAIS))
            if not relais:
                return
            try:
                await self.coordinator.async_alarm_stoppen(relais)
                self.fehler = None
            except Exception as err:  # noqa: BLE001
                self.fehler = str(err)
                _LOGGER.warning("Weckerlampe: nicht gestoppt: %s", err)
        return _senden

    def _licht_befehl(self, dienst: str, daten: dict[str, Any]) -> Callable[[], Awaitable[None]]:
        async def _senden() -> None:
            entity = self.hauptlicht
            if not entity:
                return
            try:
                await self.hass.services.async_call(
                    "light", dienst, {"entity_id": entity, **daten}, blocking=True
                )
            except Exception as err:  # noqa: BLE001
                self.fehler = str(err)
                _LOGGER.warning("Weckerlampe: Hauptlicht %s %s: %s", entity, dienst, err)
        return _senden

    async def _alles_aus(self) -> None:
        """Leuchten stoppen und, wenn es mitgemacht hat, das Hauptlicht aus."""
        await self._relais_stopp()()
        if self.hauptlicht_dabei and self.hauptlicht:
            await self._licht_befehl("turn_off", {})()
        self.hauptlicht_dabei = False
        self._melden()

    # --- Kleinkram ----------------------------------------------------

    def _timer_vorlauf_weg(self) -> None:
        if self._timer_vorlauf:
            self._timer_vorlauf()
            self._timer_vorlauf = None

    def _timer_phase_weg(self) -> None:
        for t in self._timer_phase:
            t()
        self._timer_phase = []

    def _melden(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_LAMPE.format(self.entry.entry_id))
