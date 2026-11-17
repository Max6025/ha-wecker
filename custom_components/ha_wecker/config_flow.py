"""Einrichtung der HA-Wecker-Integration ueber die Oberflaeche.

Erster Schritt ist ein Menue: Wecker (Android-App), Signalsaeule
(Arduino UNO R4 WiFi) oder Garage (ESP32 an der Lichtschranke). Eine Relaisbox
gab es bis November 2026 daneben; die Weckerlampe haengt seitdem am Wecker,
siehe ablauf.py.

Den Schritt "garage" durchlaeuft normalerweise kein Mensch: der Garagen-ESP
startet ihn selbst ueber die REST-Schnittstelle (POST
/api/config/config_entries/flow mit handler ha_wecker, dann next_step_id
garage, dann name und host). Darum muss er mit genau diesen Feldern stabil
bleiben; ein Wechsel der IP laeuft ueber denselben Weg und aktualisiert nur
die Adresse (updates=... beim abort).
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import webhook
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME, CONF_WEBHOOK_ID
from homeassistant.core import callback
from homeassistant.helpers import selector

from .ablauf import ablauf_lesen
from .const import (
    CONF_ABLAUF,
    CONF_HAUPTLICHT,
    CONF_HOST,
    CONF_STROM,
    CONF_STROMPLAN,
    CONF_TYP,
    DOMAIN,
    TYP_GARAGE,
    TYP_SAEULE,
    TYP_WECKER,
)
from .garage import garage_abfragen
from .strom import stromplan_lesen
from .saeule import host_zu_url, saeule_abfragen

DEFAULT_NAME_WECKER = "HA Wecker"
DEFAULT_NAME_SAEULE = "Signalsäule"
DEFAULT_NAME_GARAGE = "Garage"




class HaWeckerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Menue -> Wecker oder Signalsaeule."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str = ""
        self._gefunden: dict[str, Any] | None = None

    # --- Menue -----------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["wecker", "saeule", "garage"])

    # --- Wecker (Android-App) -------------------------------------------

    async def async_step_wecker(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            name = (user_input.get(CONF_NAME) or DEFAULT_NAME_WECKER).strip() or DEFAULT_NAME_WECKER
            webhook_id = webhook.async_generate_id()
            return self.async_create_entry(
                title=name,
                data={CONF_TYP: TYP_WECKER, CONF_NAME: name, CONF_WEBHOOK_ID: webhook_id},
            )

        schema = vol.Schema({vol.Optional(CONF_NAME, default=DEFAULT_NAME_WECKER): str})
        return self.async_show_form(step_id="wecker", data_schema=schema)

    # --- Signalsaeule (Arduino UNO R4 WiFi) ------------------------------

    async def async_step_saeule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = (user_input.get(CONF_HOST) or "").strip()
            daten = None
            if host:
                try:
                    daten = await saeule_abfragen(self.hass, host)
                except Exception:  # noqa: BLE001 - jede Art von Nichterreichbarkeit
                    daten = None
            if not host:
                errors[CONF_HOST] = "host_fehlt"
            elif daten is None:
                errors[CONF_HOST] = "keine_saeule"
            else:
                mac = str(daten.get("mac") or host).lower()
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                name = (user_input.get(CONF_NAME) or DEFAULT_NAME_SAEULE).strip() or DEFAULT_NAME_SAEULE
                return self.async_create_entry(
                    title=name,
                    data={CONF_TYP: TYP_SAEULE, CONF_NAME: name, CONF_HOST: host},
                )

        schema = vol.Schema(
            {
                vol.Optional(CONF_NAME, default=DEFAULT_NAME_SAEULE): str,
                vol.Required(CONF_HOST, default="signalsaeule.local"): str,
            }
        )
        return self.async_show_form(step_id="saeule", data_schema=schema, errors=errors)

    # --- Garage (ESP32 an der Lichtschranke) ------------------------------

    async def async_step_garage(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = (user_input.get(CONF_HOST) or "").strip()
            daten = None
            if host:
                try:
                    daten = await garage_abfragen(self.hass, host)
                except Exception:  # noqa: BLE001
                    daten = None
            if not host:
                errors[CONF_HOST] = "host_fehlt"
            elif daten is None:
                errors[CONF_HOST] = "keine_garage"
            else:
                mac = str(daten.get("mac") or host).lower()
                await self.async_set_unique_id(mac)
                # Meldet sich der ESP mit neuer IP noch einmal, wird nur die Adresse nachgezogen
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                name = (user_input.get(CONF_NAME) or DEFAULT_NAME_GARAGE).strip() or DEFAULT_NAME_GARAGE
                return self.async_create_entry(
                    title=name,
                    data={CONF_TYP: TYP_GARAGE, CONF_NAME: name, CONF_HOST: host},
                )

        schema = vol.Schema(
            {
                vol.Optional(CONF_NAME, default=DEFAULT_NAME_GARAGE): str,
                vol.Required(CONF_HOST, default="van206-ls.local"): str,
            }
        )
        return self.async_show_form(step_id="garage", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        typ = config_entry.data.get(CONF_TYP, TYP_WECKER)
        if typ == TYP_SAEULE:
            return SaeuleOptionsFlow(config_entry)
        if typ == TYP_GARAGE:
            return GarageOptionsFlow(config_entry)
        return WeckerOptionsFlow(config_entry)


class WeckerOptionsFlow(OptionsFlow):
    """Webhook-Adresse, Hauptlicht, Ablaufdatei und Stromplan der Saeule."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        # Bewusst eigenes Attribut: self.config_entry wird in neueren
        # HA-Versionen vom Rahmen gesetzt, selbst zuweisen ist veraltet.
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        opt = self._entry.options

        if user_input is not None:
            roh = (user_input.get(CONF_ABLAUF) or "").strip()
            roh_strom = (user_input.get(CONF_STROMPLAN) or "").strip()
            _, fehler = ablauf_lesen(roh)
            _, fehler_strom = stromplan_lesen(roh_strom)
            if fehler:
                errors[CONF_ABLAUF] = "ablauf_fehler"
            if fehler_strom:
                errors[CONF_STROMPLAN] = "stromplan_fehler"
            if not errors:
                daten = dict(opt)
                daten[CONF_ABLAUF] = roh
                daten[CONF_STROMPLAN] = roh_strom
                # Leere Auswahl heisst: nicht mehr gesetzt, also wirklich loeschen
                for feld, domaene in ((CONF_HAUPTLICHT, "light"), (CONF_STROM, "switch")):
                    wert = user_input.get(feld)
                    if wert:
                        daten[feld] = str(wert)
                    else:
                        daten.pop(feld, None)
                return self.async_create_entry(title="", data=daten)

        webhook_url = f"/api/webhook/{self._entry.data.get(CONF_WEBHOOK_ID, '')}"
        try:
            webhook_url = webhook.async_generate_url(
                self.hass, self._entry.data[CONF_WEBHOOK_ID]
            )
        except Exception:  # noqa: BLE001 - nur Anzeige
            pass

        # Bewusst NICHT mit dem Standardablauf vorausfuellen: wer das Feld
        # einmal so speichert, friert den damaligen Stand ein und bekommt
        # spaetere Verbesserungen nie. Leer heisst "nimm den aktuellen
        # Standard"; wer einen eigenen Ablauf hat, sieht hier seinen.
        vorgabe = opt.get(CONF_ABLAUF) or ""
        felder: dict[Any, Any] = {}
        felder[vol.Optional(CONF_HAUPTLICHT, description={"suggested_value": opt.get(CONF_HAUPTLICHT)})] = (
            selector.EntitySelector(selector.EntitySelectorConfig(domain="light"))
        )
        felder[vol.Optional(CONF_ABLAUF, description={"suggested_value": vorgabe})] = (
            selector.TextSelector(selector.TextSelectorConfig(multiline=True))
        )
        felder[vol.Optional(CONF_STROM, description={"suggested_value": opt.get(CONF_STROM)})] = (
            selector.EntitySelector(selector.EntitySelectorConfig(domain="switch"))
        )
        felder[
            vol.Optional(
                CONF_STROMPLAN,
                description={"suggested_value": opt.get(CONF_STROMPLAN) or ""},
            )
        ] = selector.TextSelector(selector.TextSelectorConfig(multiline=True))
        _, fehler = ablauf_lesen(opt.get(CONF_ABLAUF))
        _, fehler_strom = stromplan_lesen(opt.get(CONF_STROMPLAN))
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(felder),
            errors=errors,
            description_placeholders={
                "webhook_url": webhook_url,
                "fehler": fehler or "-",
                "fehler_strom": fehler_strom or "-",
            },
        )


