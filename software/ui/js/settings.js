"use strict";
/* Settings page. Every one of the 39 settings keys has a control carrying data-k="<key>".
   Controls send {type:"settings", patch:{key:value}} over the WebSocket; the backend validates and
   answers with the full settings (or an error event), so the UI always ends up showing the truth. */
const CATS = ["Persona", "Answers", "Voice & wake", "Routines", "Audio", "Emotions", "Privacy", "Appearance", "Device", "Health", "System", "Developer", "About"];
const H = {   /* one line helper text per key (the backend schema text wins when it is loaded) */
  persona: "Who Hullabaloo is. Files live in the personas folder.", custom_persona_text: "Your own persona, used when the persona is 'custom'. Max 1200 characters.",
  content: "The device itself always starts in PG. Unfiltered is only ever set here and resets on restart or reconnect.",
  privacy_mode: "Debug keeps transcripts 24 hours. Faire keeps only names and facts.",
  reply_length: "How long replies are.", sarcasm_level: "0 warm to 3 maximum sass.", temperature: "Creativity of the model.",
  roast_user: "Tease the person more (still PG in PG mode).", blocklist: "Words or topics that always get deflected. Comma or line separated.",
  proximity_wake: "Wake when someone walks up to the device.",
  owner_name: "Your name. Other people's names are saved only after they confirm them.",
  web_search: "For recent things (release dates, prices, news). Sends that question to DuckDuckGo. Adds about 1 second.",
  mic_mode: "Off closes the mic. Hotkey only opens it while you hold the key. Hotkey + wake word: the key still works, and it also listens for the wake word.",
  wake_word_sensitivity: "Higher wakes more easily, and falsely.", ptt_hotkey: "Hold to talk, anywhere in Windows. In browser mode the dev window always uses Ctrl+Space.",
  vad_silence_ms: "Silence that ends your sentence.", idle_timeout_s: "Go to sleep after this much quiet.",
  mic_device: "Microphone to listen with.", mic_gain: "Input gain.", noise_gate: "Treat input below this level as silence. 0 is off.",
  speaker_device: "Where speech plays. Auto picks the Hullabaloo device if present.", volume: "Speaker volume.", mute: "Silence the speaker.",
  tts_speed_scale: "Multiplies every emotion's speaking speed.", lipsync_offset_ms: "Shift the mouth later (+) or earlier (-) than the audio.",
  voice_overrides: "Per emotion speed, voice and pause overrides saved in settings.", emotion_map: "Which face each state shows.",
  device_mode: "Simulator on screen, or the real device over USB.", serial_port: "COM port of the base. Auto-detect looks for the ESP32-S3.",
  device_brightness_cap: "Maximum LED brightness sent to the device.", llm_model: "Ollama model name.",
  ollama_url: "Must be this computer.", stt_model: "Whisper model size.", stt_device: "Where Whisper runs.", tts_device: "Where Kokoro runs.",
  timezone: "Used for the time in the prompt, like Asia/Kolkata.", autostart: "Start with Windows.", start_minimized: "Start in the tray.",
  tray_icon: "Closing the window minimizes to the tray.", log_level: "How much the log records.", ui_scale: "Text and bubble size. The layout rearranges to fit.", ui_theme: "Classic sage cards, or frosted liquid glass over a moving colourful background.", ui_animations: "Background waves and other motion. On even if Windows animations are off."
};
const hlp = k => (S.schema[k] && S.schema[k].help) || H[k] || "";
const reloadNote = k => (S.schema[k] && S.schema[k].live === false) ? " Applies after the app restarts." : "";
const sv = k => S.settings[k];
const FMT = {
  x2: v => (+v).toFixed(2) + "x", sec: v => v + " s", ms: v => v + " ms", pct: v => Math.round(v * 100) + "%", int: v => String(Math.round(v)),
  f1: v => (+v).toFixed(1), vol: v => v + "%", scale: v => Math.round(v * 100) + "%", gain: v => (+v).toFixed(1) + "x"
};

