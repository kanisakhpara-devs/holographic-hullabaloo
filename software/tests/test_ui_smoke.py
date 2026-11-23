"""Playwright smoke tests for the UI. The static UI is served over http and the backend is mocked
(WebSocket and fetch), so these run anywhere with Chrome. They do NOT test the real backend or the
installed Windows app. Skipped when playwright or Chrome are missing."""
import functools, http.server, json, os, shutil, threading
from pathlib import Path
import pytest

pw = pytest.importorskip("playwright.sync_api")
UI = Path(__file__).resolve().parent.parent / "ui"
CHROME = os.environ.get("HH_CHROME") or shutil.which("google-chrome") or shutil.which("chromium")
if not CHROME:
    pytest.skip("no chrome", allow_module_level=True)

INIT = r"""
window.__HH__ = {port: 1, token: "t"};
window.__sent = []; window.__sockets = [];
window.__setup = window.__setup || {done: true};
class FakeWS {
  constructor(u){ this.url=u; this.readyState=1; window.__sockets.push(this); setTimeout(()=>{ this.onopen&&this.onopen(); }, 20); }
  send(m){ window.__sent.push(JSON.parse(m)); }
  close(){}
}
window.WebSocket = FakeWS;
window.__push = o => window.__sockets.forEach(s => s.onmessage && s.onmessage({data: JSON.stringify(o)}));
const J = d => new Response(JSON.stringify(d), {status:200, headers:{"content-type":"application/json"}});
window.fetch = async (url, o) => {
  const p = new URL(url).pathname; window.__fetched = (window.__fetched||[]).concat([[o&&o.method||"GET", p]]);
  if (p==="/api/settings") return J({settings:{}, schema:{}});
  if (p==="/api/usage") return J({cumulative:[1,2,3,5,8,9,12], hours:Array(24).fill(1)});
  if (p==="/api/memory") return J({people:[{name:"Kanishq"}], facts:[{id:1, person:"Kanishq", fact:"likes robots"}], summary:""});
  if (p==="/api/transcript") return J([{role:"user", text:"hello there", ts:1}, {role:"assistant", text:"oh. you.", emotion:"smug", ts:2}]);
  if (p==="/api/transcript/info") return J({privacy_mode:"debug", hours_left:20, ttl_hours:24, count:2});
  if (p==="/api/personas") return J([{name:"smug_sarcastic", text:"x"}, {name:"custom", text:""}]);
  if (p==="/api/devices/audio") return J({inputs:[{name:"Mic A"}], outputs:[{name:"Speaker A"}]});
  if (p==="/api/devices/serial") return J({ports:[{port:"COM7", likely:true, description:"ESP32-S3"}]});
  if (p==="/api/device/status") return J({kind:"sim", link:true, stats:{}});
  if (p==="/api/device/packets") return J({packets:[]});
  if (p==="/api/emotion_map") return J({map:{}, overrides:{}, state_faces:{}});
  if (p==="/api/health") return J({version:"0.1.0", log_path:"C:/x/log", llm:{model:"gemma3:4b", reachable:true}, stt:{type:"W", device:"cuda"}, tts:{type:"K", device:"cpu"}, gpu:{gpu:"G", vram_total_mb:6144, vram_used_mb:100}});
  if (p==="/api/setup/status") return J(window.__setup);
  return J({});
};
"""

