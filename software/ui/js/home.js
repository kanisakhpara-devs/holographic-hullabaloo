"use strict";
/* Home page: usage heatmap, face preview, mic switch, live captions (your words + its words, karaoke), talk row.
   The right column is a flex column, so text sizes follow the Interface size setting and everything reflows. */

/* ---------- usage: labelled heatmap, one square per day = minutes talked ---------- */
const RAMP = ["#d4dccf", "#bfe3cb", "#86cf9f", "#45b26f", "#16884a"];
function usageCard() {
  const d = (S.usage && S.usage.daily) || [];
  const mx = Math.max(1, ...d.map(x => x.minutes));
  const total = d.reduce((a, x) => a + x.minutes, 0), turns = d.reduce((a, x) => a + x.turns, 0);
  const lvl = m => m <= 0 ? 0 : Math.min(4, 1 + Math.floor(m / mx * 3.999));
  /* weeks as columns, Mon..Sun as rows, like a contribution graph */
  const cols = [];
  let col = new Array(7).fill(null);
  d.forEach((x, i) => {
    const wd = (new Date(x.date + "T12:00:00").getDay() + 6) % 7;      /* Mon=0 */
    if (i && wd === 0) { cols.push(col); col = new Array(7).fill(null); }
    col[wd] = x;
  });
  if (d.length) cols.push(col);
  const fmtDay = x => new Date(x.date + "T12:00:00").toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  const grid = cols.map(c => `<div class="hcol">${c.map(x => x
    ? `<b class="l${lvl(x.minutes)}" title="${esc(fmtDay(x))}: ${x.minutes} min, ${x.turns} turns"></b>`
    : `<b class="none"></b>`).join("")}</div>`).join("");
  const months = cols.map(c => { const x = c.find(Boolean); return x ? new Date(x.date + "T12:00:00").getDate() : ""; });
  if (d.length <= 14) {
    return `<div class="ucard" id="usage"><div class="lbl">Minutes talked</div>
    <select id="since" aria-label="Usage period" onchange="S.days=+this.value;loadUsage()">${[[7, "7 days"], [30, "30 days"], [90, "90 days"]].map(([v, l]) => `<option value="${v}" ${S.days == v ? "selected" : ""}>Last ${l}</option>`).join("")}</select>
    <div id="heatrow">${d.map(x => `<div class="hday"><b class="l${lvl(x.minutes)}" title="${esc(fmtDay(x))}: ${x.minutes} min, ${x.turns} turns">${x.minutes >= 1 ? Math.round(x.minutes) : (x.minutes > 0 ? "<1" : "")}</b><span>${esc(x.weekday)}</span></div>`).join("")}</div>
    <div class="hfoot"><span>${Math.round(total)} min, ${turns} turns</span>
      <span class="legend">less ${RAMP.map((c, i) => `<b class="l${i}"></b>`).join("")} more</span></div></div>`;
  }
  return `<div class="ucard" id="usage"><div class="lbl">Minutes talked</div>
  <select id="since" aria-label="Usage period" onchange="S.days=+this.value;loadUsage()">${[[7, "7 days"], [30, "30 days"], [90, "90 days"]].map(([v, l]) => `<option value="${v}" ${S.days == v ? "selected" : ""}>Last ${l}</option>`).join("")}</select>
  <div id="heat2">
    <div class="hdays">${["Mon", "", "Wed", "", "Fri", "", "Sun"].map(x => `<span>${x}</span>`).join("")}</div>
    <div class="hgrid${cols.length <= 2 ? " big" : ""}"><div class="hdates">${months.map(m => `<span>${m}</span>`).join("")}</div><div class="hcols">${grid}</div></div>
  </div>
  <div class="hfoot"><span>${Math.round(total)} min, ${turns} turns</span>
    <span class="legend">less ${RAMP.map((c, i) => `<b class="l${i}"></b>`).join("")} more</span></div></div>`;
}
function renderUsageOnly() { const u = $("#drawer #usage"); if (u) u.outerHTML = usageCard(); }

