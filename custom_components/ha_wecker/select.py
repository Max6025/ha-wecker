"""Auswahlfelder der Signalsaeule: Betriebsart und Status.

Betriebsart "Auto": der Status unten treibt die Saeule. Jeder Wechsel wird
angesagt (Aufbau, Abbau, Einrasten) und bleibt danach stehen, bis man einen
anderen Status waehlt.

Betriebsart "Manuell": der Status gilt nicht, stattdessen schaltet man die
Leuchten einzeln ueber die Schalter. Waehlt man dort doch einen Status, stellt
die Saeule selbst auf Auto zurueck - ein Status waehlen heisst, sie soll ihn
fahren.

Betriebsart "Ampel": die Saeule zeigt die Ampel der Garage - rot, wenn der 206
richtig drinsteht, gruen wenn frei. Beim Umschalten gibt der Tongeber zwei
ganz kurze Toene. Diese Betriebsart gibt es nur hier, nicht in der Saeule;
am Geraet steht sie dabei auf "manuell". Alles dazu in ampel.py.

Betriebsart "Drucker": die Saeule als Werkstattanzeige des 3D-Druckers -
gruen waehrend des Drucks, orange beim Ruesten, gruen und Hinweis, wenn ein
Teil zum Abholen liegt, rot bei einer Stoerung. Auch die gibt es nur hier;
sie steht nur im Schalter, wenn ein Drucker in Home Assistant eingerichtet
ist. Alles dazu in drucker.py.

Beide Plaetze schliessen sich gegenseitig aus: wer auf den einen schaltet,
verlaesst den anderen.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MODUS_AMPEL, MODUS_AUTO, MODUS_DRUCKER, MODUS_MANUELL
from .entity import SaeuleEntity
from .saeule import SaeuleCoordinator

BETRIEBSART = {
    MODUS_AUTO: "Auto",
    MODUS_MANUELL: "Manuell",
    MODUS_AMPEL: "Ampel",
    MODUS_DRUCKER: "Drucker",
}
# Die Betriebsarten, die es nur in Home Assistant gibt, mit dem Feld am
# Coordinator, an dem sie haengen
NUR_HIER = {MODUS_AMPEL: "ampel", MODUS_DRUCKER: "drucker"}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    obj = hass.data[DOMAIN][entry.entry_id]
    if not isinstance(obj, SaeuleCoordinator):
        return
    async_add_entities([BetriebsartSelect(obj), StatusSelect(obj)])


class BetriebsartSelect(SaeuleEntity, SelectEntity):
    """Auto, Manuell, Ampel oder Drucker - der Schalter ganz oben."""

    _attr_name = "Betriebsart"

    def __init__(self, coordinator: SaeuleCoordinator) -> None:
        super().__init__(coordinator, "betriebsart")

    def _modus(self, kennung: str) -> Any | None:
        """Die Betriebsart aus Home Assistant zu dieser Kennung."""
        return getattr(self.coordinator, NUR_HIER[kennung], None)

    @property
    def options(self) -> list[str]:
        """Ampel und Drucker stehen nur da, wenn es sie wirklich gibt.

        Die Ampel braucht den Garagen-ESP, der Drucker die Bambu-Integration.
        Was gerade laeuft, bleibt in der Liste - sonst stuende der Schalter
        auf einem Wert, den es laut Liste nicht gibt.
        """
        namen = [BETRIEBSART[MODUS_AUTO], BETRIEBSART[MODUS_MANUELL]]
        ampel = self._modus(MODUS_AMPEL)
        if ampel is not None and (ampel.garage() is not None or ampel.aktiv):
            namen.append(BETRIEBSART[MODUS_AMPEL])
        drucker = self._modus(MODUS_DRUCKER)
        if drucker is not None and (drucker.vorhanden or drucker.aktiv):
            namen.append(BETRIEBSART[MODUS_DRUCKER])
        return namen

    @property
    def _laeuft(self) -> str | None:
        """Welche Betriebsart aus Home Assistant gerade das Bild schreibt."""
        for kennung in NUR_HIER:
            modus = self._modus(kennung)
            if modus is not None and modus.aktiv:
                return kennung
        return None

    @property
    def icon(self) -> str:
        laeuft = self._laeuft
        if laeuft == MODUS_AMPEL:
            return "mdi:traffic-light"
        if laeuft == MODUS_DRUCKER:
            return "mdi:printer-3d-nozzle"
        return "mdi:robot" if self.coordinator.auto else "mdi:hand-back-right"

    @property
    def current_option(self) -> str | None:
        """Ampel und Drucker stehen ueber dem, was das Geraet meldet.

        Die Saeule selbst kennt diese Betriebsarten nicht - sie steht dabei
        auf "manuell". Was hier zaehlt, ist, wer die Stufen stellt.
        """
        laeuft = self._laeuft
        if laeuft is not None:
            return BETRIEBSART[laeuft]
        return BETRIEBSART.get(self.coordinator.modus)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attr: dict[str, Any] = {"geraet": self.coordinator.modus}
        ampel = self._modus(MODUS_AMPEL)
        if ampel is not None:
            attr.update(ampel.attribute())
        # Die Daten des Druckers stehen am eigenen Sensor; hier nur, was
        # gerade gilt - sonst traegt der Schalter zwei Geraete im Attribut.
        drucker = self._modus(MODUS_DRUCKER)
        if drucker is not None and drucker.aktiv:
            attr.update(drucker.attribute())
        return attr

    async def async_select_option(self, option: str) -> None:
        gewaehlt = next(
            (k for k, name in BETRIEBSART.items() if name == option), None
        )
        try:
            if gewaehlt in NUR_HIER:
                modus = self._modus(gewaehlt)
                if modus is None:
                    raise HomeAssistantError(
                        f"Die Betriebsart \"{option}\" gibt es hier nicht"
                    )
                # Die beiden schliessen sich aus: erst die andere beenden
                for kennung in NUR_HIER:
                    if kennung != gewaehlt:
                        anderer = self._modus(kennung)
                        if anderer is not None:
                            anderer.verlassen()
                await modus.async_an()
            else:
                # Erst jede Betriebsart beenden, dann umstellen: sonst zieht
                # sie ihr Bild gleich wieder nach.
                self.coordinator.betriebsart_verlassen()
                await self.coordinator.async_modus(option == BETRIEBSART[MODUS_AUTO])
        except HomeAssistantError:
            raise
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err
        self.async_write_ha_state()


class StatusSelect(SaeuleEntity, SelectEntity):
    """Der Status, den die Saeule anzeigt. Die Liste kommt von der Saeule."""

    _attr_name = "Status"
    _attr_icon = "mdi:traffic-light"

    def __init__(self, coordinator: SaeuleCoordinator) -> None:
        super().__init__(coordinator, "status")

    @property
    def options(self) -> list[str]:
        return self.coordinator.status_namen()

    @property
    def current_option(self) -> str | None:
        return self.coordinator.status_name(self.coordinator.status)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "kennung": self.coordinator.status,
            "wechsel_laeuft": bool((self.coordinator.data or {}).get("wechsel")),
            "gilt": self.coordinator.auto,
        }

    async def async_select_option(self, option: str) -> None:
        kennung = self.coordinator.status_id(option)
        if kennung is None:
            raise HomeAssistantError(f"Unbekannter Status: {option}")
        # Einen Status zu waehlen heisst, die Saeule soll ihn fahren - und
        # nicht die Garagenampel oder der Drucker. Dieselbe Regel wie in der
        # Firmware, die bei einem Status von Manuell auf Auto zurueckstellt.
        self.coordinator.betriebsart_verlassen()
        try:
            await self.coordinator.async_status(kennung)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err
