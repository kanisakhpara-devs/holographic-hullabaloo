"use strict";
/* Core: state, backend connection, helpers, navigation. Plain classic scripts (no bundler): the
   Tauri shell serves the whole ui folder, and the pages share these globals. */
const EMOS = ["neutral", "happy", "smug", "angry", "surprised", "sad", "confused", "sleepy", "bored", "suspicious", "laughing", "eyeroll"];
const VIS = ["closed", "ah", "oh", "ee", "oo", "fv"];
const STATES = ["sleeping", "waking", "listening", "thinking", "speaking", "interrupted", "disconnected"];
const $ = s => document.querySelector(s);
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const QS = new URLSearchParams(location.search);
/* backend address: injected by the desktop shell (port + launch token); in browser mode the page is
   served by the backend itself (http://localhost:5000), so use the page's own host and port */
const SAME_ORIGIN = !window.__HH__ && location.protocol === "http:" && !!location.port;
const HH = window.__HH__ || { port: +(QS.get("port") || (SAME_ORIGIN ? location.port : 8765)), token: QS.get("token") || "" };
const HOST = SAME_ORIGIN ? location.hostname : "127.0.0.1";
const API = "http://" + HOST + ":" + HH.port, HDR = { "X-Token": HH.token };
const DEMO = QS.get("demo") === "1";            /* fake data ONLY with ?demo=1 */

const DEFAULTS = {
  persona: "smug_sarcastic", custom_persona_text: "", content: "pg", privacy_mode: "debug", reply_length: "normal",
  sarcasm_level: 2, temperature: 0.9, roast_user: false, blocklist: "", owner_name: "", web_search: false, proximity_wake: true, mic_mode: "hotkey",
  wake_word_sensitivity: 0.5, ptt_hotkey: "Ctrl+Space", vad_silence_ms: 700, idle_timeout_s: 30, mic_device: "",
  mic_gain: 1.0, noise_gate: 0.0, speaker_device: "", volume: 80, mute: false, tts_speed_scale: 1.0,
  lipsync_offset_ms: 0, voice_overrides: {}, emotion_map: {}, device_mode: "sim", serial_port: "",
  device_brightness_cap: 255, llm_model: "gemma3:4b", ollama_url: "http://127.0.0.1:11434", stt_model: "small",
  stt_device: "cuda", tts_device: "cpu", timezone: "Asia/Kolkata", autostart: false, start_minimized: false,
  tray_icon: true, log_level: "info", ui_scale: 1.0, ui_animations: true, ui_theme: "classic"
};

const S = {
  page: "home", cat: "Persona", state: "sleeping", face: "neutral", mouth: "closed",
  say: "", sayDur: 0, sayAt: 0, said: "",
  backend: false, booting: true, connected: false, demo: DEMO,
  settings: JSON.parse(JSON.stringify(DEFAULTS)), schema: {}, personas: [],
  people: [], facts: [], mem: { people: [], facts: [], summary: "" },
  transcript: [], tinfo: null, search: "",
  usage: { cumulative: [0, 0, 0, 0, 0, 0, 0], hours: new Array(24).fill(0), daily: [] }, days: 7, cap: [],
  level: 0, micDropped: 0, latencies: [], counters: {}, lastInterrupt: null,
  device: {}, packets: [], health: null, selftest: null, audio: { inputs: [], outputs: [] }, ports: [],
  emap: null, prompt: null, micTest: "", setup: null, wizard: false, wstep: 0, wbusy: "", wprogress: null
};
let ws = null;

/* ---------- REST helper: {ok, status, data}. Never throws. */
async function api(path, opt) {
  opt = opt || {};
  if (S.demo && window.demoApi) return window.demoApi(path, opt);
  try {
    const r = await fetch(API + path, {
      method: opt.method || "GET",
      headers: Object.assign({}, HDR, opt.body !== undefined ? { "Content-Type": "application/json" } : {}),
      body: opt.body !== undefined ? JSON.stringify(opt.body) : undefined
    });
    if (opt.raw) return { ok: r.ok, status: r.status, resp: r };
    const ct = r.headers.get("content-type") || "";
    const data = ct.includes("json") ? await r.json() : null;
    return { ok: r.ok, status: r.status, data };
  } catch (e) { return { ok: false, status: 0, data: null }; }
}

