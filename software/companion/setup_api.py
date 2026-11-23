"""First-run setup helpers (wizard). Nothing here runs unless the UI asks.

Honest scope: Ollama is detected, started and its model pulled with live progress. Installing Ollama is
NOT automated (the wizard shows the manual steps and a download button). The Whisper and Kokoro models are
fetched by their libraries when the backend starts, so the wizard reports whether they loaded; it cannot
show a byte progress bar for them.
"""
import json, os, shutil, subprocess, sys
import httpx

OLLAMA_DOWNLOAD_URL = "https://ollama.com/download/windows"
TRANSPORT = None          # tests put an httpx.MockTransport here


def ollama_exe():
    exe = shutil.which("ollama")
    if exe:
        return exe
    local = os.environ.get("LOCALAPPDATA")
    if local:
        p = os.path.join(local, "Programs", "Ollama", "ollama.exe")
        if os.path.exists(p):
            return p
    return None


def ollama_models(url: str):
    """(reachable, [model names])."""
    try:
        with httpx.Client(transport=TRANSPORT, timeout=3.0) as c:
            r = c.get(url.rstrip("/") + "/api/tags")
            r.raise_for_status()
            return True, [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:
        return False, []


def model_present(model: str, names) -> bool:
    base = model if ":" in model else model + ":latest"
    return model in names or base in names


def start_ollama():
    """Start `ollama serve` detached. Returns (ok, message)."""
    exe = ollama_exe()
    if not exe:
        return False, "Ollama is not installed"
    try:
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
        subprocess.Popen([exe, "serve"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True)
        return True, "starting"
    except OSError as ex:
        return False, str(ex)


async def pull_stream(url: str, model: str):
    """Yield progress dicts from Ollama's pull API, ending with {'done': True} or {'error': ...}."""
    try:
        async with httpx.AsyncClient(transport=TRANSPORT, timeout=None) as c:
            async with c.stream("POST", url.rstrip("/") + "/api/pull", json={"model": model, "stream": True}) as r:
                if r.status_code != 200:
                    yield {"error": f"Ollama answered {r.status_code}"}
                    return
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    if d.get("error"):
                        yield {"error": str(d["error"])}
                        return
                    total, done = d.get("total"), d.get("completed")
                    yield {"status": d.get("status", ""), "total": total, "completed": done,
                           "percent": round(100.0 * done / total, 1) if total and done is not None else None}
    except httpx.HTTPError as ex:
        yield {"error": "Ollama is not running" if isinstance(ex, httpx.ConnectError) else str(ex)}
        return
    yield {"done": True}
