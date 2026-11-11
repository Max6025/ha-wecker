"""Weckerlampe: die Leuchten an der Relaisbox folgen dem Wecker der App.

Jedes Relais hat im Plan (Optionen) ein Muster fuer "aktiv" und eins fuer
"nachlauf"; Vorgabe: 1 Lampe dreifachblitz/doppelblitz, 2 Gruen und 3 Rot
langsam/aus, 4 Warnleuchte dauer/aus (die blinkt von selbst).

Ablauf, solange der Schalter "Weckerlampe" an ist:
- eine Minute vor dem naechsten Weckruf: die "aktiv"-Muster starten
- der Wecker klingelt: sie laufen weiter; fehlte der Vorlauf (etwa nach
  dem Schlummern oder weil HA gerade erst gestartet ist), starten sie jetzt
- Schlummern: alles aus; klingelt es wieder, geht es wie beim Klingeln weiter
- Wecker beendet: die "nachlauf"-Muster fuer fuenf Minuten, der Rest aus

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
    CONF_LAMPE_PLAN,
    DOMAIN,
    LAMPE_AKTIV,
    LAMPE_KLINGELN_MAX_S,
    LAMPE_MUSTER_LISTE,
    LAMPE_NACHLAUF,
    LAMPE_NACHLAUF_S,
    LAMPE_PLAN_FELDER,
    LAMPE_PLAN_SONST,
    LAMPE_PLAN_STANDARD,
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


def plan_fuer(optionen: Any, relais: list[int]) -> dict[int, dict[str, str]]:
    """Plan fuer die genannten Relais: gespeicherte Optionen ueber den Vorgaben.

    Unbekannte Muster fallen auf die Vorgabe zurueck, damit ein Tippfehler in
    den Optionen nie einen Befehl mit unbekanntem Muster an die Box schickt.
    """
    gespeichert = optionen if isinstance(optionen, dict) else {}
    plan: dict[int, dict[str, str]] = {}
    for nr in relais:
        vorgabe = LAMPE_PLAN_STANDARD.get(nr, LAMPE_PLAN_SONST)
        eigen = gespeichert.get(str(nr)) or gespeichert.get(nr) or {}
        eintrag: dict[str, str] = {}
        for phase in (LAMPE_AKTIV, LAMPE_NACHLAUF):
            wert = str(eigen.get(phase) or vorgabe[phase]) if isinstance(eigen, dict) else vorgabe[phase]
            eintrag[phase] = wert if wert in LAMPE_MUSTER_LISTE else vorgabe[phase]
        plan[nr] = eintrag
    return plan


class WeckerLampe:
    """Steuert die Relais der Box nach dem Stand der Wecker-App."""

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

    def plan(self) -> dict[int, dict[str, str]]:
        """Muster je Relais: Optionen ueber den Vorgaben, nur Relais, die die Box meldet."""
        return plan_fuer(self.entry.options.get(CONF_LAMPE_PLAN), self.relais_nummern())

    def relais_nummern(self) -> list[int]:
        """Relais der Box (ohne defekte); vor der ersten Antwort die Vorgabe 1-4."""
        nrn = [int(r["nr"]) for r in self.coordinator.brauchbare_relais() if "nr" in r]
        return nrn or list(range(1, LAMPE_PLAN_FELDER + 1))

    def relais_beteiligt(self) -> list[int]:
        """Relais, die in irgendeiner Phase etwas tun (die muessen beim Stopp aus)."""
        return sorted(nr for nr, m in self.plan().items() if m[LAMPE_AKTIV] != "aus" or m[LAMPE_NACHLAUF] != "aus")

    @property
    def vorlauf_ab(self) -> datetime | None:
        if self.naechster_wecker is None:
            return None
        return self.naechster_wecker - timedelta(seconds=LAMPE_VORLAUF_S)

    def attribute(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "relais": self.relais_beteiligt(),
            "plan": {str(nr): dict(m) for nr, m in sorted(self.plan().items())},
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
        self._starten(LAMPE_AKTIV, LAMPE_VORLAUF_S + LAMPE_KLINGELN_MAX_S)

    def _klingeln(self) -> None:
        self._timer_nachlauf_weg()
        vorher = self.phase
        self.phase = PHASE_KLINGELN
        if vorher == PHASE_VORLAUF:
            return                      # Muster laeuft schon, nicht neu starten
        self._starten(LAMPE_AKTIV, LAMPE_KLINGELN_MAX_S)

    def _schlummern(self) -> None:
        self._timer_nachlauf_weg()
        self.phase = PHASE_SCHLUMMER
        self.hass.async_create_task(self._stoppen())

    def _beendet(self) -> None:
        self._timer_nachlauf_weg()
        self.phase = PHASE_NACHLAUF
        self._starten(LAMPE_NACHLAUF, LAMPE_NACHLAUF_S, rest_aus=True)
        self._timer_nachlauf = async_call_later(self.hass, LAMPE_NACHLAUF_S, self._nachlauf_vorbei)

    def _ausschalten(self) -> None:
        self._timer_nachlauf_weg()
        self.phase = PHASE_AUS
        self.hass.async_create_task(self._stoppen())

    # --- Befehle an die Box -------------------------------------------

    def _starten(self, phase: str, dauer_s: int, rest_aus: bool = False) -> None:
        self.hass.async_create_task(self._befehl_starten(phase, dauer_s, rest_aus))

    async def _befehl_starten(self, phase: str, dauer_s: int, rest_aus: bool) -> None:
        """Je Muster ein Befehl an die Box; "aus" wird gestoppt, wenn rest_aus gesetzt ist.

        rest_aus gilt fuer den Nachlauf: Relais, die dort nichts mehr tun,
        liefen vorher und muessen aus.
        """
        gruppen: dict[str, list[int]] = {}
        for nr, m in self.plan().items():
            gruppen.setdefault(m[phase], []).append(nr)
        aus = gruppen.pop("aus", [])
        try:
            if rest_aus and aus:
                await self.coordinator.async_alarm_stoppen(sorted(aus))
            for muster in sorted(gruppen):
                await self.coordinator.async_alarm_starten(gruppen[muster], muster, dauer_s)
            self.fehler = None
        except Exception as err:  # noqa: BLE001
            self.fehler = str(err)
            _LOGGER.warning("Weckerlampe: %s nicht gestartet: %s", phase, err)
        self._melden()

    async def _stoppen(self) -> None:
        relais = self.relais_beteiligt()
        if not relais:
            return
        try:
            await self.coordinator.async_alarm_stoppen(relais)
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