/* ---------- toast, modal ---------- */
let toastT = null;
function toast(msg, ms) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove("show"), ms || 4000);
}
function showModal(html) { $("#mbox").innerHTML = html; $("#modal").classList.add("show"); const b = $("#mbox button, #mbox textarea"); if (b) b.focus(); }
function closeModal() { $("#modal").classList.remove("show"); $("#mbox").innerHTML = ""; }
function ask(text, okLabel, danger) {       /* in-page confirm (window.confirm blocks the webview) */
  return new Promise(res => {
    window.__askDone = v => { closeModal(); res(v); };
    showModal(`<div>${esc(text)}</div><div class="seg"><button class="pill" onclick="__askDone(false)">Cancel</button>
      <button class="pill ${danger ? "danger" : "on"}" id="askok" onclick="__askDone(true)">${esc(okLabel || "OK")}</button></div>`);
  });
}
addEventListener("keydown", e => { if (e.key === "Escape" && $("#modal").classList.contains("show")) { if (window.__askDone) window.__askDone(false); else closeModal(); } });

/* ---------- scaling: the stage is 1080 units tall and as wide as the window's shape (at least 1500), scaled to
   fit, so there are no empty strips at the sides. Interface size (ui_scale) is separate: it multiplies every font
   size (--z in app.css), so text and bubbles grow and the panels reflow. */
let STAGE_W = 1920;
function fit() {
  const st = $("#stage");
  STAGE_W = Math.max(1500, Math.min(2600, Math.round(1080 * innerWidth / innerHeight)));
  st.style.width = STAGE_W + "px";
  const k = Math.min(innerWidth / STAGE_W, innerHeight / 1080);
  st.style.setProperty("--z", S.settings.ui_scale || 1);
  st.classList.toggle("still", S.settings.ui_animations === false);
  st.classList.toggle("glass", S.settings.ui_theme === "glass");
  if (typeof drawFace === "function") drawFace();
  const cap = $("#cap"); if (cap) requestAnimationFrame(() => { cap.scrollTop = cap.scrollHeight; });
  st.style.transform = `scale(${k})`;
  st.style.left = (innerWidth - STAGE_W * k) / 2 + "px"; st.style.top = (innerHeight - 1080 * k) / 2 + "px";
}
addEventListener("resize", fit);

/* ---------- navigation ---------- */
function go(p) { S.page = p; location.hash = p; render(); }
addEventListener("hashchange", () => { const p = location.hash.slice(1); if (["home", "transcript", "settings"].includes(p) && p !== S.page) { S.page = p; render(); } });
function navBtns() { return ""; }   /* page tabs live in the top bar now */

/* ---------- top bar: title, page tabs, status chip, More drawer (same on every page) ---------- */
function topbarHtml() {
  const tabs = [["home", "Home"], ["transcript", "Transcript"], ["settings", "Settings"]];
  return `<div class="brand" onclick="go('home')" role="button" tabindex="0"><span id="ttl">Holographic Hullabaloo</span><span id="sub">The coolest AI to ever be.</span></div>
   <nav class="tabs" role="tablist">${tabs.map(([p, l]) => `<button class="tab ${S.page === p ? "on" : ""}" role="tab" aria-selected="${S.page === p}" data-nav="${p}" onclick="go('${p}')">${l}</button>`).join("")}</nav>
   <div class="tright"><div class="chip" id="tchip"><span class="dot" id="dot"></span><span id="st"></span><span class="eq"><i></i><i></i><i></i><i></i></span></div>
   <button class="pill more" id="morebtn" aria-expanded="${!!S.drawer}" onclick="toggleDrawer()">More</button></div>`;
}
const SC = { sleeping: "#777", waking: "#e0a800", listening: "#14b05a", thinking: "#7a2cf0", speaking: "#0b5ccc", interrupted: "#e07000", disconnected: "#d33" };
function paintChip() {
  const s = $("#st"), d = $("#dot"), c = $("#tchip"); if (!s) return;
  s.textContent = S.booting ? "starting" : (S.state === "disconnected" ? "no device" : S.state);
  d.style.background = S.booting ? "#e0a800" : SC[S.state];
  c.dataset.state = S.booting ? "booting" : S.state;
}

