import io, json, os, sys, zipfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import httpx
from fastapi.testclient import TestClient
from companion import setup_api
from companion.server import create_app
from companion.adapters.mock import MockSTT, MockLLM, MockTTS
from companion.device import SimDevice


def mk(tmp_path):
    return create_app(MockSTT(), MockLLM(), MockTTS(), SimDevice(), str(tmp_path / "s.db"), realtime=0.0, data_dir=str(tmp_path))


def test_prompt_endpoint(tmp_path):
    with TestClient(mk(tmp_path)) as c:
        r = c.get("/api/prompt").json()
        assert isinstance(r["prompt"], str) and len(r["prompt"]) > 50
        assert "options" in r


def test_setup_status_shape_and_done_flag(tmp_path, monkeypatch):
    def handler(req):
        return httpx.Response(200, json={"models": [{"name": "gemma3:4b"}]})
    monkeypatch.setattr(setup_api, "TRANSPORT", httpx.MockTransport(handler))
    with TestClient(mk(tmp_path)) as c:
        s = c.get("/api/setup/status").json()
        assert s["done"] is False
        assert s["ollama"]["running"] is True and s["ollama"]["model_present"] is True
        assert s["whisper"]["loaded"] is False and s["kokoro"]["loaded"] is False   # mocks, not the real models
        assert s["ollama"]["download_url"].startswith("https://")
        assert c.post("/api/setup/done").json() == {"ok": True}
        assert c.get("/api/setup/status").json()["done"] is True
        assert os.path.exists(tmp_path / "setup_done")
    with TestClient(mk(tmp_path)) as c2:                       # survives a restart
        assert c2.get("/api/setup/status").json()["done"] is True
        c2.post("/api/setup/reset")
        assert c2.get("/api/setup/status").json()["done"] is False
        assert not os.path.exists(tmp_path / "setup_done")


def test_setup_status_ollama_down(tmp_path, monkeypatch):
    def handler(req):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(setup_api, "TRANSPORT", httpx.MockTransport(handler))
    with TestClient(mk(tmp_path)) as c:
        s = c.get("/api/setup/status").json()
        assert s["ollama"]["running"] is False and s["ollama"]["model_present"] is False


def test_pull_streams_progress_then_done(tmp_path, monkeypatch):
    lines = [{"status": "pulling manifest"}, {"status": "pulling abc", "total": 200, "completed": 50},
             {"status": "pulling abc", "total": 200, "completed": 200}, {"status": "success"}]
    body = "\n".join(json.dumps(x) for x in lines) + "\n"
    monkeypatch.setattr(setup_api, "TRANSPORT", httpx.MockTransport(lambda req: httpx.Response(200, content=body.encode())))
    with TestClient(mk(tmp_path)) as c:
        r = c.post("/api/setup/pull")
        assert r.headers["content-type"].startswith("text/event-stream")
        ev = [json.loads(x[6:]) for x in r.text.split("\n\n") if x.startswith("data: ")]
        assert ev[1]["percent"] == 25.0 and ev[2]["percent"] == 100.0
        assert ev[-1] == {"done": True}


def test_pull_error_and_connect_error(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_api, "TRANSPORT", httpx.MockTransport(
        lambda req: httpx.Response(200, content=b'{"error": "disk full"}\n')))
    with TestClient(mk(tmp_path)) as c:
        ev = [json.loads(x[6:]) for x in c.post("/api/setup/pull").text.split("\n\n") if x.startswith("data: ")]
        assert ev == [{"error": "disk full"}]

    def boom(req):
        raise httpx.ConnectError("no")
    monkeypatch.setattr(setup_api, "TRANSPORT", httpx.MockTransport(boom))
    with TestClient(mk(tmp_path)) as c:
        ev = [json.loads(x[6:]) for x in c.post("/api/setup/pull").text.split("\n\n") if x.startswith("data: ")]
        assert ev == [{"error": "Ollama is not running"}]


def test_ollama_start_without_install(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_api, "ollama_exe", lambda: None)
    with TestClient(mk(tmp_path)) as c:
        r = c.post("/api/setup/ollama_start").json()
        assert r["ok"] is False


def test_model_present_matching():
    assert setup_api.model_present("gemma3:4b", ["gemma3:4b"])
    assert setup_api.model_present("llama3", ["llama3:latest"])
    assert not setup_api.model_present("gemma3:4b", ["gemma3:1b"])


def test_diagnostics_zip_has_no_database_or_private_text(tmp_path):
    with TestClient(mk(tmp_path)) as c:
        with c.websocket_connect("/ws") as ws:
            ws.receive_text()
            ws.send_text(json.dumps({"type": "settings", "patch": {"custom_persona_text": "SECRET PERSONA", "blocklist": ["badword"]}}))
            for _ in range(20):
                if json.loads(ws.receive_text())["type"] == "settings":
                    break
        r = c.get("/api/diagnostics.zip")
        assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
        z = zipfile.ZipFile(io.BytesIO(r.content))
        names = z.namelist()
        assert {"settings.json", "health.json", "device.json"} <= set(names)
        assert not any(n.endswith(".db") for n in names)
        blob = b"".join(z.read(n) for n in names)
        assert b"SECRET PERSONA" not in blob and b"badword" not in blob


def test_calibrate_endpoint(tmp_path):
    with TestClient(mk(tmp_path)) as c:
        r = c.post("/api/audio/calibrate")
        assert r.status_code == 200 and "ok" in r.json()


def test_mic_test_message(tmp_path):
    with TestClient(mk(tmp_path)) as c:
        with c.websocket_connect("/ws") as ws:
            ws.receive_text()
            ws.send_text(json.dumps({"type": "mic_test", "on": True}))
            ws.send_text(json.dumps({"type": "mic_test", "on": False}))
            ws.send_text(json.dumps({"type": "text", "text": "hi"}))   # the socket still works after
            for _ in range(60):
                if json.loads(ws.receive_text()).get("type") == "transcript":
                    break
            else:
                raise AssertionError("no reply after mic_test toggling")


def test_health_has_version(tmp_path):
    with TestClient(mk(tmp_path)) as c:
        h = c.get("/api/health").json()
        assert h["version"] and "log_path" in h and "privacy_mode" in h


def test_engine_mic_test_reports_text_and_does_not_reply(tmp_path):
    import asyncio
    from companion.engine import Engine
    from companion.memory import Memory
    ev = []
    e = Engine(MockSTT(), MockLLM(), MockTTS(), SimDevice(), Memory(str(tmp_path / "t.db")), emit=ev.append, realtime=0.0)

    async def go():
        e.attach_loop()
        e.wake("test")
        e.mic_test = True
        out = await e.on_audio(b"testing one two three")
        return out
    assert asyncio.run(go()) is None
    mt = [x for x in ev if x["type"] == "mic_test"]
    assert mt and mt[0]["text"] and "stt_ms" in mt[0]
    assert not [x for x in ev if x["type"] == "transcript"]          # no turn happened, nothing stored
