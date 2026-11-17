"""Knoepfe: Diagnose der Saeule, Alarm stoppen, Probelauf des Weckablaufs."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, PROBELAUF_VORLAUF_S, SIGNAL_ABLAUF
from .entity import GarageEntity, SaeuleEntity, WeckerEntity
from .garage import GarageCoordinator
from .saeule import SaeuleCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    obj = hass.data[DOMAIN][entry.entry_id]
    if getattr(obj, "ablauf", None) is not None:
        async_add_entities([ProbelaufButton(obj), AbbrechenButton(obj)])
        return
    if isinstance(obj, SaeuleCoordinator):
        async_add_entities([DiagnoseButton(obj), AllesAusButton(obj)])
        return
    if isinstance(obj, GarageCoordinator):
        async_add_entities([GarageLampeTestButton(obj), GarageNeustartButton(obj)])
        return
    # Mehr hat der Wecker nicht: die App laeuft nicht im Hintergrund und
    # bietet nichts zum Abfragen.



class DiagnoseButton(SaeuleEntity, ButtonEntity):
    """Startet die Selbstdiagnose der Saeule. Das Ergebnis steht im Sensor."""

    _attr_name = "Selbstdiagnose"
    _attr_icon = "mdi:stethoscope"

    def __init__(self, coordinator: SaeuleCoordinator) -> None:
        super().__init__(coordinator, "diagnose")

    async def async_press(self) -> None:
        try:
            await self.coordinator.async_diagnose()
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err


class AllesAusButton(SaeuleEntity, ButtonEntity):
    """Alle Leuchten aus, Warnleuchte aus, Betriebsart Manuell."""

    _attr_name = "Alles aus"
    _attr_icon = "mdi:lightbulb-off"

    def __init__(self, coordinator: SaeuleCoordinator) -> None:
        super().__init__(coordinator, "alles_aus")

    async def async_press(self) -> None:
        try:
            await self.coordinator.async_alles_aus()
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err


class ProbelaufButton(WeckerEntity, ButtonEntity):
    """Spielt den Weckablauf sofort durch, ohne auf einen echten Weckruf zu warten.

    Gedacht zum Nachsehen: eine Minute nach dem Druck "klingelt" es, vorher
    laeuft der Vorlauf. Jeder Schritt steht danach im Protokoll am Schalter
    "Weckablauf" - mit Ergebnis, auch wenn die Lampe nicht mitgespielt hat.
    """

    _attr_name = "Probelauf"
    _attr_icon = "mdi:play-circle-outline"

    def __init__(self, data) -> None:
        super().__init__(data, "probelauf")

    @property
    def available(self) -> bool:
        return True

    async def async_press(self) -> None:
        await self._data.ablauf.async_probelauf(PROBELAUF_VORLAUF_S)


class AbbrechenButton(WeckerEntity, ButtonEntity):
    """Stoppt einen laufenden Ablauf und raeumt auf: Licht aus, Saeule auf Ruhe."""

    _attr_name = "Ablauf abbrechen"
    _attr_icon = "mdi:stop-circle-outline"

    def __init__(self, data) -> None:
        super().__init__(data, "ablauf_abbrechen")

    @property
    def available(self) -> bool:
        return True

    async def async_press(self) -> None:
        await self._data.ablauf.async_abbrechen()


class GarageLampeTestButton(GarageEntity, ButtonEntity):
    """Rote Lampe in der Garage zehn Sekunden an - zum Nachsehen, ob Relais und Leuchte leben."""

    _attr_name = "Lampe testen"
    _attr_icon = "mdi:alarm-light-outline"

    def __init__(self, coordinator: GarageCoordinator) -> None:
        super().__init__(coordinator, "lampe_test")

    async def async_press(self) -> None:
        try:
            await self.coordinator.async_lampe_testen()
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err


class GarageNeustartButton(GarageEntity, ButtonEntity):
    """Den Garagen-ESP neu starten."""

    _attr_name = "Neustart"
    _attr_icon = "mdi:restart"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: GarageCoordinator) -> None:
        super().__init__(coordinator, "neustart")

    async def async_press(self) -> None:
        try:
            await self.coordinator.async_neustart()
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err
