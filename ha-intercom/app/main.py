"""HA Intercom signaling API."""
import json
import logging
import os
import time

from flask import Flask, jsonify, request

from ha_client import HAClient
from intercom import CallState, IntercomManager

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "info").upper(),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

GO2RTC_URL = os.environ.get("GO2RTC_URL", "http://localhost:1984")
CALL_TIMEOUT = int(os.environ.get("CALL_TIMEOUT", "30"))
MAX_CALL_DURATION = int(os.environ.get("MAX_CALL_DURATION", "300"))
OPTIONS_PATH = os.environ.get("OPTIONS_PATH", "/data/options.json")

_start_time = time.time()
manager = IntercomManager(GO2RTC_URL, CALL_TIMEOUT, MAX_CALL_DURATION)
ha = HAClient()


def load_options() -> dict:
    try:
        with open(OPTIONS_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"devices": []}


def find_device(name: str) -> dict | None:
    for d in load_options().get("devices", []):
        if d.get("name") == name:
            return d
    return None


def base_url() -> str:
    host = request.host.split(":")[0]
    return f"http://{host}:8099"


# ---------------------------------------------------------------------------
# Health / watchdog
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "uptime": int(time.time() - _start_time),
        "active_calls": len(manager.get_active_calls()),
    })


# ---------------------------------------------------------------------------
# Ingress panel
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    opts = load_options()
    devices = opts.get("devices", [])
    return _render_panel(devices)


