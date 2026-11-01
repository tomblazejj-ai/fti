"""Desktop launcher: the app as a normal program window, no console.

Run with pythonw.exe (the desktop shortcut does). Starts the FastAPI server
in a background thread, shows the dashboard in a native window (Edge
WebView2 via pywebview) and stops everything when the window is closed.
If the server is already running (e.g. a second click on the icon), it just
opens another window onto it. Server logs go to backend/fti.log.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import httpx
import uvicorn
import webview

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

    server: uvicorn.Server | None = None
    if not _server_is_up():
        server = uvicorn.Server(uvicorn.Config("app.main:app", host=HOST, port=PORT, log_config=None))
        threading.Thread(target=server.run, daemon=True).start()
        deadline = time.monotonic() + 30
        while not _server_is_up():
            if time.monotonic() > deadline:
                logging.error("Server did not start within 30 s")
                break
            time.sleep(0.25)

    webview.create_window(
        "FTI – Financial Trading Intelligence",
        URL,
        width=1400,
        height=900,
        min_size=(380, 600),
        background_color="#0d0d0d",
    )
    webview.start()

    if server is not None:
        server.should_exit = True


if __name__ == "__main__":
    main()
