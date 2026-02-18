from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_BASE_URL,
    CONF_CHARGER_IDENTIFIER,
    CONF_COGNITO_CLIENT_ID,
    CONF_COGNITO_USERNAME,
    CONF_COGNITO_REGION,
    CONF_CONNECTOR,
    CONF_DRIVER_ID,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    DEFAULT_BASE_URL,
    DEFAULT_COGNITO_CLIENT_ID,
    DEFAULT_COGNITO_REGION,
    DEFAULT_CONNECTOR,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .wevo_api import WevoApiClient, WevoApiError


class WevoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._login_data: dict[str, Any] = {}
        self._chargers: list[str] = []
        self._driver_id: int | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input["email"].strip()
            password = user_input["password"]
            base_url = user_input.get(CONF_BASE_URL, DEFAULT_BASE_URL)
            cognito_region = user_input.get(CONF_COGNITO_REGION, DEFAULT_COGNITO_REGION)
            cognito_client_id = user_input.get(CONF_COGNITO_CLIENT_ID, DEFAULT_COGNITO_CLIENT_ID)

            session = async_get_clientsession(self.hass)
            api = WevoApiClient(session, base_url, cognito_region, cognito_client_id)

            try:
                tokens = await api.login(email, password)
                details = await api.get_user_details(tokens.access_token)
                txs = await api.get_transactions(tokens.access_token)

                chargers = set()
                assigned = details.get("chargerIdentifier")
                if assigned:
                    chargers.add(str(assigned))
                for tx in txs:
                    cid = tx.get("chargerIdentifier")
                    if cid:
                        chargers.add(str(cid))

                if not chargers:
                    errors["base"] = "no_chargers"
                else:
                    self._chargers = sorted(chargers)
                    self._driver_id = details.get("userId")
                    self._login_data = {
                        CONF_ACCESS_TOKEN: tokens.access_token,
                        CONF_REFRESH_TOKEN: tokens.refresh_token,
                        CONF_EXPIRES_AT: tokens.expires_at,
                        CONF_BASE_URL: base_url,
                        CONF_COGNITO_REGION: cognito_region,
                        CONF_COGNITO_CLIENT_ID: cognito_client_id,
                        CONF_COGNITO_USERNAME: tokens.cognito_username,
                    }
                    return await self.async_step_charger()
            except WevoApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"

        schema = vol.Schema(
            {
                vol.Required("email"): str,
                vol.Required("password"): str,
                vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
                vol.Optional(CONF_COGNITO_REGION, default=DEFAULT_COGNITO_REGION): str,
                vol.Optional(CONF_COGNITO_CLIENT_ID, default=DEFAULT_COGNITO_CLIENT_ID): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_charger(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            charger_identifier = user_input[CONF_CHARGER_IDENTIFIER]
            await self.async_set_unique_id(f"{DOMAIN}_{charger_identifier}")
            self._abort_if_unique_id_configured()

            data = {
                **self._login_data,
                CONF_CHARGER_IDENTIFIER: charger_identifier,
                CONF_CONNECTOR: int(user_input.get(CONF_CONNECTOR, DEFAULT_CONNECTOR)),
                CONF_SCAN_INTERVAL: int(user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
            }
            if self._driver_id is not None:
                data[CONF_DRIVER_ID] = int(self._driver_id)

            return self.async_create_entry(title=f"Wevo {charger_identifier}", data=data)

        schema = vol.Schema(
            {
                vol.Required(CONF_CHARGER_IDENTIFIER): vol.In(self._chargers),
                vol.Optional(CONF_CONNECTOR, default=DEFAULT_CONNECTOR): vol.Coerce(int),
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.Coerce(int),
            }
        )
        return self.async_show_form(step_id="charger", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return WevoOptionsFlow(config_entry)


class WevoOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            new_data = {**self.config_entry.data, **user_input}
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            return self.async_create_entry(title="", data={})

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.Coerce(int),
                vol.Optional(
                    CONF_CONNECTOR,
                    default=self.config_entry.data.get(CONF_CONNECTOR, DEFAULT_CONNECTOR),
                ): vol.Coerce(int),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
