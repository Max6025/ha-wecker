"""Verbindung zur Signalsaeule (Arduino UNO R4 WiFi).

Die Saeule meldet unter /api/state eine Liste "relais" (vier Stufen und die
Blitz-Warnleuchte), nimmt Befehle als POST entgegen und haelt auf einem
eigenen Port eine Verbindung offen, ueber die sie jede Aenderung sofort
schickt. Die Abfrage alle paar Sekunden ist nur die Rueckfallebene.

Bis November 2026 stand hier eine Relaisbox (ESP32) daneben und dieser
Coordinator erbte von ihrem. Die Box gibt es nicht mehr; was von ihr gebraucht
wurde - Abfrage, Ereignisstrom, POST - steht jetzt hier.
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

from .const import (
    CONF_HOST,
    DOMAIN,
    MODUS_AUTO,
    MODUS_MANUELL,
    ROLLE_STUFE,
    ROLLE_TON,
    ROLLE_WARN,
    SAEULE_ABFRAGE_S,
    STATUS_STANDARD,
)

_LOGGER = logging.getLogger(__name__)

ZEIT = aiohttp.ClientTimeout(total=8)
# Ereignisstrom: keine Gesamtdauer, aber die Saeule schickt alle 15 s ein
# Lebenszeichen - bleibt das 60 s aus, gilt die Verbindung als tot.
ZEIT_EVENTS = aiohttp.ClientTimeout(total=None, sock_connect=8, sock_read=60)
EVENTS_PORT_STANDARD = 8081


def host_zu_url(host: str) -> str:
    host = (host or "").strip().rstrip("/")
    if host and "://" not in host:
        host = "http://" + host
    return host


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


class SaeuleCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fragt die Signalsaeule ab und schickt ihre Befehle."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} Signalsaeule",
            update_interval=timedelta(seconds=SAEULE_ABFRAGE_S),
        )
        self.entry = entry
        self._events_task: asyncio.Task | None = None
        self.events_verbunden = False
        self.test_aktiv = False      # Schalter "Testmodus"
        # Betriebsart "Ampel" - siehe ampel.py. Sie steht nicht hier, weil sie
        # die Garage braucht und saeule.py die nicht kennen soll; __init__.py
        # haengt sie ein.
        self.ampel: Any = None

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
            return await saeule_abfragen(self.hass, self.host)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise UpdateFailed(f"Signalsaeule {self.host} nicht erreichbar: {err}") from err

    def relais(self, nr: int) -> dict[str, Any] | None:
        for r in (self.data or {}).get("relais", []) or []:
            if r.get("nr") == nr:
                return r
        return None

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

    def leuchten(self, rolle: str | None = None) -> list[dict[str, Any]]:
        """Die Ausgaenge der Saeule, bei Bedarf nur die einer Rolle.

        Ohne Angabe alle. Ein Ausgang ohne gemeldete Rolle gilt als Stufe -
        sonst fielen bei einer aelteren Firmware alle Schalter weg.
        """
        aus = []
        for r in (self.data or {}).get("relais", []) or []:
            if not isinstance(r, dict):
                continue
            if rolle is None or str(r.get("rolle") or ROLLE_STUFE) == rolle:
                aus.append(r)
        return aus

    def nummer_fuer(self, rolle: str) -> int | None:
        """Nummer des Ausgangs mit dieser Rolle; None, wenn es ihn nicht gibt.

        Die Nummern sind in der Firmware stabil (1-4 Stufen, 5 Warnleuchte,
        6 Ton), aber hier nicht hartkodiert: eine Saeule ohne Tongeber meldet
        Nr. 6 einfach nicht, und dann soll der Schritt sauber ausfallen statt
        ins Leere zu schalten.
        """
        for r in self.leuchten(rolle):
            nr = r.get("nr")
            if isinstance(nr, int):
                return nr
        return None

    def nummer_farbe(self, farbe: str) -> int | None:
        """Nummer des Ausgangs mit dieser Farbe; None, wenn es ihn nicht gibt.

        Die Farbe meldet die Saeule selbst (ab Firmware 1.3.0). Die Ampel der
        Garage braucht genau das: "rot" und "gruen", nicht Nummer drei und
        Nummer eins. Eine aeltere Firmware meldet keine Farbe - dann findet
        sich keine, und wer danach fragt, bekommt sauber nichts.
        """
        for r in self.leuchten():
            if str(r.get("farbe") or "") == farbe:
                nr = r.get("nr")
                if isinstance(nr, int):
                    return nr
        return None

    def stufen_farben(self) -> list[str]:
        """Die Farben, die die Saeule als Stufen meldet - fuer die Diagnose."""
        return [str(r.get("farbe") or "") for r in self.leuchten(ROLLE_STUFE)]

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

    async def async_piep(self, muster: str | None = None) -> None:
        """Quittungston auf dem Tongeber.

        Die Saeule gibt die Folge selbst, nicht Home Assistant mit mehreren
        Schaltbefehlen und Pausen dazwischen: so stimmen die Zeiten wirklich,
        auch wenn das Netz gerade langsam ist. Ohne Angabe gilt das Muster,
        das in der Firmware steht - das ist Absicht, denn gehoert wird es am
        Geraet und nicht hier. `muster` nimmt Dauern in Millisekunden,
        abwechselnd Ton und Pause ("400,500,800"). Der Dauerton des Schalters
        bleibt unberuehrt.
        """
        await self._post("/api/piep", {"muster": muster} if muster else {})

    async def async_stufen_stellen(self, bild: dict[str, int]) -> None:
        """Das ganze Stufenbild in einem Zug setzen (Betriebsart manuell).

        `bild` bildet die Farbe auf die Blinkperiode in ms ab, 0 heisst
        dauernd; was nicht darin steht, geht aus. Fuer die Betriebsart
        "Ampel": die Saeule soll ein ruhiges Bild zeigen, keine Choreografie -
        darum nicht ueber den Status. Und in einem Ruf, nicht Stufe fuer
        Stufe: vier Anfragen hintereinander sieht man flackern. Braucht
        Firmware 1.7.0.
        """
        werte = {farbe: periode for farbe, periode in bild.items()}
        await self._post("/api/stufen", werte)

    # --- Ereignisstrom -----------------------------------------------

    @property
    def events_url(self) -> str:
        port = (self.data or {}).get("events_port") or EVENTS_PORT_STANDARD
        schema, _, rest = self.url.partition("://")
        erster = rest.split("/", 1)[0]
        hostteil = erster.rsplit(":", 1)[0] if ":" in erster else erster
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
                    raise UpdateFailed(f"Signalsaeule antwortete {resp.status}: {text}")
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise UpdateFailed(f"Signalsaeule {self.host} nicht erreichbar: {err}") from err
        if isinstance(data, dict) and "relais" in data:
            # Antwort ist der neue Zustand - direkt uebernehmen, ohne Abfrage
            self.async_set_updated_data(data)

    async def async_schalten(
        self, nr: int, an: bool, blinken_ms: int = 0
    ) -> None:
        """Eine Leuchte schalten, auf Wunsch blinkend.

        `blinken_ms` ist die Periode (halb an, halb aus) und gilt nur fuer die
        Stufen in der Betriebsart manuell - die Saeule macht das Blinken
        selbst, denn Home Assistant kann nicht im Sekundentakt schalten.
        Braucht Firmware 1.6.0.
        """
        werte: dict[str, Any] = {"an": 1 if an else 0}
        if an and blinken_ms:
            werte["blinken"] = blinken_ms
        await self._post(f"/api/relais/{nr}", werte)

    async def async_rolle_schalten(self, rolle: str, an: bool) -> None:
        """Den Ausgang dieser Rolle schalten (Warnleuchte, Tongeber)."""
        nr = self.nummer_fuer(rolle)
        if nr is None:
            raise UpdateFailed(f"Die Saeule hat keinen Ausgang \"{rolle}\"")
        await self.async_schalten(nr, an)

    @property
    def ton_an(self) -> bool:
        return bool((self.data or {}).get(ROLLE_TON))
