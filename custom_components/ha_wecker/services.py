"""Aktionen der Integration: Alarm auf Relais starten und stoppen."""
from __future__ import annotations

import logging
from collections import defaultdict

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

try:  # HA ab 2025.x: Ziel-Aufloesung in helpers.target
    from homeassistant.helpers.target import (
        TargetSelection,
        async_extract_referenced_entity_ids as _extract_target,
    )

    def _referenzen(hass: HomeAssistant, call: ServiceCall):
        return _extract_target(hass, TargetSelection(call.data))

except ImportError:  # aeltere HA-Versionen
    from homeassistant.helpers.service import (
        async_extract_referenced_entity_ids as _extract_service,
    )

    def _referenzen(hass: HomeAssistant, call: ServiceCall):
        return _extract_service(hass, call)

from .const import (
    ATTR_DAUER,
    ATTR_MUSTER,
    DOMAIN,
    MUSTER_LISTE,
    MUSTER_STANDARD,
    SERVICE_ALARM_STARTEN,
    SERVICE_ALARM_STOPPEN,
)
from .relais import RelaisCoordinator

_LOGGER = logging.getLogger(__name__)

# Ziel (entity_id/device_id/area_id ...) ist erlaubt, aber nicht Pflicht:
# ohne Ziel sind alle Relaisboxen gemeint.
SCHEMA_STARTEN = vol.Schema(
    {
        **cv.ENTITY_SERVICE_FIELDS,
        vol.Optional(ATTR_MUSTER, default=MUSTER_STANDARD): vol.In(MUSTER_LISTE),
        vol.Optional(ATTR_DAUER, default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=86400)),
    }
)
SCHEMA_STOPPEN = vol.Schema({**cv.ENTITY_SERVICE_FIELDS})


def _ziele(hass: HomeAssistant, call: ServiceCall) -> dict[RelaisCoordinator, list[int]]:
    """Die angesprochenen Relais-Schalter nach Relaisbox gruppieren.

    Wird ein Geraet oder ein Bereich angegeben, zaehlen alle seine Relais.
    Ohne Ziel sind alle Relaisboxen gemeint.
    """
    registry = er.async_get(hass)
    daten = hass.data.get(DOMAIN, {})
    ergebnis: dict[RelaisCoordinator, list[int]] = defaultdict(list)

    ref = _referenzen(hass, call)
    entity_ids = ref.referenced | ref.indirectly_referenced
    if not entity_ids and not ref.referenced_devices and not ref.referenced_areas:
        # Kein Ziel: alle Relaisboxen, alle Relais
        for obj in daten.values():
            if isinstance(obj, RelaisCoordinator):
                ergebnis[obj] = []
        return ergebnis

    for entity_id in entity_ids:
        eintrag = registry.async_get(entity_id)
        if eintrag is None or eintrag.platform != DOMAIN or eintrag.domain != "switch":
            continue
        coord = daten.get(eintrag.config_entry_id)
        if not isinstance(coord, RelaisCoordinator):
            continue
        try:
            nr = int(str(eintrag.unique_id).rsplit("_relais_", 1)[1])
        except (IndexError, ValueError):
            continue
        ergebnis[coord].append(nr)

    if not ergebnis:
        raise ServiceValidationError(
            "Kein Relais-Schalter der Relaisbox als Ziel gefunden."
        )
    return ergebnis


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Aktionen einmal je HA-Instanz anmelden."""
    if hass.services.has_service(DOMAIN, SERVICE_ALARM_STARTEN):
        return

    async def _starten(call: ServiceCall) -> None:
        muster = call.data.get(ATTR_MUSTER, MUSTER_STANDARD)
        dauer = int(call.data.get(ATTR_DAUER, 0))
        fehler: list[str] = []
        for coord, relais in _ziele(hass, call).items():
            try:
                await coord.async_alarm_starten(relais or None, muster, dauer)
            except Exception as err:  # noqa: BLE001 - alle Boxen versuchen
                fehler.append(str(err))
        if fehler:
            raise HomeAssistantError("; ".join(fehler))

    async def _stoppen(call: ServiceCall) -> None:
        fehler: list[str] = []
        for coord, relais in _ziele(hass, call).items():
            try:
                await coord.async_alarm_stoppen(relais or None)
            except Exception as err:  # noqa: BLE001
                fehler.append(str(err))
        if fehler:
            raise HomeAssistantError("; ".join(fehler))

    hass.services.async_register(DOMAIN, SERVICE_ALARM_STARTEN, _starten, schema=SCHEMA_STARTEN)
    hass.services.async_register(DOMAIN, SERVICE_ALARM_STOPPEN, _stoppen, schema=SCHEMA_STOPPEN)


@callback
def async_unload_services(hass: HomeAssistant) -> None:
    """Aktionen abmelden, wenn der letzte Eintrag weg ist."""
    if not hass.data.get(DOMAIN):
        for name in (SERVICE_ALARM_STARTEN, SERVICE_ALARM_STOPPEN):
            if hass.services.has_service(DOMAIN, name):
                hass.services.async_remove(DOMAIN, name)
