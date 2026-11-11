"""Send the iPhone app and the games' data over the home Wi-Fi: a small web server the launcher runs while its window is open.

GitHub refuses a release file of 2 GB or more (the shell IPA passes that with its second game) and is no place for the games'
data, so the player picks this instead: the IPA and each built game's data folder are offered at
`http://<this PC>:<port>/<code>/`. FlareStore installs the IPA from its address (or Safari downloads it), and the iPhone app's
"Receive from PC" fetches the games' data straight into its own folder (frontend-ios, PCTransfer.swift).

Nothing leaves the home network, nothing is sent until the iPhone asks, and only what is listed here is served: the IPA and,
per game, the regular files of its data folder (romfs.img, romfs.img.id, aoc/…). A random code in every address keeps another
device on the network from guessing them; the server stops when the window closes.

Files are opened with FILE_SHARE_DELETE on Windows: a build of the queue replaces the IPA (os.replace) and a game's romfs.img
when it ends, and that must not fail because the iPhone is downloading the old one at that moment (it gets the old one whole).
"""
from __future__ import annotations

import html
import json
import os
import re
import secrets
import socket
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

PORT = 8765
#: No look-alike letters or digits: the code is typed on a phone.
CODE_ALPHABET = 'abcdefghjkmnpqrstuvwxyz23456789'
CHUNK = 1 << 20


def new_code(n: int = 6) -> str:
    return ''.join(secrets.choice(CODE_ALPHABET) for _ in range(n))


@dataclass(frozen=True)
class SharedGame:
    title_id: str
    name: str
    folder: Path          # the game's data folder: romfs.img (or romfs/), romfs.img.id, aoc/…

    def files(self) -> list[tuple[str, int]]:
        """(path relative to the folder, with '/', size) of each regular file inside, links and hidden files left out."""
        out: list[tuple[str, int]] = []
        root = self.folder
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith('.') and not os.path.islink(os.path.join(dirpath, d)))
            for name in sorted(filenames):
                if name.startswith('.') or name.endswith(('.part', '.partial', '.tmp', '.link')):
                    continue
                p = Path(dirpath, name)
                if p.is_symlink() or not p.is_file():
                    continue
                out.append((p.relative_to(root).as_posix(), p.stat().st_size))
        return sorted(out)


def data_folder(game) -> Path | None:
    """Where a library game's built data is: its archive path, else <root>/games/<title ID> beside its output or inputs."""
    tid = (game.title_id or '').upper()
    if not re.fullmatch(r'[0-9A-F]{16}', tid):
        return None

    def holds_data(d: Path) -> bool:
        return d.is_dir() and ((d / 'romfs.img').is_file() or (d / 'romfs').is_dir() or (d / 'aoc').is_dir())

    cands: list[Path] = []
    if getattr(game, 'archive_path', ''):
        cands.append(Path(game.archive_path))
    roots: list[Path] = []
    if getattr(game, 'output_dir', ''):
        roots.append(Path(game.output_dir))
    base = ((getattr(game, 'inputs', {}) or {}).get('base') or [''])[0]
    if base:
        p = Path(base)
        roots += [p.parent, p.parent.parent, p.parent.parent.parent]
    cands += [r / 'games' / tid for r in roots]
    return next((c for c in cands if holds_data(c)), None)


def shared_games(library_games: Iterable) -> list[SharedGame]:
    out, seen = [], set()
    for g in library_games:
        folder = data_folder(g)
        if folder is not None and g.title_id.upper() not in seen:
            seen.add(g.title_id.upper())
            out.append(SharedGame(g.title_id.upper(), g.name or g.title_id, folder))
    return out


def local_addresses() -> list[str]:
    """This PC's IPv4 addresses on the local network, the one the default route uses first."""
    found: list[str] = []
    try:   # no packet is sent: connecting a UDP socket only picks the interface
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('10.255.255.255', 1))
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    private = re.compile(r'^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)')
    seen: list[str] = []
    for a in found:
        if a not in seen and not a.startswith(('127.', '169.254.', '0.')):
            seen.append(a)
    return sorted(seen, key=lambda a: (not private.match(a), seen.index(a)))


