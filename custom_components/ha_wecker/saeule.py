"""Verbindung zur Signalsaeule (Arduino UNO R4 WiFi).

Die Saeule spricht dieselbe HTTP-Schnittstelle wie die Relaisbox - /api/state
mit einer Liste "relais", /api/relais/<nr>, Ereignisstrom auf Port 8081 - und
hat drei Wege mehr: Betriebsart, Status und Selbstdiagnose. Darum erbt der
Coordinator von dem der Relaisbox und ergaenzt nur diese Befehle.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import (
    MODUS_AUTO,
    MODUS_MANUELL,
    SAEULE_ABFRAGE_S,
    STATUS_STANDARD,
)
from .relais import ZEIT, RelaisCoordinator, host_zu_url

_LOGGER = logging.getLogger(__name__)


async def saeule_abfragen(hass: HomeAssistant, host: str) -> dict[str, Any]:
    """Einmaliger Abruf von /api/state, fuer Config-Flow und Coordinator."""
    url = f"{host_zu_url(host)}/api/state"
    session = async_get_clientsession(hass)
    async with session.get(url, timeout=ZEIT) as resp:
        if resp.status != 200:
            raise UpdateFailed(f"{url} lieferte {resp.status}")
        data = await resp.json(content_type=None)
    if not isinstance(data, dict) or data.get("typ") != "saeule":
        raise UpdateFailed(f"{url}: keine Signalsaeule")
    return data


class SaeuleCoordinator(RelaisCoordinator):
    """Fragt die Signalsaeule ab und schickt ihre Befehle."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self.name = "ha_wecker Signalsaeule"
        self.update_interval = timedelta(seconds=SAEULE_ABFRAGE_S)
        self.lampe = None            # die Saeule hat keine Weckerlampe

    # --- Lesen --------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await saeule_abfragen(self.hass, self.host)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise UpdateFailed(f"Signalsaeule {self.host} nicht erreichbar: {err}") from err

    @property
    def modus(self) -> str:
        return str((self.data or {}).get("modus") or MODUS_AUTO)

    @property
    def auto(self) -> bool:
        return self.modus == MODUS_AUTO

    @property
    def status(self) -> str:
        return str((self.data or {}).get("status") or STATUS_STANDARD)

    @property
    def status_liste(self) -> list[dict[str, str]]:
        liste = (self.data or {}).get("status_liste") or []
        return [s for s in liste if isinstance(s, dict) and s.get("id")]

    def status_namen(self) -> list[str]:
        return [str(s.get("name") or s["id"]) for s in self.status_liste]

    def status_name(self, kennung: str) -> str | None:
        for s in self.status_liste:
            if s.get("id") == kennung:
                return str(s.get("name") or kennung)
        return None

    def status_id(self, name: str) -> str | None:
        for s in self.status_liste:
            if str(s.get("name") or s["id"]) == name:
                return str(s["id"])
        return None

    @property
    def diagnose(self) -> dict[str, Any]:
        d = (self.data or {}).get("diagnose")
        return d if isinstance(d, dict) else {}

    @property
    def usb(self) -> dict[str, Any]:
        u = (self.data or {}).get("usb")
        return u if isinstance(u, dict) else {}

    def leuchten(self, nur_warn: bool | None = None) -> list[dict[str, Any]]:
        """Die Leuchten der Saeule; nur_warn trennt Stufen und Warnleuchte."""
        aus = []
        for r in (self.data or {}).get("relais", []) or []:
            if not isinstance(r, dict):
                continue
            warn = r.get("rolle") == "warn"
            if nur_warn is None or warn == nur_warn:
                aus.append(r)
        return aus

    # --- Befehle ------------------------------------------------------

    async def async_modus(self, auto: bool) -> None:
        await self._post("/api/modus", {"modus": MODUS_AUTO if auto else MODUS_MANUELL})

    async def async_status(self, kennung: str) -> None:
        """Status setzen. Die Saeule stellt dabei selbst auf Auto um."""
        await self._post("/api/status", {"status": kennung})

    async def async_test(self, an: bool) -> None:
        self.test_aktiv = an
        await self._post("/api/test", {"an": 1 if an else 0})

    async def async_diagnose(self) -> None:
        await self._post("/api/diagnose", {})

    async def async_alles_aus(self) -> None:
        await self._post("/api/alarm/stop", {})
