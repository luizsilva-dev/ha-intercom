# Intercom — Home Assistant Add-on

A Home Assistant add-on that enables bidirectional voice calls between devices using **WebRTC** (peer-to-peer, no relay server required).

## Features

- Bidirectional audio between HA mobile app devices (Android / iOS)
- Auto-discovers all registered `mobile_app` devices on startup — no manual device configuration
- Automatically detects which device the current user is on
- Sidebar panel with a **Call** button for each device
- Push notification to the callee with **Answer** and **Reject** buttons
- Answering opens the call screen and connects immediately; rejecting dismisses the notification
- Notification cleared on both devices after answer or reject
- Active calls list in the panel with a hang-up button
- Mute button on the call screen
- Call screen auto-closes 2 seconds after the call ends

## Requirements

- Home Assistant OS or Supervised
- HA Companion App installed on each device (Android or iOS)

## Installation

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store**
2. Click the three-dot menu → **Repositories**
3. Add: `https://github.com/luizsilva-dev/ha-intercom`
4. Find **Intercom** in the store and click **Install**
5. Start the add-on
6. Go to **Settings → Dashboards** and enable the **Intercom** sidebar panel (if not already visible)

## Configuration

The add-on has no required configuration. All devices are discovered automatically at startup.

Optional settings (available in the add-on configuration tab):

| Option | Default | Description |
|--------|---------|-------------|
| `call_timeout` | `30` | Seconds before an unanswered call times out |
| `max_call_duration` | `300` | Maximum call duration in seconds |
| `log_level` | `info` | Log verbosity: `debug`, `info`, `warning`, `error` |

## How it works

1. Open the **Intercom** panel from the HA sidebar
2. The panel shows all discovered devices. Your own device is automatically selected under **I am using** (or you can pick it manually from the dropdown)
3. Tap **Call [device name]** to start a call
4. The callee receives a push notification with **Answer** and **Reject** buttons
5. When both sides answer, a peer-to-peer WebRTC audio connection is established directly between the devices

## Voice Assistant (HA Assist / Cloud AI)

The add-on automatically creates HA scripts for every discovered device and for answer/reject/hangup. These scripts appear in HA as entities, so both the **local Assist** and the **Home Assistant Cloud AI** can find and run them by name — in any language the AI understands.

### Setup (one-time)

1. Add the contents of `voice/configuration_snippet.yaml` to your `configuration.yaml` and restart HA
2. The add-on will automatically create scripts like:
   - `script.intercom_call_cel_luiz` — alias: "Intercom - Call Cel Luiz" / "Intercom - Ligar para Cel Luiz"
   - `script.intercom_answer` — alias: "Intercom - Answer" / "Intercom - Atender"
   - `script.intercom_reject` — alias: "Intercom - Reject" / "Intercom - Recusar"
   - `script.intercom_hangup` — alias: "Intercom - Hang Up" / "Intercom - Desligar"
3. Optionally set **Default Caller** in the add-on configuration tab (device id used when a voice command starts a call)

### Voice commands (examples)

| Portuguese | English | Action |
|------------|---------|--------|
| "Ligar para Cel Luiz" | "Call Cel Luiz" | Calls that device |
| "Atender" / "Atender intercom" | "Answer" / "Answer intercom" | Answers ringing call |
| "Recusar" / "Recusar a chamada" | "Reject" / "Decline the call" | Rejects ringing call |
| "Desligar" / "Encerrar chamada" | "Hang up" / "End the call" | Hangs up active call |

Scripts are recreated automatically every 5 minutes and whenever new devices are discovered.

## REST API

The add-on exposes a REST API on port 8099 (also accessible via HA ingress):

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/api/devices` | List discovered devices |
| GET | `/api/my_device` | Current user's device (from HA headers) |
| POST | `/api/call/initiate` | Start a call `{"caller": "id", "callee": "id"}` |
| POST | `/api/call/answer/<id>` | Answer a call |
| POST | `/api/call/reject/<id>` | Reject a call |
| POST | `/api/call/hangup/<id>` | Hang up a call |
| GET | `/api/call/status` | List active calls |
| GET | `/api/call/<id>` | Get a single call's state |

## Architecture

```
Home Assistant
  └── Intercom add-on (Flask :8099)
        ├── Discovers mobile_app devices via HA Supervisor API
        ├── Stores SDP offer/answer for WebRTC signaling
        └── Sends push notifications via HA notify services

Browser A (caller)          Browser B (callee)
  └── WebRTC offer ──────────────────────► Flask (stored)
                                           Flask (retrieved) ──► callee fetches offer
  ◄── WebRTC answer ◄─────────────────── callee posts answer
  └────────────── P2P audio (WebRTC) ──────────────────────────┘
```