def open_shared(path: Path):
    """A binary read handle the file can be replaced or deleted under (FILE_SHARE_DELETE on Windows)."""
    if os.name != 'nt':
        return open(path, 'rb')
    import ctypes
    import msvcrt
    from ctypes import wintypes
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k32.CreateFileW.restype = wintypes.HANDLE
    GENERIC_READ, SHARE_ALL, OPEN_EXISTING = 0x80000000, 0x7, 3
    h = k32.CreateFileW(str(path), GENERIC_READ, SHARE_ALL, None, OPEN_EXISTING, 0x80, None)
    if h in (None, wintypes.HANDLE(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    fd = msvcrt.open_osfhandle(h, os.O_RDONLY | getattr(os, 'O_BINARY', 0))
    return os.fdopen(fd, 'rb')


SNAPSHOTS = '.wifi-share'


def open_snapshot(path: Path):
    """Read `path` through a hard link of its own, so the file can be replaced while it is sent.

    Opening the file itself, even with FILE_SHARE_DELETE, made os.replace onto it fail on Windows (access denied): the
    export at the end of each queued build replaces the IPA that way, and a transfer at that moment would have failed
    the build. Through a second name, the replace goes through and the iPhone still gets the old file whole. Returns
    (file, link path to remove after closing, or None where the volume cannot link)."""
    snap_dir = path.parent / SNAPSHOTS
    try:
        snap_dir.mkdir(exist_ok=True)
        link = snap_dir / f'{os.getpid()}-{threading.get_ident()}-{secrets.token_hex(4)}{path.suffix}'
        os.link(path, link)
    except OSError:
        return open_shared(path), None
    try:
        return open_shared(link), link
    except OSError:
        link.unlink(missing_ok=True)
        raise


def clear_snapshots(folders: Iterable[Path]) -> None:
    """Remove the links a stopped share left (each keeps an old file's space in use)."""
    for d in folders:
        snap_dir = Path(d) / SNAPSHOTS
        if snap_dir.is_dir():
            for p in snap_dir.iterdir():
                try:
                    p.unlink()
                except OSError:
                    pass
            try:
                snap_dir.rmdir()
            except OSError:
                pass


@dataclass
class Activity:
    """What the iPhone asked for, for the window: the last requests and the transfers going on."""
    lock: threading.Lock = field(default_factory=threading.Lock)
    recent: list[str] = field(default_factory=list)
    sending: dict[int, tuple[str, int, int]] = field(default_factory=dict)   # id → (what, sent, total)

    def note(self, line: str) -> None:
        with self.lock:
            self.recent = (self.recent + [line])[-8:]


class ShareServer:
    def __init__(self, ipa: Callable[[], Path | None], games: Callable[[], list[SharedGame]],
                 page: Callable[[dict, str], str] | None = None, port: int = PORT, code: str | None = None) -> None:
        self.ipa = ipa
        self.games = games
        self.page = page or default_page
        self.code = code or new_code()
        self.wanted_port = port
        self.port = 0
        self.activity = Activity()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # ---- life
    def start(self) -> int:
        """Listen on every interface, on PORT or the next free port. Returns the port."""
        self.clear()   # what a share that ended without stopping left
        last: OSError | None = None
        for port in range(self.wanted_port, self.wanted_port + 20):
            try:
                httpd = ThreadingHTTPServer(('0.0.0.0', port), _handler_for(self))
                break
            except OSError as e:
                last = e
        else:
            raise last or OSError('no free port')
        httpd.daemon_threads = True
        self._httpd, self.port = httpd, httpd.server_address[1]
        self._thread = threading.Thread(target=httpd.serve_forever, name='wifi-share', daemon=True)
        self._thread.start()
        return self.port

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        self.clear()

    def clear(self) -> None:
        """Remove the links transfers left beside the IPA and in each game's data folder."""
        ipa = self.ipa()
        folders = ([ipa.parent] if ipa is not None else []) + [g.folder for g in self.games()]
        clear_snapshots(folders)

    @property
    def running(self) -> bool:
        return self._httpd is not None

    def address(self, host: str) -> str:
        return f'http://{host}:{self.port}/{self.code}/'

    # ---- what is offered
    def catalog(self) -> dict:
        ipa = self.ipa()
        ipa_info = None
        if ipa is not None and ipa.is_file():
            st = ipa.stat()
            ipa_info = {'path': 'NX2Apple.ipa', 'size': st.st_size, 'modified': int(st.st_mtime)}
        games = []
        for g in self.games():
            files = [{'path': p, 'size': s} for p, s in g.files()]
            games.append({'title_id': g.title_id, 'name': g.name, 'bytes': sum(f['size'] for f in files), 'files': files})
        return {'version': 1, 'ipa': ipa_info, 'games': games}

    def resolve(self, rel: str) -> Path | None:
        """The file a request path (after the code) names, or None: only the IPA and files listed in the catalog."""
        if rel == 'NX2Apple.ipa':
            ipa = self.ipa()
            return ipa if ipa is not None and ipa.is_file() else None
        m = re.fullmatch(r'games/([0-9A-Fa-f]{16})/(.+)', rel)
        if not m:
            return None
        tid, inner = m.group(1).upper(), m.group(2)
        for g in self.games():
            if g.title_id == tid:
                listed = {p for p, _ in g.files()}
                return g.folder / inner if inner in listed else None
        return None


def default_page(cat: dict, base: str = '') -> str:
    """The page Safari shows at the address (English; the window passes its own words)."""
    return render_page(cat, {
        'title': 'NX2Apple on this PC', 'ipa': 'Download the app (IPA)', 'noIpa': 'No IPA yet: build a game first.',
        'flare': 'In FlareStore, paste this address in the link field:', 'data': 'Games’ data',
        'dataNote': 'In the NX2Apple app: Settings › Receive from PC, with this page’s address.', 'none': 'No game data yet.',
    }, base)


def render_page(cat: dict, words: dict, base: str) -> str:
    e = html.escape
    rows = []
    ipa = cat.get('ipa')
    if ipa:
        when = time.strftime('%Y-%m-%d %H:%M', time.localtime(ipa['modified']))
        rows.append(f'<a class="btn" href="NX2Apple.ipa">{e(words["ipa"])}</a>'
                    f'<p class="muted">{_size(ipa["size"])} · {e(when)}</p>'
                    f'<p>{e(words["flare"])}</p><p class="code">{e(base)}NX2Apple.ipa</p>')
    else:
        rows.append(f'<p class="muted">{e(words["noIpa"])}</p>')
    games = cat.get('games') or []
    items = ''.join(f'<li>{e(g["name"])} <span class="muted">{_size(g["bytes"])}</span></li>' for g in games)
    rows.append(f'<h2>{e(words["data"])}</h2><p>{e(words["dataNote"])}</p>'
                + (f'<ul>{items}</ul>' if items else f'<p class="muted">{e(words["none"])}</p>'))
    return ('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{e(words["title"])}</title><style>'
            'body{font:17px -apple-system,system-ui,sans-serif;background:#000;color:#f5f5f7;margin:0;padding:24px;max-width:640px}'
            'h1{font-size:26px}h2{font-size:20px;margin-top:32px}.muted{color:#8e8e93}'
            '.btn{display:block;text-align:center;background:#fff3d6;color:#000;border-radius:14px;padding:16px;font-weight:700;text-decoration:none;margin-top:12px}'
            '.code{font-family:ui-monospace,Menlo,monospace;font-size:14px;word-break:break-all;background:#1c1c1e;padding:10px;border-radius:10px}'
            'li{margin:6px 0}</style></head><body>'
            f'<h1>{e(words["title"])}</h1>' + ''.join(rows) + '</body></html>')


def _size(n: int) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1000 or unit == 'GB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1000
    return f'{n:.1f} GB'


def _handler_for(server: ShareServer):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        server_version = 'NX2Apple'
        sys_version = ''

        def log_message(self, fmt, *args):   # a windowed app has no stderr: nothing is written there
            pass

        def _rel(self) -> str | None:
            path = unquote(self.path.split('?', 1)[0])
            prefix = f'/{server.code}/'
            if path == f'/{server.code}':
                return ''
            if not path.startswith(prefix) or '..' in path.split('/') or '\\' in path:
                return None
            return path[len(prefix):]

        def _send_bytes(self, body: bytes, ctype: str, head: bool) -> None:
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            if not head:
                self.wfile.write(body)

        def _not_found(self) -> None:
            body = b'not found'
            self.send_response(404)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_HEAD(self):
            self._serve(head=True)

        def do_GET(self):
            self._serve(head=False)

        def _serve(self, head: bool) -> None:
            rel = self._rel()
            if rel is None:
                return self._not_found()
            if rel in ('', 'index.html'):
                cat = server.catalog()
                base = f'http://{self.headers.get("Host", "")}/{server.code}/'
                return self._send_bytes(server.page(cat, base).encode('utf-8'), 'text/html; charset=utf-8', head)
            if rel == 'catalog.json':
                server.activity.note(f'{time.strftime("%H:%M:%S")} catalog')
                return self._send_bytes(json.dumps(server.catalog()).encode('utf-8'), 'application/json', head)
            target = server.resolve(rel)
            if target is None:
                return self._not_found()
            self._send_file(target, rel, head)

        def _send_file(self, target: Path, rel: str, head: bool) -> None:
            try:
                f, link = open_snapshot(target)
            except OSError:
                return self._not_found()
            try:
                self._send_open(f, rel, head)
            finally:
                f.close()
                if link is not None:
                    link.unlink(missing_ok=True)

        def _send_open(self, f, rel: str, head: bool) -> None:
            size = os.fstat(f.fileno()).st_size
            start, end = 0, size - 1
            rng = re.fullmatch(r'bytes=(\d*)-(\d*)', self.headers.get('Range', '').strip())
            partial = bool(rng) and (rng.group(1) or rng.group(2))
            if partial:
                if rng.group(1):
                    start = int(rng.group(1))
                    end = min(int(rng.group(2)), size - 1) if rng.group(2) else size - 1
                else:   # the last n bytes
                    start = max(0, size - int(rng.group(2)))
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header('Content-Range', f'bytes */{size}')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
            length = end - start + 1 if size else 0
            self.send_response(206 if partial else 200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Length', str(length))
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Last-Modified', self.date_time_string(int(os.fstat(f.fileno()).st_mtime)))
            if rel == 'NX2Apple.ipa':
                self.send_header('Content-Disposition', 'attachment; filename="NX2Apple.ipa"')
            if partial:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.end_headers()
            if head:
                return
            key = id(self)
            server.activity.note(f'{time.strftime("%H:%M:%S")} {rel}')
            f.seek(start)
            left, sent = length, 0
            try:
                while left > 0:
                    chunk = f.read(min(CHUNK, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
                    sent += len(chunk)
                    with server.activity.lock:
                        server.activity.sending[key] = (rel, start + sent, size)
            except (ConnectionError, OSError):
                pass   # the iPhone stopped: it can ask again from where it was (Range)
            finally:
                with server.activity.lock:
                    server.activity.sending.pop(key, None)

    return Handler
