import os
import time
import uuid
import requests
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

SUPERVISOR_TOKEN = os.environ.get('SUPERVISOR_TOKEN', '')
HA_URL = 'http://supervisor/core'

devices = []
user_device_map = {}
calls = {}
start_time = time.time()

# ---------------------------------------------------------------------------
# Device discovery
# ---------------------------------------------------------------------------

def _ha_headers():
    return {
        'Authorization': f'Bearer {SUPERVISOR_TOKEN}',
        'Content-Type': 'application/json',
    }


def refresh_devices():
    global devices, user_device_map
    devices = []
    user_device_map = {}

    try:
        resp = requests.get(f'{HA_URL}/api/services', headers=_ha_headers(), timeout=10)
        if resp.status_code == 200:
            for domain_entry in resp.json():
                if domain_entry.get('domain') == 'notify':
                    for svc_name, svc_data in domain_entry.get('services', {}).items():
                        if svc_name.startswith('mobile_app_'):
                            friendly = svc_data.get('name') or svc_name
                            devices.append({'id': svc_name, 'name': friendly})
    except Exception as e:
        print(f'[refresh_devices] services error: {e}')

    try:
        resp = requests.get(
            f'{HA_URL}/api/config/config_entries',
            params={'domain': 'mobile_app'},
            headers=_ha_headers(),
            timeout=10,
        )
        if resp.status_code == 200:
            for entry in resp.json():
                uid = entry.get('user_id') or entry.get('options', {}).get('user_id')
                if uid:
                    user_device_map[uid] = entry.get('entry_id') or entry.get('title', '')
    except Exception as e:
        print(f'[refresh_devices] config_entries error: {e}')

    print(f'[refresh_devices] found {len(devices)} devices, {len(user_device_map)} user mappings')


def get_my_device(user_id):
    if not user_id:
        return None
    device_id = user_device_map.get(user_id)
    if not device_id:
        return None
    for d in devices:
        if d['id'] == device_id or d['id'] == f'mobile_app_{device_id}':
            return d
    return None


def _device_name(device_id):
    for d in devices:
        if d['id'] == device_id:
            return d['name']
    return device_id


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def _ingress_url():
    try:
        resp = requests.get('http://supervisor/addons/self/info', headers=_ha_headers(), timeout=5)
        if resp.status_code == 200:
            data = resp.json().get('data', {})
            ingress_url = data.get('ingress_url', '')
            if ingress_url:
                return ingress_url.rstrip('/')
    except Exception:
        pass
    ingress_path = request.headers.get('X-Ingress-Path', '')
    return ingress_path.rstrip('/')


def send_call_notification(call):
    callee_id = call['callee']
    call_id = call['id']
    caller_name = call['caller_name']

    base = _ingress_url()
    answer_url = f'{base}/call/{call_id}?role=callee&auto_answer=1'
    reject_url = f'{base}/call/{call_id}?role=callee&action=reject'

    payload = {
        'title': f'📞 Chamada de {caller_name}',
        'message': 'Toque para atender',
        'data': {
            'push': {
                'tag': f'intercom_{call_id}',
                'actions': [
                    {'action': 'URI', 'title': '📞 Atender', 'uri': answer_url},
                    {'action': 'URI', 'title': '❌ Rejeitar', 'uri': reject_url},
                ],
            }
        },
    }

    try:
        url = f'{HA_URL}/api/services/notify/mobile_app_{callee_id}' if not callee_id.startswith('mobile_app_') else f'{HA_URL}/api/services/notify/{callee_id}'
        requests.post(url, json=payload, headers=_ha_headers(), timeout=10)
    except Exception as e:
        print(f'[notification] send error: {e}')


