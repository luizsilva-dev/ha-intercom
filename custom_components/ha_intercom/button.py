"""Button entities — one per device for 'Call <device>' actions."""
from __future__ import annotations

import logging

import requests
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    api_url = data["api_url"]
    my_device = data["my_device"]
    devices = data["devices"]

    entities = [
        CallButton(api_url, my_device, device)
        for device in devices
        if device.get("name") != my_device
    ]
    async_add_entities(entities, update_before_add=False)


class CallButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:phone"

    def __init__(self, api_url: str, caller: str, callee_device: dict):
        self._api_url = api_url
        self._caller = caller
        self._callee = callee_device["name"]
        self._attr_name = f"Ligar para {self._callee}"
        self._attr_unique_id = f"ha_intercom_call_{caller}_to_{self._callee}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "ha_intercom")},
            name="HA Intercom",
            manufacturer="ha-intercom",
            model="go2rtc WebRTC",
        )

    async def async_press(self) -> None:
        try:
            await self.hass.async_add_executor_job(
                lambda: requests.post(
                    f"{self._api_url}/api/call/initiate",
                    json={"caller": self._caller, "callee": self._callee},
                    timeout=10,
                )
            )
        except Exception as err:
            _LOGGER.error("Failed to initiate call to %s: %s", self._callee, err)
