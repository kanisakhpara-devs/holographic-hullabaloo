"use strict";
/* Transcript page: bubbles, search, copy, export, privacy banner, Remembered card with delete buttons. */
async function loadTranscriptPage() {
  S.search = "";
  const r = await api("/api/transcript");
  if (r.ok && Array.isArray(r.data)) S.transcript = r.data;
  const i = await api("/api/transcript/info");
  if (i.ok) S.tinfo = i.data;
  await loadMem();
}
function visibleMessages() {
  if (S.settings.privacy_mode === "faire") return [];
  const q = S.search.trim().toLowerCase();
  return S.transcript.filter(m => !q || m.text.toLowerCase().includes(q));
}
function chatHtml() {
  const faire = S.settings.privacy_mode === "faire", msgs = visibleMessages();
  if (!msgs.length) {
    return `<div class="empty">${faire ? "Transcripts are not kept in Faire mode." : (S.search ? "No matches." : "Nothing said yet.")}</div>`;
  }
  return msgs.map(m => `<div class="m ${m.role}"><small>${m.role === "user" ? "you" : "hullabaloo"}${m.emotion ? " · " + esc(m.emotion) : ""}</small>${esc(m.text)}</div>`).join("");
}
function bannerHtml() {
  if (S.settings.privacy_mode === "faire") return `<div id="banner" class="faire">Faire mode: transcripts are not kept. Only names and facts people told it are remembered.</div>`;
  const h = S.tinfo && S.tinfo.hours_left;
  return `<div id="banner">Debug mode: transcripts are saved on this computer and deleted after 24 hours${h != null ? " (oldest goes in " + h.toFixed(1) + " h)" : ""}.</div>`;
}
function refreshChat() {
  const c = $("#chat"); if (!c) return;
  const atEnd = c.scrollTop + c.clientHeight >= c.scrollHeight - 60;
  c.innerHTML = chatHtml(); if (atEnd) c.scrollTop = c.scrollHeight;
}
function renderTranscript(L, P) {
  const people = S.mem.people || [], facts = S.mem.facts || [];
  L.innerHTML = `<div class="card" id="usage"><div class="lbl">Remembered</div><div class="list" id="remembered">
   <h4>People</h4>${people.length ? "<ul>" + people.map(p => `<li class="rm"><span>${esc(p.name)}</span><button aria-label="Forget ${esc(p.name)}" data-del-person="${esc(p.name)}" onclick="delPerson(this.dataset.delPerson)">×</button></li>`).join("") + "</ul>" : '<div style="opacity:.5">nobody yet</div>'}
   <h4>Facts</h4>${facts.length ? "<ul>" + facts.map(f => `<li class="rm"><span>${esc(f.person)}: ${esc(f.fact)}</span><button aria-label="Forget this fact" data-del-fact="${f.id}" onclick="delFact(+this.dataset.delFact)">×</button></li>`).join("") + "</ul>" : '<div style="opacity:.5">nothing yet</div>'}</div>
   <div class="lbtns"><button class="pill sm" id="wipebtn" onclick="wipe()">Wipe transcripts</button>
   <button class="pill sm danger" id="forgetbtn" onclick="forgetAll()">Forget everything</button>
   <button class="pill sm" id="expmem" onclick="exportMemory()">Export memory</button></div></div>` + navBtns();
  P.innerHTML = `<div class="tcol"><div id="tbar"><input id="tsearch" type="search" aria-label="Search transcript" placeholder="Search" value="${esc(S.search)}" oninput="S.search=this.value;refreshChat()">
   <button class="pill sm" id="copybtn" onclick="copyTranscript()">Copy</button><button class="pill sm" id="exptxt" onclick="exportTranscript()">Export text</button></div>
   ${bannerHtml()}<div id="chat" class="scroll">${chatHtml()}</div></div>`;
  const c = $("#chat"); c.scrollTop = c.scrollHeight;
}
function transcriptText() {
  return visibleMessages().map(m => `${m.ts ? fmtTime(m.ts) + " " : ""}${m.role === "user" ? "You" : "Hullabaloo"}${m.emotion ? " [" + m.emotion + "]" : ""}: ${m.text}`).join("\n");
}
async function copyTranscript() {
  const t = transcriptText(); if (!t) { toast("Nothing to copy"); return; }
  try { await navigator.clipboard.writeText(t); toast("Copied " + visibleMessages().length + " messages"); } catch (e) { toast("Could not copy"); }
}
function exportTranscript() {
  const t = transcriptText(); if (!t) { toast("Nothing to export"); return; }
  download("hullabaloo_transcript.txt", new Blob([t + "\n"], { type: "text/plain" }));
}
async function wipe() {
  if (!(await ask("Delete every saved transcript now?", "Wipe", true))) return;
  S.transcript = [];
  await api("/api/transcript/wipe", { method: "POST" });
  const i = await api("/api/transcript/info"); if (i.ok) S.tinfo = i.data;
  refresh();
}
async function delPerson(name) { await api("/api/memory/person/" + encodeURIComponent(name), { method: "DELETE" }); loadMem(); }
async function delFact(id) { await api("/api/memory/fact/" + id, { method: "DELETE" }); loadMem(); }
async function forgetAll() {
  if (!(await ask("Forget every name and fact it knows? This cannot be undone.", "Forget everything", true))) return;
  await api("/api/memory/forget_all", { method: "POST", body: { confirm: true } });
  loadMem();
}
function exportMemory() { downloadApi("/api/memory/export", "hullabaloo_memory.json"); }