/* ---------- control builders ---------- */
function row(label, k, ctrl, extra) { return `<div class="set"><div>${label}<small>${esc(hlp(k))}${reloadNote(k)}${extra || ""}</small></div>${ctrl}</div>`; }
function wrow(label, k, ctrl, extra) { return `<div class="wide"><div>${label}<small>${esc(hlp(k))}${reloadNote(k)}</small></div>${ctrl}${extra || ""}</div>`; }
function tog(k) { return `<button class="sw ${sv(k) ? "on" : ""}" role="switch" aria-checked="${!!sv(k)}" aria-label="${esc(k)}" data-k="${k}" data-fk="${k}" style="border:0;padding:0" onclick="setS({${k}:${!sv(k)}})"></button>`; }
function seg(k, opts) { return `<div class="seg">${opts.map(([v, l]) => `<button class="pill ${sv(k) === v ? "on" : ""}" data-k="${k}" data-v="${v}" data-fk="${k}:${v}" onclick="setS({${k}:'${v}'})">${l}</button>`).join("")}</div>`; }
function rng(k, min, max, step, fmt) {
  return `<div style="display:flex;align-items:center;gap:14px"><span class="val" id="v_${k}">${FMT[fmt](sv(k))}</span>
  <input type="range" data-k="${k}" data-fk="${k}" data-fmt="${fmt}" aria-label="${esc(k)}" min="${min}" max="${max}" step="${step}" value="${sv(k)}" oninput="rngLive(this)" onchange="setS({${k}:+this.value})"></div>`;
}
function rngLive(el) { $("#v_" + el.dataset.k).textContent = FMT[el.dataset.fmt](+el.value); }
function sel(k, opts, cur) {
  cur = cur === undefined ? sv(k) : cur;
  return `<select class="pill" data-k="${k}" data-fk="${k}" aria-label="${esc(k)}" onchange="setS({${k}:this.value})">${opts.map(([v, l]) => `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
}
function txt(k, w) { return `<input type="text" data-k="${k}" data-fk="${k}" aria-label="${esc(k)}" style="width:${w || 320}px" value="${esc(sv(k))}" onchange="setS({${k}:this.value})">`; }
function area(k, max) {
  return `<textarea data-k="${k}" data-fk="${k}" aria-label="${esc(k)}" maxlength="${max}" oninput="$('#c_${k}').textContent=this.value.length" onchange="setS({${k}:this.value})">${esc(sv(k))}</textarea>
  <div class="note"><span id="c_${k}">${(sv(k) || "").length}</span> / ${max}</div>`;
}
function hotkey(k) { return `<button class="pill keyrec" data-k="${k}" data-fk="${k}" onclick="recordKey('${k}',this)">${esc(sv(k))}</button>`; }
function recordKey(k, btn) {
  btn.textContent = "Press keys..."; btn.classList.add("rec");
  const done = () => { removeEventListener("keydown", h, true); btn.classList.remove("rec"); render(); };
  const h = e => {
    e.preventDefault(); e.stopPropagation();
    if (["Control", "Shift", "Alt", "Meta"].includes(e.key)) return;
    const mods = [e.ctrlKey && "Ctrl", e.altKey && "Alt", e.shiftKey && "Shift", e.metaKey && "Super"].filter(Boolean);
    const key = e.key === " " ? "Space" : (e.key.length === 1 ? e.key.toUpperCase() : e.key);
    if (key === "Escape" && !mods.length) { done(); return; }
    removeEventListener("keydown", h, true); btn.classList.remove("rec");
    setS({ [k]: [...mods, key].join("+") });
  };
  addEventListener("keydown", h, true);
}
const chip = (txt2, cls) => `<span class="chipm ${cls || ""}">${esc(txt2)}</span>`;

/* ---------- page ---------- */
function renderSettings(L, P) {
  L.innerHTML = `<div class="card" id="usage"><div class="lbl">Settings</div><div class="inner hide"></div>
   <div id="cats" style="position:absolute" role="tablist">${CATS.map(c => `<button class="cat ${S.cat === c ? "on" : ""}" role="tab" aria-selected="${S.cat === c}" data-cat="${esc(c)}" onclick="pickCat(this.dataset.cat)">${esc(c)}</button>`).join("")}</div></div>` + navBtns();
  P.innerHTML = `<div id="sbody">${settingsBody()}</div>`;
}
function pickCat(c) { S.cat = c; render(); loadCat(); }
async function loadSettingsPage() { await loadSchema(); loadCat(); }
let pollT = null;
function stopPolling() { clearInterval(pollT); pollT = null; }
async function loadCat() {
  stopPolling();
  const c = S.cat;
  if (c === "Persona") { const r = await api("/api/personas"); if (r.ok) S.personaTexts = r.data; }
  if (c === "Audio") { const r = await api("/api/devices/audio"); if (r.ok && r.data) S.audio = r.data; }
  if (c === "Emotions") { const r = await api("/api/emotion_map"); if (r.ok) S.emap = r.data; }
  if (c === "Privacy") { const i = await api("/api/transcript/info"); if (i.ok) S.tinfo = i.data; await loadMem(); }
  if (c === "Device" || c === "Developer" || c === "Health") { await pollDevice(true); pollT = setInterval(() => pollDevice(false), 1000); }
  if (c === "Routines") await loadExtras();
  if (c === "System" || c === "About") { const h = await api("/api/health"); if (h.ok) S.health = h.data; }
  if (S.page === "settings" && S.cat === c) refresh();
}
let pollN = 0;
async function pollDevice(first) {
  if (S.page !== "settings" || (S.cat !== "Device" && S.cat !== "Developer" && S.cat !== "Health")) { stopPolling(); return; }
  const p = await api("/api/device/packets"); if (p.ok && p.data) S.packets = p.data.packets || [];
  const st = await api("/api/device/status"); if (st.ok) S.device = st.data;
  if (first || ++pollN % 3 === 0) { const h = await api("/api/health"); if (h.ok) S.health = h.data; }
  if (first) { const sp = await api("/api/devices/serial"); if (sp.ok && sp.data) S.ports = sp.data.ports || []; }
  paintDevice();
}
function paintDevice() {     /* update the live parts in place (no full rebuild, keeps focus) */
  const pk = $("#pk"); if (pk) pk.innerHTML = packetLines();
  const lt = $("#lat"); if (lt) lt.innerHTML = latencyRows();
  const cn = $("#counters"); if (cn) cn.innerHTML = counterChips();
  const vr = $("#vram"); if (vr) vr.innerHTML = vramHtml();
  const lk = $("#linkstate"); if (lk) lk.innerHTML = linkHtml();
  const stx = $("#selftxt"); if (stx) stx.textContent = selftestText();
  if (window.paintHealth) paintHealth();
}

