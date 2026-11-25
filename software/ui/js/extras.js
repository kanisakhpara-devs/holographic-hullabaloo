"use strict";
/* Nov 25: timers and reminders, study buddy, games, night hours, music reactions (Home strip) plus the
   Routines and Health settings pages. State comes from {type:"extras"} events and GET /api/extras. */
S.extras = S.extras || { timers: [], study: null, game: null, night: false, music: { on: false } };
S.musicStatus = S.musicStatus || { ok: false, message: "off" };
S.clockSkew = 0;                    /* server time minus browser time, so countdowns match the backend */

const mmss = s => { s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(x).padStart(2, "0"); };
const nowS = () => Date.now() / 1000 + S.clockSkew;

function extrasEvent(e) {
  if (e.type === "extras" || e.type === "snapshot") {
    const x = e.type === "snapshot" ? e.extras : e;
    if (!x) return;
    S.extras = { timers: x.timers || [], study: x.study || null, game: x.game || null, night: !!x.night, music: x.music || { on: false } };
    if (x.now) S.clockSkew = x.now - Date.now() / 1000;
    paintActs();
  } else if (e.type === "music_status") { S.musicStatus = e; if (S.page === "settings" && S.cat === "Routines") refresh(); }
  else if (e.type === "look") { S.look = e.cols; if (S.page === "home") paintLook(); }
  else if (e.type === "device_rotor_power" || e.type === "device_rotor_spin") {
    const d = Object.assign({}, S.device); delete d.type;
    Object.keys(e).forEach(k => { if (k !== "type") d[k] = e[k]; });
    S.device = d; if (S.page === "settings" && S.cat === "Health") paintHealth();
  }
}
async function loadExtras() {
  const r = await api("/api/extras");
  if (r.ok && r.data) { extrasEvent(Object.assign({ type: "extras" }, r.data)); S.musicStatus = r.data.music_status || S.musicStatus; }
}

/* ---------- Home: one row of chips above the captions ---------- */
function actsHtml() {
  const x = S.extras, now = nowS(), out = [];
  if (x.night) out.push(`<span class="act night" title="Night hours">🌙 night hours until ${esc(S.settings.night_end)}</span>`);
  if (x.study) {
    const st = x.study, left = st.ends - now;
    out.push(`<span class="act study ${st.phase}"><b>${st.phase === "focus" ? "Focus" : "Break"}</b> ${esc(st.subject || "study")} · <span class="cd" data-end="${st.ends}">${mmss(left)}</span>
      <button class="x" aria-label="Stop the study session" onclick="studyStop()">×</button></span>`);
  }
  if (x.game) out.push(`<span class="act game"><b>${esc(x.game.title)}</b>${x.game.topic ? " · " + esc(x.game.topic) : ""}${x.game.name === "twenty_questions" ? " · " + x.game.turns + "/20" : ""}
      <button class="x" aria-label="Stop the game" onclick="gameStop()">×</button></span>`);
  (x.timers || []).forEach(t => out.push(`<span class="act timer" title="${esc(t.kind)}"><b>${t.kind === "reminder" ? "⏰" : "⏱"}</b> ${esc(t.label || (t.kind === "reminder" ? "reminder" : "timer"))} · <span class="cd" data-end="${t.due}">${mmss(t.due - now)}</span>
      <button class="x" aria-label="Cancel ${esc(t.label || t.kind)}" data-tid="${t.id}" onclick="timerCancel(+this.dataset.tid)">×</button></span>`));
  if (x.music && x.music.on) out.push(`<span class="act music">♪ bobbing to the music</span>`);
  out.push(`<span class="addacts"><button class="pill mini" id="addtimer" onclick="timerModal()">+ Timer</button>${x.study ? "" : `<button class="pill mini" id="addstudy" onclick="studyModal()">Study</button>`}${x.game ? "" : `<button class="pill mini" id="addgame" onclick="gameModal()">Game</button>`}</span>`);
  return out.join("");
}
function paintActs() { const el = $("#acts"); if (el) el.innerHTML = actsHtml(); }
setInterval(() => {            /* countdowns tick without rebuilding the row */
  const now = nowS();
  document.querySelectorAll("#acts .cd").forEach(el => { el.textContent = mmss(+el.dataset.end - now); });
}, 1000);
function paintLook() { const c = $("#face"); if (c) c.style.transform = S.look ? `translateX(${S.look * 6}px) rotate(${S.look * 0.8}deg)` : ""; }

