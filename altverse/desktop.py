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
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
LOG = os.path.join(os.environ.get("TEMP", HERE), "altverse-desktop.log")


def _log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%.1f %s\n" % (time.time(), msg))
    except Exception:  # noqa: BLE001 - logging never fatal
        pass


# Progress is published over a tiny local HTTP endpoint instead of by calling
# into the webview. window.evaluate_js() is marshalled onto the GUI thread and
# can block *while holding the GIL*, freezing the whole app - the splash then
# sits on "Starting up" forever while only its JS timer keeps counting.
STATUS_PORT = 5058
_status = {"msg": "Starting up\u2026"}


def _start_status_server():
    """Serve the current startup message to the splash page (best effort)."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps(_status).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    try:
        srv = ThreadingHTTPServer((HOST, STATUS_PORT), Handler)
    except Exception:  # noqa: BLE001 - port busy: splash just shows the timer
        return
    threading.Thread(target=srv.serve_forever, daemon=True).start()

SPLASH = """<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
body{margin:0;height:100vh;display:flex;flex-direction:column;align-items:center;
justify-content:center;background:#f2f5f3;color:#15141a;
font-family:system-ui,Segoe UI,Arial,sans-serif}
h1{font-size:44px;margin:0 0 6px;font-weight:800}p{color:#5b5b66;margin:0 0 26px}
.spin{width:34px;height:34px;border:4px solid #dbe6df;border-top-color:#1a7f37;
border-radius:50%;animation:s 1s linear infinite}@keyframes s{to{transform:rotate(360deg)}}
#msg{margin-top:14px;font-size:13px;color:#6d6d80}
#t{margin-top:6px;font-size:12px;color:#a8a8bb}
</style></head><body>
<h1><span style="color:#1a7f37">A</span>ltVerse</h1>
<p>Every timeline ever. None of it true.</p>
<div class="spin"></div><div id="msg">Starting up&hellip;</div><div id="t">0s</div>
<script>
var s=0;setInterval(function(){s++;document.getElementById('t').textContent=s+'s';},1000);
function altPoll(){
  fetch('http://127.0.0.1:5058/status',{cache:'no-store'})
    .then(function(r){return r.json()})
    .then(function(j){if(j&&j.msg)document.getElementById('msg').textContent=j.msg;})
    .catch(function(){});
}
altPoll();setInterval(altPoll,700);
</script>
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


def _port_open(port, timeout=1.0):
    """Is anything listening on the loopback port at all?"""
    import socket
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((HOST, port))
        return True
    except Exception:  # noqa: BLE001 - nothing there
        return False
    finally:
        try:
            s.close()
        except Exception:  # noqa: BLE001
            pass


def _port_ok(timeout=3):
    """Is the Flask UI up?"""
    return _http_ok(f"{BASE}/api/models", timeout)


def _lemonade_ok(timeout=5):
    """Is the Lemonade server up (its own port, not ours)?

    A busy Lemonade can take a few seconds to answer, and a false negative here
    made startup wait on a second server that was never needed.
    """
    return _http_ok("http://127.0.0.1:13305/api/version", timeout)


def _port_state():
    """'free' = nothing there, 'serving' = our app answers, 'stuck' = bound but dead."""
    import socket
    s = socket.socket()
    s.settimeout(1.5)
    try:
        s.connect((HOST, PORT))
    except Exception:  # noqa: BLE001 - nothing listening
        return "free"
    finally:
        try:
            s.close()
        except Exception:  # noqa: BLE001
            pass
    return "serving" if _port_ok() else "stuck"


def _lemonade_cli():
    for p in (r"%LOCALAPPDATA%\lemonade_server\bin\lemonade.exe",
              r"%ProgramFiles%\lemonade_server\bin\lemonade.exe"):
        path = os.path.expandvars(p)
        if os.path.exists(path):
            return path
    return "lemonade"


def _lemonade_server_exe():
    if os.name == "nt":
        cands = (r"%LOCALAPPDATA%\lemonade_server\bin\LemonadeServer.exe",
                 r"%ProgramFiles%\lemonade_server\bin\LemonadeServer.exe")
    else:
        cands = ("/usr/bin/LemonadeServer", "/usr/local/bin/LemonadeServer",
                 "/usr/bin/lemond", "/usr/local/bin/lemond",
                 os.path.expanduser("~/.local/bin/lemond"),
                 os.path.expanduser("~/.local/bin/LemonadeServer"))
    for p in cands:
        path = os.path.expandvars(p)
        if os.path.exists(path):
            return path
    return None


def _start_lemonade_linux():
    """Best-effort start of the Lemonade service on Linux."""
    import shutil
    for cmd in (["systemctl", "--user", "restart", "lemonade"],
                ["systemctl", "restart", "lemonade"],
                ["systemctl", "--user", "restart", "lemond"],
                ["systemctl", "restart", "lemond"]):
        exe = shutil.which(cmd[0])
        if not exe:
            continue
        try:
            subprocess.run([exe] + cmd[1:], capture_output=True, timeout=30,
                           creationflags=CREATE_NO_WINDOW)
            return True
        except Exception:  # noqa: BLE001 - try the next form
            continue
    return False


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
    # If something already listens on the port, Lemonade IS running - it is
    # just busy. Wait for it, and never launch a second server that would fight
    # the first for the same port (that is what made startup crawl).
    if _port_open(13305):
        for _ in range(10):          # ~30s
            time.sleep(3)
            if _lemonade_ok():
                return True
        return True                  # up but slow: let the app retry, do not
                                     # claim it is missing
    if not srv:
        if os.name != "nt" and _start_lemonade_linux():
            for _ in range(20):
                time.sleep(3)
                if _lemonade_ok():
                    return True
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
    """Kick the preferred model off loading, then get out of the way.

    A big model can take many minutes to load (or fail), and holding the splash
    for it is exactly what made the app look stuck. So start the load in the
    background and open the UI immediately; the Flask server adopts the model
    when it appears and shows the load progress in the browser while you wait.
    """
    if loaded_models():
        return
    want = model_name()
    update_msg(f"Loading {want} - the first time can take a few minutes...")
    try:
        _hidden_popen([_lemonade_cli(), "load", want])
    except Exception:  # noqa: BLE001 - the server will load it on demand
        pass


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
        style = u32.GetWindowLongW(hwnd, -16) & 0xFFFFFFFF
        _log("icon: applied hwnd=%s style=0x%X caption=%s frameless=%s"
             % (hwnd, style, bool(style & 0x00C00000), not (style & 0x00C00000)))
    except Exception as e:  # noqa: BLE001 - icon is cosmetic, never fatal
        _log("icon error: " + repr(e))


def ensure_shortcut():
    """Keep a launcher that starts AltVerse without a console."""
    if os.name != "nt":
        try:
            entry = ("[Desktop Entry]\nType=Application\nName=AltVerse Browser\n"
                     "Comment=Local AI alternate-universe browser\n"
                     "Exec=%s %s\nPath=%s\nIcon=%s\nTerminal=false\n"
                     "Categories=Network;WebBrowser;\n" % (
                         sys.executable, os.path.join(HERE, "desktop.py"), HERE,
                         os.path.join(HERE, "icon.ico")))
            for d in (os.path.expanduser("~/.local/share/applications"),
                      os.path.expanduser("~/Desktop")):
                try:
                    os.makedirs(d, exist_ok=True)
                    with open(os.path.join(d, "altverse-browser.desktop"), "w",
                              encoding="utf-8") as f:
                        f.write(entry)
                    os.chmod(os.path.join(d, "altverse-browser.desktop"), 0o755)
                except Exception:  # noqa: BLE001 - best effort
                    pass
        except Exception:  # noqa: BLE001 - cosmetic, never fatal
            pass
        return
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


# Window controls for the custom titlebar. These are registered one at a time
# with window.expose() instead of being passed as a single js_api object:
# pywebview introspects a js_api *recursively* to build the JS bridge, and the
# api <-> window reference cycle made that walk never terminate - it held the
# GIL and froze the whole app on the "Starting up" splash.
_WIN = {"window": None, "maxed": False, "saved": None}


def _work_area():
    """Screen minus the taskbar, so maximizing never hides it (Windows only)."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes
    r = wintypes.RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def minimize():
    """Minimize the window (titlebar button)."""
    try:
        _WIN["window"].minimize()
    except Exception:  # noqa: BLE001 - cosmetic
        pass


def toggle_max():
    """Maximize or restore the window; returns the new maximized state."""
    win = _WIN["window"]
    try:
        if os.name != "nt":
            if _WIN["maxed"]:
                win.restore()
            else:
                win.maximize()
            _WIN["maxed"] = not _WIN["maxed"]
            return _WIN["maxed"]
        if not _WIN["maxed"]:
            try:
                _WIN["saved"] = (win.x, win.y, win.width, win.height)
            except Exception:  # noqa: BLE001 - geometry not exposed
                _WIN["saved"] = None
            x, y, w, h = _work_area()
            win.move(x, y)
            win.resize(w, h)
            _WIN["maxed"] = True
        else:
            sx, sy, sw, sh = _WIN["saved"] or (80, 60, 1280, 820)
            win.move(sx, sy)
            win.resize(sw, sh)
            _WIN["maxed"] = False
    except Exception:  # noqa: BLE001 - cosmetic
        pass
    return _WIN["maxed"]


def close():
    """Close the window (titlebar button)."""
    try:
        _WIN["window"].destroy()
    except Exception:  # noqa: BLE001 - cosmetic
        pass


def main():
    _fix_stdio()
    ensure_deps()
    ensure_shortcut()
    _start_status_server()
    import webview  # imported late so deps can install first

    frameless = os.environ.get("ALTVERSE_FRAMELESS",
                                   "1" if os.name == "nt" else "0") != "0"
    window = webview.create_window(
        TITLE, html=SPLASH, width=1280, height=820, min_size=(900, 600),
        background_color="#f2f5f3", frameless=frameless,
        easy_drag=not frameless)
    _WIN["window"] = window
    # Register the titlebar controls individually (see _WIN above).
    window.expose(minimize, toggle_max, close)

    def boot():
        _log("boot start")

        def msg(text):
            # Never touches the webview: the splash polls STATUS_PORT for this,
            # so no step here can block on a GUI call.
            _log("msg: " + text)
            _status["msg"] = text

        try:
            state = _port_state()
            _log("port state: " + state)
            if state == "serving":
                _log("reusing the already-running instance")
                window.load_url(BASE)
                return
            if state == "stuck":
                _log("port bound but unresponsive")
                msg("AltVerse is already open but not responding. "
                    "Close it (or restart), then reopen.")
                return
            msg("Checking the AI backend...")
            if not ensure_lemonade():
                _log("lemonade unreachable")
                msg("Lemonade Server is not reachable. Install it, then reopen.")
                return
            _log("lemonade ok; loaded=" + repr(loaded_models()))
            ensure_model(msg)
            _log("model ok")
            msg("Opening your browser...")

            import app as app_module
            _log("imported app")
            app_module.WIN_HOOK["fn"] = (
                lambda a: minimize() if a == "min"
                else toggle_max() if a == "max" else close())
            threading.Thread(target=_run_app, args=(app_module.app,),
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