function settingsBody() {
  switch (S.cat) {
    case "Persona": return pagePersona();
    case "Answers": return pageAnswers();
    case "Voice & wake": return pageVoice();
    case "Audio": return pageAudio();
    case "Emotions": return pageEmotions();
    case "Privacy": return pagePrivacy();
    case "Appearance": return pageAppearance();
    case "Device": return pageDevice();
    case "Routines": return pageRoutines();
    case "Health": return pageHealth();
    case "System": return pageSystem();
    case "Developer": return pageDeveloper();
    default: return pageAbout();
  }
}

/* ---------- Persona ---------- */
function pagePersona() {
  const names = S.personas.length ? S.personas : ["smug_sarcastic", "grumpy_wizard", "hype_buddy", "custom"];
  return row("Your name", "owner_name", txt("owner_name", 220))
    + row("Look things up online", "web_search", tog("web_search"))
    + row("Personality", "persona", `<div style="display:flex;gap:10px">${sel("persona", names.map(n => [n, pretty(n)]))}<button class="pill" id="editpersona" onclick="editPersona()">Edit</button></div>`)
    + wrow("Custom persona", "custom_persona_text", area("custom_persona_text", 1200))
    + row("Content", "content", seg("content", [["pg", "PG"], ["unfiltered", "Unfiltered"]]))
    + (sv("content") === "unfiltered" ? `<div class="warn" id="unfwarn">Unfiltered is on. It resets to PG when the app restarts or the device reconnects. Do not use it at the Faire.</div>` : "");
}
function editPersona() {
  const name = sv("persona");
  if (name === "custom") { toast("Edit the custom persona in the box below"); const a = document.querySelector('[data-k="custom_persona_text"]'); if (a) a.focus(); return; }
  const t = (S.personaTexts || []).find(p => p.name === name);
  showModal(`<div>Edit ${esc(pretty(name))}</div><textarea id="ptext" aria-label="Persona text" style="width:780px;height:300px;margin-top:14px;font:inherit;font-size:26px;border:0;border-radius:22px;padding:14px;background:#d3e0cb">${esc(t ? t.text : "")}</textarea>
   <div class="seg"><button class="pill" onclick="closeModal()">Cancel</button><button class="pill on" id="psave" data-name="${esc(name)}" onclick="savePersona(this.dataset.name)">Save</button></div>`);
}
async function savePersona(name) {
  const text = $("#ptext").value;
  const r = await api("/api/personas/" + encodeURIComponent(name), { method: "PUT", body: { text } });
  if (r.ok) { toast("Saved " + pretty(name)); const p = await api("/api/personas"); if (p.ok) S.personaTexts = p.data; closeModal(); }
  else toast("Could not save: " + ((r.data && r.data.detail) || r.status));
}

/* ---------- Answers ---------- */
function pageAnswers() {
  return row("Reply length", "reply_length", seg("reply_length", [["short", "Short"], ["normal", "Normal"], ["long", "Long"]]))
    + row("Sarcasm", "sarcasm_level", rng("sarcasm_level", 0, 3, 1, "int"))
    + row("Creativity", "temperature", rng("temperature", 0.5, 1.2, 0.05, "f1"))
    + row("Roast the user", "roast_user", tog("roast_user"))
    + wrow("Blocklist", "blocklist", area("blocklist", 2000))
    + `<div class="wide"><div><button class="pill" id="testprompt" onclick="showPrompt()">Test prompt</button><small>Shows the exact system prompt the model gets right now. Read only.</small></div>
      ${S.prompt ? `<div class="promptbox" id="promptbox" tabindex="0">${esc(S.prompt)}</div>` : ""}</div>
      <div class="note">Language: English only for now.</div>`;
}
async function showPrompt() {
  const r = await api("/api/prompt");
  S.prompt = r.ok && r.data ? r.data.prompt : "Could not load the prompt.";
  refresh();
}

