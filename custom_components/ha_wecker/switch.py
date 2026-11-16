"""Schalter: die Leuchten der Signalsaeule und der Weckablauf am Wecker."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, ROLLE_STUFE, ROLLE_TON, ROLLE_WARN, SIGNAL_ABLAUF
from .entity import SaeuleEntity, WeckerEntity
from .saeule import SaeuleCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    obj = hass.data[DOMAIN][entry.entry_id]
    if getattr(obj, "ablauf", None) is not None:
        async_add_entities([WeckablaufSwitch(obj)])
        return
    if isinstance(obj, SaeuleCoordinator):
        saeule: list[SwitchEntity] = [
            LeuchteSwitch(obj, r["nr"]) for r in obj.leuchten(ROLLE_STUFE)
        ]
        saeule += [WarnleuchteSwitch(obj, r["nr"]) for r in obj.leuchten(ROLLE_WARN)]
        saeule += [TonSwitch(obj, r["nr"]) for r in obj.leuchten(ROLLE_TON)]
        saeule.append(SaeuleTestSwitch(obj))
        async_add_entities(saeule)
        return


# --- Signalsaeule -----------------------------------------------------------


class _SaeuleLeuchte(SaeuleEntity, SwitchEntity):
    """Grundlage der Leuchtenschalter: Zustand kommt aus /api/state."""

    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator: SaeuleCoordinator, nr: int, schluessel: str) -> None:
        super().__init__(coordinator, f"{schluessel}_{nr}")
        self.nr = nr

    @property
    def _leuchte(self) -> dict[str, Any] | None:
        return self.coordinator.relais(self.nr)

    @property
    def available(self) -> bool:
        return super().available and self._leuchte is not None

    @property
    def is_on(self) -> bool | None:
        r = self._leuchte
        # "an" ist der logische Zustand: er bleibt stehen, waehrend die Leuchte
        # blinkt. "live" ist der Pegel in diesem Augenblick - nur ein Attribut,
        # sonst wuerde Home Assistant im Sekundentakt flattern.
        return bool(r.get("an")) if r else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        r = self._leuchte or {}
        return {
            "nr": self.nr,
            "pin": r.get("gpio"),
            "leuchtet_jetzt": bool(r.get("live")),
            "pegel": r.get("pegel"),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._schalten(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._schalten(False)

    async def _schalten(self, an: bool) -> None:
        try:
            await self.coordinator.async_schalten(self.nr, an)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err


class LeuchteSwitch(_SaeuleLeuchte):
    """Eine Stufe der Saeule. Von Hand zu schalten stellt auf Manuell um."""

    def __init__(self, coordinator: SaeuleCoordinator, nr: int) -> None:
        super().__init__(coordinator, nr, "leuchte")
        r = coordinator.relais(nr) or {}
        self._attr_name = str(r.get("name") or f"Leuchte {nr}")

    @property
    def icon(self) -> str:
        r = self._leuchte or {}
        if not r.get("an"):
            return "mdi:lightbulb-outline"
        return "mdi:lightbulb-on" if r.get("live") else "mdi:lightbulb-on-outline"


class WarnleuchteSwitch(_SaeuleLeuchte):
    """Die Blitz-Warnleuchte. Eigener Schalter, gilt in beiden Betriebsarten.

    Im Status Alarm schaltet die Saeule sie selbst ein, sobald das Alarmbild
    laeuft; beim Verlassen bekommt sie wieder ihren Stand von vorher.
    """

    _attr_name = "Warnleuchte"

    def __init__(self, coordinator: SaeuleCoordinator, nr: int) -> None:
        super().__init__(coordinator, nr, "warnleuchte")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        werte = super().extra_state_attributes
        werte["vom_alarm"] = bool((self.coordinator.data or {}).get("warn_vom_alarm"))
        return werte

    @property
    def icon(self) -> str:
        return "mdi:alarm-light" if self.is_on else "mdi:alarm-light-off-outline"


class TonSwitch(_SaeuleLeuchte):
    """Der Tongeber am Relais D7. Piept, solange Strom drauf ist.

    Haengt an keiner Choreografie: kein Status, kein Testmodus und kein
    Startablauf nehmen ihn mit, und die Saeule merkt ihn auch nicht - nach
    einem Stromausfall ist er aus. Nur dieser Schalter und der Weckablauf
    (Schritt "saeule": {"ton": true}) schalten ihn.
    """

    _attr_name = "Ton"

    def __init__(self, coordinator: SaeuleCoordinator, nr: int) -> None:
        super().__init__(coordinator, nr, "ton")

    @property
    def icon(self) -> str:
        return "mdi:bullhorn" if self.is_on else "mdi:bullhorn-outline"


class SaeuleTestSwitch(SaeuleEntity, SwitchEntity):
    """Testmodus: Lauflicht ueber alle Stufen, die Warnleuchte blitzt in Schueben."""

    _attr_name = "Testmodus"
    _attr_icon = "mdi:test-tube"

    def __init__(self, coordinator: SaeuleCoordinator) -> None:
        super().__init__(coordinator, "testmodus")

    @property
    def is_on(self) -> bool:
        return bool((self.coordinator.data or {}).get("test"))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._setzen(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._setzen(False)

    async def _setzen(self, an: bool) -> None:
        try:
            await self.coordinator.async_test(an)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err


class WeckablaufSwitch(WeckerEntity, SwitchEntity, RestoreEntity):
    """Weckablauf: an = Hauptlicht und Saeule folgen dem Wecker (siehe ablauf.py)."""

    _attr_name = "Weckablauf"

    def __init__(self, data) -> None:
        super().__init__(data, "weckablauf")

    @property
    def _ablauf(self):
        return self._data.ablauf

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        letzter = await self.async_get_last_state()
        self._ablauf.aktiv = letzter is None or letzter.state == "on"
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_ABLAUF.format(self._data.entry.entry_id), self.async_write_ha_state
            )
        )

    @property
    def available(self) -> bool:
        return True          # der Ablauf lebt auch, wenn die App laenger schweigt

    @property
    def is_on(self) -> bool:
        return bool(self._ablauf.aktiv)

    @property
    def icon(self) -> str:
        if not self.is_on:
            return "mdi:lightbulb-off-outline"
        return "mdi:lightbulb-on" if self._ablauf.laeuft else "mdi:lightbulb-outline"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._ablauf.attribute()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._ablauf.async_setzen(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._ablauf.async_setzen(False)
        self.async_write_ha_state()
