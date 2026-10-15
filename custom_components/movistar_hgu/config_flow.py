"""Config flow for the Movistar HGU integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import CONF_SSH_ENABLED, CONF_SSH_PORT, DEFAULT_HOST, DEFAULT_SSH_PORT, DOMAIN
from .coordinator import HguConfigEntry
from .hgu.client import HguClient, new_session
from .hgu.errors import HguAuthError, HguConnectionError, HguError
from .hgu.models import SystemInfo

_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


async def _validate(hass: Any, host: str, password: str) -> SystemInfo:
    async with new_session() as session:
        client = HguClient(session, host, password)
        try:
            return await client.async_get_summary()
        finally:
            await client.async_logout()


def _errors_for(err: Exception) -> dict[str, str]:
    if isinstance(err, HguAuthError):
        return {"base": "invalid_auth"}
    if isinstance(err, HguConnectionError):
        return {"base": "cannot_connect"}
    return {"base": "unknown"}


class MovistarHguConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a router: host + admin password (the one on its sticker)."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: HguConfigEntry) -> OptionsFlow:
        return MovistarHguOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await _validate(self.hass, user_input[CONF_HOST], user_input[CONF_PASSWORD])
            except HguError as err:
                errors = _errors_for(err)
            else:
                await self.async_set_unique_id(info.serial_number or user_input[CONF_HOST])
                self._abort_if_unique_id_configured(updates={CONF_HOST: user_input[CONF_HOST]})
                return self.async_create_entry(
                    title=f"Router Movistar {info.model}", data=user_input
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_HOST): str, vol.Required(CONF_PASSWORD): _PASSWORD}),
                user_input or {CONF_HOST: DEFAULT_HOST},
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await _validate(self.hass, entry.data[CONF_HOST], user_input[CONF_PASSWORD])
            except HguError as err:
                errors = _errors_for(err)
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): _PASSWORD}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change host/password (e.g. when the LAN moves to 192.168.0.1)."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await _validate(self.hass, user_input[CONF_HOST], user_input[CONF_PASSWORD])
            except HguError as err:
                errors = _errors_for(err)
            else:
                await self.async_set_unique_id(info.serial_number or user_input[CONF_HOST])
                self._abort_if_unique_id_mismatch(reason="wrong_router")
                return self.async_update_reload_and_abort(entry, data_updates=user_input)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_HOST): str, vol.Required(CONF_PASSWORD): _PASSWORD}),
                {CONF_HOST: entry.data[CONF_HOST]},
            ),
            errors=errors,
        )


class MovistarHguOptionsFlow(OptionsFlow):
    """SSH console extras on/off."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_SSH_ENABLED): bool,
                        vol.Required(CONF_SSH_PORT): vol.All(
                            vol.Coerce(int), vol.Range(min=1, max=65535)
                        ),
                    }
                ),
                {
                    CONF_SSH_ENABLED: self.config_entry.options.get(CONF_SSH_ENABLED, False),
                    CONF_SSH_PORT: self.config_entry.options.get(CONF_SSH_PORT, DEFAULT_SSH_PORT),
                },
            ),
        )