async function timerCancel(id) { await api("/api/timers/" + id, { method: "DELETE" }); }
async function studyStop() { await api("/api/study", { method: "POST", body: { action: "stop" } }); }
async function gameStop() { await api("/api/game", { method: "POST", body: { action: "stop" } }); }
function timerModal() {
  showModal(`<div>New timer</div>
   <div class="mform"><label>Minutes <input type="number" id="tmin" min="1" max="1440" value="10" aria-label="Minutes"></label>
   <label>Label <input type="text" id="tlabel" maxlength="80" placeholder="pasta (optional)" aria-label="Label"></label>
   <label><input type="checkbox" id="trem" aria-label="Reminder"> Reminder (it reminds you to do the label)</label></div>
   <div class="note">Or just say "set a timer for 10 minutes" or "remind me in 20 minutes to call mom".</div>
   <div class="seg"><button class="pill" onclick="closeModal()">Cancel</button><button class="pill on" id="tgo" onclick="timerAdd()">Start</button></div>`);
}
async function timerAdd() {
  const r = await api("/api/timers", { method: "POST", body: { minutes: +$("#tmin").value, label: $("#tlabel").value, kind: $("#trem").checked ? "reminder" : "timer" } });
  if (r.ok) closeModal(); else toast("Could not set it: " + ((r.data && r.data.detail) || r.status));
}
function studyModal() {
  showModal(`<div>Study session</div>
   <div class="mform"><label>Subject <input type="text" id="ssub" maxlength="40" placeholder="chemistry" aria-label="Subject"></label>
   <label>Focus minutes <input type="number" id="smin" min="5" max="120" value="${S.settings.study_focus_min || 25}" aria-label="Focus minutes"></label></div>
   <div class="note">${S.settings.study_break_min || 5} minute breaks${S.settings.study_quiz ? ", with a quiz question at the start of each" : ""}. Change these in Settings, Routines. Or say "let's study chemistry".</div>
   <div class="seg"><button class="pill" onclick="closeModal()">Cancel</button><button class="pill on" id="sgo" onclick="studyStart()">Start</button></div>`);
}
async function studyStart() {
  const r = await api("/api/study", { method: "POST", body: { subject: $("#ssub").value, focus_min: +$("#smin").value } });
  if (r.ok) closeModal(); else toast("Could not start: " + ((r.data && r.data.detail) || r.status));
}
function gameModal() {
  const g = [["trivia", "Trivia"], ["twenty_questions", "20 questions"], ["would_you_rather", "Would you rather"]];
  showModal(`<div>Play a game</div>
   <div class="mform"><label>Trivia topic <input type="text" id="gtopic" maxlength="40" placeholder="space (optional)" aria-label="Trivia topic"></label></div>
   <div class="note">It's played by voice. Say "stop the game" to end it.</div>
   <div class="seg">${g.map(([v, l]) => `<button class="pill on" data-game="${v}" onclick="gameStart('${v}')">${l}</button>`).join("")}<button class="pill" onclick="closeModal()">Cancel</button></div>`);
}
async function gameStart(g) {
  const r = await api("/api/game", { method: "POST", body: { game: g, topic: ($("#gtopic") || {}).value || "" } });
  if (r.ok) closeModal(); else toast("Could not start: " + ((r.data && r.data.detail) || r.status));
}

/* ---------- Settings, Routines ---------- */
function timeIn(k) { return `<input type="time" data-k="${k}" data-fk="${k}" aria-label="${esc(k)}" value="${esc(sv(k))}" onchange="setS({${k}:this.value})">`; }
function pageRoutines() {
  const ms = S.musicStatus || {};
  return `<h3>Night hours</h3>`
    + row("Sleep at night", "night_sleep", tog("night_sleep"))
    + row("From", "night_start", timeIn("night_start"))
    + row("Until", "night_end", timeIn("night_end"))
    + `<h3 style="margin-top:20px">Saying hello</h3>`
    + row("Greet people who come near", "proximity_greet", tog("proximity_greet"), " Uses the distance sensors on the base.")
    + row("Wait between greetings", "greet_cooldown_min", rng("greet_cooldown_min", 1, 120, 1, "int"), " Minutes.")
    + `<h3 style="margin-top:20px">Study buddy</h3>`
    + row("Focus block", "study_focus_min", rng("study_focus_min", 5, 120, 5, "int"), " Minutes.")
    + row("Break", "study_break_min", rng("study_break_min", 1, 30, 1, "int"), " Minutes.")
    + row("Quiz me on breaks", "study_quiz", tog("study_quiz"))
    + `<div class="note">Start one from Home, or say "let's study physics for 30 minutes". During focus it answers study questions properly and nags you about anything else. Games wait for the break.</div>`
    + `<h3 style="margin-top:20px">Music</h3>`
    + row("Bob along to music", "music_react", tog("music_react"))
    + row("Music sensitivity", "music_sensitivity", rng("music_sensitivity", 0, 1, 0.05, "pct"))
    + `<div class="note" id="musicstat">Status: ${esc(ms.message || "off")}.${S.extras.music && S.extras.music.on ? " Music playing now." : ""} Only the beat and loudness of what this laptop plays are used; nothing is recorded.</div>`
    + `<h3 style="margin-top:20px">Timers</h3><div class="note">Say "set a timer for 10 minutes", "remind me at 5 pm to start physics", "what timers do I have" or "cancel the pasta timer". Running ones show on Home. They survive a restart, and ring during night hours too.</div>`;
}