class SaeuleOptionsFlow(OptionsFlow):
    """Adresse der Signalsaeule. Alles Weitere steht auf ihrem eigenen Dashboard."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        # Eigener Schritt-Name, damit der Text nicht mit dem des Weckers kollidiert
        return await self.async_step_saeule(user_input)

    async def async_step_saeule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        opt = self._entry.options
        current = opt.get(CONF_HOST, self._entry.data.get(CONF_HOST, ""))

        if user_input is not None:
            host = (user_input.get(CONF_HOST) or "").strip()
            if not host:
                errors[CONF_HOST] = "host_fehlt"
            else:
                try:
                    await saeule_abfragen(self.hass, host)
                except Exception:  # noqa: BLE001
                    errors[CONF_HOST] = "keine_saeule"
                else:
                    return self.async_create_entry(title="", data={CONF_HOST: host})

        return self.async_show_form(
            step_id="saeule",
            data_schema=vol.Schema({vol.Required(CONF_HOST, default=current): str}),
            errors=errors,
            description_placeholders={"url": host_zu_url(current)},
        )


class GarageOptionsFlow(OptionsFlow):
    """Adresse des Garagen-ESP. Normalerweise haelt er sie selbst aktuell."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_garage(user_input)

    async def async_step_garage(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        opt = self._entry.options
        current = opt.get(CONF_HOST, self._entry.data.get(CONF_HOST, ""))

        if user_input is not None:
            host = (user_input.get(CONF_HOST) or "").strip()
            if not host:
                errors[CONF_HOST] = "host_fehlt"
            else:
                try:
                    await garage_abfragen(self.hass, host)
                except Exception:  # noqa: BLE001
                    errors[CONF_HOST] = "keine_garage"
                else:
                    return self.async_create_entry(title="", data={CONF_HOST: host})

        return self.async_show_form(
            step_id="garage",
            data_schema=vol.Schema({vol.Required(CONF_HOST, default=current): str}),
            errors=errors,
            description_placeholders={"url": host_zu_url(current)},
        )
