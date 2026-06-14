"""Config flow for HA Intercom."""
from __future__ import annotations

import requests
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from . import CONF_API_URL, CONF_MY_DEVICE, DOMAIN

STEP_USER_SCHEMA = vol.Schema({
    vol.Required(CONF_API_URL, default="http://homeassistant.local:8099"): str,
    vol.Required(CONF_MY_DEVICE): str,
})


class IntercomConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            api_url = user_input[CONF_API_URL].rstrip("/")
            try:
                resp = await self.hass.async_add_executor_job(
                    lambda: requests.get(f"{api_url}/api/devices", timeout=5)
                )
                resp.raise_for_status()
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(api_url)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="HA Intercom",
                    data={CONF_API_URL: api_url, CONF_MY_DEVICE: user_input[CONF_MY_DEVICE]},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )
