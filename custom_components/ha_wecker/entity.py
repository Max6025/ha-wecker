"""Gemeinsame Basis aller HA-Wecker-Entitaeten."""
from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import WeckerData
from .const import DOMAIN, SIGNAL_UPDATE
from .relais import RelaisCoordinator


class WeckerEntity(Entity):
    """Entitaet des Geraets "Wecker" (Android-App)."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, data: WeckerData, key: str) -> None:
        self._data = data
        self._key = key
        self._attr_unique_id = f"{data.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, data.entry.entry_id)},
            name=data.entry.title or "HA Wecker",
            manufacturer="Maximilian Starnberg",
            model="Android-Weckerapp",
            sw_version=str((data.payload or {}).get("api_version", "1")),
        )

    @property
    def payload(self) -> dict[str, Any]:
        return self._data.payload or {}

    @property
    def available(self) -> bool:
        return self._data.payload is not None

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_UPDATE.format(self._data.entry.entry_id),
                self.async_write_ha_state,
            )
        )


class RelaisEntity(CoordinatorEntity[RelaisCoordinator]):
    """Entitaet des Geraets "Relaisbox" (ESP32)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: RelaisCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{coordinator.mac}_{key}"
        daten = coordinator.data or {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.mac)},
            name=coordinator.entry.title or "Relaisbox",
            manufacturer="Maximilian Starnberg",
            model="Relaisbox ESP32-S3",
            sw_version=str(daten.get("version", "")),
            configuration_url=coordinator.url or None,
        )

    @property
    def daten(self) -> dict[str, Any]:
        return self.coordinator.data or {}
