"""AltVerse Browser - native desktop app.

One process, one window: an embedded WebView2 window with a splash while the
Lemonade server and model come up, then the browser UI. No Chrome/Edge/Firefox
is ever launched, and there is no console window.

Closing the window quits everything.
"""

import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
HOST, PORT = "127.0.0.1", 5057
BASE = f"http://{HOST}:{PORT}"
TITLE = "AltVerse Browser"
CREATE_NO_WINDOW = 0x08000000
LOG = os.path.join(os.environ.get("TEMP", HERE), "altverse-desktop.log")


def _log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%.1f %s\n" % (time.time(), msg))
    except Exception:  # noqa: BLE001 - logging never fatal
        pass

SPLASH = """<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
body{margin:0;height:100vh;display:flex;flex-direction:column;align-items:center;
justify-content:center;background:#f2f5f3;color:#15141a;
font-family:system-ui,Segoe UI,Arial,sans-serif}
h1{font-size:44px;margin:0 0 6px;font-weight:800}p{color:#5b5b66;margin:0 0 26px}
.spin{width:34px;height:34px;border:4px solid #dbe6df;border-top-color:#1a7f37;
border-radius:50%;animation:s 1s linear infinite}@keyframes s{to{transform:rotate(360deg)}}
#msg{margin-top:14px;font-size:13px;color:#6d6d80}
</style></head><body>
<h1><span style="color:#1a7f37">A</span>ltVerse</h1>
<p>Every timeline ever. None of it true.</p>
<div class="spin"></div><div id="msg">Starting up&hellip;</div>
</body></html>"""


def _hidden_popen(args, **kw):
    return subprocess.Popen(args, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=CREATE_NO_WINDOW, **kw)


def _http_ok(url, timeout=3):
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except Exception:  # noqa: BLE001 - not up yet
        return False


def _port_ok(timeout=3):
    """Is the Flask UI up?"""
    return _http_ok(f"{BASE}/api/models", timeout)


def _lemonade_ok(timeout=3):
    """Is the Lemonade server up (its own port, not ours)?"""
    return _http_ok("http://127.0.0.1:13305/api/version", timeout)


def _lemonade_cli():
    for p in (r"%LOCALAPPDATA%\lemonade_server\bin\lemonade.exe",
              r"%ProgramFiles%\lemonade_server\bin\lemonade.exe"):
        path = os.path.expandvars(p)
        if os.path.exists(path):
            return path
    return "lemonade"


def _lemonade_server_exe():
    for p in (r"%LOCALAPPDATA%\lemonade_server\bin\LemonadeServer.exe",
              r"%ProgramFiles%\lemonade_server\bin\LemonadeServer.exe"):
        path = os.path.expandvars(p)
        if os.path.exists(path):
            return path
    return None


def ensure_deps():
    """Make sure flask/requests/pywebview exist (silent, one-time)."""
    need = []
    for mod, pkg in (("flask", "flask"), ("requests", "requests"),
                     ("webview", "pywebview"), ("waitress", "waitress")):
        try:
            __import__(mod)
        except ImportError:
            need.append(pkg)
    if not need:
        return
    try:
        _hidden_popen([sys.executable, "-m", "pip", "install", "--quiet",
                       "--disable-pip-version-check", *need]).wait(timeout=600)
    except Exception:  # noqa: BLE001 - best effort, import will re-report
        pass


def ensure_lemonade():
    if _lemonade_ok():
        return True
    srv = _lemonade_server_exe()
    if not srv:
        return False
    _hidden_popen([srv, "--silent"])
    for _ in range(20):
        time.sleep(3)
        if _lemonade_ok():
            return True
    return False


def model_name():
    try:
        with open(os.path.join(HERE, "model.txt"), encoding="utf-8") as f:
            first = f.readline().strip()
            if first:
                return first
    except OSError:
        pass
    return os.environ.get("ALTVERSE_MODEL", "Qwen3-4B-Instruct-2507-GGUF")


def loaded_models():
    """Names of models currently resident in the Lemonade server."""
    try:
        h = json.load(urllib.request.urlopen(
            "http://127.0.0.1:13305/api/v1/health", timeout=10))
        return [m.get("model_name") for m in h.get("all_models_loaded", [])]
    except Exception:  # noqa: BLE001 - fall through to the CLI
        pass
    try:
        out = subprocess.run([_lemonade_cli(), "status", "--json"],
                             capture_output=True, text=True, timeout=30,
                             creationflags=CREATE_NO_WINDOW)
        return [m.get("model_name") for m in
                json.loads(out.stdout).get("models", [])]
    except Exception:  # noqa: BLE001 - treat as "nothing loaded"
        return []


