"""Verbindung zur Relaisbox (ESP32) ueber ihre HTTP-Schnittstelle."""
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

from .const import CONF_HOST, DOMAIN, RELAIS_ABFRAGE_S

_LOGGER = logging.getLogger(__name__)

ZEIT = aiohttp.ClientTimeout(total=8)
# Ereignisstrom: keine Gesamtdauer, aber die Box schickt alle 15 s ein
# Lebenszeichen - bleibt das 60 s aus, gilt die Verbindung als tot.
ZEIT_EVENTS = aiohttp.ClientTimeout(total=None, sock_connect=8, sock_read=60)
EVENTS_PORT_STANDARD = 8081


def host_zu_url(host: str) -> str:
    host = (host or "").strip().rstrip("/")
    if host and "://" not in host:
        host = "http://" + host
    return host


async def relaisbox_abfragen(hass: HomeAssistant, host: str) -> dict[str, Any]:
    """Einmaliger Abruf von /api/state, fuer Config-Flow und Coordinator."""
    url = f"{host_zu_url(host)}/api/state"
    session = async_get_clientsession(hass)
    async with session.get(url, timeout=ZEIT) as resp:
        if resp.status != 200:
            raise UpdateFailed(f"{url} lieferte {resp.status}")
        data = await resp.json(content_type=None)
    if not isinstance(data, dict) or "relais" not in data:
        raise UpdateFailed(f"{url}: keine Relaisbox-Antwort")
    return data


class RelaisCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fragt die Relaisbox regelmaessig ab und schickt Befehle."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} Relaisbox",
            update_interval=timedelta(seconds=RELAIS_ABFRAGE_S),
        )
        self.entry = entry
        self._events_task: asyncio.Task | None = None
        self.events_verbunden = False

    @property
    def host(self) -> str:
        return self.entry.options.get(CONF_HOST, self.entry.data.get(CONF_HOST, ""))

    @property
    def url(self) -> str:
        return host_zu_url(self.host)

    @property
    def mac(self) -> str:
        return (self.data or {}).get("mac") or self.entry.unique_id or self.entry.entry_id

    def relais(self, nr: int) -> dict[str, Any] | None:
        for r in (self.data or {}).get("relais", []) or []:
            if r.get("nr") == nr:
                return r
        return None

    def brauchbare_relais(self) -> list[dict[str, Any]]:
        return [
            r for r in (self.data or {}).get("relais", []) or []
            if isinstance(r, dict) and not r.get("defekt")
        ]

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await relaisbox_abfragen(self.hass, self.host)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise UpdateFailed(f"Relaisbox {self.host} nicht erreichbar: {err}") from err

    # --- Ereignisstrom -----------------------------------------------
    #
    # Die Box haelt auf einem eigenen Port eine Verbindung offen und schickt
    # bei jeder Aenderung sofort den kompletten Zustand (Server-Sent Events).
    # Die Abfrage alle paar Sekunden bleibt als Rueckfallebene.

    @property
    def events_url(self) -> str:
        port = (self.data or {}).get("events_port") or EVENTS_PORT_STANDARD
        basis = self.url
        # Port 80 der Basis durch den Ereignisport ersetzen
        schema, _, rest = basis.partition("://")
        hostteil = rest.split("/", 1)[0].rsplit(":", 1)[0] if ":" in rest.split("/", 1)[0] else rest.split("/", 1)[0]
        return f"{schema}://{hostteil}:{port}/api/events"

    def async_start_events(self) -> None:
        if self._events_task is None or self._events_task.done():
            self._events_task = self.entry.async_create_background_task(
                self.hass, self._events_loop(), f"{DOMAIN}_events_{self.entry.entry_id}"
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
                            continue  # Lebenszeichen, retry:, Leerzeile
                        try:
                            data = json.loads(line[5:].strip())
                        except ValueError:
                            continue
                        if isinstance(data, dict) and "relais" in data:
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
                    raise UpdateFailed(f"Relaisbox antwortete {resp.status}: {text}")
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise UpdateFailed(f"Relaisbox {self.host} nicht erreichbar: {err}") from err
        if isinstance(data, dict) and "relais" in data:
            # Antwort ist der neue Zustand - direkt uebernehmen, ohne Abfrage
            self.async_set_updated_data(data)

    async def async_schalten(self, nr: int, an: bool) -> None:
        await self._post(f"/api/relais/{nr}", {"an": 1 if an else 0})

    async def async_alarm_starten(
        self, relais: list[int] | None, muster: str, dauer_s: int = 0
    ) -> None:
        liste = "alle" if not relais else ",".join(str(n) for n in sorted(set(relais)))
        await self._post(
            "/api/alarm", {"relais": liste, "muster": muster, "dauer": int(dauer_s or 0)}
        )

    async def async_alarm_stoppen(self, relais: list[int] | None = None) -> None:
        liste = "alle" if not relais else ",".join(str(n) for n in sorted(set(relais)))
        await self._post("/api/alarm/stop", {"relais": liste})