/* ---------- More drawer: usage, device button, shut down, quick developer panel ---------- */
function toggleDrawer(open) {
  S.drawer = open === undefined ? !S.drawer : open;
  if (S.drawer) loadUsage();
  paintDrawer();
  const b = $("#morebtn"); if (b) b.setAttribute("aria-expanded", !!S.drawer);
}
addEventListener("keydown", e => { if (e.key === "Escape" && S.drawer) toggleDrawer(false); });
function paintDrawer() {
  const d = $("#drawer"); if (!d) return;
  d.classList.toggle("open", !!S.drawer);
  if (!S.drawer) return;
  const c = S.counters || {}, last = (S.latencies || [])[S.latencies.length - 1];
  const sim = S.settings.device_mode === "sim";
  d.innerHTML = `<div class="dhead"><b>More</b><button class="pill sm" onclick="toggleDrawer(false)" aria-label="Close">Close</button></div>
   <div class="dscroll scroll">
   <section>${window.usageCard ? usageCard() : ""}</section>
   <section class="dsec"><h4>Controls</h4>
     <div class="drow"><div>Device button<small>Same as pressing the button on the base: interrupts it mid sentence.</small></div><button class="pill sm" id="btnbtn" onclick="send({type:'button'})">Press</button></div>
     <div class="drow"><div>Shut down<small>Stops the app, frees the GPU, closes the old app.</small></div><button class="pill sm power" id="powerbtn" onclick="shutDown()">Shut down</button></div>
   </section>
   <section class="dsec"><h4>Developer</h4>
     <div class="drow"><div>Mic level</div><div id="dlvl" class="lvlbar"><i></i></div></div>
     <div class="drow"><div>Mic ignored<small>Times you talked while it was busy.</small></div><b>${S.micDropped || c.mic_dropped || 0}</b></div>
     <div class="drow"><div>Last turn<small>Time to first audio.</small></div><b>${last ? Math.round(last.total_ms) + " ms" : "none yet"}</b></div>
     <div class="drow"><div>Device<small>${sim ? "Simulator" : "Serial (USB)"}</small></div><b>${S.connected ? "connected" : "not connected"}</b></div>
     ${sim ? `<div class="drow"><div>Simulate</div><div class="seg wrap">${["near", "far", "press", "unplug", "plug"].map(w => `<button class="pill sm" data-sim="${w}" onclick="send({type:'sim',what:'${w}'})">${w}</button>`).join("")}</div></div>` : ""}
     <div class="drow"><div>Everything else<small>Packets, counters, latency, VRAM, self test.</small></div><button class="pill sm" onclick="toggleDrawer(false);S.cat='Developer';go('settings')">Open Developer</button></div>
   </section></div>`;
}


/* ---------- render ---------- */
let lastPage = null;
function render() {
  if (render.busy) { setTimeout(render, 0); return; }     /* a change event fired by removing a focused field must not re-enter */
  render.busy = true;
  try { renderNow(); } finally { render.busy = false; }
}
function renderNow() {
  const fk = document.activeElement && document.activeElement.dataset && document.activeElement.dataset.fk;
  const L = $("#left"), P = $("#pin"), st = $("#stage");
  const sbPos = $("#sbody") ? $("#sbody").scrollTop : 0, keepScroll = lastPage === S.page && S.page === "settings";
  st.classList.toggle("sp", S.page !== "home");
  if (S.page !== lastPage) {
    lastPage = S.page; st.classList.add("entering"); clearTimeout(render.t);
    render.t = setTimeout(() => st.classList.remove("entering"), 800);
    stopPolling();
    if (S.page === "transcript") loadTranscriptPage();
    if (S.page === "settings") loadSettingsPage();
  }
  $("#topbar").innerHTML = topbarHtml(); paintChip(); paintDrawer();
  if (S.page === "home") renderHome(L, P);
  else if (S.page === "transcript") renderTranscript(L, P);
  else renderSettings(L, P);
  if (keepScroll && $("#sbody")) $("#sbody").scrollTop = sbPos;
  if (fk) { const el = document.querySelector(`[data-fk="${fk}"]`); if (el) el.focus(); }
  renderWizard();
}
function typing() {      /* do not rebuild the page under someone who is typing */
  const a = document.activeElement;
  return !!(a && a.closest && a.closest("#pin") && ((a.tagName === "INPUT" && a.type !== "range" && a.type !== "checkbox") || a.tagName === "TEXTAREA"));
}
function refresh() { if (!typing()) render(); }

/* ---------- sending ---------- */
function send(o) { if (S.demo && window.demoIn) { window.demoIn(o); return; } if (ws && ws.readyState === 1) ws.send(JSON.stringify(o)); }
function setS(p) {
  Object.assign(S.settings, p);
  if ("ui_scale" in p || "ui_animations" in p || "ui_theme" in p) fit();
  send({ type: "settings", patch: p });
  refresh();
}

