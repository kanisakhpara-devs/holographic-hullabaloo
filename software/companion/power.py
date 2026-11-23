"""Shut down button (Home): stop everything Hullabaloo and free the GPU.

Order:
 1. Ask Ollama to unload every loaded model right now (keep_alive 0). Ollama itself keeps running
    (other apps may use it); the model's VRAM is freed.
 2. Kill the old installed app if it is still running (holographic-hullabaloo.exe and its hh-backend.exe).
 3. Stop the browser dev runner (dev.py, the black DEV window) and this backend. Whisper's VRAM is freed
    when this process exits.
"""
import json, logging, os, signal, subprocess, sys, threading, time, urllib.request

log = logging.getLogger("hullabaloo.power")
OLD_APP_EXES = ("holographic-hullabaloo.exe", "hh-backend.exe")


def unload_ollama(url="http://127.0.0.1:11434", timeout=3.0):
    """-> list of model names that were asked to unload."""
    done = []
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/ps", timeout=timeout) as r:
            models = [m.get("name") or m.get("model") for m in json.load(r).get("models", [])]
    except Exception as ex:
        log.info("ollama not reachable for unload: %s", ex)
        return done
    for m in models:
        if not m:
            continue
        try:
            req = urllib.request.Request(url.rstrip("/") + "/api/generate",
                                         data=json.dumps({"model": m, "keep_alive": 0}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=timeout).read()
            done.append(m)
        except Exception as ex:
            log.warning("could not unload %s: %s", m, ex)
    return done


def kill_old_app():
    """Windows only. -> list of exe names that were running and got killed."""
    if sys.platform != "win32":
        return []
    killed = []
    for exe in OLD_APP_EXES:
        try:
            r = subprocess.run(["taskkill", "/F", "/T", "/IM", exe], capture_output=True, text=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=10)
            if r.returncode == 0:
                killed.append(exe)
        except Exception as ex:
            log.warning("taskkill %s failed: %s", exe, ex)
    return killed


def stop_self_and_runner(delay=0.6):
    """After `delay` (so the HTTP reply gets out): tell DEV.cmd it was a clean stop, kill dev.py, exit."""
    def go():
        time.sleep(delay)
        root = os.environ.get("HH_DEV_ROOT")
        if root:
            try:
                open(os.path.join(root, "dev_stopped.flag"), "w").close()
            except OSError:
                pass
        pid = os.environ.get("HH_DEV_PID")
        if pid:
            try:
                os.kill(int(pid), signal.SIGTERM)          # TerminateProcess on Windows
            except Exception as ex:
                log.warning("could not stop the dev runner: %s", ex)
        logging.shutdown()
        os._exit(0)
    threading.Thread(target=go, daemon=True).start()


def shutdown_everything(ollama_url, kill=True):
    unloaded = unload_ollama(ollama_url)
    killed = kill_old_app() if kill else []
    log.info("shutdown: unloaded %s, killed %s", unloaded, killed)
    return {"unloaded": unloaded, "killed": killed}
