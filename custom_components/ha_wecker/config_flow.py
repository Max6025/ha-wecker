"""Einrichtung der HA-Wecker-Integration ueber die Oberflaeche.

Erster Schritt ist ein Menue: Wecker (Android-App) oder Relaisbox (ESP32).
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
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import (
    CONF_HOST,
    CONF_LAMPE_MUSTER_NACHLAUF,
    CONF_LAMPE_MUSTER_VORLAUF,
    CONF_LAMPE_RELAIS,
    CONF_TYP,
    DOMAIN,
    LAMPE_MUSTER_NACHLAUF_STANDARD,
    LAMPE_MUSTER_VORLAUF_STANDARD,
    LAMPE_RELAIS_STANDARD,
    MUSTER_LISTE,
    TYP_RELAIS,
    TYP_WECKER,
)
from .relais import host_zu_url, relaisbox_abfragen

DEFAULT_NAME_WECKER = "HA Wecker"
DEFAULT_NAME_RELAIS = "Relaisbox"




class HaWeckerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Menue -> Wecker oder Relaisbox."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str = ""
        self._gefunden: dict[str, Any] | None = None

    # --- Menue -----------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["wecker", "relais"])

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

    # --- Relaisbox (ESP32) ----------------------------------------------

    async def _relaisbox_pruefen(self, host: str) -> dict[str, Any] | None:
        try:
            return await relaisbox_abfragen(self.hass, host)
        except Exception:  # noqa: BLE001 - jede Art von Nichterreichbarkeit
            return None

    async def async_step_relais(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = (user_input.get(CONF_HOST) or "").strip()
            daten = await self._relaisbox_pruefen(host) if host else None
            if not host:
                errors[CONF_HOST] = "host_fehlt"
            elif daten is None:
                errors[CONF_HOST] = "nicht_erreichbar"
            else:
                mac = str(daten.get("mac") or host).lower()
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                name = (user_input.get(CONF_NAME) or DEFAULT_NAME_RELAIS).strip() or DEFAULT_NAME_RELAIS
                return self.async_create_entry(
                    title=name,
                    data={CONF_TYP: TYP_RELAIS, CONF_NAME: name, CONF_HOST: host},
                )

        schema = vol.Schema(
            {
                vol.Optional(CONF_NAME, default=DEFAULT_NAME_RELAIS): str,
                vol.Required(CONF_HOST, default=self._host or "relaisbox.local"): str,
            }
        )
        return self.async_show_form(step_id="relais", data_schema=schema, errors=errors)

    # --- Relaisbox per mDNS gefunden -------------------------------------

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        if (discovery_info.properties or {}).get("typ") != "relaisbox":
            return self.async_abort(reason="nicht_relaisbox")
        host = str(discovery_info.host)
        daten = await self._relaisbox_pruefen(host)
        if daten is None:
            return self.async_abort(reason="nicht_erreichbar")
        mac = str(daten.get("mac") or host).lower()
        await self.async_set_unique_id(mac)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        self._host = host
        self._gefunden = daten
        self.context["title_placeholders"] = {"name": f"Relaisbox ({host})"}
        return await self.async_step_relais_bestaetigen()

    async def async_step_relais_bestaetigen(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            name = (user_input.get(CONF_NAME) or DEFAULT_NAME_RELAIS).strip() or DEFAULT_NAME_RELAIS
            return self.async_create_entry(
                title=name,
                data={CONF_TYP: TYP_RELAIS, CONF_NAME: name, CONF_HOST: self._host},
            )
        schema = vol.Schema({vol.Optional(CONF_NAME, default=DEFAULT_NAME_RELAIS): str})
        return self.async_show_form(
            step_id="relais_bestaetigen",
            data_schema=schema,
            description_placeholders={
                "host": self._host,
                "version": str((self._gefunden or {}).get("version", "")),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        if config_entry.data.get(CONF_TYP, TYP_WECKER) == TYP_RELAIS:
            return RelaisOptionsFlow(config_entry)
        return WeckerOptionsFlow(config_entry)


class WeckerOptionsFlow(OptionsFlow):
    """Zeigt die Webhook-Adresse fuer die App. Einzustellen gibt es nichts."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        # Bewusst eigenes Attribut: self.config_entry wird in neueren
        # HA-Versionen vom Rahmen gesetzt, selbst zuweisen ist veraltet.
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=dict(self._entry.options))

        webhook_url = f"/api/webhook/{self._entry.data.get(CONF_WEBHOOK_ID, '')}"
        try:
            webhook_url = webhook.async_generate_url(
                self.hass, self._entry.data[CONF_WEBHOOK_ID]
            )
        except Exception:  # noqa: BLE001 - nur Anzeige
            pass

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({}),
            description_placeholders={"webhook_url": webhook_url},
        )


class RelaisOptionsFlow(OptionsFlow):
    """Adresse der Relaisbox und die Weckerlampe (Relais, Muster) einstellen."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_relais(user_input)

    async def async_step_relais(
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
                    await relaisbox_abfragen(self.hass, host)
                except Exception:  # noqa: BLE001
                    errors[CONF_HOST] = "nicht_erreichbar"
                else:
                    return self.async_create_entry(
                        title="",
                        data={
                            CONF_HOST: host,
                            CONF_LAMPE_RELAIS: int(user_input.get(CONF_LAMPE_RELAIS, LAMPE_RELAIS_STANDARD)),
                            CONF_LAMPE_MUSTER_VORLAUF: user_input.get(
                                CONF_LAMPE_MUSTER_VORLAUF, LAMPE_MUSTER_VORLAUF_STANDARD
                            ),
                            CONF_LAMPE_MUSTER_NACHLAUF: user_input.get(
                                CONF_LAMPE_MUSTER_NACHLAUF, LAMPE_MUSTER_NACHLAUF_STANDARD
                            ),
                        },
                    )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=current): str,
                vol.Required(
                    CONF_LAMPE_RELAIS, default=opt.get(CONF_LAMPE_RELAIS, LAMPE_RELAIS_STANDARD)
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=16)),
                vol.Required(
                    CONF_LAMPE_MUSTER_VORLAUF,
                    default=opt.get(CONF_LAMPE_MUSTER_VORLAUF, LAMPE_MUSTER_VORLAUF_STANDARD),
                ): vol.In(MUSTER_LISTE),
                vol.Required(
                    CONF_LAMPE_MUSTER_NACHLAUF,
                    default=opt.get(CONF_LAMPE_MUSTER_NACHLAUF, LAMPE_MUSTER_NACHLAUF_STANDARD),
                ): vol.In(MUSTER_LISTE),
            }
        )
        return self.async_show_form(
            step_id="relais",
            data_schema=schema,
            errors=errors,
            description_placeholders={"url": host_zu_url(current)},
        )
