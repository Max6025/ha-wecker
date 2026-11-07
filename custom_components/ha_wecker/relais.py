"""Verbindung zur Relaisbox (ESP32) ueber ihre HTTP-Schnittstelle."""
from __future__ import annotations

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
