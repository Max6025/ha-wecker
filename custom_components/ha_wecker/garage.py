"""Verbindung zum Garagen-ESP (VAN206 LS, ESP32 an der Lichtschranke).

Der ESP in der Garage liest die Lichtschranke (steht der 206 weit genug drin?),
schaltet die rote Lampe und hoert per ESP-NOW den ESP im Auto. Unter
/api/state meldet er alles, was daraus folgt - die Ampel (Stopp, Frei, kein
Strom, aus), Tor, Auto zu hoeren, verriegelt, Zuendung, Rueckwaertsgang - und
haelt auf einem eigenen Port einen Ereignisstrom offen, ueber den jede
Aenderung sofort kommt. Die Abfrage alle paar Sekunden ist die Rueckfallebene.

Der ESP meldet sich selbst in Home Assistant an (er startet den
Konfigurationsablauf dieser Integration ueber die REST-Schnittstelle), in HA
muss niemand etwas anlegen. Aufbau wie bei der Signalsaeule (saeule.py).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_HOST, DOMAIN, GARAGE_ABFRAGE_S
from .saeule import host_zu_url

_LOGGER = logging.getLogger(__name__)

ZEIT = aiohttp.ClientTimeout(total=8)
ZEIT_EVENTS = aiohttp.ClientTimeout(total=None, sock_connect=8, sock_read=60)
EVENTS_PORT_STANDARD = 8081

# Die Ampel, wie sie auch der Tacho im Auto zeichnet
AMPEL_STOPP = "stopp"
AMPEL_FREI = "frei"
AMPEL_KEIN_STROM = "kein_strom"
AMPEL_AUS = "aus"
AMPEL_ALLE = [AMPEL_STOPP, AMPEL_FREI, AMPEL_KEIN_STROM, AMPEL_AUS]


async def garage_abfragen(hass: HomeAssistant, host: str) -> dict[str, Any]:
    """Einmaliger Abruf von /api/state, fuer Config-Flow und Coordinator."""
    url = f"{host_zu_url(host)}/api/state"
    session = async_get_clientsession(hass)
    async with session.get(url, timeout=ZEIT) as resp:
        if resp.status != 200:
            raise UpdateFailed(f"{url} lieferte {resp.status}")
        data = await resp.json(content_type=None)
    if not isinstance(data, dict) or data.get("typ") != "garage":
        raise UpdateFailed(f"{url}: kein Garagen-ESP")
    return data


class GarageCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fragt den Garagen-ESP ab und schickt ihm die wenigen Befehle."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} Garage",
            update_interval=timedelta(seconds=GARAGE_ABFRAGE_S),
        )
        self.entry = entry
        self._events_task: asyncio.Task | None = None
        self.events_verbunden = False

    # --- Adresse ------------------------------------------------------

    @property
    def host(self) -> str:
        return self.entry.options.get(CONF_HOST, self.entry.data.get(CONF_HOST, ""))

    @property
    def url(self) -> str:
        return host_zu_url(self.host)

    @property
    def mac(self) -> str:
        return (self.data or {}).get("mac") or self.entry.unique_id or self.entry.entry_id

    # --- Lesen --------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await garage_abfragen(self.hass, self.host)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise UpdateFailed(f"Garagen-ESP {self.host} nicht erreichbar: {err}") from err

    @property
    def daten(self) -> dict[str, Any]:
        return self.data or {}

    def wert(self, key: str, vorgabe: Any = None) -> Any:
        return self.daten.get(key, vorgabe)

    def ja(self, key: str) -> bool | None:
        """Dreiwertig: True/False, None wenn der ESP es nicht weiss."""
        w = self.daten.get(key)
        if w is None:
            return None
        return bool(w)

    @property
    def ampel(self) -> str:
        a = str(self.daten.get("ampel") or AMPEL_AUS)
        return a if a in AMPEL_ALLE else AMPEL_AUS

    @property
    def auto_zu_hoeren(self) -> bool:
        return bool(self.daten.get("auto_zu_hoeren"))

    # --- Ereignisstrom -----------------------------------------------

    @property
    def events_url(self) -> str:
        port = self.daten.get("events_port") or EVENTS_PORT_STANDARD
        schema, _, rest = self.url.partition("://")
        erster = rest.split("/", 1)[0]
        hostteil = erster.rsplit(":", 1)[0] if ":" in erster else erster
        return f"{schema}://{hostteil}:{port}/api/events"

    def async_start_events(self) -> None:
        if self._events_task is None or self._events_task.done():
            self._events_task = self.entry.async_create_background_task(
                self.hass, self._events_loop(), f"{DOMAIN}_garage_events_{self.entry.entry_id}"
            )

    async def async_stop_events(self) -> None:
        task, self._events_task = self._events_task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def _events_loop(self) -> None:
        session = async_get_clientsession(self.hass)
        pause = 3
        while True:
            try:
                async with session.get(self.events_url, timeout=ZEIT_EVENTS) as resp:
                    if resp.status != 200:
                        raise UpdateFailed(f"Ereignisstrom antwortete {resp.status}")
                    self.events_verbunden = True
                    pause = 3
                    _LOGGER.debug("Ereignisstrom %s verbunden", self.events_url)
                    async for raw in resp.content:
                        line = raw.decode("utf-8", "replace").strip()
                        if not line.startswith("data:"):
                            continue  # Lebenszeichen, Leerzeile
                        try:
                            data = json.loads(line[5:].strip())
                        except ValueError:
                            continue
                        if isinstance(data, dict) and data.get("typ") == "garage":
                            self.async_set_updated_data(data)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - immer wieder neu versuchen
                _LOGGER.debug("Ereignisstrom %s: %s", self.events_url, err)
            self.events_verbunden = False
            await asyncio.sleep(pause)
            pause = min(pause * 2, 60)

    # --- Befehle ------------------------------------------------------

    async def _post(self, pfad: str, params: dict[str, Any]) -> None:
        url = f"{self.url}{pfad}"
        session = async_get_clientsession(self.hass)
        try:
            async with session.post(
                url, params={k: str(v) for k, v in params.items()}, timeout=ZEIT
            ) as resp:
                if resp.status != 200:
                    text = (await resp.text())[:120]
                    raise UpdateFailed(f"Garagen-ESP antwortete {resp.status}: {text}")
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise UpdateFailed(f"Garagen-ESP {self.host} nicht erreichbar: {err}") from err
        if isinstance(data, dict) and data.get("typ") == "garage":
            self.async_set_updated_data(data)

    async def async_lampe_testen(self) -> None:
        """Rote Lampe zehn Sekunden an, danach gilt wieder die Logik des ESP."""
        await self._post("/api/lampe", {"an": 1})

    async def async_neustart(self) -> None:
        await self._post("/api/neustart", {})
