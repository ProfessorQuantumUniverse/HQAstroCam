/* global state */
const state = {
  settings: {},
  meta: {},
  presets: {},
  isRecording: false,
  activePreset: null,
};

/* ── Utilities ─────────────────────────────────────────────────────── */
const $ = id => document.getElementById(id);

async function api(method, path, body) {
  const opts = {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  };
  const res = await fetch(path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

function showFeedback(msg, ok = true) {
  const el = $('capture-feedback');
  el.textContent = msg;
  el.className = 'capture-feedback ' + (ok ? 'ok' : 'err');
  el.classList.remove('hidden');
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.add('hidden'), 5000);
}

function formatBytes(bytes) {
  if (bytes < 1024)     return bytes + ' B';
  if (bytes < 1048576)  return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1048576).toFixed(1) + ' MB';
}

function formatDate(ts) {
  return new Date(ts * 1000).toLocaleString();
}

/* ── Settings & Presets ─────────────────────────────────────────────── */
async function loadSettings() {
  const data = await api('GET', '/api/settings');
  state.settings = data.settings;
  state.meta      = data.meta;
  state.presets   = data.presets;
  state.isRecording = data.is_recording;
  buildPresetsUI();
  buildControlsUI();
  updateOverlay();
  updateRecordingUI();
}

function buildPresetsUI() {
  const container = $('presets-container');
  container.innerHTML = '';
  const grid = document.createElement('div');
  grid.className = 'preset-grid';
  Object.entries(state.presets).forEach(([key, preset]) => {
    const btn = document.createElement('button');
    btn.className = 'preset-btn' + (key === state.activePreset ? ' active' : '');
    btn.textContent = preset.label;
    btn.dataset.preset = key;
    btn.addEventListener('click', () => applyPreset(key));
    grid.appendChild(btn);
  });
  container.appendChild(grid);
}

function buildControlsUI() {
  const container = $('controls-container');
  container.innerHTML = '';

  const CONTROL_ORDER = [
    'AeEnable', 'AwbEnable', 'ExposureTime', 'AnalogueGain',
    'ColourGains', 'NoiseReductionMode', 'Brightness', 'Contrast',
    'Saturation', 'Sharpness', 'AfMode', 'LensPosition',
  ];

  CONTROL_ORDER.forEach(key => {
    if (!(key in state.meta)) return;
    const meta = state.meta[key];
    const val  = state.settings[key];
    if (val === undefined) return;
    container.appendChild(buildControlRow(key, meta, val));
  });
}

function buildControlRow(key, meta, value) {
  const row = document.createElement('div');
  row.className = 'control-row';
  row.dataset.key = key;

  const label = document.createElement('label');

  if (meta.type === 'bool') {
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = !!value;
    checkbox.id = 'ctrl-' + key;
    label.htmlFor = 'ctrl-' + key;
    label.textContent = meta.label;
    row.appendChild(checkbox);
    row.appendChild(label);
  } else if (meta.type === 'select') {
    label.textContent = meta.label;
    const sel = document.createElement('select');
    sel.id = 'ctrl-' + key;
    Object.entries(meta.options).forEach(([k, v]) => {
      const opt = document.createElement('option');
      opt.value = k;
      opt.textContent = v;
      if (parseInt(k) === value) opt.selected = true;
      sel.appendChild(opt);
    });
    row.appendChild(label);
    row.appendChild(sel);
  } else if (meta.type === 'tuple2') {
    label.textContent = meta.label;
    row.appendChild(label);
    const wrap = document.createElement('div');
    wrap.className = 'tuple-row';
    const vals = Array.isArray(value) ? value : [value, value];
    ['R', 'B'].forEach((ch, i) => {
      const inp = document.createElement('input');
      inp.type = 'number';
      inp.id = `ctrl-${key}-${ch}`;
      inp.min  = meta.min;
      inp.max  = meta.max;
      inp.step = meta.step;
      inp.value = vals[i];
      inp.placeholder = ch;
      wrap.appendChild(inp);
    });
    row.appendChild(wrap);
  } else {
    // int or float
    const valSpan = document.createElement('span');
    valSpan.className = 'control-val';
    valSpan.id = 'ctrl-val-' + key;
    valSpan.textContent = formatControlValue(key, value, meta);
    label.innerHTML = meta.label + ' ';
    label.appendChild(valSpan);

    const inp = document.createElement('input');
    inp.type  = 'number';
    inp.id    = 'ctrl-' + key;
    inp.min   = meta.min;
    inp.max   = meta.max;
    inp.step  = meta.step;
    inp.value = value;
    inp.addEventListener('input', () => {
      $('ctrl-val-' + key).textContent = formatControlValue(key, inp.value, meta);
    });
    row.appendChild(label);
    row.appendChild(inp);
  }
  return row;
}

function formatControlValue(key, raw, meta) {
  const v = parseFloat(raw);
  if (key === 'ExposureTime') {
    if (v >= 1e6) return (v / 1e6).toFixed(3) + ' s';
    if (v >= 1e3) return (v / 1e3).toFixed(1) + ' ms';
    return v + ' µs';
  }
  if (meta.type === 'float') return parseFloat(v).toFixed(2);
  return String(raw);
}

