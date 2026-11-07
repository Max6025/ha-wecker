"""Knoepfe: "Alarm stoppen" der Relaisbox."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    if isinstance(obj, RelaisCoordinator):
        async_add_entities([AlarmStopButton(obj)])
        return
    # Der Wecker hat keine Knoepfe: die App laeuft nicht im Hintergrund und
    # bietet nichts zum Abfragen.



class AlarmStopButton(RelaisEntity, ButtonEntity):
    """Beendet alle Muster auf der Relaisbox und schaltet die Relais aus."""

    _attr_name = "Alarm stoppen"
    _attr_icon = "mdi:alarm-light-off"

    def __init__(self, coordinator: RelaisCoordinator) -> None:
        super().__init__(coordinator, "alarm_stop")

    async def async_press(self) -> None:
        try:
            await self.coordinator.async_alarm_stoppen(None)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err