/* ---------- Settings, Health (device health page) ---------- */
function healthVal(v, unit, digits) { return v == null ? "<span class='nd'>no data</span>" : (digits != null ? (+v).toFixed(digits) : v) + (unit || ""); }
function healthHtml() {
  const d = S.device || {}, up = S.connected, sim = d.simulated || d.kind === "sim";
  const pct = d.battery_pct, mv = d.battery_mv, rpm = d.rpm, tgt = d.target_rpm || 1500;
  const rpmOff = rpm != null && rpm > 0 ? Math.round((rpm - tgt) / tgt * 1000) / 10 : null;
  const tile = (label, val, cls, sub) => `<div class="htile ${cls || ""}"><small>${label}</small><b>${val}</b>${sub ? `<span>${sub}</span>` : ""}</div>`;
  const batCls = pct == null ? "" : pct < 20 ? "bad" : pct < 40 ? "warn" : "ok";
  const rpmCls = rpm == null ? "" : rpm === 0 ? "" : Math.abs(rpmOff) > 2 ? "bad" : Math.abs(rpmOff) > 0.5 ? "warn" : "ok";
  const errs = (d.checksum_errors || 0) + (d.tx_dropped || 0);
  return (sim ? `<div class="warn">Simulator: these numbers are made up so you can see the page. Switch Device to Serial for the real ones.</div>` : "")
    + `<div class="htiles">`
    + tile("Link", up ? "connected" : "disconnected", up ? "ok" : "bad", d.kind === "serial" ? esc(d.port || "no port") : "simulator")
    + tile("Ping", healthVal(d.ping_ms, " ms"), d.ping_ms == null ? "" : d.ping_ms > 50 ? "warn" : "ok", "laptop to base")
    + tile("Rotor", d.rotor_ok == null ? "<span class='nd'>no data</span>" : d.rotor_ok ? "ok" : "fault", d.rotor_ok == null ? "" : d.rotor_ok ? "ok" : "bad",
      d.rotor_seen_s != null ? "heard " + d.rotor_seen_s + " s ago" : "radio link to the spinning part")
    + tile("Battery", pct == null ? "<span class='nd'>no data</span>" : pct + "%", batCls, mv != null ? (mv / 1000).toFixed(2) + " V" : "1S LiPo on the rotor")
    + tile("Charging", d.charging == null ? "<span class='nd'>no data</span>" : d.charging ? "yes" : "no", "", d.power_good == null ? "coil power" : d.power_good ? "coil power good" : "no coil power")
    + tile("Spin", rpm == null ? "<span class='nd'>no data</span>" : rpm + " rpm", rpmCls, rpm ? (rpmOff >= 0 ? "+" : "") + rpmOff + "% vs " + tgt : "target " + tgt + " rpm")
    + tile("Brightness", healthVal(d.brightness_ack != null ? d.brightness_ack : d.brightness_cap), "", "cap the device is using")
    + tile("Errors", errs, errs ? "warn" : "ok", (d.checksum_errors || 0) + " checksum, " + (d.tx_dropped || 0) + " dropped")
    + `</div>`
    + (d.last_error && !up ? `<div class="note">Last error: ${esc(d.last_error)}</div>` : "")
    + `<div class="note">The face only holds still if the spin stays within about 0.25% from one turn to the next. Battery % is a rough guess from the voltage. Updates every second.</div>`;
}
function pageHealth() { return `<div id="health">${healthHtml()}</div>`; }
function paintHealth() { const h = $("#health"); if (h) h.innerHTML = healthHtml(); }

/* ---------- Voice & wake: custom wake word helper (added under the wake word rows) ---------- */
function wakeHelpHtml() {
  const ph = (S.wake && S.wake.phrase) || "hey jarvis";
  return `<div class="set"><div>Custom wake word<small>Now: "${esc(ph)}". To use "hey hullabaloo", train a model (about an hour, free, in Google Colab, see docs/WAKE_WORD.md), name it hey_hullabaloo.onnx and drop it in the wake word folder. Then switch the mic off and back to wake word.</small></div>
    <button class="pill" id="wakefolder" onclick="openWakeFolder()">Open folder</button></div>`;
}
async function openWakeFolder() { const r = await api("/api/wakeword/folder", { method: "POST" }); if (r.ok && r.data) toast("Folder: " + r.data.folder, 8000); }
