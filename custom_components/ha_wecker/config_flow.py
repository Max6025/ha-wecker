"""Einrichtung der HA-Wecker-Integration ueber die Oberflaeche.

Erster Schritt ist ein Menue: Wecker (Android-App) oder Signalsaeule
(Arduino UNO R4 WiFi). Eine Relaisbox gab es bis November 2026 daneben;
die Weckerlampe haengt seitdem am Wecker, siehe ablauf.py.
"""
from __future__ import annotations

import json

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

from .ablauf import STANDARD_ABLAUF, ablauf_lesen
from .const import (
    CONF_ABLAUF,
    CONF_HAUPTLICHT,
    CONF_HOST,
    CONF_TYP,
    DOMAIN,
    TYP_SAEULE,
    TYP_WECKER,
)
from .saeule import host_zu_url, saeule_abfragen

DEFAULT_NAME_WECKER = "HA Wecker"
DEFAULT_NAME_SAEULE = "Signalsäule"




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
        return self.async_show_menu(step_id="user", menu_options=["wecker", "saeule"])

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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        typ = config_entry.data.get(CONF_TYP, TYP_WECKER)
        if typ == TYP_SAEULE:
            return SaeuleOptionsFlow(config_entry)
        return WeckerOptionsFlow(config_entry)


class WeckerOptionsFlow(OptionsFlow):
    """Webhook-Adresse, Hauptlicht und die Ablaufdatei des Weckablaufs."""

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
            _, fehler = ablauf_lesen(roh)
            if fehler:
                errors[CONF_ABLAUF] = "ablauf_fehler"
            else:
                daten = dict(opt)
                daten[CONF_ABLAUF] = roh
                # Leere Auswahl heisst: kein Hauptlicht mehr, also wirklich loeschen
                licht = user_input.get(CONF_HAUPTLICHT)
                if licht:
                    daten[CONF_HAUPTLICHT] = str(licht)
                else:
                    daten.pop(CONF_HAUPTLICHT, None)
                return self.async_create_entry(title="", data=daten)

        webhook_url = f"/api/webhook/{self._entry.data.get(CONF_WEBHOOK_ID, '')}"
        try:
            webhook_url = webhook.async_generate_url(
                self.hass, self._entry.data[CONF_WEBHOOK_ID]
            )
        except Exception:  # noqa: BLE001 - nur Anzeige
            pass

        vorgabe = opt.get(CONF_ABLAUF) or json.dumps(
            STANDARD_ABLAUF, indent=2, ensure_ascii=False
        )
        felder: dict[Any, Any] = {}
        felder[vol.Optional(CONF_HAUPTLICHT, description={"suggested_value": opt.get(CONF_HAUPTLICHT)})] = (
            selector.EntitySelector(selector.EntitySelectorConfig(domain="light"))
        )
        felder[vol.Optional(CONF_ABLAUF, description={"suggested_value": vorgabe})] = (
            selector.TextSelector(selector.TextSelectorConfig(multiline=True))
        )
        _, fehler = ablauf_lesen(opt.get(CONF_ABLAUF))
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(felder),
            errors=errors,
            description_placeholders={"webhook_url": webhook_url, "fehler": fehler or "-"},
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
