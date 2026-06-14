"""HA Intercom signaling API."""
import json
import logging
import os

from flask import Flask, jsonify, request

from ha_client import HAClient
from intercom import CallState, IntercomManager

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "info").upper(),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Initialise singletons
GO2RTC_URL = os.environ.get("GO2RTC_URL", "http://localhost:1984")
CALL_TIMEOUT = int(os.environ.get("CALL_TIMEOUT", "30"))
MAX_CALL_DURATION = int(os.environ.get("MAX_CALL_DURATION", "300"))
OPTIONS_PATH = os.environ.get("OPTIONS_PATH", "/data/options.json")

manager = IntercomManager(GO2RTC_URL, CALL_TIMEOUT, MAX_CALL_DURATION)
ha = HAClient()


def load_options() -> dict:
    try:
        with open(OPTIONS_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"devices": []}


def find_device(name: str) -> dict | None:
    opts = load_options()
    for d in opts.get("devices", []):
        if d.get("name") == name:
            return d
    return None


def base_url() -> str:
    host = request.host.split(":")[0]
    return f"http://{host}:8099"


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.get("/api/devices")
def list_devices():
    opts = load_options()
    return jsonify({"devices": opts.get("devices", [])})


@app.post("/api/call/initiate")
def initiate_call():
    body = request.get_json(silent=True) or {}
    caller_name = body.get("caller")
    callee_name = body.get("callee")

    if not caller_name or not callee_name:
        return jsonify({"error": "caller and callee required"}), 400

    caller = find_device(caller_name)
    callee = find_device(callee_name)

    if not caller:
        return jsonify({"error": f"Unknown caller: {caller_name}"}), 404
    if not callee:
        return jsonify({"error": f"Unknown callee: {callee_name}"}), 404

    call = manager.initiate(caller_name, callee_name)
    urls = manager.get_stream_urls(call, base_url())

    # Fire HA event so automations can react
    ha.fire_event("ha_intercom_call_initiated", {
        "call_id": call.id,
        "caller": caller_name,
        "callee": callee_name,
        **urls,
    })

    # Notify callee based on device type
    _notify_callee(callee, caller_name, call.id, urls)

    return jsonify({
        "call_id": call.id,
        "state": call.state,
        **urls,
    })


@app.post("/api/call/answer/<call_id>")
def answer_call(call_id: str):
    call = manager.answer(call_id)
    if not call:
        return jsonify({"error": "Call not found or not ringing"}), 404

    urls = manager.get_stream_urls(call, base_url())
    ha.fire_event("ha_intercom_call_answered", {"call_id": call_id, **urls})

    return jsonify({"call_id": call_id, "state": call.state, **urls})


@app.post("/api/call/reject/<call_id>")
def reject_call(call_id: str):
    call = manager.reject(call_id)
    if not call:
        return jsonify({"error": "Call not found"}), 404

    ha.fire_event("ha_intercom_call_rejected", {"call_id": call_id})
    return jsonify({"call_id": call_id, "state": call.state})


@app.post("/api/call/hangup/<call_id>")
def hangup_call(call_id: str):
    call = manager.hangup(call_id)
    if not call:
        return jsonify({"error": "Call not found"}), 404

    ha.fire_event("ha_intercom_call_ended", {"call_id": call_id})
    return jsonify({"call_id": call_id, "state": call.state})


@app.get("/api/call/status")
def call_status():
    active = manager.get_active_calls()
    return jsonify({"calls": [c.to_dict() for c in active]})


@app.get("/api/call/<call_id>")
def get_call(call_id: str):
    call = manager.get_call(call_id)
    if not call:
        return jsonify({"error": "Call not found"}), 404
    return jsonify(call.to_dict())


@app.get("/")
def index():
    """Ingress landing page."""
    return """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>HA Intercom</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { font-family: sans-serif; padding: 2rem; background: #1c1c1c; color: #eee; }
  h1 { color: #03a9f4; }
  .card { background: #2d2d2d; border-radius: 8px; padding: 1rem; margin: 1rem 0; }
  a { color: #03a9f4; }
</style>
</head>
<body>
<h1>HA Intercom</h1>
<div class="card">
  <p>Signaling API: <a href="/api/devices">/api/devices</a></p>
  <p>Active calls: <a href="/api/call/status">/api/call/status</a></p>
  <p>go2rtc UI: <a href="http://homeassistant.local:1984" target="_blank">:1984</a></p>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _notify_callee(callee: dict, caller_name: str, call_id: str, urls: dict):
    device_type = callee.get("type", "android")
    room = callee.get("room", "")

    if device_type == "android":
        mobile_app_id = callee.get("mobile_app_id")
        if mobile_app_id:
            ha.notify_mobile(
                mobile_app_id=mobile_app_id,
                title="Chamada de Intercom",
                message=f"{caller_name} está ligando para você",
                call_id=call_id,
                action="answer",
            )
        else:
            logger.warning("Android device %s has no mobile_app_id configured", callee.get("name"))

    elif device_type == "voice_pe":
        ha_device_id = callee.get("ha_device_id")
        if ha_device_id:
            ha.announce_voice_pe(
                entity_id=ha_device_id,
                message=f"Chamada de intercom de {caller_name}. Diga OK para atender.",
            )
        else:
            logger.warning("Voice PE device %s has no ha_device_id configured", callee.get("name"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8099"))
    logger.info("Starting intercom API on port %d", port)
    app.run(host="0.0.0.0", port=port, threaded=True)