function renderHome(L, P) {
  L.innerHTML = "";                                       /* usage moved to the More drawer */
  P.innerHTML = `<div id="head"><canvas id="face" width="560" height="768" aria-label="Hullabaloo's face"></canvas><div id="zzz"><span>z</span><span>z</span><span>z</span></div></div>
   <div id="hcol">
    <div class="toprow">
     <div class="mic seg" id="mic" role="radiogroup" aria-label="Microphone">${[["off", "mic off"], ["hotkey", "hotkey"], ["wake", "hotkey + wake word"]].map(([v, l]) => `<button role="radio" data-m="${v}" onclick="setMic('${v}')">${l}</button>`).join("")}</div>
     <div id="lvl" aria-hidden="true"><i></i></div></div>
    <div id="hint"></div>
    <div id="acts" class="acts" aria-label="Timers, study and games"></div>
    <div id="cap" class="scroll" aria-live="polite" onscroll="capScrolled()"></div>
    <div id="boot"><div class="dots"><span></span><span></span><span></span></div><div class="bar"></div></div>
    <div class="row talkbar"><input id="tx" aria-label="Type to talk" placeholder="Type to talk" onkeydown="if(event.key==='Enter')sendText()">
     <button class="pill" id="sendbtn" onclick="sendText()">Send</button>
     <button class="pill talk" id="ptt" aria-label="Hold to talk">Hold to talk</button></div>
   </div>`;
  wirePTT();
  drawFace(); renderCaptions(true); paintState(); paintLevel(); paintMic(); if (window.paintActs) paintActs();
}

/* hold to talk: pointer or keyboard (Space/Enter) held */
function wirePTT() {
  const b = $("#ptt"); if (!b) return; let on = false;
  const down = () => { if (on) return; on = true; b.classList.add("on"); b.textContent = "Listening..."; send({ type: "ptt_down" }); };
  const up = () => { if (!on) return; on = false; b.classList.remove("on"); b.textContent = "Hold to talk"; send({ type: "ptt_up" }); };
  b.addEventListener("pointerdown", e => { e.preventDefault(); down(); });
  ["pointerup", "pointerleave", "pointercancel", "blur"].forEach(ev => b.addEventListener(ev, up));
  b.addEventListener("keydown", e => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); down(); } });
  b.addEventListener("keyup", e => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); up(); } });
}
function sendText() { const i = $("#tx"); if (!i || !i.value.trim()) return; send({ type: "text", text: i.value }); i.value = ""; }

/* ---------- face: drawn by face.js (pixel-art layers) ---------- */
function drawFace() {
  const c = $("#face"); if (!c || typeof Face === "undefined") return;
  Face.draw(c, { emotion: S.face, mouth: S.mouth, state: S.state, booting: S.booting });
  const h = $("#head"); if (h) h.classList.toggle("off", (S.state === "sleeping" && !(S.extras && S.extras.music && S.extras.music.on)) || S.state === "disconnected" || S.booting);
  if (window.paintLook) paintLook();
}
function drawHead() { drawFace(); }

function paintState() {
  paintChip();
  const pin = $("#pin"); if (!pin || S.page !== "home") return;
  pin.dataset.state = S.state; pin.classList.toggle("booting", !!S.booting);
  paintMic(); paintHint(); drawFace();
}

/* one quiet status line above the captions (the conversation itself stays visible) */
function paintHint() {
  const el = $("#hint"); if (!el) return;
  const m = S.settings.mic_mode || "hotkey", w = S.wake || {};
  const talk = m === "off" ? "The mic is off. Type below, or switch the mic on."
    : m === "wake" ? `Say "${esc(w.phrase || "hey jarvis")}", or hold Ctrl+Space.` : "Hold Ctrl+Space or Hold to talk.";
  let h = "";
  if (S.booting) h = esc(S.say || "Starting up, loading the voice models...");
  else if (S.state === "disconnected") h = `No device. Plug in the base, or use the simulator in Settings, Device. <button class="pill mini" onclick="send({type:'reconnect'})">Reconnect</button>`;
  else if (S.state === "sleeping") h = "Asleep. " + talk;
  else if (S.state === "waking") h = "Waking up...";
  else if (S.state === "thinking") h = `Thinking<span class="dots3"><i>.</i><i>.</i><i>.</i></span>`;
  else if (S.state === "listening") h = S.micOpen ? "Listening..." : talk;
  else if (S.state === "interrupted") h = "Interrupted.";
  if (m === "wake" && w.message && !w.ok) h += ` <span class="warnline">Wake word: ${esc(w.message)}</span>`;
  el.innerHTML = h;
}
function renderSay() { paintHint(); }

