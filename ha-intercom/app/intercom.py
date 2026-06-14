"""Call state management and go2rtc stream lifecycle."""
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import requests

logger = logging.getLogger(__name__)

GO2RTC_URL = None  # set at startup


class CallState(str, Enum):
    RINGING = "ringing"
    ACTIVE = "active"
    ENDED = "ended"
    REJECTED = "rejected"
    TIMEOUT = "timeout"


@dataclass
class Call:
    id: str
    caller: str
    callee: str
    state: CallState = CallState.RINGING
    created_at: float = field(default_factory=time.time)
    answered_at: Optional[float] = None
    ended_at: Optional[float] = None
    stream_name: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "caller": self.caller,
            "callee": self.callee,
            "state": self.state,
            "created_at": self.created_at,
            "answered_at": self.answered_at,
            "ended_at": self.ended_at,
            "stream_name": self.stream_name,
        }


class IntercomManager:
    def __init__(self, go2rtc_url: str, call_timeout: int, max_call_duration: int):
        self._calls: dict[str, Call] = {}
        self._lock = threading.Lock()
        self._go2rtc_url = go2rtc_url
        self._call_timeout = call_timeout
        self._max_call_duration = max_call_duration
        self._start_watchdog()

    def _start_watchdog(self):
        t = threading.Thread(target=self._watchdog, daemon=True)
        t.start()

    def _watchdog(self):
        """Ends stale calls that were never answered or exceeded max duration."""
        while True:
            time.sleep(5)
            now = time.time()
            with self._lock:
                for call in list(self._calls.values()):
                    if call.state == CallState.RINGING:
                        if now - call.created_at > self._call_timeout:
                            logger.info("Call %s timed out", call.id)
                            self._end_call_locked(call, CallState.TIMEOUT)
                    elif call.state == CallState.ACTIVE:
                        if call.answered_at and now - call.answered_at > self._max_call_duration:
                            logger.info("Call %s reached max duration", call.id)
                            self._end_call_locked(call, CallState.ENDED)

    def initiate(self, caller: str, callee: str) -> Call:
        call_id = str(uuid.uuid4())[:8]
        stream_name = f"intercom_{call_id}"
        call = Call(id=call_id, caller=caller, callee=callee, stream_name=stream_name)

        self._create_go2rtc_stream(stream_name)

        with self._lock:
            self._calls[call_id] = call

        logger.info("Call %s initiated: %s -> %s", call_id, caller, callee)
        return call

    def answer(self, call_id: str) -> Optional[Call]:
        with self._lock:
            call = self._calls.get(call_id)
            if not call or call.state != CallState.RINGING:
                return None
            call.state = CallState.ACTIVE
            call.answered_at = time.time()
        logger.info("Call %s answered", call_id)
        return call

    def hangup(self, call_id: str) -> Optional[Call]:
        with self._lock:
            call = self._calls.get(call_id)
            if not call or call.state == CallState.ENDED:
                return None
            self._end_call_locked(call, CallState.ENDED)
        return call

    def reject(self, call_id: str) -> Optional[Call]:
        with self._lock:
            call = self._calls.get(call_id)
            if not call or call.state != CallState.RINGING:
                return None
            self._end_call_locked(call, CallState.REJECTED)
        return call

    def get_call(self, call_id: str) -> Optional[Call]:
        return self._calls.get(call_id)

    def get_active_calls(self) -> list[Call]:
        with self._lock:
            return [c for c in self._calls.values() if c.state in (CallState.RINGING, CallState.ACTIVE)]

    def _end_call_locked(self, call: Call, state: CallState):
        call.state = state
        call.ended_at = time.time()
        self._delete_go2rtc_stream(call.stream_name)

    def _create_go2rtc_stream(self, stream_name: str):
        """Streams are created dynamically by go2rtc when a WebRTC publisher
        connects via ?dst=stream_name. No pre-creation needed."""
        logger.debug("Stream %s will be created on-demand by go2rtc", stream_name)

    def _delete_go2rtc_stream(self, stream_name: str):
        try:
            url = f"{self._go2rtc_url}/api/streams"
            requests.delete(url, params={"name": stream_name}, timeout=5)
            logger.debug("Deleted go2rtc stream: %s", stream_name)
        except Exception as e:
            logger.warning("Failed to delete go2rtc stream %s: %s", stream_name, e)

    def get_stream_urls(self, call: Call, base_url: str) -> dict:
        """Return WebRTC and RTSP URLs for the call stream."""
        return {
            "webrtc": f"{base_url.replace('http', 'ws').replace('8099', '8555')}/api/ws?src={call.stream_name}",
            "webrtc_http": f"{base_url.replace(':8099', ':1984')}/api/stream.html?src={call.stream_name}",
            "rtsp": f"rtsp://{base_url.split('//')[1].split(':')[0]}:8554/{call.stream_name}",
            "stream_name": call.stream_name,
        }