/* ---------- hooks called by the desktop shell ---------- */
window.hhPTT = down => send({ type: down ? "ptt_down" : "ptt_up" });
window.hhTray = what => { if (what === "sleep") send({ type: "sleep" }); else if (what === "mute") setS({ mute: !S.settings.mute }); };
window.hhHotkeyFailed = k => { toast("Push-to-talk hotkey " + k + " is used by another app. Pick another in Settings, Voice and wake.", 8000); };
window.hhBackendRestarted = () => { try { ws && ws.close(); } catch (e) { } };
window.hhBackendDead = logPath => {
  const d = document.createElement("div"); d.id = "dead";
  d.style.cssText = "position:fixed;inset:0;background:#e5eedf;z-index:99;display:flex;flex-direction:column;align-items:center;justify-content:center;font:30px 'Old Standard TT',serif;gap:20px;text-align:center";
  d.innerHTML = "<b>The companion backend keeps crashing.</b><div style='font-size:24px'>Log file: " + esc(logPath) + "</div><button style='font-size:26px;padding:10px 26px' onclick='location.reload()'>Restart backend</button>";
  document.body.appendChild(d);
};

/* ---------- events from the backend ---------- */
function onEvent(e) {
  switch (e.type) {
    case "snapshot":
      Object.assign(S, { state: e.state, face: e.face || "neutral", people: e.people || [], facts: e.facts || [], connected: !!e.device_connected,
        device: e.device || S.device, personas: e.personas || S.personas, wake: e.wake_status || S.wake });
      Object.assign(S.settings, e.settings || {});
      if (e.diagnostics) { S.latencies = (e.diagnostics.latencies || []).slice(-20); S.counters = e.diagnostics.counters || {}; S.lastInterrupt = e.diagnostics.last_interrupt_ms; }
      fit(); break;
    case "state":
      S.state = e.state; S.connected = e.state !== "disconnected";
      if (e.state === "sleeping" || e.state === "disconnected") { S.say = ""; stopSubs(); }
      if (e.state === "listening" && e.prev !== "interrupted") S.said = "";
      break;
    case "face": S.face = e.emotion; break;
    case "mouth": S.mouth = e.viseme; break;
    case "say": S.say = e.text; S.sayDur = e.duration || 0; S.sayAt = performance.now(); break;
    case "interrupted": S.said = e.said_so_far || ""; break;
    case "transcript":
      S.transcript.push({ role: e.role, text: e.text, emotion: (e.emotions && e.emotions[0]) || "", ts: Date.now() / 1000 });
      if (e.role === "user") S.usage.cumulative[S.usage.cumulative.length - 1]++;
      break;
    case "memory": break;
    case "settings": Object.assign(S.settings, e.settings || {}); fit(); break;
    case "wake_status": S.wake = e; if (S.page === "settings") refresh(); if (S.page === "home" && window.paintMic) paintMic(); break;
    case "mic_stream": S.micOpen = !!e.open; if (S.page === "home" && window.paintMic) paintMic(); break;
    case "wake_heard": S.wakeHeard = Date.now(); if (S.page === "home" && window.paintMic) paintMic(); break;
    case "toast": toast(e.message || ""); break;
    case "mic_dropped": S.micDropped = e.count || S.micDropped + 1; break;
    case "level": S.level = e.level; paintLevel(); return;
    case "latency": S.latencies.push(e); if (S.latencies.length > 20) S.latencies.shift(); break;
    case "device_link": S.connected = !!e.connected; if (e.device) S.device = e.device; break;
    case "device_rotor": S.device = Object.assign({}, S.device, { rotor_ok: e.ok }); break;
    case "selftest": S.selftest = e; break;
    case "mic_test": S.micTest = e.text; break;
    case "error":
      toast((e.where || "error") + ": " + (e.message || JSON.stringify(e.errors || e)), 6000); break;
  }
  afterEvent(e);
}
function afterEvent(e) {
  const t = e.type;
  if (t === "state" || t === "snapshot" || t === "device_link") paintChip();
  if (S.drawer && ["latency", "mic_dropped", "device_link", "state", "settings"].includes(t)) paintDrawer();
  const capChanged = window.capEvent ? capEvent(e) : false;     /* captions keep their history on every page */
  if (t === "face" || t === "mouth") { if (S.page === "home") drawFace(); return; }
  if (t === "transcript" && e.role === "assistant") { clearTimeout(afterEvent.u); afterEvent.u = setTimeout(loadUsage, 800); }
  if (S.page === "home") {
    if (capChanged) renderCaptions();
    if (t === "say" || t === "partial") return;
    if (t === "memory" || t === "latency") return;
    if (t === "transcript") return;
    paintState(); drawFace();
    return;
  }
  if (S.page === "transcript") {
    if (t === "transcript") { refreshChat(); return; }
    if (t === "memory") { loadMem(); return; }
    if (t === "settings") { refresh(); return; }
    return;
  }
  if (S.page === "settings") {
    if (t === "settings" || t === "device_link" || t === "selftest" || t === "state") refresh();
    else if (t === "latency" && (S.cat === "Device" || S.cat === "Developer")) refresh();
    else if (t === "memory" && S.cat === "Privacy") loadMem();
  }
  if (S.wizard && ["mic_test", "latency", "state", "device_link", "snapshot"].includes(t)) renderWizard();
}