/* ---------- Voice & wake ---------- */
function pageVoice() {
  return row("Wake when someone is near", "proximity_wake", tog("proximity_wake"))
    + row("Microphone", "mic_mode", sel("mic_mode", [["off", "Off"], ["hotkey", "Hotkey only"], ["wake", "Hotkey + wake word"]]), " Also on Home.")
    + `<div class="note" id="wakestat">Wake word: ${esc((S.wake && S.wake.phrase) || "hey jarvis")}. Status: ${esc((S.wake && S.wake.message) || "off")}.</div>`
    + row("Wake word sensitivity", "wake_word_sensitivity", rng("wake_word_sensitivity", 0, 1, 0.05, "pct"))
    + wakeHelpHtml()
    + row("Push to talk key", "ptt_hotkey", hotkey("ptt_hotkey"))
    + row("End of sentence silence", "vad_silence_ms", rng("vad_silence_ms", 200, 3000, 50, "ms"))
    + row("Go to sleep after", "idle_timeout_s", rng("idle_timeout_s", 5, 300, 5, "sec"));
}

/* ---------- Audio ---------- */
function devOpts(list) { const seen = new Set(); const o = [["", "System default"]]; list.forEach(d => { if (!seen.has(d.name)) { seen.add(d.name); o.push([d.name, d.name]); } }); return o; }
function pageAudio() {
  const ins = devOpts(S.audio.inputs || []), outs = devOpts(S.audio.outputs || []);
  if (sv("mic_device") && !ins.some(o => o[0] === sv("mic_device"))) ins.push([sv("mic_device"), sv("mic_device") + " (not found)"]);
  if (sv("speaker_device") && !outs.some(o => o[0] === sv("speaker_device"))) outs.push([sv("speaker_device"), sv("speaker_device") + " (not found)"]);
  outs[0][1] = "Auto (Hullabaloo device, else default)";
  return (S.audio.error ? `<div class="warn">No audio devices: ${esc(S.audio.error)}</div>` : "")
    + row("Microphone", "mic_device", sel("mic_device", ins))
    + `<div class="set"><div>Input level<small>Talk and watch it move.</small></div><div class="bar" id="slvl" style="width:300px"><i></i></div></div>`
    + row("Input gain", "mic_gain", rng("mic_gain", 0.1, 8, 0.1, "gain"))
    + row("Noise gate", "noise_gate", rng("noise_gate", 0, 1, 0.01, "pct"))
    + row("Speaker", "speaker_device", sel("speaker_device", outs))
    + row("Volume", "volume", rng("volume", 0, 100, 1, "vol"))
    + row("Mute", "mute", tog("mute"))
    + `<div class="set"><div>Test sound<small>Speaks one sentence through the speaker.</small></div><button class="pill" id="testsound" onclick="testSound()">Play</button></div>`
    + row("Speaking speed", "tts_speed_scale", rng("tts_speed_scale", 0.7, 1.3, 0.05, "x2"))
    + row("Lip sync offset", "lipsync_offset_ms", rng("lipsync_offset_ms", -200, 200, 5, "ms"),
      "")
    + `<div class="set"><div>Calibrate lip sync<small>Plays a beep and flashes the mouth. If the mouth is early, raise the offset. If late, lower it.</small></div><button class="pill" id="calibrate" onclick="calibrate()">Beep and flash</button></div>`;
}
async function testSound() { const r = await api("/api/tts/preview", { method: "POST", body: { emotion: "neutral", text: "Sound check. One, two, three." } }); if (!r.ok || !r.data.ok) toast("Not now, it is busy"); }
async function calibrate() { const r = await api("/api/audio/calibrate", { method: "POST" }); if (!r.ok || !r.data.ok) toast("Not now, it is busy"); }

