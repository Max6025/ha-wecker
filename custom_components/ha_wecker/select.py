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
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MODUS_AMPEL, MODUS_AUTO, MODUS_MANUELL
from .entity import SaeuleEntity
from .saeule import SaeuleCoordinator

BETRIEBSART = {MODUS_AUTO: "Auto", MODUS_MANUELL: "Manuell", MODUS_AMPEL: "Ampel"}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    obj = hass.data[DOMAIN][entry.entry_id]
    if not isinstance(obj, SaeuleCoordinator):
        return
    async_add_entities([BetriebsartSelect(obj), StatusSelect(obj)])


class BetriebsartSelect(SaeuleEntity, SelectEntity):
    """Auto, Manuell oder Ampel - der Schalter ganz oben."""

    _attr_name = "Betriebsart"

    def __init__(self, coordinator: SaeuleCoordinator) -> None:
        super().__init__(coordinator, "betriebsart")

    @property
    def options(self) -> list[str]:
        """Ampel steht nur da, wenn es den Garagen-ESP wirklich gibt."""
        ampel = self.coordinator.ampel
        namen = [BETRIEBSART[MODUS_AUTO], BETRIEBSART[MODUS_MANUELL]]
        if ampel is not None and (ampel.garage() is not None or ampel.aktiv):
            namen.append(BETRIEBSART[MODUS_AMPEL])
        return namen

    @property
    def _ampelmodus(self) -> bool:
        ampel = self.coordinator.ampel
        return bool(ampel is not None and ampel.aktiv)

    @property
    def icon(self) -> str:
        if self._ampelmodus:
            return "mdi:traffic-light"
        return "mdi:robot" if self.coordinator.auto else "mdi:hand-back-right"

    @property
    def current_option(self) -> str | None:
        """Ampel steht ueber dem, was das Geraet meldet.

        Die Saeule selbst kennt die Betriebsart nicht - sie steht dabei auf
        "manuell". Was hier zaehlt, ist, wer die Stufen stellt.
        """
        if self._ampelmodus:
            return BETRIEBSART[MODUS_AMPEL]
        return BETRIEBSART.get(self.coordinator.modus)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ampel = self.coordinator.ampel
        attr: dict[str, Any] = {"geraet": self.coordinator.modus}
        if ampel is not None:
            attr.update(ampel.attribute())
        return attr

    async def async_select_option(self, option: str) -> None:
        ampel = self.coordinator.ampel
        try:
            if option == BETRIEBSART[MODUS_AMPEL]:
                if ampel is None:
                    raise HomeAssistantError("Die Betriebsart \"Ampel\" gibt es hier nicht")
                await ampel.async_an()
            else:
                # Erst die Betriebsart beenden, dann umstellen: sonst zieht
                # sie das Ampelbild gleich wieder nach.
                if ampel is not None:
                    ampel.verlassen()
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
        # nicht die Garagenampel. Dieselbe Regel wie in der Firmware, die bei
        # einem Status von Manuell auf Auto zurueckstellt.
        if self.coordinator.ampel is not None:
            self.coordinator.ampel.verlassen()
        try:
            await self.coordinator.async_status(kennung)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err
