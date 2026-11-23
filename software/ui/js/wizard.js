"use strict";
/* First run setup wizard: 9 steps, each re-checked from the backend, each with Retry. */
const WSTEPS = ["GPU", "Ollama", "Language model", "Speech recognition", "Voice", "Microphone", "Speaker", "Device", "Test conversation"];
S.micOk = false; S.spkOk = false; S.turnMs = null;

async function refreshSetup() {
  const r = await api("/api/setup/status");
  if (r.ok && r.data) S.setup = r.data;
  renderWizard();
}
async function checkSetup() {              /* on connect: show the wizard until it has been completed once */
  const r = await api("/api/setup/status");
  if (r.ok && r.data) { S.setup = r.data; if (!r.data.done && !DEMO) openWizard(); }
}
function openWizard() { S.wizard = true; S.wstep = 0; S.micOk = S.spkOk = false; S.turnMs = null; refreshSetup(); renderWizard(); }
function closeWizard() { send({ type: "mic_test", on: false }); S.wizard = false; renderWizard(); }
async function finishWizard() { await api("/api/setup/done", { method: "POST" }); if (S.setup) S.setup.done = true; closeWizard(); }

function wstatus(i) {
  const s = S.setup; if (!s) return "todo";
  switch (i) {
    case 0: return s.gpu && s.gpu.gpu ? (s.gpu.cuda ? "ok" : "warn") : "warn";
    case 1: return s.ollama.running ? "ok" : "bad";
    case 2: return s.ollama.model_present ? "ok" : (s.ollama.running ? "bad" : "todo");
    case 3: return s.whisper.loaded ? "ok" : "bad";
    case 4: return s.kokoro.loaded ? "ok" : "bad";
    case 5: return S.micOk ? "ok" : "todo";
    case 6: return S.spkOk ? "ok" : "todo";
    case 7: return S.connected ? "ok" : "warn";
    default: return S.turnMs != null ? "ok" : "todo";
  }
}
const WCOL = { ok: "#14b05a", bad: "#d33", warn: "#e0a800", todo: "#888" };
function wgo(i) {
  if (S.wstep === 5 && i !== 5) send({ type: "mic_test", on: false });
  S.wstep = Math.max(0, Math.min(WSTEPS.length - 1, i)); renderWizard();
}

function renderWizard() {
  const w = $("#wiz"); if (!w) return;
  w.classList.toggle("show", !!S.wizard); const st = $("#stage"); if (st) st.classList.toggle("wz", !!S.wizard);
  if (!S.wizard) { w.innerHTML = ""; return; }
  const done = WSTEPS.filter((_, i) => wstatus(i) === "ok").length;
  w.innerHTML = `<h2>Setting things up</h2><div id="wprog" aria-label="Setup progress"><i style="width:${Math.round(100 * done / WSTEPS.length)}%"></i></div>
   <div id="wsteps">${WSTEPS.map((n, i) => `<button class="${S.wstep === i ? "on" : ""}" data-step="${i}" onclick="wgo(${i})"><span class="dot" style="background:${WCOL[wstatus(i)]}"></span>${i + 1}. ${n}</button>`).join("")}</div>
   <div id="wdetail">${wizBody(S.wstep)}
    <div class="wact" style="margin-top:28px">
     <button class="pill" id="wback" onclick="wgo(S.wstep-1)" ${S.wstep === 0 ? "disabled" : ""}>Back</button>
     <button class="pill" id="wretry" onclick="refreshSetup()">Retry</button>
     ${S.wstep < WSTEPS.length - 1 ? `<button class="pill on" id="wnext" onclick="wgo(S.wstep+1)">Next</button>` : `<button class="pill on" id="wfinish" onclick="finishWizard()">Finish</button>`}
     <button class="pill" id="wskip" onclick="closeWizard()">Skip for now</button></div></div>`;
  paintLevel();
}