/* ---------- Emotions ---------- */
const SAMPLE = {
  neutral: "Well, here we are.", happy: "Oh, that is actually great news.", smug: "Of course I knew that already.", angry: "That is the third time you asked.",
  surprised: "Wait, you actually did it?", sad: "I suppose nobody asked how I feel.", confused: "Hm, that does not add up.", sleepy: "Five more minutes, please.",
  bored: "Truly the highlight of my day.", suspicious: "Why do you want to know that?", laughing: "Ha, your face right now.", eyeroll: "Sure. Whatever you say."
};
const VOICES = ["am_michael", "am_adam", "am_eric", "am_liam", "am_onyx", "am_echo", "af_heart", "af_bella", "af_nicole", "af_sarah", "af_sky", "bm_george", "bm_lewis", "bm_daniel", "bf_emma", "bf_isabella"];
function pageEmotions() {
  const m = S.emap; if (!m) return `<div class="note">Loading...</div>`;
  const ov = Object.keys(sv("voice_overrides") || {}).length;
  const head = `<div class="emorow" style="border:0;opacity:.6;font-size:20px"><span></span><span>Emotion</span><span>Speed</span><span>Voice</span><span>Pause ms</span><span></span></div>`;
  const rows = EMOS.map(e => {
    const x = m.map[e] || { speed: 1, voice: "am_michael", pause_ms: 180 };
    const voices = VOICES.includes(x.voice) ? VOICES : [x.voice, ...VOICES];
    return `<div class="emorow" data-emo="${e}"><span class="emothumb" style="background-position:0 ${-EMOS.indexOf(e) * 78 * 0.75}px" aria-hidden="true"></span>
      <span>${e}</span>
      <span style="display:flex;gap:8px;align-items:center"><span id="sp_${e}" style="min-width:54px">${(+x.speed).toFixed(2)}</span><input type="range" min="0.6" max="1.5" step="0.02" value="${x.speed}" aria-label="${e} speed" oninput="$('#sp_${e}').textContent=(+this.value).toFixed(2)" onchange="emoSet('${e}','speed',+this.value)"></span>
      <select aria-label="${e} voice" onchange="emoSet('${e}','voice',this.value)">${voices.map(v => `<option ${v === x.voice ? "selected" : ""}>${v}</option>`).join("")}</select>
      <input type="number" min="0" max="2000" step="10" value="${x.pause_ms}" aria-label="${e} pause" onchange="emoSet('${e}','pause_ms',+this.value)">
      <button class="pill sm" data-prev="${e}" onclick="emoPreview('${e}')">Preview</button></div>`;
  }).join("");
  const sf = m.state_faces || {};
  const states = STATES.map(s => `<div class="set"><div>${s}</div>
    <select class="pill" data-k="emotion_map" data-fk="emap_${s}" data-state="${s}" aria-label="Face for ${s}" onchange="stateFace('${s}',this.value)">${EMOS.map(e => `<option ${sf[s] === e ? "selected" : ""}>${e}</option>`).join("")}</select></div>`).join("");
  return `<h3>Voice for each emotion</h3><div class="note">Saved to a JSON file you can also edit by hand.</div>${head}${rows}
    <div class="set" style="margin-top:10px"><div>Saved overrides<small>${esc(hlp("voice_overrides"))} Active: ${ov}.</small></div>
      <button class="pill" data-k="voice_overrides" data-fk="voice_overrides" onclick="setS({voice_overrides:{}})">Clear overrides</button></div>
    <h3 style="margin-top:22px">Face for each state</h3><div class="note">${esc(hlp("emotion_map"))}</div>${states}`;
}
async function emoSet(e, field, v) {
  const x = Object.assign({}, S.emap.map[e], { [field]: v }); S.emap.map[e] = x;
  const r = await api("/api/emotion_map", { method: "PUT", body: { [e]: { speed: x.speed, voice: x.voice, pause_ms: x.pause_ms } } });
  if (!r.ok) { toast("Rejected: " + ((r.data && r.data.detail) || r.status)); const g = await api("/api/emotion_map"); if (g.ok) S.emap = g.data; render(); }
}
async function emoPreview(e) { const r = await api("/api/tts/preview", { method: "POST", body: { emotion: e, text: SAMPLE[e] } }); if (!r.ok || !r.data.ok) toast("Not now, it is busy"); }
function stateFace(s, e) {
  S.emap.state_faces[s] = e;
  setS({ emotion_map: Object.assign({}, S.emap.state_faces) });
}

