"""Weckerlampe: eine Leuchte an der Relaisbox folgt dem Wecker der App.

Ablauf, solange der Schalter "Weckerlampe" an ist:
- eine Minute vor dem naechsten Weckruf: Muster "Vorlauf" (Vorgabe blinken)
- der Wecker klingelt: das Muster laeuft weiter; fehlte der Vorlauf (etwa nach
  dem Schlummern oder weil HA gerade erst gestartet ist), startet es jetzt
- Schlummern: Lampe aus; klingelt es wieder, geht es wie beim Klingeln weiter
- Wecker beendet: Muster "Nachlauf" (Vorgabe doppelblitz) fuer fuenf Minuten,
  dann aus

Die Muster laufen auf der Relaisbox selbst, jeder Start bekommt eine
Hoechstdauer. Bleibt die App stumm (Handy aus, kein Netz), geht die Lampe
spaetestens nach dieser Dauer von allein aus.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .const import (
    CONF_LAMPE_MUSTER_NACHLAUF,
    CONF_LAMPE_MUSTER_VORLAUF,
    CONF_LAMPE_RELAIS,
    DOMAIN,
    LAMPE_KLINGELN_MAX_S,
    LAMPE_MUSTER_NACHLAUF_STANDARD,
    LAMPE_MUSTER_VORLAUF_STANDARD,
    LAMPE_NACHLAUF_S,
    LAMPE_RELAIS_STANDARD,
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


class WeckerLampe:
    """Steuert ein Relais der Box nach dem Stand der Wecker-App."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: RelaisCoordinator) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self.aktiv = True                 # Schalter "Weckerlampe"; wird wiederhergestellt
        self.phase = PHASE_AUS
        self.naechster_wecker: datetime | None = None
        self.fehler: str | None = None
        self._klingelt_alt = False
        self._timer_vorlauf: CALLBACK_TYPE | None = None
        self._timer_nachlauf: CALLBACK_TYPE | None = None
        self._unsub_signal: CALLBACK_TYPE | None = None

    # --- Einstellungen ------------------------------------------------

    @property
    def relais_nr(self) -> int:
        try:
            return int(self.entry.options.get(CONF_LAMPE_RELAIS, LAMPE_RELAIS_STANDARD))
        except (TypeError, ValueError):
            return LAMPE_RELAIS_STANDARD

    @property
    def muster_vorlauf(self) -> str:
        return str(self.entry.options.get(CONF_LAMPE_MUSTER_VORLAUF) or LAMPE_MUSTER_VORLAUF_STANDARD)

    @property
    def muster_nachlauf(self) -> str:
        return str(self.entry.options.get(CONF_LAMPE_MUSTER_NACHLAUF) or LAMPE_MUSTER_NACHLAUF_STANDARD)

    @property
    def vorlauf_ab(self) -> datetime | None:
        if self.naechster_wecker is None:
            return None
        return self.naechster_wecker - timedelta(seconds=LAMPE_VORLAUF_S)

    def attribute(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "relais": self.relais_nr,
            "muster_vorlauf": self.muster_vorlauf,
            "muster_nachlauf": self.muster_nachlauf,
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
        self._timer_nachlauf_weg()

    async def async_setzen(self, an: bool, befehl: bool = True) -> None:
        """Schalter umlegen. Aus: Lampe sofort aus, keine Timer mehr."""
        self.aktiv = an
        if an:
            self._wecker_geaendert()
            return
        self._timer_vorlauf_weg()
        self._timer_nachlauf_weg()
        if befehl and self.phase != PHASE_AUS:
            await self._stoppen()
        self.phase = PHASE_AUS
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
            self._klingeln()
        elif flanke_aus:
            if schlummert:
                self._schlummern()
            else:
                self._beendet()
        elif klingelt and self.phase not in (PHASE_KLINGELN,):
            # HA hat das Klingeln erst jetzt gesehen (Start, Neuladen)
            self._klingeln()
        elif self.phase == PHASE_VORLAUF and not klingelt:
            # Vorlauf laeuft, aber der Weckruf ist weg (abgeschaltet, uebersprungen)
            jetzt = dt_util.utcnow()
            if naechster is None or naechster - jetzt > timedelta(seconds=LAMPE_VORLAUF_S + 30):
                self._ausschalten()

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
                self._vorlauf()
            return
        self._timer_vorlauf = async_track_point_in_utc_time(self.hass, self._vorlauf_faellig, ab)

    @callback
    def _vorlauf_faellig(self, _jetzt: datetime) -> None:
        self._timer_vorlauf = None
        if self.aktiv and self.phase in (PHASE_AUS, PHASE_NACHLAUF, PHASE_SCHLUMMER):
            self._vorlauf()
            self._melden()

    @callback
    def _nachlauf_vorbei(self, _jetzt: datetime) -> None:
        self._timer_nachlauf = None
        if self.phase == PHASE_NACHLAUF:
            self.phase = PHASE_AUS      # die Box hat das Muster selbst beendet
            self._vorlauf_planen(False)
            self._melden()

    # --- Phasen -------------------------------------------------------

    def _vorlauf(self) -> None:
        self._timer_nachlauf_weg()
        self.phase = PHASE_VORLAUF
        self._starten(self.muster_vorlauf, LAMPE_VORLAUF_S + LAMPE_KLINGELN_MAX_S)

    def _klingeln(self) -> None:
        self._timer_nachlauf_weg()
        vorher = self.phase
        self.phase = PHASE_KLINGELN
        if vorher == PHASE_VORLAUF:
            return                      # Muster laeuft schon, nicht neu starten
        self._starten(self.muster_vorlauf, LAMPE_KLINGELN_MAX_S)

    def _schlummern(self) -> None:
        self._timer_nachlauf_weg()
        self.phase = PHASE_SCHLUMMER
        self.hass.async_create_task(self._stoppen())

    def _beendet(self) -> None:
        self._timer_nachlauf_weg()
        self.phase = PHASE_NACHLAUF
        self._starten(self.muster_nachlauf, LAMPE_NACHLAUF_S)
        self._timer_nachlauf = async_call_later(self.hass, LAMPE_NACHLAUF_S, self._nachlauf_vorbei)

    def _ausschalten(self) -> None:
        self._timer_nachlauf_weg()
        self.phase = PHASE_AUS
        self.hass.async_create_task(self._stoppen())

    # --- Befehle an die Box -------------------------------------------

    def _starten(self, muster: str, dauer_s: int) -> None:
        self.hass.async_create_task(self._befehl_starten(muster, dauer_s))

    async def _befehl_starten(self, muster: str, dauer_s: int) -> None:
        try:
            await self.coordinator.async_alarm_starten([self.relais_nr], muster, dauer_s)
            self.fehler = None
        except Exception as err:  # noqa: BLE001
            self.fehler = str(err)
            _LOGGER.warning("Weckerlampe: %s nicht gestartet: %s", muster, err)
        self._melden()

    async def _stoppen(self) -> None:
        try:
            await self.coordinator.async_alarm_stoppen([self.relais_nr])
            self.fehler = None
        except Exception as err:  # noqa: BLE001
            self.fehler = str(err)
            _LOGGER.warning("Weckerlampe: nicht gestoppt: %s", err)
        self._melden()

    # --- Kleinkram ----------------------------------------------------

    def _timer_vorlauf_weg(self) -> None:
        if self._timer_vorlauf:
            self._timer_vorlauf()
            self._timer_vorlauf = None

    def _timer_nachlauf_weg(self) -> None:
        if self._timer_nachlauf:
            self._timer_nachlauf()
            self._timer_nachlauf = None

    def _melden(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_LAMPE.format(self.entry.entry_id))
