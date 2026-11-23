"use strict";
/* ?demo=1 only. Fake backend for screenshots and design work. */
const w = ms => new Promise(r => setTimeout(r, ms));
function demoUsage() { const n = S.days; let t = 0; S.usage = { cumulative: Array.from({ length: n }, () => t += Math.round(Math.random() * 9)), hours: Array.from({ length: 24 }, (_, h) => h < 8 ? 0 : Math.round(Math.random() * 12)) }; }
window.demoApi = async function (path, opt) {
  const ok = data => ({ ok: true, status: 200, data });
  if (path.startsWith("/api/usage")) { demoUsage(); return ok(S.usage); }
  if (path === "/api/settings") return ok({ settings: S.settings, schema: {} });
  if (path === "/api/memory") return ok({ people: S.people.map(n => ({ name: n })), facts: S.facts.map((f, i) => ({ id: i, person: f[0], fact: f[1] })), summary: "" });
  if (path === "/api/transcript") return ok(S.transcript);
  if (path === "/api/transcript/info") return ok({ privacy_mode: "debug", hours_left: 23.5, ttl_hours: 24, count: S.transcript.length });
  if (path === "/api/personas") return ok(["smug_sarcastic", "grumpy_wizard", "hype_buddy"].map(n => ({ name: n, text: "demo" })));
  if (path === "/api/devices/audio") return ok({ inputs: [{ name: "Demo microphone" }], outputs: [{ name: "Demo speakers" }] });
  if (path === "/api/devices/serial") return ok({ ports: [] });
  if (path === "/api/emotion_map") { const map = {}; EMOS.forEach(e => map[e] = { speed: 1, voice: "am_michael", pause_ms: 180 }); const sf = {}; STATES.forEach(s => sf[s] = "neutral"); return ok({ map, overrides: {}, state_faces: sf }); }
  if (path === "/api/health") return ok({ version: "0.1.0-demo", log_path: "demo", llm: { model: "gemma3:4b", reachable: true }, stt: { type: "WhisperSTT", device: "cuda" }, tts: { type: "KokoroTTS", device: "cpu" }, gpu: { gpu: "Demo GPU", vram_total_mb: 6144, vram_used_mb: 3500 } });
  if (path === "/api/setup/status") return ok({ done: true });
  return ok({});
};
window.demoIn = o => { if (o.type === "settings") { Object.assign(S.settings, o.patch); render(); } };
window.startDemo = function () {
  S.demo = true; S.connected = true; S.booting = false; S.device = { kind: "sim" }; demoUsage();
  S.people = ["Kanishq"]; S.facts = [["Kanishq", "likes robots"]];
  S.transcript = [{ role: "user", text: "Hi, my name is Kanishq and I like robots" }, { role: "assistant", emotion: "smug", text: "Kanishq. Of course you do. Robots do what they are told." }]; render();
  const script = [["user", "Hey, are you awake?"], ["assistant", [["surprised", "Oh. You again."], ["smug", "I was having a lovely nap."]]], ["user", "Tell me a joke"], ["assistant", [["laughing", "Your posture."], ["smug", "I'll be here all week."]]]];
  let i = 0;
  const step = async () => {
    const [r, t] = script[i % script.length]; i++;
    if (r === "user") { onEvent({ type: "state", state: "listening" }); await w(1200); onEvent({ type: "transcript", role: "user", text: t }); onEvent({ type: "state", state: "thinking" }); onEvent({ type: "face", emotion: "suspicious" }); await w(900); }
    else {
      onEvent({ type: "state", state: "speaking" });
      for (const [e, tx] of t) { onEvent({ type: "face", emotion: e }); onEvent({ type: "say", text: tx, duration: tx.length / 14 }); for (let k = 0; k < tx.length / 2.2; k++) { onEvent({ type: "mouth", viseme: VIS[(k * 7 + 3) % 6 * (k % 3 ? 1 : 0)] }); await w(110); } onEvent({ type: "mouth", viseme: "closed" }); await w(250); }
      onEvent({ type: "transcript", role: "assistant", text: t.map(x => x[1]).join(" ") }); onEvent({ type: "state", state: "listening" }); onEvent({ type: "face", emotion: "neutral" }); await w(1500);
    }
    setTimeout(step, 200);
  };
  onEvent({ type: "state", state: "sleeping" }); setTimeout(step, 1500);
};