/* ---------- Privacy ---------- */
function pagePrivacy() {
  const h = S.tinfo && S.tinfo.hours_left, faire = sv("privacy_mode") === "faire";
  const people = S.mem.people || [], facts = S.mem.facts || [];
  return row("Mode", "privacy_mode", seg("privacy_mode", [["debug", "Debug"], ["faire", "Faire"]]),
    " Debug saves transcripts for 24 hours. Faire keeps only names and facts and wipes everything else the moment you switch.")
    + `<div class="set"><div>Transcript retention<small>${faire ? "Faire mode: nothing is saved." : (h != null ? "Oldest saved line is deleted in " + h.toFixed(1) + " hours." : "Nothing saved right now.")}</small></div>
       <button class="pill" id="wipe2" onclick="wipe()">Wipe now</button></div>`
    + `<div class="wide"><div>Remembered<small>Names and facts people told it. Delete any you do not want kept.</small></div>
      ${people.map(p => `<div class="rm"><span>${esc(p.name)}</span><button aria-label="Forget ${esc(p.name)}" data-del-person="${esc(p.name)}" onclick="delPerson(this.dataset.delPerson)">×</button></div>`).join("") || '<div class="note">nobody yet</div>'}
      ${facts.map(f => `<div class="rm" style="font-size:26px"><span>${esc(f.person)}: ${esc(f.fact)}</span><button aria-label="Forget this fact" data-del-fact="${f.id}" onclick="delFact(+this.dataset.delFact)">×</button></div>`).join("")}
      <div class="wact"><button class="pill danger" id="forget2" onclick="forgetAll()">Forget everything</button><button class="pill" id="expmem2" onclick="exportMemory()">Export memory</button></div></div>`;
}

/* ---------- Device ---------- */
const simKind = () => (S.device && S.device.kind) ? S.device.kind === "sim" : sv("device_mode") === "sim";
function linkHtml() {
  const d = S.device || {}, up = S.connected;
  return `<span class="dot" style="background:${up ? "#14b05a" : "#d33"}"></span>${up ? "connected" : "disconnected"} · ${d.kind === "serial" ? ("serial " + (d.port || "no port")) : "simulator"}`
    + (d.kind === "serial" && d.rotor_ok != null ? ` · rotor ${d.rotor_ok ? "ok" : "fault"}` : "")
    + (d.kind === "serial" && d.last_error && !up ? `<div class="note">${esc(d.last_error)}</div>` : "");
}
function packetLines() {
  const p = (S.packets || []).slice(-100);
  if (!p.length) return "no packets yet";
  return p.map(x => `${fmtClock(x.t)} ${x.dir === "tx" ? "→" : "←"} ${esc(x.hex)}   ${esc(x.text)}`).join("\n");
}
function counterChips() {
  const d = S.device || {}, c = S.counters || {};
  const items = [["checksum errors", d.checksum_errors || 0], ["dropped bytes", d.dropped_bytes || 0], ["tx dropped", d.tx_dropped || 0], ["tx packets", d.tx_packets || 0],
    ["rx packets", d.rx_packets || 0], ["link drops", d.link_downs || 0], ["ping ms", d.ping_ms == null ? "n/a" : d.ping_ms],
    ["untagged replies", c.untagged_replies || 0], ["tag retries", c.tag_retries || 0], ["mic dropped", S.micDropped || c.mic_dropped || 0], ["interrupts", c.interrupts || 0]];
  return items.map(([k, v]) => chip(k + ": " + v, (k.includes("error") || k.includes("drop")) && v ? "warn" : "")).join("");
}
function latencyRows() {
  const L = (S.latencies || []).slice(-20).reverse();
  if (!L.length) return `<tr><td colspan="6">no turns yet</td></tr>`;
  return L.map(l => `<tr><td>${l.ts ? fmtTime(l.ts) : ""}</td><td>${esc(l.source || "")}</td><td>${l.stt_ms ?? ""}</td><td>${l.llm_first_sentence_ms ?? ""}</td><td>${l.tts_first_chunk_ms ?? ""}</td><td><b>${l.total_ms ?? ""}</b></td></tr>`).join("");
}
function vramHtml() {
  const g = S.health && S.health.gpu;
  if (!g || g.vram_total_mb == null) return `<div class="note">No NVIDIA GPU readout (driver or nvidia-smi not found).</div>`;
  const pct = Math.round(100 * g.vram_used_mb / g.vram_total_mb);
  return `<div class="note">${esc(g.gpu || "GPU")}: ${g.vram_used_mb} of ${g.vram_total_mb} MB in use (${pct}%). Other programs count too.</div><div class="bar"><i style="width:${pct}%"></i></div>`;
}
function modelChips() {
  const h = S.health; if (!h) return `<div class="note">Loading...</div>`;
  const c = [];
  c.push(chip("Ollama " + (h.llm.model || "") + (h.llm.reachable ? "" : " not reachable"), h.llm.reachable ? "ok" : "bad"));
  c.push(chip(h.stt.type === "WhisperSTT" ? "Whisper " + (h.stt.device || "") : "Whisper not loaded", h.stt.type === "WhisperSTT" ? "ok" : "bad"));
  c.push(chip(h.tts.type === "KokoroTTS" ? "Kokoro " + (h.tts.device || "") : "Kokoro not loaded", h.tts.type === "KokoroTTS" ? "ok" : "bad"));
  c.push(chip(h.mic && h.mic.device ? "Mic " + h.mic.device : "No microphone", h.mic && h.mic.device ? "ok" : "warn"));
  c.push(chip(h.audio_out && h.audio_out.device ? "Speaker " + h.audio_out.device : "No speaker", h.audio_out && h.audio_out.device ? "ok" : "warn"));
  return `<div class="chips">${c.join("")}</div>` + (h.stt.note ? `<div class="note">Whisper: ${esc(h.stt.note)}</div>` : "");
}
function selftestText() {
  const s = S.selftest; if (!s) return "Not run.";
  if (s.finished) return s.completed ? "Done: all 12 faces and 6 mouth shapes sent." : "Stopped after " + s.step + " of " + s.total + ".";
  return `Step ${s.step} of ${s.total}: ${s.what} ${s.name}`;
}
function pageDevice() {
  const ports = [["", "Auto-detect (ESP32-S3)"]].concat((S.ports || []).map(p => [p.port, p.port + (p.likely ? " (ESP32-S3)" : "") + (p.description ? " " + p.description : "")]));
  if (sv("serial_port") && !ports.some(o => o[0] === sv("serial_port"))) ports.push([sv("serial_port"), sv("serial_port") + " (not present)"]);
  return `<div class="set"><div>Link<small>Base ESP32-S3 over USB, or the simulator.</small></div><div id="linkstate">${linkHtml()}</div></div>
   ${row("Device", "device_mode", seg("device_mode", [["sim", "Simulator"], ["serial", "Serial"]]))}
   ${row("Port", "serial_port", `<div style="display:flex;gap:10px">${sel("serial_port", ports)}<button class="pill" id="refports" onclick="refreshPorts()">Refresh</button></div>`)}
   <div class="set"><div>Reconnect<small>Close the port and open it again.</small></div><button class="pill" id="reconbtn" onclick="send({type:'reconnect'})">Reconnect</button></div>
   ${row("Brightness cap", "device_brightness_cap", rng("device_brightness_cap", 0, 255, 5, "int"))}
   <div class="note">Simulator buttons, self test, packet log, counters, latency and VRAM are in Developer.</div>`;
}

