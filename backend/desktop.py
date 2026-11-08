"""Desktop launcher: the app as a normal program window, no console.

Run with pythonw.exe (the desktop shortcut does). Starts the FastAPI server
in a background thread, shows the dashboard in a native window (Edge
WebView2 via pywebview) and stops everything when the window is closed.
Only one FTI runs at a time: a second click on the icon brings the open
window to the front (see _single_instance). Server logs and crashes go to
backend/fti.log, every phase of a start to backend/fti-start.log.
"""

from __future__ import annotations

import faulthandler
import logging
import os
import sys
import threading
import time
from pathlib import Path

# pythonw has no console: sys.stdout / sys.stderr are None, so anything printed (tracebacks, warnings) would vanish.
# Send it to a file next to the log — before any other import can write there.
CONSOLE_FILE = Path(__file__).resolve().parent / "fti-console.log"
if sys.stderr is None or sys.stdout is None:
    _console = open(CONSOLE_FILE, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 — lives as long as the app
    sys.stdout = sys.stdout or _console
    sys.stderr = sys.stderr or _console
    faulthandler.enable(_console)  # even a hard crash of the interpreter leaves a trace

# Every phase of a start goes to fti-start.log with this process's id and its parent's id, so a start that
# stops somewhere (or a second start) can be traced exactly — written directly, before any import that could hang.
START_LOG = Path(__file__).resolve().parent / "fti-start.log"


def _trace(phase: str) -> None:
    try:
        with open(START_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}.{int(time.time() * 1000) % 1000:03d} pid {os.getpid()} "
                    f"rodič {os.getppid()} [{__name__}] {phase}\n")
    except OSError:
        pass


_trace(f"proces startuje: {sys.executable} {sys.argv}")

WINDOW_TITLE = "FTI – Financial Trading Intelligence"
MUTEX_NAME = "Local\\FTI-Financial-Trading-Intelligence"
_mutex = None  # owned by this process for its whole life; Windows hands it over when the process ends


def _single_instance() -> bool:
    """One FTI at a time (a named Windows mutex). True = this process may start FTI.

    Two starts at once used to give two servers racing for the port and two data cycles on one database.
    Now a second start (a double click, a click while FTI is starting, running or still finishing its data cycle
    after the window was closed) starts nothing: it brings the FTI window to the front and ends, or waits
    until the previous FTI has ended and then starts normally. It never ends or touches another process."""
    global _mutex
    if os.name != "nt":
        return True
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    _mutex = kernel32.CreateMutexW(None, True, MUTEX_NAME)
    if ctypes.get_last_error() != 183:  # not ERROR_ALREADY_EXISTS: this process owns it now
        return True
    _trace("FTI už běží nebo se spouští")
    user32 = ctypes.windll.user32
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        hwnd = _fti_window()
        if hwnd:
            user32.ShowWindow(hwnd, 9 if user32.IsIconic(hwnd) else 5)  # SW_RESTORE when minimised, else SW_SHOW
            user32.SetForegroundWindow(hwnd)
            time.sleep(1)
            if _fti_window() == hwnd:  # not a window that was just being closed
                _trace("okno běžícího FTI přeneseno do popředí — toto spuštění končí")
                return False
        if kernel32.WaitForSingleObject(_mutex, 500) in (0, 0x80):  # WAIT_OBJECT_0 / WAIT_ABANDONED: the previous FTI ended
            _trace("předchozí FTI skončilo — spouštím")
            return True
    _trace("FTI se pořád spouští a okno ještě nemá — toto spuštění končí a nic nespouští")
    return False


def _fti_window() -> int:
    """The visible FTI window (pywebview's WinForms form with FTI's title), or 0."""
    import ctypes

    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, WINDOW_TITLE)
    cls = ctypes.create_unicode_buffer(64)
    if hwnd and user32.IsWindowVisible(hwnd) and user32.GetClassNameW(hwnd, cls, 64) and cls.value.startswith("WindowsForms10."):
        return hwnd
    return 0


if __name__ == "__main__":
    if not _single_instance():
        os._exit(0)
    _trace("jediná instance FTI potvrzena")

import httpx  # noqa: E402

_trace("načteno httpx")
import uvicorn  # noqa: E402

_trace("načteno uvicorn")
import webview  # noqa: E402

_trace("načteno webview")

HOST, PORT = "127.0.0.1", 8000
URL = f"http://{HOST}:{PORT}"
LOG_FILE = Path(__file__).resolve().parent / "fti.log"


def _server_is_up() -> bool:
    try:
        return httpx.get(f"{URL}/api/health", timeout=1.0).status_code == 200
    except httpx.HTTPError:
        return False


def main() -> None:
    # pythonw has no console: send all logging to a file instead.
    logging.basicConfig(
        filename=LOG_FILE, level=logging.INFO, encoding="utf-8",
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # what this start looks like — to compare the desktop icon with a manual start
    env = {k: v for k, v in os.environ.items() if k.startswith(("FTI_", "PYTHON", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"))}
    logging.info("FTI start: interpreter %s | argv %s | cwd %s | prefix %s | console %s | env %s",
                 sys.executable, sys.argv, os.getcwd(), sys.prefix, "soubor" if sys.stderr is not sys.__stderr__ else "ano", env)
    # pythonw has no stderr either: a crash in the server thread must end up in the log, not vanish
    threading.excepthook = lambda a: logging.error("FTI thread crashed", exc_info=(a.exc_type, a.exc_value, a.exc_traceback))

    state: dict = {"server": None, "thread": None, "closing": False}
    _trace("hlavní funkce: kontrola serveru")
    _ensure_server(state)
    _trace(f"server odpovídá: {_server_is_up()} (vlastní server v tomto procesu: {state['server'] is not None})")
    # If the server goes away later (its thread crashed, or this window attached to a server started some other way), start our own.
    threading.Thread(target=_watch_server, args=(state,), daemon=True).start()

    _trace("otevírám okno")
    webview.create_window(
        WINDOW_TITLE,
        URL,
        width=1400,
        height=900,
        min_size=(380, 600),
        background_color="#0d0d0d",
    )
    webview.start()
    _trace("okno zavřeno, končím")

    state["closing"] = True
    if state["server"] is not None:
        state["server"].should_exit = True
        state["thread"].join(timeout=10)  # let uvicorn shut the app down (scheduler, open requests)
        _trace(f"server zastaven: {not state['thread'].is_alive()}")


def _ensure_server(state: dict) -> None:
    """Start a server in this process when none answers, and wait until it does (at most 30 s)."""
    if _server_is_up() or (state["thread"] is not None and state["thread"].is_alive()):
        return
    logging.info("No FTI server answers on %s — starting one in this window", URL)
    server = uvicorn.Server(uvicorn.Config("app.main:app", host=HOST, port=PORT, log_config=None))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    state.update(server=server, thread=thread)
    deadline = time.monotonic() + 30
    while not _server_is_up():
        if time.monotonic() > deadline or not thread.is_alive():
            logging.error("FTI server did not start within 30 s (thread alive: %s)", thread.is_alive())
            break
        time.sleep(0.25)


def _watch_server(state: dict) -> None:
    while not state["closing"]:
        time.sleep(5)
        if not state["closing"]:
            _ensure_server(state)


if __name__ == "__main__":
    main()
    _trace("proces končí")
    # End now. Otherwise Python waits for a data cycle still running (~2 min, up to 7) and the process lingered
    # windowless, holding up the next start. The cut cycle is safe: SQLite rolls an unfinished write back and the
    # next start runs the cycle again.
    logging.shutdown()
    os._exit(0)
