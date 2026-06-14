"""HA Intercom custom integration."""
from __future__ import annotations

import logging

import requests
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady

_LOGGER = logging.getLogger(__name__)
DOMAIN = "ha_intercom"
PLATFORMS = [Platform.BUTTON]

CONF_API_URL = "api_url"
CONF_MY_DEVICE = "my_device"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    api_url = entry.data[CONF_API_URL]

    # Verify add-on is reachable
    try:
        resp = await hass.async_add_executor_job(
            lambda: requests.get(f"{api_url}/api/devices", timeout=5)
        )
        resp.raise_for_status()
        devices = resp.json().get("devices", [])
    except Exception as err:
        raise ConfigEntryNotReady(f"Cannot reach intercom API at {api_url}: {err}") from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "api_url": api_url,
        "my_device": entry.data.get(CONF_MY_DEVICE, ""),
        "devices": devices,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register HA services
    async def handle_initiate(call: ServiceCall):
        caller = call.data.get("caller", entry.data.get(CONF_MY_DEVICE, ""))
        callee = call.data["callee"]
        await hass.async_add_executor_job(
            lambda: requests.post(
                f"{api_url}/api/call/initiate",
                json={"caller": caller, "callee": callee},
                timeout=10,
            )
        )

    async def handle_hangup(call: ServiceCall):
        call_id = call.data["call_id"]
        await hass.async_add_executor_job(
            lambda: requests.post(f"{api_url}/api/call/hangup/{call_id}", timeout=10)
        )

    hass.services.async_register(DOMAIN, "initiate_call", handle_initiate)
    hass.services.async_register(DOMAIN, "hangup_call", handle_hangup)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