function collectSettings() {
  const out = {};
  document.querySelectorAll('.control-row').forEach(row => {
    const key  = row.dataset.key;
    const meta = state.meta[key];
    if (!meta) return;

    if (meta.type === 'bool') {
      const cb = document.getElementById('ctrl-' + key);
      if (cb) out[key] = cb.checked;
    } else if (meta.type === 'select') {
      const sel = document.getElementById('ctrl-' + key);
      if (sel) out[key] = parseInt(sel.value);
    } else if (meta.type === 'tuple2') {
      const r = document.getElementById(`ctrl-${key}-R`);
      const b = document.getElementById(`ctrl-${key}-B`);
      if (r && b) out[key] = [parseFloat(r.value), parseFloat(b.value)];
    } else {
      const inp = document.getElementById('ctrl-' + key);
      if (inp) out[key] = meta.type === 'int' ? parseInt(inp.value) : parseFloat(inp.value);
    }
  });
  return out;
}

async function applyPreset(key) {
  try {
    const data = await api('POST', '/api/preset', { preset: key });
    state.settings  = data.settings;
    state.activePreset = key;
    buildControlsUI();
    updateOverlay();
    // Update active button
    document.querySelectorAll('.preset-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.preset === key);
    });
    showFeedback(`Preset "${state.presets[key]?.label || key}" applied`);
  } catch (e) {
    showFeedback('Preset error: ' + e.message, false);
  }
}

$('btn-apply').addEventListener('click', async () => {
  try {
    const data = await api('POST', '/api/settings', { settings: collectSettings() });
    state.settings  = data.settings;
    state.activePreset = null;
    document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
    updateOverlay();
    showFeedback('Settings applied ✓');
  } catch (e) {
    showFeedback('Error: ' + e.message, false);
  }
});

function updateOverlay() {
  const exp = state.settings.ExposureTime;
  const gain = state.settings.AnalogueGain;
  if (exp !== undefined) {
    const sec = exp / 1e6;
    $('overlay-exposure').textContent = sec >= 1 ? sec.toFixed(1) + 's' : (exp / 1000).toFixed(0) + 'ms';
  }
  if (gain !== undefined) {
    $('overlay-gain').textContent = 'Gain ' + parseFloat(gain).toFixed(1);
  }
}

/* ── Capture ────────────────────────────────────────────────────────── */
$('btn-capture').addEventListener('click', async () => {
  const raw = $('chk-raw').checked;
  $('btn-capture').disabled = true;
  try {
    const data = await api('POST', '/api/capture', { raw });
    showFeedback('Captured: ' + data.files.join(', '));
    await loadFiles();
  } catch (e) {
    showFeedback('Capture failed: ' + e.message, false);
  } finally {
    $('btn-capture').disabled = false;
  }
});

/* ── Video ──────────────────────────────────────────────────────────── */
$('btn-record').addEventListener('click', async () => {
  try {
    if (!state.isRecording) {
      const fps = parseInt($('fps-select').value);
      const data = await api('POST', '/api/video/start', { fps });
      state.isRecording = true;
      showFeedback('Recording: ' + data.file);
    } else {
      const data = await api('POST', '/api/video/stop');
      state.isRecording = false;
      showFeedback('Saved: ' + data.file);
      await loadFiles();
    }
    updateRecordingUI();
  } catch (e) {
    showFeedback('Video error: ' + e.message, false);
  }
});

function updateRecordingUI() {
  const btn = $('btn-record');
  const badge = $('rec-badge');
  if (state.isRecording) {
    btn.textContent = '⏹ Stop Recording';
    btn.classList.remove('btn-danger');
    btn.classList.add('btn-primary');
    badge.classList.remove('hidden');
  } else {
    btn.textContent = '⏺ Start Video';
    btn.classList.remove('btn-primary');
    btn.classList.add('btn-danger');
    badge.classList.add('hidden');
  }
}

/* ── Files ──────────────────────────────────────────────────────────── */
async function loadFiles() {
  try {
    const data = await api('GET', '/api/files');
    renderFiles(data.files);
  } catch (e) {
    $('files-list').innerHTML = `<p style="color:var(--text-muted);font-size:11px;">Error: ${e.message}</p>`;
  }
}

