"""Schalter der Relaisbox: je brauchbares Relais einer, dazu die Weckerlampe."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, ROLLE_WARN, SIGNAL_LAMPE, TEST_LICHTBILD
from .entity import RelaisEntity, SaeuleEntity
from .relais import RelaisCoordinator
from .saeule import SaeuleCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    obj = hass.data[DOMAIN][entry.entry_id]
    if isinstance(obj, SaeuleCoordinator):
        saeule: list[SwitchEntity] = [
            LeuchteSwitch(obj, r["nr"]) for r in obj.leuchten(nur_warn=False)
        ]
        saeule += [WarnleuchteSwitch(obj, r["nr"]) for r in obj.leuchten(nur_warn=True)]
        saeule.append(SaeuleTestSwitch(obj))
        async_add_entities(saeule)
        return
    if not isinstance(obj, RelaisCoordinator):
        return
    entities: list[SwitchEntity] = [RelaisSwitch(obj, r["nr"]) for r in obj.brauchbare_relais()]
    if obj.lampe is not None:
        entities.append(WeckerLampeSwitch(obj))
    entities.append(TestSwitch(obj))
    async_add_entities(entities)


class RelaisSwitch(RelaisEntity, SwitchEntity):
    """Ein Relais. Einschalten = Dauer-an, Ausschalten beendet auch ein Muster."""

    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator: RelaisCoordinator, nr: int) -> None:
        super().__init__(coordinator, f"relais_{nr}")
        self.nr = nr
        r = coordinator.relais(nr) or {}
        self._attr_name = str(r.get("name") or f"Relais {nr}")   # Name aus der Box, wenn sie einen meldet

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


class WeckerLampeSwitch(RelaisEntity, SwitchEntity, RestoreEntity):
    """Weckerlampe: an = ein Relais folgt dem Wecker der App (siehe lampe.py)."""

    _attr_name = "Weckerlampe"

    def __init__(self, coordinator: RelaisCoordinator) -> None:
        super().__init__(coordinator, "weckerlampe")

    @property
    def _lampe(self):
        return self.coordinator.lampe

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        letzter = await self.async_get_last_state()
        # Neu angelegt: an. Sonst so, wie es vor dem Neustart stand.
        an = letzter is None or letzter.state == "on"
        await self._lampe.async_setzen(an, befehl=False)
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_LAMPE.format(self.coordinator.entry.entry_id), self.async_write_ha_state
            )
        )

    @property
    def is_on(self) -> bool:
        return bool(self._lampe.aktiv)

    @property
    def icon(self) -> str:
        if not self.is_on:
            return "mdi:lightbulb-off-outline"
        return "mdi:lightbulb-on" if self._lampe.phase != "aus" else "mdi:lightbulb-outline"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._lampe.attribute()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._lampe.async_setzen(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        try:
            await self._lampe.async_setzen(False)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err
        self.async_write_ha_state()


class TestSwitch(RelaisEntity, SwitchEntity):
    """Testmodus: Lampe Dreifachblitz, Rot langsam, Warnleuchte im Intervall, bis Stopp.

    Startet die Weckerlampe einen Ablauf, nimmt sie den Testmodus zurueck.
    """

    _attr_name = "Testmodus"
    _attr_icon = "mdi:test-tube"

    def __init__(self, coordinator: RelaisCoordinator) -> None:
        super().__init__(coordinator, "testmodus")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_LAMPE.format(self.coordinator.entry.entry_id), self.async_write_ha_state
            )
        )

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.test_aktiv)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"lichtbild": {str(k): v for k, v in TEST_LICHTBILD.items()}}

    async def async_turn_on(self, **kwargs: Any) -> None:
        try:
            await self.coordinator.async_test(True)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        try:
            await self.coordinator.async_test(False)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(str(err)) from err
        self.async_write_ha_state()


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