/* ---------- 3-way mic switch: off / hotkey only / wake word ---------- */
function setMic(m) { S.settings.mic_mode = m; send({ type: "settings", patch: { mic_mode: m } }); paintMic(); paintHint(); }
function paintMic() {
  const g = $("#mic"); if (!g) return;
  const m = S.settings.mic_mode || "hotkey";
  g.querySelectorAll("button").forEach(b => { const on = b.dataset.m === m; b.classList.toggle("on", on); b.setAttribute("aria-checked", on); });
  g.classList.toggle("live", !!S.micOpen);                       /* red dot only while the OS mic is actually open */
  const w = S.wake || {};
  g.title = m === "wake" ? ("Say " + (w.phrase || "hey jarvis") + " or hold Ctrl+Space. " + (w.message || "")) : (m === "hotkey" ? "Mic opens only while you hold Ctrl+Space or Hold to talk." : "Mic closed.");
  g.classList.toggle("warn", m === "wake" && !!w.message && !w.ok);
}

function paintLevel() {
  const i = document.querySelector("#lvl i"); const v = S.micOpen || S.wizard || S.page === "settings" ? Math.min(100, S.level * 300) : 0;
  if (i) i.style.width = v + "%";
  const b = document.querySelector("#slvl i"); if (b) b.style.width = Math.min(100, S.level * 300) + "%";
  const w = document.querySelector("#wlvl i"); if (w) w.style.width = Math.min(100, S.level * 300) + "%";
  const d = document.querySelector("#dlvl i"); if (d) d.style.width = Math.min(100, S.level * 300) + "%";
}

/* ======================= live captions =======================
   S.cap = [{role:"user", text, partial}, {role:"hulla", sents:[{words, times, dur, at, cut}], done}]
   Your words appear while you talk (rough, then the final Whisper text). Its words light up as they are
   spoken: spoken = dark, current = glow, upcoming = faded. The box scrolls and follows the current word,
   unless you scrolled up yourself in the last few seconds. */
S.cap = S.cap || [];
const CAP_MAX = 14;
let capUserScrollAt = 0, capAuto = false;
function capScrolled() { if (!capAuto) capUserScrollAt = performance.now(); }
function capPush(x) { S.cap.push(x); if (S.cap.length > CAP_MAX) S.cap.splice(0, S.cap.length - CAP_MAX); }
function lastCap(role) { const x = S.cap[S.cap.length - 1]; return x && x.role === role ? x : null; }