def _render_panel(devices: list) -> str:
    device_cards = ""
    for dev in devices:
        dtype = dev.get("type", "android")
        icon = "mdi:cellphone" if dtype == "android" else "mdi:home-assistant"
        room = dev.get("room", "")
        name = dev.get("name", "")
        call_buttons = "".join(
            f'<button class="call-btn" onclick="initiateCall(\'{name}\', \'{other[\"name\"]}\')">📞 {other["name"]}</button>'
            for other in devices if other.get("name") != name
        )
        device_cards += f"""
        <div class="device-card" id="card-{name}">
          <div class="device-header">
            <span class="device-icon">{"📱" if dtype == "android" else "🔊"}</span>
            <div>
              <div class="device-name">{name}</div>
              <div class="device-room">{room} · {dtype}</div>
            </div>
            <span class="status-dot" id="status-{name}"></span>
          </div>
          <div class="call-buttons">{call_buttons if call_buttons else "<span class='no-devices'>Nenhum outro dispositivo</span>"}</div>
        </div>"""

    no_devices_msg = ""
    if not devices:
        no_devices_msg = '<div class="empty-state">⚙️ Nenhum dispositivo configurado.<br>Adicione dispositivos nas opções do add-on.</div>'

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>HA Intercom</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {{
    --bg: #111318;
    --surface: #1c1f26;
    --surface2: #252931;
    --accent: #03a9f4;
    --accent2: #4fc3f7;
    --green: #4caf50;
    --red: #f44336;
    --yellow: #ff9800;
    --text: #e8eaed;
    --text2: #9aa0a6;
    --radius: 12px;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Roboto', sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }}

  .header {{
    background: linear-gradient(135deg, #0d47a1, #01579b);
    padding: 20px 24px;
    display: flex;
    align-items: center;
    gap: 12px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.4);
  }}
  .header h1 {{ font-size: 1.4rem; font-weight: 500; }}
  .header-sub {{ font-size: 0.8rem; color: #90caf9; margin-top: 2px; }}
  .header-icon {{ font-size: 2rem; }}

  .status-bar {{
    background: var(--surface);
    padding: 10px 24px;
    display: flex;
    gap: 20px;
    font-size: 0.82rem;
    color: var(--text2);
    border-bottom: 1px solid #2a2d35;
  }}
  .status-bar span {{ display: flex; align-items: center; gap: 6px; }}
  .dot {{ width: 8px; height: 8px; border-radius: 50%; background: var(--green); animation: pulse 2s infinite; }}
  .dot.red {{ background: var(--red); animation: none; }}
  @keyframes pulse {{ 0%,100% {{ opacity:1 }} 50% {{ opacity:.4 }} }}

  .main {{ padding: 24px; max-width: 900px; margin: 0 auto; }}

  .section-title {{
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--text2);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin: 24px 0 12px;
  }}

  .device-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }}

  .device-card {{
    background: var(--surface);
    border-radius: var(--radius);
    padding: 16px;
    border: 1px solid #2a2d35;
    transition: border-color .2s;
  }}
  .device-card.calling {{ border-color: var(--yellow); }}
  .device-card.in-call {{ border-color: var(--green); }}

  .device-header {{ display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }}
  .device-icon {{ font-size: 1.8rem; }}
  .device-name {{ font-weight: 500; font-size: 1rem; }}
  .device-room {{ font-size: 0.8rem; color: var(--text2); margin-top: 2px; }}
  .status-dot {{
    width: 10px; height: 10px; border-radius: 50%;
    background: #555; margin-left: auto; flex-shrink: 0;
    transition: background .3s;
  }}
  .status-dot.active {{ background: var(--green); box-shadow: 0 0 6px var(--green); }}
  .status-dot.ringing {{ background: var(--yellow); animation: pulse 1s infinite; }}

  .call-buttons {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .call-btn {{
    background: var(--accent);
    color: #fff;
    border: none;
    border-radius: 20px;
    padding: 6px 14px;
    font-size: 0.82rem;
    cursor: pointer;
    transition: background .2s, transform .1s;
  }}
  .call-btn:hover {{ background: var(--accent2); transform: scale(1.02); }}
  .call-btn:active {{ transform: scale(.97); }}
  .call-btn:disabled {{ background: #444; cursor: not-allowed; }}
  .no-devices {{ font-size: 0.8rem; color: var(--text2); }}

  /* Active calls */
  .calls-panel {{
    background: var(--surface);
    border-radius: var(--radius);
    border: 1px solid #2a2d35;
    overflow: hidden;
  }}
  .call-row {{
    display: flex;
    align-items: center;
    padding: 14px 16px;
    border-bottom: 1px solid #2a2d35;
    gap: 12px;
    animation: slideIn .3s ease;
  }}
  .call-row:last-child {{ border-bottom: none; }}
  @keyframes slideIn {{ from {{ opacity:0; transform:translateY(-8px) }} to {{ opacity:1; transform:translateY(0) }} }}
  .call-info {{ flex: 1; }}
  .call-parties {{ font-weight: 500; font-size: 0.95rem; }}
  .call-meta {{ font-size: 0.78rem; color: var(--text2); margin-top: 3px; }}
  .call-state {{
    font-size: 0.75rem; font-weight: 600; padding: 3px 10px;
    border-radius: 12px; text-transform: uppercase;
  }}
  .call-state.ringing {{ background: rgba(255,152,0,.15); color: var(--yellow); }}
  .call-state.active {{ background: rgba(76,175,80,.15); color: var(--green); }}
  .hangup-btn {{
    background: var(--red); color: #fff; border: none;
    border-radius: 50%; width: 34px; height: 34px;
    font-size: 1rem; cursor: pointer; transition: background .2s;
    display: flex; align-items: center; justify-content: center;
  }}
  .hangup-btn:hover {{ background: #e53935; }}
  .no-calls {{ padding: 20px; text-align: center; color: var(--text2); font-size: 0.88rem; }}

  .empty-state {{
    background: var(--surface);
    border-radius: var(--radius);
    padding: 40px;
    text-align: center;
    color: var(--text2);
    line-height: 2;
  }}

  .toast {{
    position: fixed; bottom: 24px; right: 24px;
    background: var(--surface2); color: var(--text);
    padding: 12px 20px; border-radius: 8px;
    box-shadow: 0 4px 16px rgba(0,0,0,.4);
    font-size: 0.88rem; z-index: 999;
    transform: translateY(80px); opacity: 0;
    transition: all .3s;
  }}
  .toast.show {{ transform: translateY(0); opacity: 1; }}
  .toast.success {{ border-left: 3px solid var(--green); }}
  .toast.error {{ border-left: 3px solid var(--red); }}

  .go2rtc-link {{
    display: inline-flex; align-items: center; gap: 6px;
    color: var(--accent); font-size: 0.82rem; text-decoration: none;
    padding: 6px 12px; border-radius: 20px;
    border: 1px solid var(--accent);
    transition: background .2s;
    margin-top: 8px;
  }}
  .go2rtc-link:hover {{ background: rgba(3,169,244,.1); }}
</style>
</head>
<body>

<div class="header">
  <span class="header-icon">📞</span>
  <div>
    <h1>HA Intercom</h1>
    <div class="header-sub">Intercom bidirecional via WebRTC · go2rtc 1.9.4</div>
  </div>
</div>

<div class="status-bar">
  <span><span class="dot" id="api-dot"></span> API</span>
  <span><span class="dot" id="go2rtc-dot"></span> go2rtc</span>
  <span id="uptime-label">⏱ Uptime: —</span>
  <span id="call-count-label">📞 Chamadas ativas: 0</span>
</div>

<div class="main">
  <div class="section-title">Chamadas ativas</div>
  <div class="calls-panel" id="calls-panel">
    <div class="no-calls" id="no-calls-msg">Nenhuma chamada ativa</div>
  </div>

  <div class="section-title">Dispositivos</div>
  <div class="device-grid">
    {device_cards}
    {no_devices_msg}
  </div>

  <div style="margin-top: 24px;">
    <a class="go2rtc-link" href="http://homeassistant.local:1984" target="_blank">🎥 Abrir go2rtc UI</a>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const BASE = window.location.origin;

function showToast(msg, type='success') {{
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast ' + type + ' show';
  setTimeout(() => t.classList.remove('show'), 3500);
}}

async function initiateCall(caller, callee) {{
  try {{
    const r = await fetch(`${{BASE}}/api/call/initiate`, {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{caller, callee}})
    }});
    const d = await r.json();
    if (r.ok) {{
      showToast(`📞 Chamando ${{callee}}...`);
    }} else {{
      showToast(d.error || 'Erro ao iniciar chamada', 'error');
    }}
  }} catch(e) {{
    showToast('Erro de conexão', 'error');
  }}
}}

async function hangupCall(callId) {{
  await fetch(`${{BASE}}/api/call/hangup/${{callId}}`, {{method: 'POST'}});
}}

function formatDuration(seconds) {{
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return m > 0 ? `${{m}}m ${{s}}s` : `${{s}}s`;
}}

function renderCalls(calls) {{
  const panel = document.getElementById('calls-panel');
  const noMsg = document.getElementById('no-calls-label');
  document.getElementById('call-count-label').textContent = `📞 Chamadas ativas: ${{calls.length}}`;

  if (calls.length === 0) {{
    panel.innerHTML = '<div class="no-calls" id="no-calls-msg">Nenhuma chamada ativa</div>';
    return;
  }}

  const now = Date.now() / 1000;
  panel.innerHTML = calls.map(c => {{
    const stateLabel = c.state === 'ringing' ? 'Chamando' : 'Em chamada';
    const since = c.answered_at ? formatDuration(now - c.answered_at) : formatDuration(now - c.created_at);
    return `
      <div class="call-row">
        <div class="call-info">
          <div class="call-parties">📱 ${{c.caller}} → ${{c.callee}}</div>
          <div class="call-meta">ID: ${{c.id}} · ${{since}}</div>
        </div>
        <span class="call-state ${{c.state}}">${{stateLabel}}</span>
        <button class="hangup-btn" onclick="hangupCall('${{c.id}}')" title="Encerrar">📵</button>
      </div>`;
  }}).join('');

  // highlight device cards
  document.querySelectorAll('.device-card').forEach(el => {{
    el.classList.remove('calling', 'in-call');
  }});
  calls.forEach(c => {{
    ['caller', 'callee'].forEach(role => {{
      const card = document.getElementById('card-' + c[role]);
      if (card) card.classList.add(c.state === 'ringing' ? 'calling' : 'in-call');
      const dot = document.getElementById('status-' + c[role]);
      if (dot) dot.className = 'status-dot ' + (c.state === 'ringing' ? 'ringing' : 'active');
    }});
  }});
}}

async function checkHealth() {{
  try {{
    const r = await fetch(`${{BASE}}/health`);
    const d = await r.json();
    document.getElementById('api-dot').className = 'dot';
    document.getElementById('uptime-label').textContent = `⏱ Uptime: ${{formatDuration(d.uptime)}}`;
  }} catch {{
    document.getElementById('api-dot').className = 'dot red';
  }}
}}

async function checkGo2rtc() {{
  try {{
    const r = await fetch('http://homeassistant.local:1984/api');
    document.getElementById('go2rtc-dot').className = r.ok ? 'dot' : 'dot red';
  }} catch {{
    document.getElementById('go2rtc-dot').className = 'dot red';
  }}
}}

async function poll() {{
  try {{
    const r = await fetch(`${{BASE}}/api/call/status`);
    const d = await r.json();
    renderCalls(d.calls || []);
  }} catch {{}}
}}

// Poll every 3s for calls, health every 10s
poll();
checkHealth();
setInterval(poll, 3000);
setInterval(checkHealth, 10000);
setInterval(checkGo2rtc, 15000);
</script>
</body>
</html>"""