function renderFiles(files) {
  const list = $('files-list');
  list.innerHTML = '';
  if (!files.length) {
    list.innerHTML = '<p style="color:var(--text-dim);font-size:11px;">No captures yet</p>';
    return;
  }
  files.forEach(f => {
    const item = document.createElement('div');
    item.className = 'file-item';

    const icon = f.type?.startsWith('video')   ? '🎞️'
               : f.type?.startsWith('image')   ? '🖼️'
               : f.name?.endsWith('.dng')       ? '📷'
               : '📄';

    item.innerHTML = `
      <span class="file-icon">${icon}</span>
      <div class="file-meta">
        <div class="file-name" title="${f.name}">${f.name}</div>
        <div class="file-size">${formatBytes(f.size)} &middot; ${formatDate(f.mtime)}</div>
      </div>
      <div class="file-actions">
        <button class="file-btn dl" data-name="${f.name}" title="Download">⬇</button>
        <button class="file-btn del" data-name="${f.name}" title="Delete">🗑</button>
      </div>`;
    list.appendChild(item);
  });

  list.querySelectorAll('.file-btn.del').forEach(btn => {
    btn.addEventListener('click', async () => {
      const name = btn.dataset.name;
      if (!confirm(`Delete ${name}?`)) return;
      try {
        await api('DELETE', '/api/files/' + encodeURIComponent(name));
        await loadFiles();
      } catch (e) {
        showFeedback('Delete failed: ' + e.message, false);
      }
    });
  });
} // FIX: Missing closing brace for the renderFiles function

$('btn-refresh-files').addEventListener('click', loadFiles);
$('btn-files-toggle').addEventListener('click', () => {
  $('files-panel').classList.toggle('hidden');
});

/* ── Network ────────────────────────────────────────────────────────── */
$('btn-network').addEventListener('click', async () => {
  $('network-modal').classList.remove('hidden');
  await refreshNetStatus();
});
$('btn-net-close').addEventListener('click', () => {
  $('network-modal').classList.add('hidden');
});

async function refreshNetStatus() {
  try {
    const data = await api('GET', '/api/network/status');
    const block = $('net-status-block');
    const rows = [
      ['Mode',       data.mode],
      ['IP Address', data.ip_address || 'N/A'],
      ['Hostname',   data.hostname],
      ['Hotspot',    data.hotspot_active ? `Active (${data.hotspot_ssid})` : 'Off'],
    ];
    block.innerHTML = rows.map(([k, v]) =>
      `<div class="net-row"><span class="net-key">${k}</span><span class="net-val">${v}</span></div>`
    ).join('');
    if (data.hotspot_ssid) $('hotspot-ssid').textContent = data.hotspot_ssid;
  } catch (e) {
    $('net-status-block').innerHTML = `<p style="color:var(--red-light);">Could not fetch status: ${e.message}</p>`;
  }
}

$('btn-hotspot').addEventListener('click', async () => {
  $('btn-hotspot').disabled = true;
  try {
    const data = await api('POST', '/api/network/hotspot');
    if (data.password) $('hotspot-password').textContent = data.password;
    await refreshNetStatus();
  } catch (e) {
    alert('Hotspot error: ' + e.message);
  } finally {
    $('btn-hotspot').disabled = false;
  }
});

$('btn-scan').addEventListener('click', async () => {
  $('btn-scan').disabled = true;
  $('btn-scan').textContent = 'Scanning…';
  try {
    const data  = await api('GET', '/api/network/scan');
    const sel   = $('wifi-list');
    sel.innerHTML = '';
    if (!data.networks.length) {
      sel.innerHTML = '<option>No networks found</option>';
    } else {
      data.networks.forEach(n => {
        const opt = document.createElement('option');
        opt.value = n.ssid;
        opt.textContent = `${n.ssid} (${n.signal}%) ${n.security ? '🔒' : ''}${n.in_use ? ' ✔' : ''}`;
        sel.appendChild(opt);
      });
    }
  } catch (e) {
    alert('Scan error: ' + e.message);
  } finally {
    $('btn-scan').disabled = false;
    $('btn-scan').textContent = 'Scan Networks';
  }
});

$('btn-wifi-connect').addEventListener('click', async () => {
  const ssid = $('wifi-list').value;
  const pw   = $('wifi-password').value;
  if (!ssid) { alert('Select a network first'); return; }
  $('btn-wifi-connect').disabled = true;
  try {
    await api('POST', '/api/network/connect', { ssid, password: pw });
    await refreshNetStatus();
    showFeedback('Connected to ' + ssid);
  } catch (e) {
    alert('Connect error: ' + e.message);
  } finally {
    $('btn-wifi-connect').disabled = false;
  }
});

/* ── Night-vision dim mode ──────────────────────────────────────────── */
$('btn-dim').addEventListener('click', () => {
  document.body.classList.toggle('dim-mode');
});

/* ── System info (polled every 30 s) ────────────────────────────────── */
async function updateSysInfo() {
  try {
    const data = await api('GET', '/api/system');
    const temp = data.cpu_temp?.replace("temp=", "") || '';
    $('sys-temp').textContent = '🌡 ' + temp;
    const d = data.disk;
    if (d?.free_gb !== undefined) {
      $('sys-disk').textContent = `💾 ${d.free_gb} GB free`;
    }
  } catch { /* silently ignore */ }
}

/* ── Init ───────────────────────────────────────────────────────────── */
(async function init() {
  await loadSettings();
  await loadFiles();
  await updateSysInfo();
  setInterval(updateSysInfo, 30_000);
  // Reload recording state every 5 s
  setInterval(async () => {
    const data = await api('GET', '/api/settings').catch(() => null);
    if (data) {
      state.isRecording = data.is_recording;
      updateRecordingUI();
    }
  }, 5_000);
})();
