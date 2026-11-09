"""HA Wecker - Weckerliste der Android-App und Relaisbox (ESP32) in Home Assistant.

Zwei Geraetetypen in einer Integration:
- Wecker:    die App meldet ihren Stand per Webhook (kein Dienst im Hintergrund,
             kein lokaler Server, nichts zum Abfragen)
- Relaisbox: ESP32 im WLAN, Relais schalten und Alarmmuster laufen lassen
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from aiohttp.web import Request, Response

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_WEBHOOK_ID, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_TYP,
    DOMAIN,
    SIGNAL_UPDATE,
    SIGNAL_WECKER_ALLE,
    STORAGE_VERSION,
    TYP_RELAIS,
    TYP_WECKER,
)
from .lampe import WeckerLampe
from .relais import RelaisCoordinator
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS_WECKER: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]
PLATFORMS_RELAIS: list[Platform] = [
    Platform.SWITCH,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
]


def entry_typ(entry: ConfigEntry) -> str:
    """Geraetetyp eines Eintrags; alte Eintraege ohne Feld sind Wecker."""
    return entry.data.get(CONF_TYP, TYP_WECKER)


def platforms_fuer(entry: ConfigEntry) -> list[Platform]:
    return PLATFORMS_RELAIS if entry_typ(entry) == TYP_RELAIS else PLATFORMS_WECKER


class WeckerData:
    """Haelt den zuletzt gemeldeten Stand und verteilt Aktualisierungen."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.payload: dict[str, Any] | None = None
        self.last_seen: datetime | None = None
        self._store: Store = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )

    # --- Konfiguration ------------------------------------------------

    @property
    def webhook_id(self) -> str:
        return self.entry.data[CONF_WEBHOOK_ID]

    @property
    def webhook_url(self) -> str:
        try:
            return webhook.async_generate_url(self.hass, self.webhook_id)
        except Exception:  # noqa: BLE001 - nur Anzeige
            return f"/api/webhook/{self.webhook_id}"

    # --- Zustand ------------------------------------------------------

    async def async_restore(self) -> None:
        """Letzten Stand nach einem Neustart wieder laden."""
        stored = await self._store.async_load()
        if isinstance(stored, dict) and isinstance(stored.get("payload"), dict):
            self.payload = stored["payload"]
            self.last_seen = dt_util.parse_datetime(stored.get("last_seen") or "")

    @callback
    def async_set_payload(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.last_seen = dt_util.utcnow()
        self._store.async_delay_save(self._data_to_save, 5)
        async_dispatcher_send(self.hass, SIGNAL_UPDATE.format(self.entry.entry_id))
        async_dispatcher_send(self.hass, SIGNAL_WECKER_ALLE)

    async def async_flush(self) -> None:
        """Ausstehende Speicherung sofort schreiben (vor Unload/Reload)."""
        if self.payload is not None:
            await self._store.async_save(self._data_to_save())

    @callback
    def _data_to_save(self) -> dict[str, Any]:
        return {
            "payload": self.payload,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
        }



async def _setup_wecker(hass: HomeAssistant, entry: ConfigEntry) -> None:
    data = WeckerData(hass, entry)
    await data.async_restore()
    hass.data[DOMAIN][entry.entry_id] = data

    async def _handle_webhook(
        hass: HomeAssistant, webhook_id: str, request: Request
    ) -> Response:
        try:
            payload = await request.json()
        except ValueError:
            return Response(status=400, text="kein gueltiges JSON")
        if not isinstance(payload, dict):
            return Response(status=400, text="JSON-Objekt erwartet")
        data.async_set_payload(payload)
        return Response(status=200, text="ok")

    webhook.async_register(
        hass,
        DOMAIN,
        "HA Wecker",
        data.webhook_id,
        _handle_webhook,
        allowed_methods=["POST"],
        local_only=False,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS_WECKER)


async def _setup_relais(hass: HomeAssistant, entry: ConfigEntry) -> None:
    coordinator = RelaisCoordinator(hass, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        raise
    hass.data[DOMAIN][entry.entry_id] = coordinator
    # Weckerlampe: der Schalter stellt beim Anlegen seinen letzten Stand wieder her
    coordinator.lampe = WeckerLampe(hass, entry, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS_RELAIS)
    coordinator.lampe.async_start()
    entry.async_on_unload(coordinator.lampe.async_stop)
    # Aenderungen kommen sofort ueber den Ereignisstrom, die Abfrage ist Rueckfall
    coordinator.async_start_events()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Eintrag einrichten."""
    hass.data.setdefault(DOMAIN, {})
    if entry_typ(entry) == TYP_RELAIS:
        await _setup_relais(hass, entry)
    else:
        await _setup_wecker(hass, entry)

    async_setup_services(hass)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Eintrag wieder abbauen."""
    obj = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if isinstance(obj, RelaisCoordinator):
        await obj.async_stop_events()
    if isinstance(obj, WeckerData):
        webhook.async_unregister(hass, obj.webhook_id)
        # Sonst geht ein Push verloren, der kurz vor einem Neuladen ankam
        # (die verzoegerte Speicherung wartet 5 Sekunden).
        await obj.async_flush()

    unloaded = await hass.config_entries.async_unload_platforms(entry, platforms_fuer(entry))
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        async_unload_services(hass)
    return unloaded
