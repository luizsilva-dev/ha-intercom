"""HA Intercom signaling API + ingress panel."""
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
DEVICES_PATH = "/data/intercom_devices.json"

_start_time = time.time()
manager = IntercomManager(GO2RTC_URL, CALL_TIMEOUT, MAX_CALL_DURATION)
ha = HAClient()


# ---------------------------------------------------------------------------
# Device config persistence (stored in /data, survives restarts)
# ---------------------------------------------------------------------------

def load_devices() -> list[dict]:
    try:
        with open(DEVICES_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_devices(devices: list[dict]):
    with open(DEVICES_PATH, "w") as f:
        json.dump(devices, f, indent=2)


def find_device(name: str) -> dict | None:
    for d in load_devices():
        if d.get("name") == name or d.get("nickname") == name:
            return d
    return None


def base_url() -> str:
    host = request.host.split(":")[0]
    return f"http://{host}:8099"


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "uptime": int(time.time() - _start_time),
        "active_calls": len(manager.get_active_calls()),
    })


# ---------------------------------------------------------------------------
# Device config API
# ---------------------------------------------------------------------------

@app.get("/api/devices")
def list_devices():
    return jsonify({"devices": load_devices()})


@app.post("/api/devices")
def save_devices_endpoint():
    body = request.get_json(silent=True) or {}
    devices = body.get("devices", [])
    save_devices(devices)
    return jsonify({"ok": True, "count": len(devices)})


@app.get("/api/ha/discovered")
def discover():
    """Query HA for mobile apps and Voice PE entities."""
    discovered = ha.discover_all()
    saved = load_devices()
    saved_ids = {d.get("ha_id") for d in saved}
    # Mark already-registered ones
    for dev in discovered:
        dev["registered"] = dev["id"] in saved_ids
    return jsonify({"devices": discovered})


# ---------------------------------------------------------------------------
# Call API
# ---------------------------------------------------------------------------

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

    ha.fire_event("ha_intercom_call_initiated", {
        "call_id": call.id, "caller": caller_name, "callee": callee_name, **urls,
    })
    _notify_callee(callee, caller.get("nickname") or caller_name, call.id, urls)

    return jsonify({"call_id": call.id, "state": call.state, **urls})


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
    return jsonify({"calls": [c.to_dict() for c in manager.get_active_calls()]})


@app.get("/api/call/<call_id>")
def get_call(call_id: str):
    call = manager.get_call(call_id)
    if not call:
        return jsonify({"error": "Call not found"}), 404
    return jsonify(call.to_dict())


# ---------------------------------------------------------------------------
# Ingress panel
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return PANEL_HTML


