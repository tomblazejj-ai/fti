"""Funded Mind materials: which files from the trader's folder are already worked into the app.

The folder (default: Desktop / "Fundament Funded mind", override with FTI_METODIKA_DIR) is
only READ locally — names, sizes and SHA-256 hashes; nothing is uploaded anywhere. A file
whose hash is not listed in app/data/metodika.json shows up as "nový — zatím nezapracováno",
so after adding new material the trader sees what still waits to be worked in.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import threading
import unicodedata
from pathlib import Path

MANIFEST = Path(__file__).resolve().parent / "data" / "metodika.json"
TEXT_EXT = {".txt", ".md"}
PREVIEW_CHARS = 600
_hashes: dict[tuple[str, int, float], str] = {}
_lock = threading.Lock()


def folder() -> Path:
    env = os.environ.get("FTI_METODIKA_DIR")
    return Path(env) if env else Path.home() / "Desktop" / "Fundament Funded mind"


def _sha256(p: Path) -> str:
    st = p.stat()
    key = (str(p), st.st_size, st.st_mtime)
    with _lock:
        if key in _hashes:
            return _hashes[key]
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    with _lock:
        _hashes[key] = h.hexdigest()
    return _hashes[key]


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _preview(p: Path) -> str | None:
    if p.suffix.lower() not in TEXT_EXT:
        return None
    for enc in ("utf-8", "cp1250"):
        try:
            return p.read_text(encoding=enc)[:PREVIEW_CHARS]
        except (UnicodeDecodeError, OSError):
            continue
    return None


def scan(base: Path | None = None, now: dt.datetime | None = None) -> dict:
    manifest = load_manifest()
    by_hash = {f["sha256"]: f for f in manifest["files"]}
    by_name = {f["file"]: f for f in manifest["files"]}
    base = base or folder()
    files, seen = [], set()
    if base.is_dir():
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.name.startswith(("~$", ".")):
                continue
            name = unicodedata.normalize("NFC", p.relative_to(base).as_posix())
            try:
                digest = _sha256(p)
                stat = p.stat()
            except OSError:
                continue
            meta = by_hash.get(digest)
            if meta:
                status = "done"
                seen.add(meta["file"])
            elif name in by_name:
                meta, status = by_name[name], "changed"
                seen.add(name)
            else:
                status = "new"
            files.append({
                "file": name,
                "status": status,
                "status_text": {"done": "zapracováno", "changed": "soubor se změnil — projdu znovu",
                                "new": "nový — zatím nezapracováno"}[status],
                "title": (meta or {}).get("title"),
                "author": (meta or {}).get("author"),
                "summary": (meta or {}).get("summary"),
                "used_in": (meta or {}).get("used_in", []),
                "size_kb": round(stat.st_size / 1024),
                "modified": dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc).isoformat(),
                "preview": _preview(p) if status != "done" else None,
            })
    order = {"new": 0, "changed": 1, "done": 2}
    files.sort(key=lambda f: (order[f["status"]], f["file"].lower()))
    counts = {k: sum(1 for f in files if f["status"] == k) for k in order}
    return {
        "course": manifest.get("course"),
        "folder": str(base),
        "folder_exists": base.is_dir(),
        "files": files,
        "counts": counts,
        "missing": sorted(set(by_name) - seen),
        "principles": manifest.get("principles", []),
        "extras": manifest.get("extras", []),
        "checked_at": (now or dt.datetime.now(dt.timezone.utc)).isoformat(),
        "how_to": ("Nové PDF, poznámky (.txt) nebo obrázky stačí uložit do složky. Aplikace je tady označí jako nové; "
                   "zapracování pak proběhne v další úpravě aplikace."),
    }
