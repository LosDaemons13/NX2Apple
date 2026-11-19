"""What a build log line is (an error, a warning or neither) and the lines that say why a build failed.

The window colours each line of the log by its kind (log_view.py), and the build queue shows the error lines of a failed
game under its "Failed", so the reason is on screen without searching a log of thousands of lines. Plain text, no Qt.
"""
from __future__ import annotations

import re

ERROR = 'error'
WARNING = 'warning'
PLAIN = ''

_TIME = re.compile(r'^\[\d\d:\d\d:\d\d\]\s*')
_ERROR = (
    re.compile(r'\[RED\]'),                                       # the engine's and the emulators' red lines
    re.compile(r'^✗'),                                            # a stage that failed: "✗ [6/9] shader split (9:49)"
    re.compile(r'^Traceback \(most recent call last\)'),
    re.compile(r'^(?:[A-Za-z_][\w.]*\.)?[A-Z]\w*(?:Error|Exception)(?::|$)'),   # a traceback's last line: "OSError: [Errno 28] …"
    re.compile(r'\bERROR\b'),                                     # "export-shell: ERROR: pack_ipa.py failed: …"
    re.compile(r'\b(?:[Ee]rror|[Ff]atal)\s*:'),                   # "clang: error: …", "fatal: …"
)
_WARNING = (
    re.compile(r'^⚠'),                                            # a stage that ended without what it makes
    re.compile(r'\b[Ww]arning\s*:|\bWARNING\b|^\w*Warning:'),
    re.compile(r'^\[shim\] '),                                    # the Windows shim could not be prepared
)
_PREFIX = re.compile(r'^(?:\[\d\d:\d\d:\d\d\]\s*)?(?:\[dm\]\s*)?(?:\[RED\]\s*)?')
_STAGE_FAILED = re.compile(r'^(?:\[\d\d:\d\d:\d\d\]\s*)?✗')


def kind(line: str) -> str:
    """ERROR, WARNING or PLAIN for one line of the log (its time stamp is not read)."""
    body = _TIME.sub('', line)
    if any(p.search(body) for p in _ERROR):
        return ERROR
    if any(p.search(body) for p in _WARNING):
        return WARNING
    return PLAIN


def clean(line: str) -> str:
    """A line as the queue shows it: without its time stamp and its [dm] / [RED] markers."""
    return _PREFIX.sub('', line.strip()).strip()


def failure_lines(text: str, limit: int = 4, width: int = 300) -> list[str]:
    """The lines that say why a build failed, from its output: the error lines from the last stage that failed (its ✗ line
    first, then what the build said about it), or the last error lines when no stage failed. At most `limit` lines, each
    without its markers and cut at `width` characters."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    start = max((i for i, ln in enumerate(lines) if _STAGE_FAILED.match(ln)), default=None)
    errors = [ln for ln in (lines[start:] if start is not None else lines) if kind(ln) == ERROR]
    picked = errors[:limit] if start is not None else errors[-limit:]
    out: list[str] = []
    for ln in picked:
        c = clean(ln)
        if len(c) > width:
            c = c[:width - 1] + '…'
        if c and c not in out:
            out.append(c)
    return out