def ensure_model(update_msg):
    want = model_name()
    if want in loaded_models():
        return
    update_msg(f"Loading {want} (first run can take a minute)...")
    subprocess.run([_lemonade_cli(), "load", want],
                   capture_output=True, text=True, timeout=1800,
                   creationflags=CREATE_NO_WINDOW)


def _set_icon():
    """Give the native window the AltVerse icon (titlebar + taskbar + alt-tab)."""
    if os.name != "nt":
        return
    try:
        ico = os.path.join(HERE, "icon.ico")
        if not os.path.exists(ico):
            _log("icon: icon.ico missing")
            return
        u32 = ctypes.windll.user32
        IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
        WM_SETICON, ICON_SMALL, ICON_BIG = 0x0080, 0, 1

        hwnd = 0
        for _ in range(24):  # window may not exist the instant we start
            hwnd = u32.FindWindowW(None, TITLE)
            if hwnd:
                break
            time.sleep(0.5)
        if not hwnd:
            _log("icon: window handle not found")
            return

        for size in (16, 32, 48, 256):
            h = u32.LoadImageW(0, ico, IMAGE_ICON, size, size, LR_LOADFROMFILE)
            if h:
                u32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, h)
                u32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, h)
        _log("icon: applied to hwnd %s" % hwnd)
    except Exception as e:  # noqa: BLE001 - icon is cosmetic, never fatal
        _log("icon error: " + repr(e))


def ensure_shortcut():
    """Keep a desktop shortcut that launches this app via pythonw (no console)."""
    try:
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        if not os.path.isdir(desktop):
            return
        lnk = os.path.join(desktop, "AltVerse Browser.lnk")
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pyw):
            pyw = sys.executable
        ps = (
            "$w=New-Object -ComObject WScript.Shell;"
            "$s=$w.CreateShortcut('%s');"
            "$s.TargetPath='%s';"
            "$s.Arguments='\"%s\"';"
            "$s.WorkingDirectory='%s';"
            "$s.IconLocation='%s';"
            "$s.Save()"
        ) % (lnk, pyw, os.path.join(HERE, "desktop.py"), HERE,
             os.path.join(HERE, "icon.ico"))
        _hidden_popen(["powershell", "-NoProfile", "-Command", ps]).wait(timeout=30)
    except Exception:  # noqa: BLE001 - cosmetic, never fatal
        pass


def _fix_stdio():
    """pythonw has no console: give stdio a sink so werkzeug's logging works."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
            except Exception:  # noqa: BLE001 - best effort
                pass


def _run_app(flask_app):
    try:
        from waitress import serve
        serve(flask_app, host=HOST, port=PORT, threads=8)
    except ImportError:
        try:
            flask_app.run(host=HOST, port=PORT, threaded=True, use_reloader=False)
        except Exception as e:  # noqa: BLE001 - otherwise it dies silently
            _log("flask error: " + repr(e))
    except Exception as e:  # noqa: BLE001 - otherwise it dies silently
        _log("waitress error: " + repr(e))


def main():
    _fix_stdio()
    ensure_deps()
    ensure_shortcut()
    import webview  # imported late so deps can install first

    window = webview.create_window(TITLE, html=SPLASH, width=1280, height=820,
                                   min_size=(900, 600), background_color="#f2f5f3")

    def boot():
        def msg(text):
            try:
                window.evaluate_js(
                    "document.getElementById('msg').textContent=" + json.dumps(text))
            except Exception:  # noqa: BLE001 - splash may be gone
                pass

        try:
            _log("boot start")
            msg("Checking the AI backend...")
            if not ensure_lemonade():
                _log("lemonade unreachable")
                msg("Lemonade Server is not reachable. Install it, then reopen.")
                return
            _log("lemonade ok; loaded=" + repr(loaded_models()))
            ensure_model(msg)
            _log("model ok")
            msg("Opening your browser...")

            from app import app
            _log("imported app")
            threading.Thread(target=_run_app, args=(app,),
                             daemon=True).start()
            for _ in range(60):
                time.sleep(0.5)
                if _port_ok():
                    break
            _log("flask up; loading url")
            window.load_url(BASE)
            _log("url loaded")
        except Exception as e:  # noqa: BLE001 - surface, don't die silently
            _log("boot error: " + repr(e))
            msg("Startup error: " + str(e)[:180])

    def after_start():
        _set_icon()
        boot()

    webview.start(after_start)  # blocks until the window is closed


if __name__ == "__main__":
    main()
