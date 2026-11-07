"""Schalter der Relaisbox: je brauchbares Relais einer."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import RelaisEntity
from .relais import RelaisCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    obj = hass.data[DOMAIN][entry.entry_id]
    if not isinstance(obj, RelaisCoordinator):
        return
    async_add_entities(RelaisSwitch(obj, r["nr"]) for r in obj.brauchbare_relais())


class RelaisSwitch(RelaisEntity, SwitchEntity):
    """Ein Relais. Einschalten = Dauer-an, Ausschalten beendet auch ein Muster."""

    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator: RelaisCoordinator, nr: int) -> None:
        super().__init__(coordinator, f"relais_{nr}")
        self.nr = nr
        self._attr_name = f"Relais {nr}"

    @property
    def _relais(self) -> dict[str, Any] | None:
        return self.coordinator.relais(self.nr)

    @property
    def available(self) -> bool:
        return super().available and self._relais is not None

    @property
    def is_on(self) -> bool | None:
        r = self._relais
        return bool(r.get("an")) if r else None

    @property
    def icon(self) -> str:
        r = self._relais or {}
        muster = r.get("muster", "aus")
        if muster not in ("aus", "dauer"):
            return "mdi:alarm-light"
        return "mdi:electric-switch-closed" if r.get("an") else "mdi:electric-switch"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        r = self._relais or {}
        return {
            "nr": self.nr,
            "gpio": r.get("gpio"),
            "muster": r.get("muster"),
            "rest_s": r.get("rest_s"),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        try:
            await self.coordinator.async_schalten(self.nr, True)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err

    async def async_turn_off(self, **kwargs: Any) -> None:
        try:
            await self.coordinator.async_schalten(self.nr, False)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err
