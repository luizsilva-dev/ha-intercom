"""Home Assistant API client — notifications, events and device discovery."""
import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class HAClient:
    def __init__(self):
        self._token = os.environ.get("HA_TOKEN", "")
        self._base_url = os.environ.get("HA_URL", "http://supervisor/core")
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        })

    def _get(self, path: str) -> Optional[requests.Response]:
        try:
            resp = self._session.get(f"{self._base_url}{path}", timeout=10)
            resp.raise_for_status()
            return resp
        except Exception as e:
            logger.error("HA GET %s: %s", path, e)
            return None

    def _post(self, path: str, data: dict) -> Optional[requests.Response]:
        try:
            resp = self._session.post(f"{self._base_url}{path}", json=data, timeout=10)
            resp.raise_for_status()
            return resp
        except Exception as e:
            logger.error("HA POST %s: %s", path, e)
            return None

    # ------------------------------------------------------------------
    # Device discovery
    # ------------------------------------------------------------------

    def discover_mobile_apps(self) -> list[dict]:
        """Return mobile_app notify services registered in HA."""
        resp = self._get("/api/services")
        if not resp:
            return []
        services = resp.json()
        result = []
        for domain_block in services:
            if domain_block.get("domain") != "notify":
                continue
            for svc_id, svc in domain_block.get("services", {}).items():
                if not svc_id.startswith("mobile_app_"):
                    continue
                app_id = svc_id[len("mobile_app_"):]
                result.append({
                    "id": app_id,
                    "name": svc.get("name", app_id),
                    "type": "android",
                    "entity_id": f"notify.{svc_id}",
                })
        return result

    def discover_voice_pe(self) -> list[dict]:
        """Return media_player entities that look like Voice PE / ESPHome speakers."""
        resp = self._get("/api/states")
        if not resp:
            return []
        result = []
        for state in resp.json():
            entity_id = state.get("entity_id", "")
            if not entity_id.startswith("media_player."):
                continue
            attrs = state.get("attributes", {})
            integration = attrs.get("platform", "") or attrs.get("integration", "")
            friendly = attrs.get("friendly_name", entity_id)
            # Include ESPHome and HA voice satellites
            if any(kw in entity_id.lower() or kw in friendly.lower() or kw in integration.lower()
                   for kw in ("voice_pe", "voice pe", "esphome", "assist", "satellite")):
                result.append({
                    "id": entity_id,
                    "name": friendly,
                    "type": "voice_pe",
                    "entity_id": entity_id,
                })
        return result

    def discover_all(self) -> list[dict]:
        apps = self.discover_mobile_apps()
        pes = self.discover_voice_pe()
        return apps + pes

    # ------------------------------------------------------------------
    # Notifications & events
    # ------------------------------------------------------------------

    def fire_event(self, event_type: str, data: dict):
        self._post(f"/api/events/{event_type}", data)

    def notify_mobile(self, mobile_app_id: str, title: str, message: str, call_id: str):
        self._post(f"/api/services/notify/mobile_app_{mobile_app_id}", {
            "title": title,
            "message": message,
            "data": {
                "actions": [
                    {"action": f"INTERCOM_ANSWER_{call_id}", "title": "Atender"},
                    {"action": f"INTERCOM_REJECT_{call_id}", "title": "Rejeitar"},
                ],
                "tag": f"intercom_{call_id}",
                "channel": "intercom",
                "importance": "high",
                "ttl": 0,
                "priority": "high",
            },
        })

    def announce_voice_pe(self, entity_id: str, message: str):
        self._post("/api/services/tts/google_translate_say", {
            "entity_id": entity_id,
            "message": message,
            "language": "pt-br",
        })

    def play_rtsp_on_voice_pe(self, entity_id: str, rtsp_url: str):
        self._post("/api/services/media_player/play_media", {
            "entity_id": entity_id,
            "media_content_id": rtsp_url,
            "media_content_type": "music",
        })