/* ---------- Developer: everything for debugging, in one place ---------- */
function pageDeveloper() {
  return `<h3>Device</h3>
   <div class="set"><div>Link<small>Live.</small></div><div id="linkstate">${linkHtml()}</div></div>
   ${simKind() ? `<div class="set"><div>Simulate<small>Pretend the hardware did something.</small></div><div class="seg" style="flex-wrap:wrap;justify-content:flex-end">${["near", "far", "press", "unplug", "plug"].map(w => `<button class="pill" data-sim="${w}" onclick="send({type:'sim',what:'${w}'})">${w}</button>`).join("")}</div></div>` : `<div class="note">Simulator buttons show when Device is set to Simulator.</div>`}
   <div class="set"><div>Faces self test<small id="selftxt">${esc(selftestText())}</small></div><div class="seg"><button class="pill" id="selftest" onclick="runSelftest()">Run (12 faces, 6 mouths)</button><button class="pill" id="selftestStop" onclick="api('/api/device/selftest/stop',{method:'POST'})">Stop</button></div></div>
   <div class="set"><div>Show one face on the device<small>Device holds it for 3 seconds.</small></div><div class="seg"><select class="pill" id="testemo" aria-label="Test emotion">${EMOS.map(e => `<option>${e}</option>`).join("")}</select><button class="pill" id="testemobtn" onclick="testEmotion()">Show</button></div></div>
   <div class="wide"><div>Packet log<small>Last 100 packets. → is laptop to device, ← is device to laptop.</small></div><div class="mono" id="pk">${packetLines()}</div></div>
   <h3 style="margin-top:20px">Voice pipeline</h3>
   <div class="wide"><div>Counters<small>"mic dropped" = times you talked while it was busy.</small></div><div class="chips" id="counters">${counterChips()}</div></div>
   <div class="wide"><div>Last 20 turns (ms)<small>First audio target is under 2500.</small></div>
     <table class="t"><thead><tr><th>time</th><th>source</th><th>stt</th><th>llm 1st</th><th>tts 1st</th><th>total</th></tr></thead><tbody id="lat">${latencyRows()}</tbody></table></div>
   <div class="wide"><div>VRAM</div><div id="vram">${vramHtml()}</div></div>
   <div class="wide"><div>Models</div>${modelChips()}</div>
   <h3 style="margin-top:20px">Logs</h3>
   ${row("Log detail", "log_level", sel("log_level", [["debug", "debug"], ["info", "info"], ["warning", "warning"], ["error", "error"]]))}
   <div class="set"><div>Diagnostics<small>A zip with logs, settings and device numbers. No transcripts, memory or facts.</small></div><button class="pill" id="expdiag2" onclick="downloadApi('/api/diagnostics.zip','hullabaloo_diagnostics.zip')">Export zip</button></div>`;
}

