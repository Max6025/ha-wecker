"""Strom fuer die Signalsaeule: Steckdose nach dem Weckplan schalten.

Die Saeule haengt an einer schaltbaren Steckdose (bei Max ein Shelly Plug).
Sie soll kurz vor dem Weckruf Strom bekommen - sonst ist der Arduino noch
nicht im Netz, wenn der Vorlauf ihn ansprechen will - und abends wieder aus.

Der Plan steht als JSON in den Optionen des Weckers:

    {"version": 1, "vorlauf": 300,
     "aus": [{"wochentage": ["mo","di","mi","do","fr"], "zeit": "21:00"},
             {"wochentage": ["sa","so"], "zeit": "22:00"}]}

"vorlauf" sind Sekunden vor dem Weckruf. Die Weckzeit kommt aus demselben
Rechenweg wie beim Weckablauf (ablauf.naechste_weckzeit) - es gibt keine
zweite Wahrheit darueber, wann geweckt wird.

Ausgeschaltet wird nur zum Zeitpunkt selbst, nie nachtraeglich: war Home
Assistant um 21 Uhr aus, bleibt die Steckdose an, bis die naechste
Ausschaltzeit kommt. Eine Steckdose, die zu lange an ist, kostet nichts -
eine, die zur falschen Zeit ausgeht, nimmt der Saeule mitten im Betrieb den
Strom. Eingeschaltet wird dagegen auch nachtraeglich: nach einem Neustart um
sechs Uhr morgens soll die Saeule wieder Strom haben.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, time, timedelta
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .ablauf import TAGE, naechste_weckzeit, zeit_lesen
from .const import CONF_STROM, CONF_STROMPLAN, SIGNAL_WECKER_ALLE

_LOGGER = logging.getLogger(__name__)

# Ohne eigene Datei gilt das hier: fuenf Minuten vor dem Weckruf an, werktags
# um 21 Uhr aus, am Wochenende um 22 Uhr.
STANDARD_STROMPLAN: dict[str, Any] = {
    "version": 1,
    "vorlauf": 300,
    "aus": [
        {"wochentage": ["mo", "di", "mi", "do", "fr"], "zeit": "21:00"},
        {"wochentage": ["sa", "so"], "zeit": "22:00"},
    ],
}


def stromplan_lesen(roh: Any) -> tuple[dict[str, Any], str | None]:
    """JSON pruefen. Gibt (Plan, Fehlertext) - bei Fehler den Standardplan."""
    if not roh:
        return STANDARD_STROMPLAN, None
    daten = roh
    if isinstance(roh, str):
        try:
            daten = json.loads(roh)
        except ValueError as err:
            return STANDARD_STROMPLAN, f"JSON nicht lesbar: {err}"
    if not isinstance(daten, dict):
        return STANDARD_STROMPLAN, "Der Stromplan ist kein Objekt"
    if "vorlauf" in daten:
        try:
            int(daten["vorlauf"])
        except (TypeError, ValueError):
            return STANDARD_STROMPLAN, "\"vorlauf\" ist keine Zahl"
    if not isinstance(daten.get("aus"), list):
        return STANDARD_STROMPLAN, "Es fehlt die Liste \"aus\""
    for i, eintrag in enumerate(daten["aus"], 1):
        if not isinstance(eintrag, dict):
            return STANDARD_STROMPLAN, f"Ausschaltzeit {i} ist kein Objekt"
        if not dt_util.parse_time(str(eintrag.get("zeit") or "")):
            return STANDARD_STROMPLAN, f"Ausschaltzeit {i}: \"zeit\" fehlt oder ist keine Uhrzeit"
        tage = eintrag.get("wochentage")
        if tage is not None and not isinstance(tage, list):
            return STANDARD_STROMPLAN, f"Ausschaltzeit {i}: \"wochentage\" ist keine Liste"
    return daten, None


def vorlauf_lesen(plan: dict[str, Any]) -> int:
    try:
        return max(0, int(plan.get("vorlauf", 300)))
    except (TypeError, ValueError):
        return 300


def naechstes_aus(plan: dict[str, Any], jetzt: datetime) -> datetime | None:
    """Naechster Ausschaltzeitpunkt nach `jetzt` (UTC), aus den Wochentagen."""
    lokal = dt_util.as_local(jetzt)
    treffer: datetime | None = None
    for tage_weiter in range(0, 8):
        tag = lokal + timedelta(days=tage_weiter)
        name = TAGE[tag.weekday()]
        for eintrag in plan.get("aus", []):
            if not isinstance(eintrag, dict):
                continue
            tage = eintrag.get("wochentage") or TAGE
            if name not in [str(t).lower()[:2] for t in tage]:
                continue
            uhr = zeit_lesen(eintrag.get("zeit"), time(22, 0))
            kandidat = tag.replace(
                hour=uhr.hour, minute=uhr.minute, second=uhr.second, microsecond=0
            )
            if kandidat <= lokal:
                continue
            kandidat = dt_util.as_utc(kandidat)
            if treffer is None or kandidat < treffer:
                treffer = kandidat
        if treffer is not None:
            return treffer
    return treffer


class Stromplan:
    """Schaltet die Steckdose der Saeule vor dem Weckruf an und abends aus."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        notiz: Callable[[str, str, str], None],
        melden: Callable[[], None],
    ) -> None:
        self.hass = hass
        self.entry = entry
        self._notiz = notiz
        # Der Schalter zeigt die Zeitpunkte als Attribut. Er wird am selben
        # Signal aufgefrischt wie der Weckablauf - und zwar vor uns, weil der
        # Ablauf zuerst angemeldet ist. Ohne eigenes Melden stuende dort noch
        # der Stand von vorher.
        self._melden = melden
        self.an_um: datetime | None = None
        self.aus_um: datetime | None = None
        self._timer: list[CALLBACK_TYPE] = []
        self._unsub_signal: CALLBACK_TYPE | None = None
        # Schon erledigte Zeitpunkte, damit eine Neuplanung sie nicht
        # gleich wieder ausloest (der Weckruf ist ja noch derselbe).
        self._an_erledigt: datetime | None = None
        self._aus_erledigt: datetime | None = None
        # Eine An-Phase wird nur einmal nachgeholt. Sonst wuerde jede Meldung
        # der App die Dose wieder einschalten, nachdem sie von Hand aus wurde.
        self._phase_gesehen = False

    # --- Einstellungen ------------------------------------------------

    @property
    def entitaet(self) -> str | None:
        wert = self.entry.options.get(CONF_STROM)
        return str(wert) if wert else None

    @property
    def plan(self) -> tuple[dict[str, Any], str | None]:
        return stromplan_lesen(self.entry.options.get(CONF_STROMPLAN))

    def attribute(self) -> dict[str, Any]:
        plan, fehler = self.plan
        return {
            "entitaet": self.entitaet or "nicht eingestellt",
            "vorlauf_minuten": round(vorlauf_lesen(plan) / 60, 1),
            "naechstes_an": self.an_um.isoformat() if self.an_um else None,
            "naechstes_aus": self.aus_um.isoformat() if self.aus_um else None,
            "fehler": fehler,
        }

    # --- Lebenszyklus -------------------------------------------------

    @callback
    def async_start(self) -> None:
        self._unsub_signal = async_dispatcher_connect(
            self.hass, SIGNAL_WECKER_ALLE, self._wecker_geaendert
        )
        self.async_planen()

    @callback
    def async_stop(self) -> None:
        if self._unsub_signal:
            self._unsub_signal()
            self._unsub_signal = None
        self._timer_weg()

    @callback
    def _wecker_geaendert(self) -> None:
        self.async_planen()

    # --- Planung ------------------------------------------------------

    @callback
    def async_planen(self) -> None:
        """Beide Zeitpunkte neu auf Timer legen.

        Faengt dabei eine laufende An-Phase ab: muesste die Dose jetzt an
        sein, ist sie es aber nicht - nach einem Neustart etwa, oder weil die
        App ihre Weckzeiten erst jetzt gemeldet hat -, wird eingeschaltet.
        Das passiert einmal je An-Phase: wer die Dose von Hand ausschaltet,
        bekommt sie nicht bei der naechsten Meldung wieder angedreht.
        Ausgeschaltet wird dabei nie.
        """
        self._timer_weg()
        ziel = self.entitaet
        plan, fehler = self.plan
        if fehler:
            self._notiz("Stromplan", fehler, "fehler")
        if not ziel:
            self.an_um = self.aus_um = None
            return

        jetzt = dt_util.utcnow()
        _, _, naechster = naechste_weckzeit(self.hass)
        self.an_um = (
            naechster - timedelta(seconds=vorlauf_lesen(plan)) if naechster else None
        )
        self.aus_um = naechstes_aus(plan, jetzt)

        if self.an_um is not None and self.an_um != self._an_erledigt:
            if self.an_um <= jetzt:
                self._an_erledigt = self.an_um
                self._phase_gesehen = True      # nichts mehr nachzuholen
                self._schalten_spaeter(True, "Weckruf steht an")
            else:
                self._timer.append(
                    async_track_point_in_utc_time(
                        self.hass, self._an_faellig, self.an_um
                    )
                )
        if self.aus_um is not None and self.aus_um != self._aus_erledigt:
            self._timer.append(
                async_track_point_in_utc_time(self.hass, self._aus_faellig, self.aus_um)
            )

        soll = self.soll_an(jetzt)
        if soll is True:
            if not self._phase_gesehen and not self._ist_an():
                # Ohne die Marke _an_erledigt zu setzen: die gehoert dem
                # Einschaltzeitpunkt, der hier noch bevorsteht. Wuerde sie
                # hier verbogen, faende der Timer nachher nichts mehr vor.
                self._schalten_spaeter(True, "nachgeholt, die Phase lief schon")
            self._phase_gesehen = True
        elif soll is False:
            self._phase_gesehen = False
        self._melden()

    def soll_an(self, jetzt: datetime) -> bool | None:
        """Muesste die Steckdose jetzt an sein? None = nicht zu sagen.

        Steht als naechstes ein Ausschalten an und erst danach das naechste
        Einschalten, dann laeuft gerade eine An-Phase. Ohne bekannten Wecker
        laesst sich nichts sagen - dann bleibt alles, wie es ist.
        """
        if self.an_um is None:
            return None
        if self.an_um <= jetzt:
            return True
        if self.aus_um is None:
            return None
        return self.aus_um < self.an_um

    def _ist_an(self) -> bool:
        ziel = self.entitaet
        zustand = self.hass.states.get(ziel) if ziel else None
        return zustand is not None and zustand.state == "on"

    @callback
    def _an_faellig(self, _jetzt: datetime) -> None:
        self._an_erledigt = self.an_um
        # Die An-Phase beginnt jetzt - sie muss nicht auch nachgeholt werden
        self._phase_gesehen = True
        self._schalten_spaeter(True, "fuenf Minuten vor dem Weckruf")
        self.async_planen()

    @callback
    def _aus_faellig(self, _jetzt: datetime) -> None:
        self._aus_erledigt = self.aus_um
        self._schalten_spaeter(False, "Ausschaltzeit erreicht")
        self.async_planen()

    @callback
    def _schalten_spaeter(self, an: bool, warum: str) -> None:
        """Schalten anstossen - und die Planung nicht daran haengen.

        Home Assistant startet eine so erzeugte Aufgabe sofort und laesst sie
        bis zum ersten echten Warten durchlaufen. Wuerde _schalten am Ende
        neu planen, liefe das hier synchron zurueck in die Planung - einmal
        im Kreis fuer jeden Schaltvorgang.
        """
        self.hass.async_create_task(self._schalten(an, warum))

    # --- Schalten -----------------------------------------------------

    async def async_sichern(self) -> None:
        """Strom sofort einschalten (Probelauf: sonst antwortet die Saeule nicht)."""
        if self.entitaet and not self._ist_an():
            await self._schalten(True, "fuer den Probelauf")

    async def _schalten(self, an: bool, warum: str) -> None:
        ziel = self.entitaet
        if not ziel:
            return
        bereich = ziel.split(".", 1)[0]
        dienst = "turn_on" if an else "turn_off"
        try:
            await self.hass.services.async_call(
                bereich, dienst, {"entity_id": ziel}, blocking=True
            )
            self._notiz(f"Strom {ziel}", f"{'an' if an else 'aus'} ({warum})", "ok")
        except Exception as err:  # noqa: BLE001
            self._notiz(f"Strom {ziel}", f"{'an' if an else 'aus'}: {err}", "fehler")
            _LOGGER.warning("Stromplan: %s %s: %s", ziel, dienst, err)

    def _timer_weg(self) -> None:
        for t in self._timer:
            t()
        self._timer = []