def clear_notification(device_id, call_id):
    payload = {
        'message': 'clear_notification',
        'data': {'push': {'tag': f'intercom_{call_id}'}},
    }
    try:
        svc = device_id if device_id.startswith('mobile_app_') else f'mobile_app_{device_id}'
        requests.post(f'{HA_URL}/api/services/notify/{svc}', json=payload, headers=_ha_headers(), timeout=10)
    except Exception as e:
        print(f'[notification] clear error: {e}')


# ---------------------------------------------------------------------------
# HTML pages
# ---------------------------------------------------------------------------

PANEL_HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Intercom</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #121212; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; padding: 16px; }
  h2 { color: #90caf9; margin-bottom: 12px; font-size: 1.1rem; }
  .section { margin-bottom: 24px; }
  .my-device { background: #1e1e2e; border-radius: 8px; padding: 12px 16px; margin-bottom: 20px; font-size: 0.95rem; color: #b0bec5; }
  .my-device strong { color: #90caf9; }
  .device-btn { display: inline-block; margin: 6px 6px 6px 0; padding: 10px 18px; background: #1565c0; color: #fff; border: none; border-radius: 24px; font-size: 0.95rem; cursor: pointer; transition: background 0.2s; }
  .device-btn:hover { background: #1976d2; }
  .call-row { background: #1e1e2e; border-radius: 8px; padding: 12px 14px; margin-bottom: 8px; display: flex; align-items: center; justify-content: space-between; }
  .call-info { font-size: 0.9rem; }
  .call-state { font-size: 0.78rem; color: #80cbc4; margin-top: 4px; }
  .hangup-btn { background: #c62828; color: #fff; border: none; border-radius: 20px; padding: 6px 14px; cursor: pointer; font-size: 0.85rem; }
  .hangup-btn:hover { background: #e53935; }
  select { background: #263238; color: #e0e0e0; border: 1px solid #37474f; border-radius: 6px; padding: 6px 10px; font-size: 0.9rem; margin-top: 8px; }
  #no-calls { color: #546e7a; font-size: 0.9rem; }
</style>
</head>
<body>
<div class="my-device" id="my-device-bar">
  Estou usando: <strong id="my-device-name">—</strong>
  <div id="device-selector-wrap" style="display:none;margin-top:8px;">
    <label style="font-size:0.85rem;">Selecione seu dispositivo:</label><br>
    <select id="device-select" onchange="saveMyDevice(this.value)">
      <option value="">-- escolha --</option>
    </select>
  </div>
</div>

<div class="section">
  <h2>Ligar para</h2>
  <div id="device-list"></div>
</div>

<div class="section">
  <h2>Chamadas ativas</h2>
  <div id="call-list"><span id="no-calls">Nenhuma chamada ativa.</span></div>
</div>

<script>
const BASE = '__BASE__';
const MY_DEVICE_SERVER = '__MY_DEVICE__';

let myDevice = MY_DEVICE_SERVER || localStorage.getItem('my_device') || '';
let allDevices = [];

function saveMyDevice(val) {
  myDevice = val;
  localStorage.setItem('my_device', val);
  renderMyDevice();
}

function renderMyDevice() {
  const nameEl = document.getElementById('my-device-name');
  const selectorWrap = document.getElementById('device-selector-wrap');
  if (myDevice) {
    const d = allDevices.find(x => x.id === myDevice);
    nameEl.textContent = d ? d.name : myDevice;
    selectorWrap.style.display = 'none';
  } else {
    nameEl.textContent = '(não detectado)';
    selectorWrap.style.display = 'block';
    const sel = document.getElementById('device-select');
    sel.innerHTML = '<option value="">-- escolha --</option>' +
      allDevices.map(d => `<option value="${d.id}"${d.id===myDevice?' selected':''}>${d.name}</option>`).join('');
  }
}

function call(deviceId) {
  if (!myDevice) { alert('Selecione seu dispositivo primeiro.'); return; }
  if (deviceId === myDevice) { alert('Você não pode ligar para si mesmo.'); return; }
  fetch(BASE + '/api/call/initiate', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({caller: myDevice, callee: deviceId}),
  })
  .then(r => r.json())
  .then(data => {
    if (data.call_id) {
      window.location.href = BASE + '/call/' + data.call_id + '?role=caller';
    } else {
      alert('Erro ao iniciar chamada: ' + (data.error || JSON.stringify(data)));
    }
  })
  .catch(e => alert('Erro: ' + e));
}

function hangup(callId) {
  fetch(BASE + '/api/call/hangup/' + callId, {method: 'POST'});
}

function formatDuration(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return (m > 0 ? m + 'm ' : '') + s + 's';
}

function renderDevices(devs) {
  allDevices = devs;
  renderMyDevice();
  const el = document.getElementById('device-list');
  if (!devs.length) { el.innerHTML = '<span style="color:#546e7a;font-size:.9rem;">Nenhum dispositivo encontrado.</span>'; return; }
  el.innerHTML = devs.map(d =>
    `<button class="device-btn" onclick="call('${d.id}')">📞 Chamar ${d.name}</button>`
  ).join('');
}

function renderCalls(callList) {
  const el = document.getElementById('call-list');
  const active = callList.filter(c => c.state === 'ringing' || c.state === 'active');
  if (!active.length) {
    el.innerHTML = '<span id="no-calls">Nenhuma chamada ativa.</span>';
    return;
  }
  const now = Date.now() / 1000;
  el.innerHTML = active.map(c => {
    const dur = c.answered_at ? formatDuration(now - c.answered_at) : '';
    const stateLabel = c.state === 'ringing' ? '🔔 Chamando...' : '🟢 Em chamada ' + dur;
    return `<div class="call-row">
      <div class="call-info">
        <div>${c.caller_name} → ${c.callee_name}</div>
        <div class="call-state">${stateLabel}</div>
      </div>
      <button class="hangup-btn" onclick="hangup('${c.id}')">Encerrar</button>
    </div>`;
  }).join('');
}

function poll() {
  fetch(BASE + '/api/call/status')
    .then(r => r.json())
    .then(data => renderCalls(data.calls || []))
    .catch(() => {});
}

fetch(BASE + '/api/devices')
  .then(r => r.json())
  .then(data => renderDevices(data.devices || []))
  .catch(() => {});

poll();
setInterval(poll, 3000);
</script>
</body>
</html>
"""

CALL_HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Chamada — Intercom</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #121212; color: #e0e0e0; font-family: 'Segoe UI', sans-serif;
         display: flex; flex-direction: column; align-items: center; justify-content: center;
         min-height: 100vh; padding: 24px; }
  .avatar { width: 90px; height: 90px; border-radius: 50%; background: #1565c0;
             display: flex; align-items: center; justify-content: center;
             font-size: 2rem; font-weight: bold; color: #fff; margin-bottom: 16px; }
  .name { font-size: 1.4rem; font-weight: 600; margin-bottom: 6px; }
  .status { font-size: 0.95rem; color: #80cbc4; margin-bottom: 8px; }
  .timer { font-size: 1rem; color: #b0bec5; margin-bottom: 24px; font-variant-numeric: tabular-nums; }
  #btn-area { display: flex; gap: 16px; }
  .btn { border: none; border-radius: 50%; width: 64px; height: 64px; font-size: 1.5rem;
         cursor: pointer; display: flex; align-items: center; justify-content: center; }
  .btn-hangup { background: #c62828; color: #fff; }
  .btn-hangup:hover { background: #e53935; }
  .btn-mute { background: #37474f; color: #fff; display: none; }
  .btn-mute.active { background: #f57f17; }
  #log { margin-top: 24px; width: 100%; max-width: 480px; background: #1e1e2e;
         border-radius: 8px; padding: 10px 14px; font-size: 0.78rem; color: #78909c;
         max-height: 200px; overflow-y: auto; white-space: pre-wrap; }
  audio { display: none; }
</style>
</head>
<body>
<div class="avatar" id="avatar">??</div>
<div class="name" id="other-name">...</div>
<div class="status" id="status">Aguardando...</div>
<div class="timer" id="timer"></div>
<div id="btn-area">
  <button class="btn btn-mute" id="btn-mute" onclick="toggleMute()" title="Mudo">🎤</button>
  <button class="btn btn-hangup" onclick="doHangup()" title="Encerrar">📵</button>
</div>
<div id="log"></div>
<audio id="remote-audio" autoplay playsinline></audio>

<script>
const BASE = (window.location.pathname.split('/call/')[0] || '').replace(/\/$/, '');
const callId = window.location.pathname.split('/call/')[1] || '';
const params = new URLSearchParams(window.location.search);
const role = params.get('role') || 'callee';
const autoAnswer = params.get('auto_answer') === '1';
const action = params.get('action') || '';

let pc = null;
let localStream = null;
let remoteAudio = document.getElementById('remote-audio');
let connected = false;
let muted = false;
let timerInterval = null;
let connectedAt = null;
let pollInterval = null;

function log(msg) {
  const el = document.getElementById('log');
  el.textContent += '[' + new Date().toLocaleTimeString() + '] ' + msg + '\n';
  el.scrollTop = el.scrollHeight;
  console.log(msg);
}

function setStatus(msg) {
  document.getElementById('status').textContent = msg;
}

async function loadCallInfo() {
  try {
    const r = await fetch(BASE + '/api/call/' + callId);
    if (!r.ok) { log('Chamada não encontrada'); endUI(); return null; }
    return await r.json();
  } catch(e) { log('Erro ao carregar chamada: ' + e); return null; }
}

function initAvatar(name) {
  const initials = (name || '?').split(' ').map(w => w[0]).join('').slice(0,2).toUpperCase();
  document.getElementById('avatar').textContent = initials;
  document.getElementById('other-name').textContent = name || '?';
}

function startTimer() {
  connectedAt = Date.now();
  timerInterval = setInterval(() => {
    const elapsed = Math.floor((Date.now() - connectedAt) / 1000);
    const m = Math.floor(elapsed / 60);
    const s = elapsed % 60;
    document.getElementById('timer').textContent = (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
  }, 1000);
}

function onConnected() {
  if (connected) return;
  connected = true;
  log('Conectado! Áudio bidirecional ativo.');
  setStatus('Em chamada');
  document.getElementById('btn-mute').style.display = 'flex';
  startTimer();
}

function endUI() {
  document.getElementById('btn-area').style.display = 'none';
  document.getElementById('status').textContent = 'Chamada encerrada';
  if (timerInterval) { clearInterval(timerInterval); timerInterval = null; }
  if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
  if (localStream) { localStream.getTracks().forEach(t => t.stop()); }
  if (pc) { try { pc.close(); } catch(e) {} }
  setTimeout(() => { window.location.href = BASE + '/'; }, 2000);
}

function toggleMute() {
  if (!localStream) return;
  muted = !muted;
  localStream.getAudioTracks().forEach(t => { t.enabled = !muted; });
  const btn = document.getElementById('btn-mute');
  btn.classList.toggle('active', muted);
  btn.title = muted ? 'Ativar mic' : 'Mudo';
}

function doHangup() {
  fetch(BASE + '/api/call/hangup/' + callId, {method: 'POST'}).catch(()=>{});
  endUI();
}

async function gatherComplete(pc) {
  if (pc.iceGatheringState === 'complete') return;
  return new Promise(resolve => {
    const t = setTimeout(resolve, 8000);
    const h = () => {
      if (pc.iceGatheringState === 'complete') {
        clearTimeout(t); pc.removeEventListener('icegatheringstatechange', h); resolve();
      }
    };
    pc.addEventListener('icegatheringstatechange', h);
  });
}

const iceServers = [{urls:'stun:stun.l.google.com:19302'},{urls:'stun:stun1.l.google.com:19302'}];

async function startCaller() {
  log('Papel: chamador. Iniciando mídia...');
  setStatus('Ligando...');
  try {
    localStream = await navigator.mediaDevices.getUserMedia({audio: true, video: false});
    log('Mídia local obtida.');
  } catch(e) { log('Erro ao acessar microfone: ' + e); setStatus('Erro de microfone'); return; }

  pc = new RTCPeerConnection({iceServers});
  localStream.getTracks().forEach(t => pc.addTrack(t, localStream));

  pc.ontrack = e => {
    log('Track remoto recebido (caller).');
    if (!remoteAudio.srcObject) remoteAudio.srcObject = new MediaStream();
    remoteAudio.srcObject.addTrack(e.track);
    remoteAudio.play().catch(() => {});
  };

  pc.oniceconnectionstatechange = () => {
    log('ICE state: ' + pc.iceConnectionState);
    if (pc.iceConnectionState === 'connected' || pc.iceConnectionState === 'completed') onConnected();
    if (pc.iceConnectionState === 'failed' || pc.iceConnectionState === 'disconnected') endUI();
  };

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  log('Offer criada. Aguardando ICE gathering...');
  await gatherComplete(pc);
  log('ICE gathering completo. Enviando offer...');

  await fetch(BASE + '/api/sdp/' + callId + '/offer', {
    method: 'POST',
    headers: {'Content-Type': 'text/plain'},
    body: pc.localDescription.sdp,
  });
  log('Offer enviada. Aguardando answer...');
  setStatus('Aguardando atendimento...');

  pollInterval = setInterval(async () => {
    try {
      const r = await fetch(BASE + '/api/sdp/' + callId + '/answer');
      if (r.status === 200) {
        const answerSdp = await r.text();
        clearInterval(pollInterval); pollInterval = null;
        log('Answer recebida! Configurando conexão...');
        await pc.setRemoteDescription({type: 'answer', sdp: answerSdp});
        log('RemoteDescription configurada.');
      }
    } catch(e) { log('Poll answer erro: ' + e); }
  }, 2000);

  // Also poll for call state to detect hang-up from callee
  const statePoller = setInterval(async () => {
    try {
      const r = await fetch(BASE + '/api/call/' + callId);
      if (r.ok) {
        const d = await r.json();
        if (d.state === 'ended' || d.state === 'rejected') {
          clearInterval(statePoller);
          log('Chamada encerrada remotamente.');
          endUI();
        }
      }
    } catch(e) {}
  }, 3000);
}

async function startCallee() {
  log('Papel: chamado. Aguardando offer...');
  setStatus('Aguardando...');

  // Poll for offer
  let offerSdp = null;
  for (let i = 0; i < 30; i++) {
    try {
      const r = await fetch(BASE + '/api/sdp/' + callId + '/offer');
      if (r.status === 200) {
        offerSdp = await r.text();
        log('Offer recebida!');
        break;
      }
    } catch(e) { log('Poll offer erro: ' + e); }
    await new Promise(res => setTimeout(res, 2000));
  }

  if (!offerSdp) { log('Timeout aguardando offer.'); endUI(); return; }

  pc = new RTCPeerConnection({iceServers});

  pc.ontrack = e => {
    log('Track remoto recebido (callee).');
    if (!remoteAudio.srcObject) remoteAudio.srcObject = new MediaStream();
    remoteAudio.srcObject.addTrack(e.track);
    remoteAudio.play().catch(() => {});
  };

  pc.oniceconnectionstatechange = () => {
    log('ICE state: ' + pc.iceConnectionState);
    if (pc.iceConnectionState === 'connected' || pc.iceConnectionState === 'completed') onConnected();
    if (pc.iceConnectionState === 'failed' || pc.iceConnectionState === 'disconnected') endUI();
  };

  await pc.setRemoteDescription({type: 'offer', sdp: offerSdp});
  log('RemoteDescription (offer) configurada.');

  try {
    localStream = await navigator.mediaDevices.getUserMedia({audio: true, video: false});
    log('Mídia local obtida.');
  } catch(e) { log('Erro ao acessar microfone: ' + e); setStatus('Erro de microfone'); return; }

  localStream.getTracks().forEach(t => pc.addTrack(t, localStream));

  const answer = await pc.createAnswer();
  await pc.setLocalDescription(answer);
  log('Answer criada. Aguardando ICE gathering...');
  await gatherComplete(pc);
  log('ICE gathering completo. Enviando answer...');

  await fetch(BASE + '/api/sdp/' + callId + '/answer', {
    method: 'POST',
    headers: {'Content-Type': 'text/plain'},
    body: pc.localDescription.sdp,
  });
  log('Answer enviada. Aguardando conexão...');
  setStatus('Conectando...');

  // Mark answered server-side
  await fetch(BASE + '/api/call/answer/' + callId, {method: 'POST'});

  // Poll for state changes
  pollInterval = setInterval(async () => {
    try {
      const r = await fetch(BASE + '/api/call/' + callId);
      if (r.ok) {
        const d = await r.json();
        if (d.state === 'ended' || d.state === 'rejected') {
          clearInterval(pollInterval); pollInterval = null;
          log('Chamada encerrada remotamente.');
          endUI();
        }
      }
    } catch(e) {}
  }, 3000);
}

async function init() {
  // Handle reject action
  if (action === 'reject') {
    setStatus('Rejeitando chamada...');
    try {
      await fetch(BASE + '/api/call/reject/' + callId, {method: 'POST'});
    } catch(e) {}
    setStatus('Chamada rejeitada');
    document.getElementById('btn-area').style.display = 'none';
    setTimeout(() => { window.location.href = BASE + '/'; }, 2000);
    return;
  }

  const callData = await loadCallInfo();
  if (!callData) return;

  if (role === 'caller') {
    initAvatar(callData.callee_name);
    await startCaller();
  } else {
    initAvatar(callData.caller_name);
    setStatus('Chamada recebida');
    if (autoAnswer) {
      log('Auto-atendimento ativado.');
      await startCallee();
    } else {
      // Manual answer UI
      setStatus('Chamada recebida — toque para atender');
      const answerBtn = document.createElement('button');
      answerBtn.className = 'btn';
      answerBtn.style.background = '#2e7d32';
      answerBtn.style.color = '#fff';
      answerBtn.title = 'Atender';
      answerBtn.textContent = '📞';
      answerBtn.onclick = async () => {
        answerBtn.remove();
        await startCallee();
      };
      document.getElementById('btn-area').prepend(answerBtn);
    }
  }
}

init();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Flask routes — pages
# ---------------------------------------------------------------------------

@app.route('/')
def panel():
    user_id = request.headers.get('X-Remote-User-ID', '')
    my_device = get_my_device(user_id)
    my_device_id = my_device['id'] if my_device else ''
    ingress_path = request.headers.get('X-Ingress-Path', '').rstrip('/')
    html = PANEL_HTML.replace('__BASE__', ingress_path).replace('__MY_DEVICE__', my_device_id)
    return Response(html, mimetype='text/html')


@app.route('/call/<call_id>')
def call_page(call_id):
    html = CALL_HTML
    return Response(html, mimetype='text/html')


# ---------------------------------------------------------------------------
# Flask routes — API
# ---------------------------------------------------------------------------

@app.route('/api/call/initiate', methods=['POST'])
def api_call_initiate():
    body = request.get_json(force=True, silent=True) or {}
    caller_id = body.get('caller', '')
    callee_id = body.get('callee', '')

    if not caller_id or not callee_id:
        return jsonify({'error': 'caller and callee required'}), 400

    call_id = str(uuid.uuid4())
    call = {
        'id': call_id,
        'caller': caller_id,
        'caller_name': _device_name(caller_id),
        'callee': callee_id,
        'callee_name': _device_name(callee_id),
        'state': 'ringing',
        'started_at': time.time(),
        'answered_at': None,
        'ended_at': None,
        'offer_sdp': None,
        'answer_sdp': None,
    }
    calls[call_id] = call
    send_call_notification(call)
    return jsonify({'call_id': call_id})


@app.route('/api/call/answer/<call_id>', methods=['POST'])
def api_call_answer(call_id):
    call = calls.get(call_id)
    if not call:
        return jsonify({'error': 'not found'}), 404
    if call['state'] == 'ringing':
        call['state'] = 'active'
        call['answered_at'] = time.time()
    clear_notification(call['caller'], call_id)
    clear_notification(call['callee'], call_id)
    return jsonify({'state': call['state']})


@app.route('/api/call/reject/<call_id>', methods=['POST'])
def api_call_reject(call_id):
    call = calls.get(call_id)
    if not call:
        return jsonify({'error': 'not found'}), 404
    call['state'] = 'rejected'
    call['ended_at'] = time.time()
    clear_notification(call['caller'], call_id)
    clear_notification(call['callee'], call_id)
    return jsonify({'state': 'rejected'})


@app.route('/api/call/hangup/<call_id>', methods=['POST'])
def api_call_hangup(call_id):
    call = calls.get(call_id)
    if not call:
        return jsonify({'error': 'not found'}), 404
    call['state'] = 'ended'
    call['ended_at'] = time.time()
    return jsonify({'state': 'ended'})


@app.route('/api/call/status')
def api_call_status():
    call_list = [
        {k: v for k, v in c.items() if k not in ('offer_sdp', 'answer_sdp')}
        for c in calls.values()
    ]
    return jsonify({'calls': call_list})


@app.route('/api/call/<call_id>')
def api_call_get(call_id):
    call = calls.get(call_id)
    if not call:
        return jsonify({'error': 'not found'}), 404
    result = {k: v for k, v in call.items() if k not in ('offer_sdp', 'answer_sdp')}
    return jsonify(result)


@app.route('/api/sdp/<call_id>/offer', methods=['POST'])
def api_sdp_offer_post(call_id):
    call = calls.get(call_id)
    if not call:
        return jsonify({'error': 'not found'}), 404
    call['offer_sdp'] = request.get_data(as_text=True)
    return jsonify({'ok': True})


@app.route('/api/sdp/<call_id>/offer', methods=['GET'])
def api_sdp_offer_get(call_id):
    call = calls.get(call_id)
    if not call or not call.get('offer_sdp'):
        return Response(status=204)
    return Response(call['offer_sdp'], mimetype='text/plain')


@app.route('/api/sdp/<call_id>/answer', methods=['POST'])
def api_sdp_answer_post(call_id):
    call = calls.get(call_id)
    if not call:
        return jsonify({'error': 'not found'}), 404
    call['answer_sdp'] = request.get_data(as_text=True)
    return jsonify({'ok': True})


@app.route('/api/sdp/<call_id>/answer', methods=['GET'])
def api_sdp_answer_get(call_id):
    call = calls.get(call_id)
    if not call or not call.get('answer_sdp'):
        return Response(status=204)
    return Response(call['answer_sdp'], mimetype='text/plain')


@app.route('/api/devices')
def api_devices():
    return jsonify({'devices': devices})


@app.route('/api/my_device')
def api_my_device():
    user_id = request.headers.get('X-Remote-User-ID', '')
    device = get_my_device(user_id)
    return jsonify({'device': device})


@app.route('/health')
def health():
    uptime = int(time.time() - start_time)
    return jsonify({'status': 'ok', 'uptime': uptime})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    refresh_devices()
    app.run(host='0.0.0.0', port=8099, debug=False)