function capEvent(e) {
  if (e.type === "partial") {
    const u = lastCap("user");
    if (u && u.partial) u.text = e.text; else capPush({ role: "user", text: e.text, partial: true });
    return true;
  }
  if (e.type === "transcript" && e.role === "user") {
    const u = lastCap("user");
    if (u && u.partial) { u.text = e.text; u.partial = false; } else capPush({ role: "user", text: e.text });
    return true;
  }
  if (e.type === "say") {
    const words = String(e.text || "").split(/\s+/).filter(Boolean);
    const sent = { words, times: wordTimes(words, e), dur: e.duration || 0, at: performance.now() + (e.offset_ms || 0), cut: -1 };
    let h = lastCap("hulla");
    if (!h || h.done) { h = { role: "hulla", sents: [] }; capPush(h); }
    h.sents.forEach(s => { s.done = true; });
    h.sents.push(sent);
    return true;
  }
  if (e.type === "interrupted") {
    const h = lastCap("hulla");
    if (h) { const s = h.sents[h.sents.length - 1]; if (s && !s.done) s.cut = curWord(s); h.done = true; }
    return true;
  }
  if (e.type === "transcript" && e.role === "assistant") {
    const h = lastCap("hulla"); if (h) h.done = true;
    return false;                                  /* let the last sentence finish lighting up */
  }
  if (e.type === "state" && (e.state === "sleeping")) {
    const u = lastCap("user"); if (u && u.partial) S.cap.pop();
  }
  return false;
}
/* word start times (s): from Kokoro when the counts match, else spread by word length */
function wordTimes(words, e) {
  const wt = e.word_times;
  if (Array.isArray(wt) && wt.length === words.length) return wt;
  const dur = e.duration || 0, lens = words.map(w => w.replace(/[^\w']/g, "").length + 1), tot = lens.reduce((a, b) => a + b, 0) || 1;
  let t = 0; return lens.map(l => { const s = t; t += l / tot * dur; return s; });
}
function curWord(s) {
  if (s.done) return s.words.length;
  const t = (performance.now() - s.at) / 1000;
  if (t >= s.dur) return s.words.length;
  let i = -1; while (i + 1 < s.times.length && s.times[i + 1] <= t) i++;
  return Math.max(0, i);
}

function renderCaptions(full) {
  const box = $("#cap"); if (!box || S.page !== "home") return;
  if (full || box.childElementCount !== S.cap.length) {
    box.innerHTML = S.cap.length ? S.cap.map((x, i) => x.role === "user"
      ? `<div class="cu${x.partial ? " partial" : ""}" data-i="${i}"><small>you</small>${esc(x.text)}</div>`
      : `<div class="ch" data-i="${i}"><small>hullabaloo</small>${x.sents.map((s, j) => `<span class="sent" data-j="${j}">${s.words.map(w => `<span class="w">${esc(w)}</span>`).join(" ")}</span>`).join(" ")}</div>`).join("")
      : `<div class="capempty">What you say and what it says will show up here.</div>`;
  } else {
    S.cap.forEach((x, i) => {
      const el = box.children[i]; if (!el) return;
      if (x.role === "user") { el.lastChild.textContent = x.text; el.classList.toggle("partial", !!x.partial); return; }
      if (el.querySelectorAll(".sent").length !== x.sents.length) {
        el.innerHTML = `<small>hullabaloo</small>` + x.sents.map((s, j) => `<span class="sent" data-j="${j}">${s.words.map(w => `<span class="w">${esc(w)}</span>`).join(" ")}</span>`).join(" ");
      }
    });
  }
  paintWords();
}

/* runs every animation frame while something is being spoken */
function paintWords() {
  const box = $("#cap"); if (!box) return;
  let cur = null, active = false;
  S.cap.forEach((x, i) => {
    if (x.role !== "hulla") return;
    const el = box.children[i]; if (!el) return;
    const sents = el.querySelectorAll(".sent");
    x.sents.forEach((s, j) => {
      const spans = sents[j] ? sents[j].children : [];
      const k = s.cut >= 0 ? s.cut : curWord(s);
      if (k < s.words.length && s.cut < 0) active = true;
      for (let n = 0; n < spans.length; n++) {
        const c = n < k ? "w said" : (n === k && s.cut < 0 ? "w now" : (s.cut >= 0 ? "w cut" : "w"));
        if (spans[n].className !== c) spans[n].className = c;
        if (n === k && s.cut < 0) cur = spans[n];
      }
    });
  });
  follow(box, cur);
  if (active) { if (!paintWords.raf) paintWords.raf = requestAnimationFrame(() => { paintWords.raf = 0; paintWords(); }); }
}
function follow(box, cur) {
  if (performance.now() - capUserScrollAt < 4000) return;      /* you scrolled up: leave it */
  capAuto = true;
  if (cur) {
    const r = cur.offsetTop - box.offsetTop, h = box.clientHeight;
    if (r < box.scrollTop + h * 0.2 || r > box.scrollTop + h * 0.7) box.scrollTop = Math.max(0, r - h * 0.4);
  } else if (box.scrollHeight - box.scrollTop - box.clientHeight > 2) {
    box.scrollTop = box.scrollHeight;
  }
  setTimeout(() => { capAuto = false; }, 50);
}
function stopSubs() { }
function startSubs() { paintWords(); }

/* ---------- Shut down: unload the AI model from the GPU, close the old app, stop the dev server ---------- */
async function shutDown() {
  if (!(await ask("Shut down Hullabaloo? This stops the app, unloads the AI model from the GPU, and closes the old installed app if it is running. To start again, double-click DEV.", "Shut down", true))) return;
  const r = await api("/api/shutdown", { method: "POST", body: { confirm: true } });
  S.off = true; try { ws && ws.close(); } catch (e) { }
  const d = (r.ok && r.data) || {};
  const what = [d.unloaded && d.unloaded.length ? "unloaded " + d.unloaded.join(", ") + " from the GPU" : "",
                d.killed && d.killed.length ? "closed the old app" : ""].filter(Boolean).join(", ");
  document.body.insertAdjacentHTML("beforeend", `<div id="offscreen"><div><h2>Hullabaloo is off.</h2>
    <p>${r.ok ? "Stopped" + (what ? ": " + esc(what) : "") + "." : "The backend did not answer, it may already be off."}</p>
    <p>To start again, double-click <b>DEV</b> in the hullabaloo folder, then reload this page.</p></div></div>`);
}
