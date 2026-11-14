"""Auswahlfelder der Signalsaeule: Betriebsart und Status.

Betriebsart "Auto": der Status unten treibt die Saeule. Jeder Wechsel wird
angesagt (Aufbau, Abbau, Einrasten) und bleibt danach stehen, bis man einen
anderen Status waehlt.

Betriebsart "Manuell": der Status gilt nicht, stattdessen schaltet man die
Leuchten einzeln ueber die Schalter. Waehlt man dort doch einen Status, stellt
die Saeule selbst auf Auto zurueck - ein Status waehlen heisst, sie soll ihn
fahren.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MODUS_AUTO
from .entity import SaeuleEntity
from .saeule import SaeuleCoordinator

BETRIEBSART = {MODUS_AUTO: "Auto", "manuell": "Manuell"}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    obj = hass.data[DOMAIN][entry.entry_id]
    if not isinstance(obj, SaeuleCoordinator):
        return
    async_add_entities([BetriebsartSelect(obj), StatusSelect(obj)])


class BetriebsartSelect(SaeuleEntity, SelectEntity):
    """Auto oder Manuell - der Schalter ganz oben."""

    _attr_name = "Betriebsart"
    _attr_options = list(BETRIEBSART.values())

    def __init__(self, coordinator: SaeuleCoordinator) -> None:
        super().__init__(coordinator, "betriebsart")

    @property
    def icon(self) -> str:
        return "mdi:robot" if self.coordinator.auto else "mdi:hand-back-right"

    @property
    def current_option(self) -> str | None:
        return BETRIEBSART.get(self.coordinator.modus)

    async def async_select_option(self, option: str) -> None:
        try:
            await self.coordinator.async_modus(option == BETRIEBSART[MODUS_AUTO])
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err


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
        try:
            await self.coordinator.async_status(kennung)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err