/* ---------- Appearance ---------- */
function pageAppearance() {
  return row("Theme", "ui_theme", seg("ui_theme", [["classic", "Classic"], ["glass", "Liquid glass"]]))
    + row("Interface size", "ui_scale", rng("ui_scale", 0.8, 1.5, 0.05, "scale"))
    + row("Animations", "ui_animations", tog("ui_animations"));
}

async function refreshPorts() { const r = await api("/api/devices/serial"); if (r.ok && r.data) S.ports = r.data.ports || []; refresh(); }
async function runSelftest() { const r = await api("/api/device/selftest", { method: "POST" }); if (!r.ok) toast("Self test refused: " + ((r.data && r.data.reason) || r.status)); }
async function testEmotion() { const r = await api("/api/device/test_emotion", { method: "POST", body: { emotion: $("#testemo").value } }); if (!r.ok) toast("Device not connected"); }

/* ---------- System ---------- */
function pageSystem() {
  const tz = ["Asia/Kolkata", "UTC", "America/New_York", "Europe/London", "Asia/Shanghai", "Asia/Dubai"];
  return `<h3>Models</h3>${modelChips()}
   ${row("Language model", "llm_model", txt("llm_model", 300))}
   ${row("Ollama address", "ollama_url", txt("ollama_url", 340))}
   ${row("Whisper size", "stt_model", sel("stt_model", [["tiny", "tiny"], ["base", "base"], ["small", "small"], ["medium", "medium"]]))}
   ${row("Whisper runs on", "stt_device", seg("stt_device", [["cuda", "GPU"], ["cpu", "CPU"]]))}
   ${row("Voice runs on", "tts_device", seg("tts_device", [["cpu", "CPU"], ["cuda", "GPU"]]))}
   <h3 style="margin-top:20px">App</h3>
   ${row("Time zone", "timezone", sel("timezone", (tz.includes(sv("timezone")) ? tz : [sv("timezone")].concat(tz)).map(z => [z, z])))}
   ${row("Start with Windows", "autostart", tog("autostart"))}
   ${row("Start in the tray", "start_minimized", tog("start_minimized"))}
   ${row("Close to the tray", "tray_icon", tog("tray_icon"))}
   <div class="set"><div>First run setup<small>Check the GPU, Ollama, models, mic, speaker and device again.</small></div><button class="pill" id="runwiz" onclick="openWizard()">Run setup</button></div>`;
}

/* ---------- About ---------- */
const LICENSES = [
  ["Kokoro TTS (model and library)", "Apache License 2.0"], ["faster-whisper and CTranslate2", "MIT License"], ["OpenAI Whisper model weights", "MIT License"],
  ["Gemma 3 (Google, run through Ollama)", "Gemma Terms of Use"], ["Ollama", "MIT License"], ["silero-vad", "MIT License"],
  ["openWakeWord (code)", "Apache License 2.0. The pretrained wake word models use a non commercial license, check before selling anything."],
  ["Old Standard TT font", "SIL Open Font License 1.1"], ["Tauri", "MIT or Apache License 2.0"], ["FastAPI, uvicorn, websockets, httpx", "MIT or BSD style licenses"]
];
function pageAbout() {
  const h = S.health || {};
  return `<div class="set"><div>Holographic Hullabaloo<small>Companion app for the Fallen POV display.</small></div><div id="ver">version ${esc(h.version || "0.1.0")}</div></div>
   <div class="set"><div>Log folder<small id="logpath">${esc(h.log_path || "not available")}</small></div><button class="pill" id="showlogs" onclick="showLogs()">Copy path</button></div>
   <div class="set"><div>Diagnostics<small>A zip with logs, settings and device numbers. No transcripts, memory or facts.</small></div><button class="pill" id="expdiag" onclick="downloadApi('/api/diagnostics.zip','hullabaloo_diagnostics.zip')">Export zip</button></div>
   <h3 style="margin-top:18px">License notices</h3>
   ${LICENSES.map(([n, l]) => `<div class="set"><div>${esc(n)}<small>${esc(l)}</small></div></div>`).join("")}
   <div class="note">Models are downloaded on first run and stay on this computer. Nothing is sent anywhere while it runs.</div>`;
}
async function showLogs() {
  const p = (S.health && S.health.log_path) || "";
  const dir = p.replace(/[\\/][^\\/]*$/, "");
  try { await navigator.clipboard.writeText(dir); toast("Copied: " + dir); } catch (e) { toast(dir || "No log path"); }
}
