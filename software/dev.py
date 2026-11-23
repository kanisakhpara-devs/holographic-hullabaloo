"""Browser dev mode for Holographic Hullabaloo.

    .venv\\Scripts\\python.exe software\\dev.py          (DEV.cmd does this)

- Runs the backend on http://localhost:5000 and serves the UI from software/ui.
- Python edits in software/companion restart the backend automatically (the page reconnects).
- UI edits (html/css/js) make the open page reload itself within a second.
- Opens Chrome on the page once the backend answers.
- Global push-to-talk: hold Ctrl+Space anywhere in Windows (polled, no keyboard hook, so typing never lags).
- Everything is also logged to dev_log.txt next to this folder.
Flags: --mock (fake models, no GPU), --no-browser, --no-hotkey
"""
import json, os, subprocess, sys, threading, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PORT = 5000
URL = "http://localhost:%d" % PORT          # what Chrome opens
API = "http://127.0.0.1:%d" % PORT          # what this script calls: "localhost" tries IPv6 (::1) first on Windows,
                                            # which the backend doesn't listen on, costing ~1 s per Ctrl+Space
LOG = os.path.join(ROOT, "dev_log.txt")


def say(msg):
    line = time.strftime("%H:%M:%S ") + "[dev] " + msg
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def port_busy():
    import socket
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def wait_up(timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            urllib.request.urlopen(API + "/index.html", timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def open_chrome():
    if not wait_up():
        say("backend did not answer within 3 minutes, see dev_log.txt")
        return
    say("backend is up: " + URL)
    for exe in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")):
        if os.path.exists(exe):
            subprocess.Popen([exe, URL])
            return
    import webbrowser
    webbrowser.open(URL)


def post_ptt(down):
    try:
        t0 = time.monotonic()
        req = urllib.request.Request(API + "/api/ptt", data=json.dumps({"down": down}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=2)
        ms = (time.monotonic() - t0) * 1000
        if ms > 150:
            say("push-to-talk %s took %d ms" % ("down" if down else "up", ms))
    except Exception as ex:
        say("push-to-talk call failed: %s" % ex)


def hotkey_thread():
    """Hold Ctrl+Space anywhere: ptt_down on press, ptt_up on release.
    Polls the key state every 30 ms (GetAsyncKeyState). No keyboard hook: a hook makes Windows wait on this
    Python process for EVERY key you type, which lagged typing by seconds while models were loading."""
    if sys.platform != "win32":
        say("global Ctrl+Space only works on Windows")
        return
    import ctypes
    get = ctypes.windll.user32.GetAsyncKeyState
    VK_CONTROL, VK_SPACE = 0x11, 0x20
    down = lambda vk: bool(get(vk) & 0x8000)
    talking = False
    say("global push-to-talk ready: hold Ctrl+Space")
    while True:
        both = down(VK_CONTROL) and down(VK_SPACE)
        if both and not talking:
            talking = True
            threading.Thread(target=post_ptt, args=(True,), daemon=True).start()
        elif talking and not both:
            talking = False
            threading.Thread(target=post_ptt, args=(False,), daemon=True).start()
        time.sleep(0.03)


def main():
    args = sys.argv[1:]
    os.chdir(HERE)
    if port_busy():
        say("port %d is already in use. Close the other Hullabaloo window (or the old app from the tray) and retry." % PORT)
        input("Press Enter to close.")
        return
    try:
        from watchfiles import run_process, PythonFilter
    except ImportError:
        say("watchfiles not installed: run INSTALL_DEV.cmd first")
        input("Press Enter to close.")
        return
    os.environ["HH_DEV_ROOT"], os.environ["HH_DEV_PID"] = ROOT, str(os.getpid())   # for the Shut down button
    flag = os.path.join(ROOT, "dev_stopped.flag")
    if os.path.exists(flag):
        os.remove(flag)
    cmd = [sys.executable, "-m", "companion.server", "--port", str(PORT), "--ui", os.path.join(HERE, "ui"),
           "--dev", "--dev-log", LOG] + (["--mock"] if "--mock" in args else [])
    if "--no-browser" not in args:
        threading.Thread(target=open_chrome, daemon=True).start()
    if "--no-hotkey" not in args:
        threading.Thread(target=hotkey_thread, daemon=True).start()
    say("starting backend (Python edits restart it automatically). Close this window to stop.")

    def changed(changes):
        say("python changed (%s), restarting backend" % ", ".join(sorted({os.path.basename(p) for _, p in changes})))

    run_process(os.path.join(HERE, "companion"), target=subprocess.list2cmdline(cmd), target_type="command",
                watch_filter=PythonFilter(), callback=changed, grace_period=0.5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        import traceback
        say("dev runner crashed:\n" + traceback.format_exc())
        raise
