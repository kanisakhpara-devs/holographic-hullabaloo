import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient
from companion.server import create_app
from companion.adapters.mock import MockSTT, MockLLM, MockTTS
from companion.device import SimDevice


def test_ws_roundtrip(tmp_path):
    app = create_app(MockSTT(), MockLLM(), MockTTS(), SimDevice(), str(tmp_path / "s.db"), realtime=0.0)
    with TestClient(app) as c:
        with c.websocket_connect("/ws") as ws:
            snap = json.loads(ws.receive_text())
            assert snap["type"] == "snapshot" and snap["state"] == "sleeping"
            ws.send_text(json.dumps({"type": "text", "text": "my name is Kanishq and I love chess"}))
            seen = []
            for _ in range(60):
                ev = json.loads(ws.receive_text())
                seen.append(ev["type"])
                if ev["type"] == "transcript" and ev["role"] == "assistant":
                    break
            assert "say" in seen and "mouth" in seen and "memory" in seen
            ws.send_text(json.dumps({"type": "settings", "patch": {"content": "unfiltered"}}))
            while True:
                ev = json.loads(ws.receive_text())
                if ev["type"] == "settings":
                    assert ev["settings"]["content"] == "unfiltered"
                    break
        snap = c.get("/api/snapshot").json()
        assert snap["people"] == [] and any("loves chess" in f for _, f in snap["facts"])   # name waits for "yes"
