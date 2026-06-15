import os, time, uuid, threading, logging
from flask import Flask, request, jsonify, Response

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

SUPERVISOR_TOKEN = os.environ.get('SUPERVISOR_TOKEN', '')
HA_URL = 'http://supervisor/core'
START_TIME = time.time()

# In-memory stores
devices = []          # [{id, name, service}]
user_device_map = {}  # user_id -> device_id
calls = {}            # call_id -> call dict
sdp_store = {}        # call_id -> {offer: str, answer: str}

def ha_get(path):
    import requests
    headers = {'Authorization': f'Bearer {SUPERVISOR_TOKEN}', 'Content-Type': 'application/json'}
    try:
        r = requests.get(f'{HA_URL}/api{path}', headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error(f'HA GET {path} failed: {e}')
        return None

def ha_post(path, data):
    import requests
    headers = {'Authorization': f'Bearer {SUPERVISOR_TOKEN}', 'Content-Type': 'application/json'}
    try:
        r = requests.post(f'{HA_URL}/api{path}', json=data, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error(f'HA POST {path} failed: {e}')
        return None

def refresh_devices():
    global devices, user_device_map
    log.info('Refreshing devices from HA...')

    # Get notify services
    services = ha_get('/services')
    new_devices = []
    if services:
        for domain_obj in services:
            if domain_obj.get('domain') == 'notify':
                for svc_name in domain_obj.get('services', {}).keys():
                    if svc_name.startswith('mobile_app_'):
                        device_id = svc_name[len('mobile_app_'):]
                        friendly = device_id.replace('_', ' ').title()
                        new_devices.append({
                            'id': device_id,
                            'name': friendly,
                            'service': f'notify.{svc_name}'
                        })
    devices = new_devices
    log.info(f'Found {len(devices)} mobile_app devices: {[d["id"] for d in devices]}')

    # Build user->device map from config entries
    # mobile_app config entry data has user_id and device_name fields
    entries = ha_get('/config/config_entries?domain=mobile_app')
    new_map = {}
    if entries:
        for entry in entries:
            data = entry.get('data', {})
            user_id = data.get('user_id')
            # device_name in config entry typically matches the notify service id
            raw_name = data.get('device_name', '')
            norm = raw_name.lower().replace(' ', '_').replace('-', '_')
            if user_id and norm:
                for d in new_devices:
                    if d['id'] == norm or norm.startswith(d['id']) or d['id'].startswith(norm):
                        new_map[user_id] = d['id']
                        break
    user_device_map = new_map
    log.info(f'User->device map: {user_device_map}')

def get_ingress_url():
    info = ha_get('/../../addons/self/info') 
    if info:
        return info.get('data', {}).get('ingress_url', '')
    return ''

def send_notification(device_id, title, message, call_id, ingress_url):
    caller_name = title
    answer_url = f'{ingress_url}/call/{call_id}?role=callee&auto_answer=1'
    reject_url = f'{ingress_url}/call/{call_id}?role=callee&action=reject'
    data = {
        'title': title,
        'message': message,
        'data': {
            'tag': f'intercom_{call_id}',
            'actions': [
                {'action': 'URI', 'title': 'Atender', 'uri': answer_url},
                {'action': 'URI', 'title': 'Rejeitar', 'uri': reject_url}
            ]
        }
    }
    ha_post(f'/services/notify/mobile_app_{device_id}', data)

def clear_notification(device_id, call_id):
    ha_post(f'/services/notify/mobile_app_{device_id}', {
        'message': 'clear_notification',
        'data': {'tag': f'intercom_{call_id}'}
    })

PANEL_HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Intercom</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #1a1a2e; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; min-height: 100vh; }
.container { max-width: 600px; margin: 0 auto; padding: 20px; }
h1 { color: #00b4d8; margin-bottom: 8px; font-size: 1.6rem; }
.subtitle { color: #888; font-size: 0.9rem; margin-bottom: 24px; }
.my-device { background: #16213e; border-radius: 10px; padding: 14px 18px; margin-bottom: 24px; display: flex; align-items: center; gap: 12px; }
.my-device label { color: #aaa; font-size: 0.9rem; white-space: nowrap; }
.my-device select, .my-device span { background: #0f3460; color: #e0e0e0; border: 1px solid #00b4d8; border-radius: 6px; padding: 6px 10px; font-size: 0.95rem; }
section { margin-bottom: 28px; }
section h2 { color: #90e0ef; font-size: 1.1rem; margin-bottom: 12px; border-bottom: 1px solid #333; padding-bottom: 6px; }
.device-btn { display: block; width: 100%; background: #0f3460; border: 1px solid #00b4d8; color: #e0e0e0; border-radius: 8px; padding: 14px 18px; margin-bottom: 10px; font-size: 1rem; cursor: pointer; text-align: left; transition: background 0.2s; }
.device-btn:hover { background: #1a4a80; }
.call-row { background: #16213e; border-radius: 8px; padding: 14px 18px; margin-bottom: 10px; display: flex; align-items: center; justify-content: space-between; }
.call-info { font-size: 0.95rem; }
.call-info .names { font-weight: bold; color: #00b4d8; }
.call-info .state { color: #aaa; font-size: 0.85rem; margin-top: 3px; }
.hangup-btn { background: #c0392b; color: white; border: none; border-radius: 6px; padding: 8px 16px; cursor: pointer; font-size: 0.9rem; }
.hangup-btn:hover { background: #e74c3c; }
.empty { color: #555; font-size: 0.9rem; padding: 10px 0; }
</style>
</head>
<body>
<div class="container">
  <h1>Intercom</h1>
  <p class="subtitle">Comunicacao via WebRTC</p>

  <div class="my-device">
    <label>Estou usando:</label>
    <span id="myDeviceDisplay">Detectando...</span>
    <select id="myDeviceSelect" style="display:none" onchange="saveMyDevice(this.value)"></select>
  </div>

  <section>
    <h2>Ligar para</h2>
    <div id="deviceList"><p class="empty">Carregando dispositivos...</p></div>
  </section>

  <section>
    <h2>Chamadas ativas</h2>
    <div id="callList"><p class="empty">Nenhuma chamada ativa</p></div>
  </section>
</div>

<script>
const BASE = '__BASE__';
let myDeviceId = localStorage.getItem('my_device_id') || null;
let allDevices = [];

async function fetchDevices() {
  try {
    const r = await fetch(BASE + '/api/devices');
    const j = await r.json();
    allDevices = j.devices || [];
    renderDevices();
  } catch(e) { console.error('fetchDevices', e); }
}

async function fetchMyDevice() {
  try {
    const r = await fetch(BASE + '/api/my_device');
    const j = await r.json();
    if (j.device) {
      myDeviceId = j.device.id;
      document.getElementById('myDeviceDisplay').textContent = j.device.name;
      document.getElementById('myDeviceSelect').style.display = 'none';
      document.getElementById('myDeviceDisplay').style.display = '';
    } else {
      // fallback to manual select
      showDeviceSelect();
    }
  } catch(e) { showDeviceSelect(); }
}

function showDeviceSelect() {
  const sel = document.getElementById('myDeviceSelect');
  const disp = document.getElementById('myDeviceDisplay');
  sel.innerHTML = '<option value="">-- Selecionar --</option>' +
    allDevices.map(d => `<option value="${d.id}" ${d.id===myDeviceId?'selected':''}>${d.name}</option>`).join('');
  disp.style.display = 'none';
  sel.style.display = '';
  if (myDeviceId) {
    const d = allDevices.find(x => x.id === myDeviceId);
    if (d) disp.textContent = d.name;
  }
}

function saveMyDevice(id) {
  myDeviceId = id;
  localStorage.setItem('my_device_id', id);
}

function renderDevices() {
  const el = document.getElementById('deviceList');
  if (!allDevices.length) { el.innerHTML = '<p class="empty">Nenhum dispositivo encontrado</p>'; return; }
  el.innerHTML = allDevices.map(d =>
    `<button class="device-btn" onclick="call('${d.id}')">Chamar ${d.name}</button>`
  ).join('');
}

async function call(calleeId) {
  if (!myDeviceId) { alert('Selecione seu dispositivo em "Estou usando"'); return; }
  if (calleeId === myDeviceId) { alert('Nao pode ligar para si mesmo'); return; }
  try {
    const r = await fetch(BASE + '/api/call/initiate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({caller: myDeviceId, callee: calleeId})
    });
    const j = await r.json();
    window.location.href = BASE + '/call/' + j.call_id + '?role=caller';
  } catch(e) { alert('Erro ao iniciar chamada: ' + e); }
}

async function hangup(callId) {
  await fetch(BASE + '/api/call/hangup/' + callId, {method: 'POST'});
  fetchCalls();
}

function timeSince(ts) {
  const s = Math.floor((Date.now()/1000) - ts);
  if (s < 60) return s + 's';
  return Math.floor(s/60) + 'm ' + (s%60) + 's';
}

async function fetchCalls() {
  try {
    const r = await fetch(BASE + '/api/call/status');
    const j = await r.json();
    const active = (j.calls || []).filter(c => ['ringing','active'].includes(c.state));
    const el = document.getElementById('callList');
    if (!active.length) { el.innerHTML = '<p class="empty">Nenhuma chamada ativa</p>'; return; }
    el.innerHTML = active.map(c => `
      <div class="call-row">
        <div class="call-info">
          <div class="names">${c.caller_name} -&gt; ${c.callee_name}</div>
          <div class="state">${c.state === 'active' ? 'Ativa - ' + timeSince(c.started_at) : 'Chamando...'}</div>
        </div>
        <button class="hangup-btn" onclick="hangup('${c.id}')">Desligar</button>
      </div>
    `).join('');
  } catch(e) {}
}

async function init() {
  await fetchDevices();
  await fetchMyDevice();
  fetchCalls();
  setInterval(fetchCalls, 3000);
}

init();
</script>
</body>
</html>
"""

CALL_HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Chamada</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #1a1a2e; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; }
.call-card { background: #16213e; border-radius: 16px; padding: 40px 32px; text-align: center; max-width: 360px; width: 90%; }
.avatar { width: 80px; height: 80px; border-radius: 50%; background: #0f3460; display: flex; align-items: center; justify-content: center; font-size: 2.5rem; margin: 0 auto 16px; }
.name { font-size: 1.5rem; font-weight: bold; color: #00b4d8; margin-bottom: 8px; }
.status { color: #aaa; margin-bottom: 8px; font-size: 0.95rem; }
.timer { color: #90e0ef; font-size: 1.1rem; margin-bottom: 24px; min-height: 1.4em; }
.controls { display: flex; gap: 16px; justify-content: center; }
.btn { border: none; border-radius: 50%; width: 60px; height: 60px; font-size: 1.5rem; cursor: pointer; transition: opacity 0.2s; }
.btn:disabled { opacity: 0.4; cursor: default; }
.btn-mute { background: #0f3460; color: #e0e0e0; }
.btn-hangup { background: #c0392b; color: white; }
.btn-hangup:hover:not(:disabled) { background: #e74c3c; }
.debug { margin-top: 20px; background: #0a0a1a; border-radius: 8px; padding: 10px; font-size: 0.75rem; color: #666; text-align: left; max-height: 120px; overflow-y: auto; font-family: monospace; }
</style>
</head>
<body>
<div class="call-card">
  <div class="avatar" id="avatar">&#128100;</div>
  <div class="name" id="otherName">...</div>
  <div class="status" id="status">Conectando...</div>
  <div class="timer" id="timer"></div>
  <div class="controls">
    <button class="btn btn-mute" id="muteBtn" onclick="toggleMute()" disabled>&#127897;</button>
    <button class="btn btn-hangup" id="hangupBtn" onclick="hangup()">&#128245;</button>
  </div>
  <div class="debug" id="debug"></div>
</div>
<audio id="remoteAudio" autoplay playsinline></audio>

<script>
const BASE = (window.location.pathname.split('/call/')[0] || '').replace(/\/$/, '');
const pathParts = window.location.pathname.split('/call/');
const CALL_ID = pathParts[1] ? pathParts[1].split('?')[0].split('/')[0] : '';
const params = new URLSearchParams(window.location.search);
const ROLE = params.get('role') || 'caller';
const AUTO_ANSWER = params.get('auto_answer') === '1';
const ACTION = params.get('action');

let pc = null;
let localStream = null;
let muted = false;
let timerInterval = null;
let callStart = null;
let ended = false;
let offerPollInterval = null;
let answerPollInterval = null;
let remoteAudio = null;

function dbg(msg) {
  console.log('[intercom]', msg);
  const el = document.getElementById('debug');
  el.textContent += '\n' + msg;
  el.scrollTop = el.scrollHeight;
}

function setStatus(s) { document.getElementById('status').textContent = s; }

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

function startTimer() {
  callStart = Date.now();
  timerInterval = setInterval(() => {
    const s = Math.floor((Date.now() - callStart) / 1000);
    const m = Math.floor(s / 60), sec = s % 60;
    document.getElementById('timer').textContent = `${m}:${sec.toString().padStart(2,'0')}`;
  }, 1000);
}

function onConnected() {
  dbg('Connected!');
  setStatus('Em chamada');
  document.getElementById('muteBtn').disabled = false;
  startTimer();
  if (remoteAudio) remoteAudio.play().catch(e => dbg('play err: ' + e));
}

function endUI(msg) {
  if (ended) return;
  ended = true;
  clearInterval(timerInterval);
  if (offerPollInterval) clearInterval(offerPollInterval);
  if (answerPollInterval) clearInterval(answerPollInterval);
  setStatus(msg || 'Chamada encerrada');
  document.getElementById('hangupBtn').disabled = true;
  document.getElementById('muteBtn').disabled = true;
  document.getElementById('timer').textContent = '';
  if (pc) { try { pc.close(); } catch(e){} }
  if (localStream) localStream.getTracks().forEach(t => t.stop());
  setTimeout(() => { window.location.href = BASE + '/'; }, 2000);
}

async function hangup() {
  await fetch(BASE + '/api/call/hangup/' + CALL_ID, {method: 'POST'}).catch(()=>{});
  endUI('Chamada encerrada');
}

function toggleMute() {
  muted = !muted;
  if (localStream) localStream.getAudioTracks().forEach(t => t.enabled = !muted);
  document.getElementById('muteBtn').textContent = muted ? '🔇' : '🎩';
}

function ringTone() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    let stop = false;
    function beep() {
      if (stop || ended) return;
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.connect(g); g.connect(ctx.destination);
      o.frequency.value = 440;
      g.gain.setValueAtTime(0.3, ctx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.5);
      o.start(); o.stop(ctx.currentTime + 0.5);
      setTimeout(beep, 1500);
    }
    beep();
    return () => { stop = true; ctx.close().catch(()=>{}); };
  } catch(e) { dbg('Ring skip: ' + e); return () => {}; }
}

async function pollCallState() {
  try {
    const r = await fetch(BASE + '/api/call/' + CALL_ID);
    if (!r.ok) return null;
    return await r.json();
  } catch(e) { return null; }
}

async function loadCallInfo() {
  const state = await pollCallState();
  if (!state) return;
  const otherName = ROLE === 'caller' ? state.callee_name : state.caller_name;
  document.getElementById('otherName').textContent = otherName || '';
}

// Caller flow
async function startCaller() {
  dbg('Role: caller');
  setStatus('Obtendo audio...');
  try {
    localStream = await navigator.mediaDevices.getUserMedia({audio: true, video: false});
  } catch(e) { setStatus('Erro: sem acesso ao microfone'); dbg('getUserMedia err: ' + e); return; }

  pc = new RTCPeerConnection({iceServers: [
    {urls: 'stun:stun.l.google.com:19302'},
    {urls: 'stun:stun1.l.google.com:19302'}
  ]});

  localStream.getTracks().forEach(t => pc.addTrack(t, localStream));

  remoteAudio = document.getElementById('remoteAudio');
  remoteAudio.srcObject = new MediaStream();
  pc.ontrack = e => {
    dbg('ontrack track=' + e.track.kind);
    remoteAudio.srcObject.addTrack(e.track);
    remoteAudio.play().catch(e2 => dbg('play err: ' + e2));
  };

  pc.oniceconnectionstatechange = () => {
    dbg('ICE: ' + pc.iceConnectionState);
    if (pc.iceConnectionState === 'connected' || pc.iceConnectionState === 'completed') onConnected();
    if (['disconnected','failed','closed'].includes(pc.iceConnectionState) && !ended) endUI('Chamada encerrada');
  };

  dbg('Creating offer...');
  setStatus('Criando oferta...');
  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  dbg('Waiting for ICE gathering...');
  await gatherComplete(pc);
  dbg('ICE gathered, posting offer');

  await fetch(BASE + '/api/sdp/' + CALL_ID + '/offer', {
    method: 'POST',
    headers: {'Content-Type': 'text/plain'},
    body: pc.localDescription.sdp
  });

  setStatus('Chamando...');
  const stopRing = ringTone();

  // Poll for answer
  let answered = false;
  answerPollInterval = setInterval(async () => {
    if (ended) { clearInterval(answerPollInterval); return; }
    try {
      const st = await pollCallState();
      if (st && st.state === 'rejected') { clearInterval(answerPollInterval); stopRing(); endUI('Chamada rejeitada'); return; }
      if (st && st.state === 'ended') { clearInterval(answerPollInterval); stopRing(); endUI('Chamada encerrada'); return; }

      const r = await fetch(BASE + '/api/sdp/' + CALL_ID + '/answer');
      if (r.status === 200) {
        const answerSdp = await r.text();
        if (answerSdp && !answered) {
          answered = true;
          clearInterval(answerPollInterval);
          stopRing();
          dbg('Got answer SDP');
          await pc.setRemoteDescription({type: 'answer', sdp: answerSdp});
          dbg('Remote description set');
          setStatus('Conectando audio...');
        }
      }
    } catch(e) { dbg('poll err: ' + e); }
  }, 1500);
}

// Callee flow
async function startCallee() {
  dbg('Role: callee');

  // Post answer to signal we're here
  await fetch(BASE + '/api/call/answer/' + CALL_ID, {method: 'POST'}).catch(()=>{});

  setStatus('Aguardando oferta...');
  dbg('Polling for offer...');

  let offerSdp = null;
  let tries = 0;
  await new Promise((resolve, reject) => {
    offerPollInterval = setInterval(async () => {
      if (ended) { clearInterval(offerPollInterval); reject(); return; }
      try {
        const r = await fetch(BASE + '/api/sdp/' + CALL_ID + '/offer');
        if (r.status === 200) {
          offerSdp = await r.text();
          if (offerSdp) { clearInterval(offerPollInterval); resolve(); return; }
        }
      } catch(e) {}
      tries++;
      if (tries > 40) { clearInterval(offerPollInterval); reject(new Error('timeout')); }
    }, 1000);
  }).catch(() => { endUI('Timeout aguardando oferta'); });

  if (!offerSdp || ended) return;
  dbg('Got offer SDP');

  pc = new RTCPeerConnection({iceServers: [
    {urls: 'stun:stun.l.google.com:19302'},
    {urls: 'stun:stun1.l.google.com:19302'}
  ]});

  remoteAudio = document.getElementById('remoteAudio');
  remoteAudio.srcObject = new MediaStream();
  pc.ontrack = e => {
    dbg('ontrack track=' + e.track.kind);
    remoteAudio.srcObject.addTrack(e.track);
    remoteAudio.play().catch(e2 => dbg('play err: ' + e2));
  };

  pc.oniceconnectionstatechange = () => {
    dbg('ICE: ' + pc.iceConnectionState);
    if (pc.iceConnectionState === 'connected' || pc.iceConnectionState === 'completed') onConnected();
    if (['disconnected','failed','closed'].includes(pc.iceConnectionState) && !ended) endUI('Chamada encerrada');
  };

  await pc.setRemoteDescription({type: 'offer', sdp: offerSdp});
  dbg('Set remote description');

  setStatus('Obtendo audio...');
  try {
    localStream = await navigator.mediaDevices.getUserMedia({audio: true, video: false});
  } catch(e) { setStatus('Erro: sem acesso ao microfone'); dbg('getUserMedia err: ' + e); return; }
  localStream.getTracks().forEach(t => pc.addTrack(t, localStream));

  const answer = await pc.createAnswer();
  await pc.setLocalDescription(answer);
  dbg('Waiting for ICE gathering...');
  await gatherComplete(pc);
  dbg('ICE gathered, posting answer');

  await fetch(BASE + '/api/sdp/' + CALL_ID + '/answer', {
    method: 'POST',
    headers: {'Content-Type': 'text/plain'},
    body: pc.localDescription.sdp
  });

  setStatus('Conectando audio...');
  dbg('Answer posted, waiting for connection...');
}

async function rejectCall() {
  dbg('Rejecting call');
  await fetch(BASE + '/api/call/reject/' + CALL_ID, {method: 'POST'}).catch(()=>{});
  endUI('Chamada rejeitada');
}

// Monitor for remote hangup
setInterval(async () => {
  if (ended) return;
  const st = await pollCallState();
  if (st && st.state === 'ended') endUI('Chamada encerrada');
}, 3000);

async function init() {
  await loadCallInfo();

  if (ACTION === 'reject') {
    await rejectCall();
    return;
  }

  if (ROLE === 'caller') {
    await startCaller();
  } else if (ROLE === 'callee') {
    if (AUTO_ANSWER) {
      await startCallee();
    } else {
      setStatus('Chamada recebida');
      document.getElementById('hangupBtn').textContent = '✅';
      document.getElementById('hangupBtn').onclick = () => startCallee();
    }
  }
}

init();
</script>
</body>
</html>
"""


@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'uptime': int(time.time() - START_TIME)})


@app.route('/')
def panel():
    ingress_path = request.headers.get('X-Ingress-Path', '')
    base = ingress_path.rstrip('/')
    user_id = request.headers.get('X-Remote-User-ID', '')
    
    my_device = get_my_device(user_id)
    html = PANEL_HTML.replace('__BASE__', base)
    return Response(html, mimetype='text/html')


@app.route('/call/<call_id>')
def call_page(call_id):
    return Response(CALL_HTML, mimetype='text/html')


@app.route('/api/devices')
def api_devices():
    return jsonify({'devices': devices})


@app.route('/api/my_device')
def api_my_device():
    user_id = request.headers.get('X-Remote-User-ID', '')
    device = get_my_device(user_id)
    return jsonify({'device': device})


def get_my_device(user_id):
    if not user_id:
        return None
    device_id = user_device_map.get(user_id)
    if not device_id:
        return None
    for d in devices:
        if d['id'] == device_id:
            return d
    return None


def get_device_name(device_id):
    for d in devices:
        if d['id'] == device_id:
            return d['name']
    return device_id.replace('_', ' ').title()


@app.route('/api/call/initiate', methods=['POST'])
def api_call_initiate():
    data = request.json or {}
    caller = data.get('caller', '')
    callee = data.get('callee', '')
    if not caller or not callee:
        return jsonify({'error': 'caller and callee required'}), 400
    
    call_id = str(uuid.uuid4())[:8]
    calls[call_id] = {
        'id': call_id,
        'caller': caller,
        'callee': callee,
        'caller_name': get_device_name(caller),
        'callee_name': get_device_name(callee),
        'state': 'ringing',
        'created_at': time.time(),
        'started_at': None
    }
    sdp_store[call_id] = {'offer': None, 'answer': None}
    
    # Get ingress URL for notification
    ingress_url = request.headers.get('X-Ingress-Path', '')
    if not ingress_url:
        try:
            import requests as req
            info = req.get(
                'http://supervisor/addons/self/info',
                headers={'Authorization': f'Bearer {SUPERVISOR_TOKEN}'},
                timeout=5
            ).json()
            ingress_url = info.get('data', {}).get('ingress_url', '')
        except Exception:
            ingress_url = ''
    
    ingress_url = ingress_url.rstrip('/')
    caller_name = get_device_name(caller)
    send_notification(
        callee,
        f'Chamada de {caller_name}',
        'Toque para atender',
        call_id,
        ingress_url
    )
    
    return jsonify({'call_id': call_id})


@app.route('/api/call/answer/<call_id>', methods=['POST'])
def api_call_answer(call_id):
    if call_id not in calls:
        return jsonify({'error': 'not found'}), 404
    calls[call_id]['state'] = 'active'
    calls[call_id]['started_at'] = time.time()
    # Clear notifications on both sides
    c = calls[call_id]
    clear_notification(c['caller'], call_id)
    clear_notification(c['callee'], call_id)
    return jsonify({'ok': True})


@app.route('/api/call/reject/<call_id>', methods=['POST'])
def api_call_reject(call_id):
    if call_id not in calls:
        return jsonify({'error': 'not found'}), 404
    calls[call_id]['state'] = 'rejected'
    c = calls[call_id]
    clear_notification(c['caller'], call_id)
    clear_notification(c['callee'], call_id)
    return jsonify({'ok': True})


@app.route('/api/call/hangup/<call_id>', methods=['POST'])
def api_call_hangup(call_id):
    if call_id not in calls:
        return jsonify({'error': 'not found'}), 404
    calls[call_id]['state'] = 'ended'
    return jsonify({'ok': True})


@app.route('/api/call/status')
def api_call_status():
    return jsonify({'calls': list(calls.values())})


@app.route('/api/call/<call_id>')
def api_call_get(call_id):
    if call_id not in calls:
        return jsonify({'error': 'not found'}), 404
    return jsonify(calls[call_id])


@app.route('/api/sdp/<call_id>/offer', methods=['POST'])
def api_sdp_offer_post(call_id):
    if call_id not in sdp_store:
        sdp_store[call_id] = {'offer': None, 'answer': None}
    sdp_store[call_id]['offer'] = request.get_data(as_text=True)
    return jsonify({'ok': True})


@app.route('/api/sdp/<call_id>/offer', methods=['GET'])
def api_sdp_offer_get(call_id):
    sdp = sdp_store.get(call_id, {}).get('offer')
    if not sdp:
        return Response(status=204)
    return Response(sdp, mimetype='text/plain')


@app.route('/api/sdp/<call_id>/answer', methods=['POST'])
def api_sdp_answer_post(call_id):
    if call_id not in sdp_store:
        sdp_store[call_id] = {'offer': None, 'answer': None}
    sdp_store[call_id]['answer'] = request.get_data(as_text=True)
    return jsonify({'ok': True})


@app.route('/api/sdp/<call_id>/answer', methods=['GET'])
def api_sdp_answer_get(call_id):
    sdp = sdp_store.get(call_id, {}).get('answer')
    if not sdp:
        return Response(status=204)
    return Response(sdp, mimetype='text/plain')


if __name__ == '__main__':
    log.info('Starting Intercom v2.0.0')
    refresh_devices()
    # Background refresh every 5 minutes
    def bg_refresh():
        while True:
            time.sleep(300)
            refresh_devices()
    t = threading.Thread(target=bg_refresh, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=8099, debug=False)