function wizBody(i) {
  const s = S.setup;
  if (!s) return `<h3>${WSTEPS[i]}</h3><div>Checking...</div>`;
  const st = wstatus(i), tag = { ok: "All good.", bad: "Needs attention.", warn: "Works, with a catch.", todo: "Not checked yet." }[st];
  switch (i) {
    case 0: {
      const g = s.gpu;
      return `<h3>1. GPU</h3><div>${g.gpu ? esc(g.gpu) + ", driver " + esc(g.driver || "?") + ", " + g.vram_total_mb + " MB video memory." : "No NVIDIA GPU or driver found."}</div>
        <div class="note">CUDA for speech recognition: ${g.cuda ? "available" : "not available"}. ${g.stt_note ? "Note: " + esc(g.stt_note) : ""}</div>
        ${g.cuda ? "" : `<div class="warn">Without CUDA, speech recognition runs on the CPU and is slower.</div><div class="wact"><button class="pill" id="usecpu" data-k="stt_device" onclick="setS({stt_device:'cpu'});toast('Speech recognition set to CPU')">Use the CPU for speech</button></div>`}
        <div class="note">${tag}</div>`;
    }
    case 1: {
      const o = s.ollama;
      if (o.running) return `<h3>2. Ollama</h3><div>Ollama is running.</div><div class="note">${tag}</div>`;
      if (o.installed) return `<h3>2. Ollama</h3><div>Ollama is installed but not running.</div><div class="wact"><button class="pill on" id="startollama" onclick="startOllama()">Start Ollama</button></div>${S.wbusy === "ollama" ? "<div class='note'>Starting, give it a few seconds, then press Retry.</div>" : ""}`;
      return `<h3>2. Ollama</h3><div>Ollama is not installed. It runs the language model on this computer.</div>
        <ol class="steps"><li>Press the button to open the download page.</li><li>Run the Windows installer and finish it.</li><li>Come back here and press Retry.</li></ol>
        <div class="wact"><button class="pill on" id="opendl" data-url="${esc(o.download_url)}" onclick="window.open(this.dataset.url,'_blank')">Open the download page</button></div>`;
    }
    case 2: {
      const o = s.ollama;
      if (o.model_present) return `<h3>3. Language model</h3><div>${esc(o.model)} is downloaded.</div><div class="note">${tag}</div>`;
      if (!o.running) return `<h3>3. Language model</h3><div>Start Ollama first (step 2).</div>`;
      const p = S.wprogress;
      return `<h3>3. Language model</h3><div>${esc(o.model)} is not downloaded yet (about 3 GB). This needs the internet once.</div>
        <div class="wact"><button class="pill on" id="pullbtn" onclick="pullModel()" ${S.wbusy === "pull" ? "disabled" : ""}>${S.wbusy === "pull" ? "Downloading..." : "Download"}</button></div>
        ${p ? (p.error ? `<div class="warn">${esc(p.error)}</div>` : `<div class="bar" style="margin-top:16px"><i style="width:${p.percent || 0}%"></i></div><div class="note">${esc(p.status || "")} ${p.percent != null ? p.percent + "%" : ""}</div>`) : ""}`;
    }
    case 3:
      return `<h3>4. Speech recognition</h3><div>${s.whisper.loaded ? "Whisper is loaded (" + esc(s.gpu.stt_device || "?") + ")." : "Whisper did not load."}</div>
        ${s.whisper.loaded ? "" : `<div class="warn">The speech model downloads when the app starts and needs the internet that first time. Check the connection, then restart the app. The log has the reason (Settings, About).</div>`}<div class="note">${tag}</div>`;
    case 4:
      return `<h3>5. Voice</h3><div>${s.kokoro.loaded ? "Kokoro is loaded." : "Kokoro did not load, so there is no voice."}</div>
        ${s.kokoro.loaded ? "" : `<div class="warn">The voice model downloads when the app starts and needs the internet that first time. Restart the app to retry. The log has the reason.</div>`}<div class="note">${tag}</div>`;
    case 5:
      return `<h3>6. Microphone</h3><div>${s.mic && s.mic.device ? "Using: " + esc(s.mic.device) : "No microphone found."}</div>
        <div class="wact"><button class="pill on" id="mictest" onclick="startMicTest()">Start test</button></div>
        <div class="bar" id="wlvl" style="margin-top:18px"><i></i></div>
        <div>${S.micTest ? "Heard: “" + esc(S.micTest) + "”" : "Press Start, then say: testing one two three."}</div>`;
    case 6:
      return `<h3>7. Speaker</h3><div>${s.speaker && s.speaker.device ? "Using: " + esc(s.speaker.device) : "Using the default output. Choose another in Settings, Audio."}</div>
        <div class="wact"><button class="pill on" id="spktest" onclick="testSound()">Play a sentence</button><button class="pill" id="spkheard" onclick="S.spkOk=true;renderWizard()">I heard it</button></div>`;
    case 7: {
      const ports = (S.ports || []);
      return `<h3>8. Device</h3><div>Link: ${S.connected ? "connected" : "not connected"}.</div>
        <div class="wact">${seg("device_mode", [["sim", "Simulator"], ["serial", "Serial"]])}</div>
        <div class="wact"><select class="pill" id="wport" data-k="serial_port" aria-label="Serial port" onchange="setS({serial_port:this.value})"><option value="">Auto-detect (ESP32-S3)</option>${ports.map(p => `<option value="${esc(p.port)}" ${sv("serial_port") === p.port ? "selected" : ""}>${esc(p.port)}${p.likely ? " (ESP32-S3)" : ""}</option>`).join("")}</select>
        <button class="pill" id="wrefports" onclick="refreshPorts().then(renderWizard)">Refresh ports</button></div>
        <div class="note">Pick the simulator if the hardware is not built yet. You can change this later in Settings.</div>`;
    }
    default:
      return `<h3>9. Test conversation</h3><div>One real turn through the whole chain.</div>
        <div class="wact"><button class="pill on" id="testturn" onclick="runTestTurn()">Say hello</button></div>
        <div>${S.turnMs != null ? "First audio after " + S.turnMs + " ms." + (S.turnMs <= 2500 ? " Under the 2500 ms target." : " Slower than the 2500 ms target.") : "Press the button and listen."}</div>`;
  }
}
async function startOllama() { S.wbusy = "ollama"; renderWizard(); await api("/api/setup/ollama_start", { method: "POST" }); setTimeout(() => { S.wbusy = ""; refreshSetup(); }, 4000); }
async function pullModel() {
  S.wbusy = "pull"; S.wprogress = { percent: 0, status: "starting" }; renderWizard();
  try {
    const r = await api("/api/setup/pull", { method: "POST", raw: true });
    const reader = r.resp.body.getReader(), dec = new TextDecoder(); let buf = "";
    for (; ;) {
      const { done, value } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true }); let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const line = buf.slice(0, i); buf = buf.slice(i + 2);
        if (line.startsWith("data: ")) { let d; try { d = JSON.parse(line.slice(6)); } catch (e) { continue; } if (d.error) S.wprogress = { error: d.error }; else if (d.done) S.wprogress = { percent: 100, status: "done" }; else S.wprogress = d; renderWizard(); }
      }
    }
  } catch (e) { S.wprogress = { error: "Download interrupted. Press Download again, it resumes." }; }
  S.wbusy = ""; await refreshSetup();
}
function startMicTest() { S.micTest = ""; send({ type: "mic_test", on: true }); send({ type: "wake" }); renderWizard(); }
function runTestTurn() { S.turnMs = null; S.turnBase = S.latencies.length ? S.latencies[S.latencies.length - 1].ts : 0; send({ type: "wake" }); send({ type: "text", text: "Say hello in one short sentence." }); }
(function () {   /* a latency event after "Say hello" completes step 9; a mic_test event completes step 6 */
  const prev = window.onEvent || onEvent;
  window.onEvent = onEvent = function (e) {
    if (e.type === "latency" && S.wizard && S.wstep === 8 && S.turnBase !== undefined) S.turnMs = e.total_ms;
    if (e.type === "mic_test" && e.text) S.micOk = true;
    return prev(e);
  };
})();