PANEL_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>HA Intercom</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root {
  --bg:#111318; --surface:#1c1f26; --surface2:#252931; --border:#2a2d35;
  --accent:#03a9f4; --accent2:#4fc3f7; --green:#4caf50; --red:#f44336;
  --yellow:#ff9800; --text:#e8eaed; --text2:#9aa0a6; --radius:12px;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Roboto,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}

/* Header */
.header{background:linear-gradient(135deg,#0d47a1,#01579b);padding:18px 24px;display:flex;align-items:center;gap:14px;box-shadow:0 2px 8px rgba(0,0,0,.4)}
.header h1{font-size:1.3rem;font-weight:500}
.header-sub{font-size:.78rem;color:#90caf9;margin-top:2px}

/* Status bar */
.status-bar{background:var(--surface);padding:8px 24px;display:flex;gap:18px;font-size:.8rem;color:var(--text2);border-bottom:1px solid var(--border)}
.status-bar span{display:flex;align-items:center;gap:5px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--green);animation:pulse 2s infinite}
.dot.red{background:var(--red);animation:none}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}

/* Tabs */
.tabs{display:flex;background:var(--surface);border-bottom:1px solid var(--border)}
.tab{padding:12px 24px;cursor:pointer;font-size:.88rem;color:var(--text2);border-bottom:2px solid transparent;transition:all .2s}
.tab.active{color:var(--accent);border-bottom-color:var(--accent)}
.tab:hover{color:var(--text)}

/* Main */
.main{padding:20px 24px;max-width:960px;margin:0 auto}
.page{display:none}.page.active{display:block}
.section-title{font-size:.72rem;font-weight:600;color:var(--text2);text-transform:uppercase;letter-spacing:1px;margin:20px 0 12px}

/* Device grid */
.device-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:14px}
.device-card{background:var(--surface);border-radius:var(--radius);padding:16px;border:1px solid var(--border);transition:border-color .2s}
.device-card.calling{border-color:var(--yellow)}
.device-card.in-call{border-color:var(--green)}
.device-header{display:flex;align-items:center;gap:12px;margin-bottom:12px}
.device-icon{font-size:1.7rem}
.device-name{font-weight:500;font-size:.95rem}
.device-meta{font-size:.76rem;color:var(--text2);margin-top:2px}
.status-dot{width:9px;height:9px;border-radius:50%;background:#444;margin-left:auto;flex-shrink:0;transition:background .3s}
.status-dot.active{background:var(--green);box-shadow:0 0 5px var(--green)}
.status-dot.ringing{background:var(--yellow);animation:pulse 1s infinite}
.call-buttons{display:flex;flex-wrap:wrap;gap:7px}
.call-btn{background:var(--accent);color:#fff;border:none;border-radius:20px;padding:5px 13px;font-size:.8rem;cursor:pointer;transition:background .2s,transform .1s}
.call-btn:hover{background:var(--accent2);transform:scale(1.02)}
.call-btn:active{transform:scale(.97)}
.no-devices-msg{color:var(--text2);font-size:.83rem}

/* Active calls */
.calls-panel{background:var(--surface);border-radius:var(--radius);border:1px solid var(--border);overflow:hidden}
.call-row{display:flex;align-items:center;padding:14px 16px;border-bottom:1px solid var(--border);gap:12px;animation:slideIn .3s ease}
.call-row:last-child{border-bottom:none}
@keyframes slideIn{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:translateY(0)}}
.call-info{flex:1}
.call-parties{font-weight:500;font-size:.92rem}
.call-meta{font-size:.76rem;color:var(--text2);margin-top:3px}
.call-badge{font-size:.7rem;font-weight:600;padding:3px 9px;border-radius:10px;text-transform:uppercase}
.call-badge.ringing{background:rgba(255,152,0,.15);color:var(--yellow)}
.call-badge.active{background:rgba(76,175,80,.15);color:var(--green)}
.hangup-btn{background:var(--red);color:#fff;border:none;border-radius:50%;width:32px;height:32px;font-size:.9rem;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background .2s}
.hangup-btn:hover{background:#e53935}
.no-calls{padding:24px;text-align:center;color:var(--text2);font-size:.86rem}

/* Settings / device registration */
.discover-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}
.btn{padding:8px 18px;border-radius:8px;border:none;cursor:pointer;font-size:.84rem;font-weight:500;transition:background .2s}
.btn-primary{background:var(--accent);color:#fff}.btn-primary:hover{background:var(--accent2)}
.btn-secondary{background:var(--surface2);color:var(--text);border:1px solid var(--border)}.btn-secondary:hover{background:#2f333d}
.btn-danger{background:var(--red);color:#fff}.btn-danger:hover{background:#e53935}
.btn-sm{padding:5px 12px;font-size:.76rem;border-radius:6px}

.discover-list{display:flex;flex-direction:column;gap:10px}
.discover-item{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:14px 16px;display:flex;align-items:center;gap:14px}
.discover-item.registered{border-color:#1a5276;background:#0d1b2a}
.discover-icon{font-size:1.6rem;flex-shrink:0}
.discover-info{flex:1}
.discover-name{font-size:.9rem;font-weight:500}
.discover-id{font-size:.72rem;color:var(--text2);margin-top:2px;font-family:monospace}
.discover-badge{font-size:.68rem;padding:2px 8px;border-radius:8px;font-weight:600}
.badge-android{background:rgba(3,169,244,.15);color:var(--accent)}
.badge-voice{background:rgba(76,175,80,.15);color:var(--green)}

.nick-input{background:var(--surface2);border:1px solid var(--border);border-radius:6px;color:var(--text);padding:5px 10px;font-size:.82rem;width:140px;outline:none}
.nick-input:focus{border-color:var(--accent)}

.registered-list{display:flex;flex-direction:column;gap:10px}
.reg-item{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:12px 16px;display:flex;align-items:center;gap:12px}
.reg-icon{font-size:1.5rem;flex-shrink:0}
.reg-info{flex:1}
.reg-nickname{font-weight:500;font-size:.92rem}
.reg-detail{font-size:.74rem;color:var(--text2);margin-top:2px}

/* Toast */
.toast{position:fixed;bottom:22px;right:22px;background:var(--surface2);color:var(--text);padding:11px 18px;border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,.4);font-size:.85rem;z-index:999;transform:translateY(70px);opacity:0;transition:all .3s;max-width:300px}
.toast.show{transform:translateY(0);opacity:1}
.toast.success{border-left:3px solid var(--green)}
.toast.error{border-left:3px solid var(--red)}

.empty-state{padding:40px;text-align:center;color:var(--text2);font-size:.88rem;line-height:2;background:var(--surface);border-radius:var(--radius)}
.spinner{display:inline-block;width:16px;height:16px;border:2px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .7s linear infinite;margin-right:6px}
@keyframes spin{to{transform:rotate(360deg)}}
.go2rtc-link{display:inline-flex;align-items:center;gap:6px;color:var(--accent);font-size:.8rem;text-decoration:none;padding:6px 12px;border-radius:20px;border:1px solid var(--accent);transition:background .2s;margin-top:10px}
.go2rtc-link:hover{background:rgba(3,169,244,.1)}
</style>
</head>
<body>

<div class="header">
  <span style="font-size:2rem">📞</span>
  <div>
    <h1>HA Intercom</h1>
    <div class="header-sub">Intercom bidirecional via WebRTC · go2rtc</div>
  </div>
</div>

<div class="status-bar">
  <span><span class="dot" id="api-dot"></span> API</span>
  <span><span class="dot" id="go2rtc-dot"></span> go2rtc</span>
  <span id="uptime-label">⏱ —</span>
  <span id="call-count-label">📞 0 chamadas</span>
</div>

<div class="tabs">
  <div class="tab active" onclick="showTab('calls')">📞 Chamadas</div>
  <div class="tab" onclick="showTab('devices')">📱 Dispositivos</div>
  <div class="tab" onclick="showTab('settings')">⚙️ Configurações</div>
</div>

<!-- TAB: Chamadas -->
<div class="main page active" id="tab-calls">
  <div class="section-title">Chamadas ativas</div>
  <div class="calls-panel" id="calls-panel">
    <div class="no-calls">Nenhuma chamada ativa</div>
  </div>

  <div class="section-title">Ligar para</div>
  <div class="device-grid" id="device-grid">
    <div class="empty-state">Carregando dispositivos...</div>
  </div>
  <a class="go2rtc-link" href="http://homeassistant.local:1984" target="_blank">🎥 Abrir go2rtc UI</a>
</div>

<!-- TAB: Dispositivos -->
<div class="main page" id="tab-devices">
  <div class="discover-header">
    <div class="section-title" style="margin:0">Dispositivos cadastrados</div>
    <button class="btn btn-primary btn-sm" onclick="showDiscovery()">＋ Adicionar dispositivo</button>
  </div>
  <div id="registered-list-container">
    <div class="empty-state">Nenhum dispositivo cadastrado ainda.<br>Clique em <b>+ Adicionar dispositivo</b> para buscar dispositivos do HA.</div>
  </div>

  <!-- Discovery panel (hidden by default) -->
  <div id="discovery-panel" style="display:none;margin-top:20px">
    <div class="discover-header">
      <div class="section-title" style="margin:0">Dispositivos encontrados no HA</div>
      <button class="btn btn-secondary btn-sm" onclick="hideDiscovery()">✕ Fechar</button>
    </div>
    <div id="discover-loading" style="padding:20px;color:var(--text2);font-size:.86rem">
      <span class="spinner"></span>Buscando dispositivos...
    </div>
    <div id="discover-list" class="discover-list" style="display:none"></div>
  </div>
</div>

<!-- TAB: Configurações -->
<div class="main page" id="tab-settings">
  <div class="section-title">Informações</div>
  <div style="background:var(--surface);border-radius:var(--radius);padding:16px;border:1px solid var(--border)">
    <p style="font-size:.85rem;color:var(--text2);line-height:1.8">
      <b style="color:var(--text)">go2rtc API:</b> <a href="http://homeassistant.local:1984" target="_blank" style="color:var(--accent)">:1984</a><br>
      <b style="color:var(--text)">RTSP:</b> rtsp://&lt;IP&gt;:8554/intercom_&lt;call_id&gt;<br>
      <b style="color:var(--text)">WebRTC:</b> ws://&lt;IP&gt;:8555/api/ws?src=intercom_&lt;call_id&gt;<br>
      <b style="color:var(--text)">Health:</b> <a href="/health" target="_blank" style="color:var(--accent)">/health</a>
    </p>
  </div>
  <div class="section-title">Eventos HA disponíveis</div>
  <div style="background:var(--surface);border-radius:var(--radius);padding:16px;border:1px solid var(--border);font-family:monospace;font-size:.8rem;line-height:2;color:var(--text2)">
    ha_intercom_call_initiated<br>
    ha_intercom_call_answered<br>
    ha_intercom_call_rejected<br>
    ha_intercom_call_ended
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const BASE = window.location.origin;

// ---- Tab navigation ----
function showTab(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  event.currentTarget.classList.add('active');
  if (name === 'devices') renderRegistered();
}

// ---- Toast ----
function showToast(msg, type='success') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast ' + type + ' show';
  setTimeout(() => t.classList.remove('show'), 3500);
}

// ---- Calls ----
function formatDur(sec) {
  const m = Math.floor(sec/60), s = Math.floor(sec%60);
  return m > 0 ? m+'m '+s+'s' : s+'s';
}

function renderCalls(calls) {
  const panel = document.getElementById('calls-panel');
  document.getElementById('call-count-label').textContent = '📞 ' + calls.length + ' chamada' + (calls.length !== 1 ? 's' : '');
  if (!calls.length) {
    panel.innerHTML = '<div class="no-calls">Nenhuma chamada ativa</div>';
    document.querySelectorAll('.device-card').forEach(c => {
      c.classList.remove('calling','in-call');
      const d = c.querySelector('.status-dot');
      if (d) d.className = 'status-dot';
    });
    return;
  }
  const now = Date.now()/1000;
  panel.innerHTML = calls.map(c => {
    const lbl = c.state === 'ringing' ? 'Chamando' : 'Em chamada';
    const since = c.answered_at ? formatDur(now - c.answered_at) : formatDur(now - c.created_at);
    return `<div class="call-row">
      <div class="call-info">
        <div class="call-parties">📱 ${c.caller} → ${c.callee}</div>
        <div class="call-meta">ID: ${c.id} · ${since}</div>
      </div>
      <span class="call-badge ${c.state}">${lbl}</span>
      <button class="hangup-btn" onclick="hangup('${c.id}')" title="Encerrar">📵</button>
    </div>`;
  }).join('');

  document.querySelectorAll('.device-card').forEach(el => el.classList.remove('calling','in-call'));
  calls.forEach(c => {
    ['caller','callee'].forEach(role => {
      const card = document.getElementById('card-' + c[role]);
      if (card) card.classList.add(c.state === 'ringing' ? 'calling' : 'in-call');
      const dot = document.getElementById('sdot-' + c[role]);
      if (dot) dot.className = 'status-dot ' + (c.state === 'ringing' ? 'ringing' : 'active');
    });
  });
}

async function hangup(callId) {
  await fetch(`${BASE}/api/call/hangup/${callId}`, {method:'POST'});
}

async function initiateCall(caller, callee) {
  try {
    const r = await fetch(`${BASE}/api/call/initiate`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({caller, callee})
    });
    const d = await r.json();
    r.ok ? showToast('📞 Chamando ' + callee + '...') : showToast(d.error || 'Erro', 'error');
  } catch { showToast('Erro de conexão', 'error'); }
}

// ---- Device grid (calls tab) ----
async function renderDeviceGrid() {
  const grid = document.getElementById('device-grid');
  const r = await fetch(`${BASE}/api/devices`);
  const {devices} = await r.json();
  if (!devices.length) {
    grid.innerHTML = '<div class="empty-state">Nenhum dispositivo cadastrado.<br>Vá na aba <b>Dispositivos</b> para adicionar.</div>';
    return;
  }
  grid.innerHTML = devices.map(dev => {
    const label = dev.nickname || dev.name;
    const icon = dev.type === 'android' ? '📱' : '🔊';
    const meta = (dev.room ? dev.room + ' · ' : '') + dev.type;
    const btns = devices.filter(o => o.name !== dev.name).map(o => {
      const ol = o.nickname || o.name;
      return `<button class="call-btn" onclick="initiateCall('${label}','${ol}')">📞 ${ol}</button>`;
    }).join('');
    return `<div class="device-card" id="card-${label}">
      <div class="device-header">
        <span class="device-icon">${icon}</span>
        <div>
          <div class="device-name">${label}</div>
          <div class="device-meta">${meta}</div>
        </div>
        <span class="status-dot" id="sdot-${label}"></span>
      </div>
      <div class="call-buttons">${btns || '<span class="no-devices-msg">Nenhum outro dispositivo</span>'}</div>
    </div>`;
  }).join('');
}

// ---- Registered devices tab ----
async function renderRegistered() {
  const container = document.getElementById('registered-list-container');
  const r = await fetch(`${BASE}/api/devices`);
  const {devices} = await r.json();
  if (!devices.length) {
    container.innerHTML = '<div class="empty-state">Nenhum dispositivo cadastrado ainda.<br>Clique em <b>+ Adicionar dispositivo</b> para buscar dispositivos do HA.</div>';
    return;
  }
  container.innerHTML = '<div class="registered-list">' + devices.map((dev, i) => {
    const label = dev.nickname || dev.name;
    const icon = dev.type === 'android' ? '📱' : '🔊';
    const room = dev.room || '—';
    return `<div class="reg-item">
      <span class="reg-icon">${icon}</span>
      <div class="reg-info">
        <div class="reg-nickname">${label}</div>
        <div class="reg-detail">${dev.ha_id} · ${room} · ${dev.type}</div>
      </div>
      <button class="btn btn-secondary btn-sm" onclick="editDevice(${i})">✏️ Editar</button>
      <button class="btn btn-danger btn-sm" onclick="removeDevice(${i})">🗑</button>
    </div>`;
  }).join('') + '</div>';
}

async function removeDevice(idx) {
  const r = await fetch(`${BASE}/api/devices`);
  const {devices} = await r.json();
  devices.splice(idx, 1);
  await fetch(`${BASE}/api/devices`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({devices})});
  showToast('Dispositivo removido');
  renderRegistered();
  renderDeviceGrid();
}

// ---- Discovery ----
let _discovered = [];

async function showDiscovery() {
  document.getElementById('discovery-panel').style.display = 'block';
  document.getElementById('discover-list').style.display = 'none';
  document.getElementById('discover-loading').style.display = 'block';
  try {
    const r = await fetch(`${BASE}/api/ha/discovered`);
    const {devices} = await r.json();
    _discovered = devices;
    renderDiscoveryList(devices);
  } catch {
    document.getElementById('discover-loading').innerHTML = '<span style="color:var(--red)">Erro ao buscar dispositivos do HA</span>';
  }
}

function hideDiscovery() {
  document.getElementById('discovery-panel').style.display = 'none';
}

function renderDiscoveryList(devices) {
  document.getElementById('discover-loading').style.display = 'none';
  const list = document.getElementById('discover-list');
  if (!devices.length) {
    list.innerHTML = '<div class="empty-state">Nenhum dispositivo mobile_app ou Voice PE encontrado no HA.</div>';
    list.style.display = 'block';
    return;
  }
  list.innerHTML = devices.map((dev, i) => {
    const icon = dev.type === 'android' ? '📱' : '🔊';
    const badge = dev.type === 'android'
      ? '<span class="discover-badge badge-android">Android</span>'
      : '<span class="discover-badge badge-voice">Voice PE</span>';
    const regLabel = dev.registered
      ? '<span style="color:var(--green);font-size:.75rem">✓ Cadastrado</span>'
      : `<button class="btn btn-primary btn-sm" onclick="addDevice(${i})">＋ Adicionar</button>`;
    return `<div class="discover-item ${dev.registered ? 'registered' : ''}" id="disc-${i}">
      <span class="discover-icon">${icon}</span>
      <div class="discover-info">
        <div class="discover-name">${dev.name} ${badge}</div>
        <div class="discover-id">${dev.entity_id || dev.id}</div>
      </div>
      <input class="nick-input" id="nick-${i}" placeholder="Apelido (opcional)" value="${dev.name}">
      <input class="nick-input" id="room-${i}" placeholder="Sala" style="width:100px">
      ${regLabel}
    </div>`;
  }).join('');
  list.style.display = 'flex';
}

async function addDevice(idx) {
  const dev = _discovered[idx];
  const nickname = document.getElementById('nick-' + idx).value.trim() || dev.name;
  const room = document.getElementById('room-' + idx).value.trim();

  const r = await fetch(`${BASE}/api/devices`);
  const {devices} = await r.json();

  devices.push({
    name: dev.id,
    nickname: nickname,
    type: dev.type,
    ha_id: dev.id,
    entity_id: dev.entity_id,
    room: room,
    mobile_app_id: dev.type === 'android' ? dev.id : null,
    ha_device_id: dev.type === 'voice_pe' ? dev.entity_id : null,
  });

  await fetch(`${BASE}/api/devices`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({devices})
  });

  showToast('✅ ' + nickname + ' adicionado!');
  _discovered[idx].registered = true;

  const item = document.getElementById('disc-' + idx);
  if (item) {
    item.classList.add('registered');
    item.querySelector('button')?.replaceWith(
      Object.assign(document.createElement('span'), {
        textContent: '✓ Cadastrado',
        style: 'color:var(--green);font-size:.75rem'
      })
    );
  }
  renderRegistered();
  renderDeviceGrid();
}

function editDevice(idx) {
  // Simple inline edit: redirect to discovery pre-filled (future enhancement)
  showToast('Para editar, remova e adicione novamente o dispositivo.', 'error');
}

// ---- Health / status ----
async function checkHealth() {
  try {
    const r = await fetch(`${BASE}/health`);
    const d = await r.json();
    document.getElementById('api-dot').className = 'dot';
    document.getElementById('uptime-label').textContent = '⏱ ' + formatDur(d.uptime);
  } catch {
    document.getElementById('api-dot').className = 'dot red';
  }
}

async function checkGo2rtc() {
  try {
    const r = await fetch('/proxy/go2rtc/api', {signal: AbortSignal.timeout(3000)}).catch(() => null);
    document.getElementById('go2rtc-dot').className = (r && r.ok) ? 'dot' : 'dot red';
  } catch {
    document.getElementById('go2rtc-dot').className = 'dot red';
  }
}

async function pollCalls() {
  try {
    const r = await fetch(`${BASE}/api/call/status`);
    const d = await r.json();
    renderCalls(d.calls || []);
  } catch {}
}

// Init
renderDeviceGrid();
checkHealth();
pollCalls();
setInterval(pollCalls, 3000);
setInterval(checkHealth, 10000);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _notify_callee(callee: dict, caller_display: str, call_id: str, urls: dict):
    dtype = callee.get("type", "android")
    if dtype == "android":
        app_id = callee.get("mobile_app_id")
        if app_id:
            ha.notify_mobile(
                mobile_app_id=app_id,
                title="Chamada de Intercom",
                message=f"{caller_display} está ligando",
                call_id=call_id,
            )
    elif dtype == "voice_pe":
        entity_id = callee.get("ha_device_id") or callee.get("entity_id")
        if entity_id:
            ha.announce_voice_pe(entity_id, f"Chamada de intercom de {caller_display}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8099"))
    logger.info("Starting intercom API on port %d", port)
    app.run(host="0.0.0.0", port=port, threaded=True)
