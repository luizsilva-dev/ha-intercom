"""Home Assistant API client for notifications and events."""
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

    def _post(self, path: str, data: dict) -> Optional[requests.Response]:
        try:
            resp = self._session.post(f"{self._base_url}{path}", json=data, timeout=10)
            resp.raise_for_status()
            return resp
        except Exception as e:
            logger.error("HA API error %s: %s", path, e)
            return None

    def fire_event(self, event_type: str, data: dict):
        self._post(f"/api/events/{event_type}", data)

    def notify_mobile(self, mobile_app_id: str, title: str, message: str, call_id: str, action: str):
        """Send actionable notification to HA Android app."""
        self._post(f"/api/services/notify/mobile_app_{mobile_app_id}", {
            "title": title,
            "message": message,
            "data": {
                "actions": [
                    {
                        "action": f"INTERCOM_ANSWER_{call_id}",
                        "title": "Atender",
                        "uri": f"/api/intercom/answer/{call_id}",
                    },
                    {
                        "action": f"INTERCOM_REJECT_{call_id}",
                        "title": "Rejeitar",
                    },
                ],
                "tag": f"intercom_{call_id}",
                "channel": "intercom",
                "importance": "high",
                "ttl": 0,
                "priority": "high",
            },
        })

    def notify_persistent(self, title: str, message: str):
        self._post("/api/services/persistent_notification/create", {
            "title": title,
            "message": message,
        })

    def announce_voice_pe(self, entity_id: str, message: str):
        """Use TTS to announce incoming call on Voice PE."""
        self._post("/api/services/tts/google_translate_say", {
            "entity_id": entity_id,
            "message": message,
            "language": "pt-br",
        })

    def play_rtsp_on_voice_pe(self, entity_id: str, rtsp_url: str):
        """Stream intercom audio to Voice PE via media_player."""
        self._post("/api/services/media_player/play_media", {
            "entity_id": entity_id,
            "media_content_id": rtsp_url,
            "media_content_type": "music",
        })

    def call_script(self, script_id: str, variables: dict = None):
        self._post(f"/api/services/script/{script_id}", variables or {})
