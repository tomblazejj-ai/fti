"""API keys never leave FTI in text: every log record and every error message the AI layer
produces passes through redact(), so a key pasted by mistake into a message is hidden too."""

from __future__ import annotations

import logging
import re

_GROQ = re.compile(r"gsk_[A-Za-z0-9]{8,}")
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}")
_installed = False


def redact(text):
    if not text:
        return text
    s = _GROQ.sub("gsk_…[skryto]", str(text))
    return _BEARER.sub(r"\1[skryto]", s)


def install_log_filter() -> None:
    """Redact every log record of the whole process (all loggers and handlers, also ones added later)."""
    global _installed
    if _installed:
        return
    previous = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 — a broken format string is the logger's problem, not ours
            return record
        clean = redact(message)
        if clean != message:
            record.msg, record.args = clean, None
        return record

    logging.setLogRecordFactory(factory)
    _installed = True