/* ---------- loaders ---------- */
async function loadUsage() {
  const r = await api("/api/usage?days=" + S.days);
  S.usage = r.ok && r.data ? r.data : { cumulative: Array(S.days).fill(0), hours: Array(24).fill(0), daily: [] };
  if (S.drawer) renderUsageOnly();
}
async function loadSchema() {
  const r = await api("/api/settings");
  if (r.ok && r.data) { S.schema = r.data.schema || {}; Object.assign(S.settings, r.data.settings || {}); fit(); }
}
async function loadMem() {
  const r = await api("/api/memory");
  if (r.ok && r.data) S.mem = r.data;
  if (S.page === "transcript" || (S.page === "settings" && S.cat === "Privacy")) refresh();
}

/* ---------- connect ---------- */
function connect() {
  if (DEMO) return startDemo();
  if (S.off) return;                                      /* shut down from the Home button: stop reconnecting */
  try { ws = new WebSocket("ws://" + HOST + ":" + HH.port + "/ws?token=" + encodeURIComponent(HH.token)); } catch (e) { return setTimeout(connect, 1000); }
  let ok = false;
  ws.onopen = () => {
    ok = true; S.backend = true; S.booting = false; S.say = "";
    loadUsage(); loadSchema(); checkSetup();
    if (S.page === "home") paintState();
  };
  ws.onmessage = m => { let e; try { e = JSON.parse(m.data); } catch (x) { return; } onEvent(e); };
  ws.onclose = () => {
    S.backend = false; S.state = "disconnected"; S.connected = false; stopSubs();
    if (!ok) { S.booting = true; S.say = "Starting up, loading the voice models..."; }
    if (S.page === "home") { renderSay(); paintState(); }
    if (!S.off) setTimeout(connect, ok ? 2000 : 1000);
  };
}

const fmtTime = ts => { const d = new Date(ts * 1000); return d.toTimeString().slice(0, 8); };
const fmtClock = ts => { const d = new Date(ts * 1000); return d.toTimeString().slice(0, 8) + "." + String(d.getMilliseconds()).padStart(3, "0"); };
const pretty = s => String(s).replace(/_/g, " ").replace(/^./, c => c.toUpperCase());
function download(name, blob) {
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
}
async function downloadApi(path, name) {
  const r = await api(path, { raw: true });
  if (!r.ok) { toast("Download failed (" + r.status + ")"); return; }
  download(name, await r.resp.blob());
}

/* ---------- dev auto-reload: in browser mode the backend reports the newest UI file time; reload on change.
   Python edits restart the backend instead, and the WebSocket reconnects by itself. */
(function devReload() {
  if (!SAME_ORIGIN || DEMO) return;
  let last = null;
  setInterval(async () => {
    try {
      const r = await fetch(API + "/api/dev/stamp", { cache: "no-store" });
      if (!r.ok) return;
      const st = (await r.json()).stamp;
      if (last !== null && st !== last) location.reload();
      last = st;
    } catch (e) { /* backend restarting */ }
  }, 1000);
})();

/* ---------- glass theme: a soft light follows the cursor over glass surfaces ---------- */
document.addEventListener("pointermove", e => {
  const st = $("#stage"); if (!st || !st.classList.contains("glass")) return;
  const el = e.target.closest && e.target.closest(".card, .pill, .cat, .tab, .chip, .mic button, #drawer section, #topbar");
  if (!el) return;
  const r = el.getBoundingClientRect();
  el.style.setProperty("--mx", ((e.clientX - r.left) / r.width * 100).toFixed(1) + "%");
  el.style.setProperty("--my", ((e.clientY - r.top) / r.height * 100).toFixed(1) + "%");
}, { passive: true });