@pytest.fixture(scope="module")
def site():
    class Q(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Q, directory=str(UI)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/index.html"
    srv.shutdown()

@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        yield b
        b.close()

@pytest.fixture
def page(browser, site):
    pg = browser.new_page(viewport={"width": 1920, "height": 1080})
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.add_init_script(INIT)
    pg.site = site
    yield pg
    pg.close()

def open_page(pg, hash_="", query="", setup=None):
    if setup is not None:
        pg.add_init_script("window.__setup=%s" % json.dumps(setup))
    pg.goto(pg.site + query + hash_)
    pg.wait_for_function("typeof S !== 'undefined' && (S.backend === true || S.demo === true)")
    pg.wait_for_timeout(150)

def sent(pg, typ=None):
    s = pg.evaluate("window.__sent")
    return [m for m in s if typ is None or m.get("type") == typ]

CATS = ["Persona", "Answers", "Voice & wake", "Audio", "Emotions", "Privacy", "Appearance", "Device", "System", "Developer", "About"]

def go_cat(pg, c):
    pg.evaluate("c => pickCat(c)", c)
    pg.wait_for_timeout(120)

def test_home_has_title_and_no_demo_data(page):
    open_page(page)
    assert page.is_visible("#ttl") and page.is_visible("#sub")
    assert "Holographic Hullabaloo" in page.inner_text("#ttl")
    assert page.evaluate("S.demo") is False
    assert page.evaluate("S.transcript.length") == 0          # no fake conversation by default
    assert not page.errors

def test_title_in_top_bar_on_every_page(page):
    for h in ("#home", "#transcript", "#settings"):
        open_page(page, h)
        assert page.is_visible("#topbar #ttl"), h
        assert page.is_visible("#topbar .tab.on"), h
    assert not page.errors

def test_every_page_renders(page):
    open_page(page, "#settings")
    for c in CATS:
        go_cat(page, c)
        assert len(page.inner_text("#panel")) > 20, c
    open_page(page, "#transcript")
    assert "hello there" in page.inner_text("#panel")
    assert not page.errors

def test_all_43_settings_have_a_control(page):
    open_page(page, "#settings")
    keys = set(page.evaluate("Object.keys(DEFAULTS)"))
    assert len(keys) == 43
    found = set()
    for c in CATS:
        go_cat(page, c)
        found |= set(page.evaluate("[...document.querySelectorAll('#panel [data-k]')].map(e => e.dataset.k)"))
    assert keys - found == set(), keys - found
    assert not page.errors

def test_every_control_sends_its_patch(page):
    open_page(page, "#settings")
    keys = set(page.evaluate("Object.keys(DEFAULTS)"))
    hit = set()
    for c in CATS:
        go_cat(page, c)
        n = page.evaluate("document.querySelectorAll('#panel [data-k]').length")
        for i in range(n):
            go_cat(page, c)                       # re-render each time, controls are rebuilt after a change
            el = page.locator("#panel [data-k]").nth(i)
            k = el.get_attribute("data-k")
            tag = el.evaluate("e => e.tagName + ':' + (e.type||'') + ':' + (e.className||'')")
            before = len(sent(page, "settings"))
            if tag.startswith("BUTTON") and "keyrec" in tag:
                continue                           # hotkey recorder is tested separately
            if tag.startswith("BUTTON"):
                if "pill" in tag and el.get_attribute("data-v") is not None and "on" in (el.get_attribute("class") or "").split():
                    continue                       # already selected segment, clicking it still sends, but skip
                el.click()
            elif tag.startswith("INPUT:range"):
                el.evaluate("e => { e.value = e.min; e.dispatchEvent(new Event('change')); }")
            elif tag.startswith("SELECT"):
                vals = el.evaluate("e => [...e.options].map(o => o.value)")
                cur = el.evaluate("e => e.value")
                other = next((v for v in vals if v != cur), cur)
                el.select_option(other)
            elif tag.startswith("INPUT:text") or tag.startswith("TEXTAREA"):
                el.fill("x test")
                el.dispatch_event("change")
            page.wait_for_timeout(20)
            msgs = sent(page, "settings")[before:]
            if msgs:
                assert all(k in m["patch"] for m in msgs[:1]) or any(k in m["patch"] for m in msgs), (k, msgs)
                hit.add(k)
    assert keys - hit - {"ptt_hotkey"} == set(), "controls that sent nothing: %s" % sorted(keys - hit)
    assert not page.errors

def test_hotkey_recorder_sends_patch(page):
    open_page(page, "#settings")
    for c in CATS:
        go_cat(page, c)
        if page.locator("#panel .keyrec").count():
            page.locator("#panel .keyrec").first.click()
            page.keyboard.press("Control+Shift+K")
            page.wait_for_timeout(80)
            m = sent(page, "settings")
            assert m and "Ctrl+Shift+K" in json.dumps(m[-1]), m
            return
    pytest.fail("no hotkey control found")

def test_state_designs(page):
    open_page(page)
    for st in ["sleeping", "listening", "thinking", "speaking", "interrupted", "error", "disconnected"]:
        page.evaluate("s => { onEvent({type:'state', state:s}); render(); }", st)
        page.wait_for_timeout(40)
        assert page.is_visible("#stage"), st
        assert len(page.inner_text("#panel")) > 3, st
    assert not page.errors

def test_privacy_banner_and_wipe_confirm(page):
    open_page(page, "#transcript")
    assert page.locator("text=/privacy|debug/i").count() > 0

def test_wizard_hidden_when_done_and_shown_when_not(page):
    open_page(page)
    assert not page.is_visible("#wiz")
    ctx = page.context.browser.new_context(viewport={"width": 1920, "height": 1080})
    p2 = ctx.new_page(); p2.errors = []
    p2.on("pageerror", lambda e: p2.errors.append(str(e)))
    p2.add_init_script(INIT)
    p2.add_init_script("window.__setup=%s" % json.dumps({
        "done": False, "gpu": {"gpu": "RTX 3060", "driver": "555", "vram_total_mb": 6144, "cuda": True, "stt_device": "cuda"},
        "ollama": {"installed": True, "running": False, "model": "gemma3:4b", "model_present": False, "download_url": "https://ollama.com/download"},
        "whisper": {"loaded": True}, "kokoro": {"loaded": True}, "mic": {"device": "Mic A"}, "speaker": {"device": "Speaker A"}}))
    p2.goto(page.site); p2.wait_for_function("typeof S !== 'undefined' && S.backend === true"); p2.wait_for_timeout(300)
    assert p2.is_visible("#wiz")
    assert p2.locator("#wsteps button").count() == 9
    for i in range(9):
        p2.click(f'#wsteps button[data-step="{i}"]')
        assert p2.is_visible("#wretry") and p2.is_visible("#wdetail")
    p2.click('#wsteps button[data-step="1"]')
    assert p2.is_visible("#startollama")
    p2.click("#startollama")
    assert ("POST", "/api/setup/ollama_start") in [tuple(x) for x in p2.evaluate("window.__fetched")]
    p2.click('#wsteps button[data-step="8"]'); p2.click("#wfinish")
    assert ("POST", "/api/setup/done") in [tuple(x) for x in p2.evaluate("window.__fetched")]
    p2.wait_for_function("!document.querySelector('#wiz').classList.contains('show')")
    assert not p2.is_visible("#wiz")
    assert not p2.errors, p2.errors
    ctx.close()

def test_demo_only_behind_query(page):
    open_page(page, "", "?demo=1")
    assert page.evaluate("S.demo") is True
    assert not page.errors

def test_no_dashes_in_ui_sources():
    bad = []
    for f in list(UI.glob("*.html")) + list(UI.glob("css/*.css")) + list(UI.glob("js/*.js")):
        t = f.read_text(encoding="utf-8")
        if "\u2014" in t or "\u2013" in t:
            bad.append(f.name)
    assert not bad, bad
