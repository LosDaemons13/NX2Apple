"""Self-update for the Windows Qt launcher: release check, zip verification, staging, and relaunch.

Mirrors the rules of `frontend/Sources/NXCore/AppUpdate.swift` so both desktop launchers
compare versions, match release assets, and verify SHA-256 digests identically.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

#: Bump together with each release tag and `AppUpdateStore.appVersion` in Swift.
APP_VERSION = '1.4.0'

LATEST_RELEASE_URL = 'https://api.github.com/repos/LNPANDY/NX2Apple/releases/latest'
RELEASES_PAGE_URL = 'https://github.com/LNPANDY/NX2Apple/releases/latest'


def _fork_build(folder: Path = Path(__file__).resolve().parent) -> dict:
    """`fork_build.json`, which a fork's workflow writes beside this file: the fork's repository and its build version."""
    try:
        data = json.loads((folder / 'fork_build.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


# A fork's build updates from the fork's own releases, so an update from upstream never replaces it with a build
# that lacks the fork's changes (the cartridge shell, for one).
_FORK = _fork_build()
if re.fullmatch(r'[A-Za-z0-9-]+/[A-Za-z0-9._-]+', str(_FORK.get('repo') or '')):
    LATEST_RELEASE_URL = f"https://api.github.com/repos/{_FORK['repo']}/releases/latest"
    RELEASES_PAGE_URL = f"https://github.com/{_FORK['repo']}/releases/latest"
if re.fullmatch(r'\d+(\.\d+)+', str(_FORK.get('version') or '')):
    APP_VERSION = str(_FORK['version'])

#: Accepted Windows release zip names, newest first.
ASSET_NAMES = (
    'NX2Apple-windows-x64.zip',
    'NS-Port-Builder-qt-windows-x64.zip',
)

#: Accepted executable names inside the unpacked Windows bundle, newest first.
EXE_NAMES = (
    'NX2Apple.exe',
    'NS Port Builder.exe',
)


@dataclass(frozen=True)
class Release:
    tag: str
    url: str
    digest: str | None = None
    notes: str = ''
    html_url: str = RELEASES_PAGE_URL


@dataclass(frozen=True)
class CheckResult:
    kind: str   # 'unreachable' | 'up_to_date' | 'found' | 'no_asset'
    release: Release | None = None
    tag: str = ''


@dataclass(frozen=True)
class StagedUpdate:
    release: Release
    app_dir: Path
    exe_name: str
    staging_root: Path


class StageError(Exception):
    """Raised when downloading, verifying, or unpacking an update fails.

    `key` is the localization key in `frontend/l10n/*.json` taking the release tag.
    """

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def _parse_version(s: str) -> tuple[list[int], int | None]:
    v = s.strip().lstrip('vV')
    rc: int | None = None
    m = re.match(r'^(.+?)-rc([1-9]\d*)$', v, re.I)
    if m:
        v, rc = m.group(1), int(m.group(2))
    nums: list[int] = []
    for part in v.split('.'):
        digits = ''.join(ch for ch in part if ch.isdigit())
        nums.append(int(digits) if digits else 0)
    return nums, rc


def is_newer(tag: str, current: str) -> bool:
    """True when `tag` ('v1.2.2') is a newer version than `current` ('1.2.0' or '1.2.2-rc3')."""
    if not tag or not current:
        return False
    a_nums, a_rc = _parse_version(tag)
    b_nums, b_rc = _parse_version(current)
    length = max(len(a_nums), len(b_nums))
    for i in range(length):
        x = a_nums[i] if i < len(a_nums) else 0
        y = b_nums[i] if i < len(b_nums) else 0
        if x != y:
            return x > y
    if a_rc is None and b_rc is not None:
        return True
    if a_rc is not None and b_rc is not None:
        return a_rc > b_rc
    return False


def release_from_json(obj: dict) -> Release | None:
    """Extract the Windows release asset and its SHA-256 digest from a GitHub release object."""
    if not isinstance(obj, dict) or obj.get('draft') or obj.get('prerelease'):
        return None
    tag = str(obj.get('tag_name') or '').strip()
    assets = obj.get('assets')
    if not tag or not isinstance(assets, list):
        return None
    html_url = str(obj.get('html_url') or RELEASES_PAGE_URL).strip() or RELEASES_PAGE_URL
    notes = str(obj.get('body') or '')
    for wanted in ASSET_NAMES:
        for a in assets:
            if isinstance(a, dict) and a.get('name') == wanted:
                u = a.get('browser_download_url')
                if isinstance(u, str) and u.strip():
                    digest = a.get('digest')
                    return Release(
                        tag=tag,
                        url=u.strip(),
                        digest=digest.strip() if isinstance(digest, str) and digest.strip() else None,
                        notes=notes,
                        html_url=html_url,
                    )
    return None


def check_release(data: bytes | str | None, current: str = APP_VERSION) -> CheckResult:
    """Compare GitHub's `releases/latest` response against `current`."""
    if not data:
        return CheckResult('unreachable')
    try:
        text = data.decode('utf-8', errors='replace') if isinstance(data, (bytes, bytearray)) else str(data)
        obj = json.loads(text)
    except (ValueError, TypeError):
        return CheckResult('up_to_date')
    if not isinstance(obj, dict) or obj.get('draft') or obj.get('prerelease'):
        return CheckResult('up_to_date')
    tag = str(obj.get('tag_name') or '').strip()
    if not is_newer(tag, current):
        return CheckResult('up_to_date')
    rel = release_from_json(obj)
    if rel is None:
        return CheckResult('no_asset', tag=tag)
    return CheckResult('found', release=rel, tag=tag)


def fetch_latest_json(url: str = LATEST_RELEASE_URL, timeout: float = 15.0) -> bytes | None:
    """Fetch the latest release metadata from GitHub."""
    req = urllib.request.Request(
        url,
        headers={
            'Accept': 'application/vnd.github+json',
            'User-Agent': f'NX2Apple/{APP_VERSION}',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, OSError, ValueError):
        return None


def sha256_file(path: Path) -> str | None:
    """Return the lowercase hex SHA-256 of `path`, or None on I/O error."""
    h = hashlib.sha256()
    try:
        with open(path, 'rb') as f:
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest().lower()
    except OSError:
        return None


def check_digest(path: Path, expected: str | None) -> str:
    """Compare `path` against `expected` ('sha256:<hex>'). Returns 'match' | 'mismatch' | 'missing'."""
    if not expected or not expected.lower().startswith('sha256:'):
        return 'missing'
    want = expected[len('sha256:'):].strip().lower()
    if not want:
        return 'missing'
    if len(want) != 64 or any(c not in '0123456789abcdef' for c in want):
        return 'mismatch'
    have = sha256_file(path)
    if have is None:
        return 'mismatch'
    return 'match' if have == want else 'mismatch'


def release_sha256(release: Release) -> str | None:
    """The SHA-256 GitHub published for the release zip, as 64 lowercase hex digits, or None."""
    d = (release.digest or '').strip().lower()
    if not d.startswith('sha256:'):
        return None
    want = d[len('sha256:'):].strip()
    return want if re.fullmatch(r'[0-9a-f]{64}', want) else None


def download_release(
    release: Release,
    dest: Path,
    progress: Callable[[int, int], None] | None = None,
    log: Callable[[str], None] | None = None,
    download: Callable[..., Path] | None = None,
) -> Path:
    """Fetch the release zip into `dest`, checked against the SHA-256 GitHub publishes for it.

    `fetch.download` only accepts a pinned digest: calling it without one raised a TypeError
    before a single byte was fetched, and every self-update failed as "GitHub unreachable".
    A release without a SHA-256 raises StageError('app.noDigest'), whose message says to
    update by hand.
    """
    want = release_sha256(release)
    if want is None:
        raise StageError('app.noDigest')
    if download is None:
        from .win import fetch
        download = fetch.download
    return download(release.url, dest, want, log=log, progress=progress)


_TAG_VERSION_RE = re.compile(r'(?:^|[-_/])(v?\d+(?:\.\d+)*(?:-rc\d+)?)$', re.I)


def display_tag(tag: str) -> str:
    """The version part of a release tag for buttons: 'cartouche-v1.4.0.3' -> 'v1.4.0.3'."""
    m = _TAG_VERSION_RE.search(tag.strip())
    return m.group(1) if m else tag


def fresh_staging_root(base_temp: Path | None = None) -> Path:
    """Return an empty staging directory for unpacking an update."""
    root = (base_temp or Path(tempfile.gettempdir())) / 'nx2apple-update'
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_extract_zip(zip_path: Path, dest_dir: Path) -> None:
    """Extract `zip_path` into `dest_dir`, rejecting any path traversal entries."""
    dest_resolved = dest_dir.resolve()
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for info in zf.infolist():
            norm = PurePosixPath(info.filename.replace('\\', '/'))
            if norm.is_absolute() or '..' in norm.parts:
                raise zipfile.BadZipFile(f'unsafe zip entry: {info.filename}')
            target = (dest_resolved / Path(*norm.parts)).resolve()
            if target != dest_resolved and dest_resolved not in target.parents:
                raise zipfile.BadZipFile(f'escaped zip entry: {info.filename}')
        zf.extractall(dest_resolved)


def _find_bundled_app_dir(unpacked_dir: Path) -> tuple[Path, str] | None:
    """Locate the unpacked PyInstaller app directory containing `NX2Apple.exe` and `_internal/`."""
    candidates = [unpacked_dir]
    try:
        candidates.extend( sorted(p for p in unpacked_dir.iterdir() if p.is_dir()) )
    except OSError:
        return None
    for cand in candidates:
        if not (cand / '_internal').is_dir():
            continue
        for exe_name in EXE_NAMES:
            if (cand / exe_name).is_file():
                return cand, exe_name
    return None


def stage_zip(
    zip_path: Path,
    release: Release,
    staging_root: Path,
    require_digest: bool = False,
) -> StagedUpdate:
    """Verify `zip_path`, unpack it inside `staging_root`, and validate the bundle layout."""
    verdict = check_digest(zip_path, release.digest)
    if verdict == 'mismatch':
        zip_path.unlink(missing_ok=True)
        raise StageError('app.digestMismatch')
    if verdict == 'missing' and require_digest:
        zip_path.unlink(missing_ok=True)
        raise StageError('app.noDigest')

    unpacked = staging_root / 'unpacked'
    shutil.rmtree(unpacked, ignore_errors=True)
    unpacked.mkdir(parents=True, exist_ok=True)
    try:
        _safe_extract_zip(zip_path, unpacked)
    except (zipfile.BadZipFile, OSError) as exc:
        zip_path.unlink(missing_ok=True)
        shutil.rmtree(unpacked, ignore_errors=True)
        raise StageError('app.unpackFail') from exc
    zip_path.unlink(missing_ok=True)

    found = _find_bundled_app_dir(unpacked)
    if found is None:
        shutil.rmtree(unpacked, ignore_errors=True)
        raise StageError('app.notOurApp')
    app_dir, exe_name = found
    return StagedUpdate(release=release, app_dir=app_dir, exe_name=exe_name, staging_root=staging_root)


#: Pure-ASCII PowerShell script that waits for the running process to exit (and stops it when it has not
#: after 30 s), copies the staged update into place with robocopy (retrying locked files), removes a legacy
#: exe name when transitioning from `NS Port Builder.exe` to `NX2Apple.exe`, and relaunches the executable.
#: Each step goes to `NX_LOG`. A copy that fails (robocopy 8 or more) keeps the staged update for another try.
WINDOWS_RELAUNCH_PS1 = (
    "$log = $env:NX_LOG; "
    "function Note($m) { if ($log) { Add-Content -LiteralPath $log -Value ((Get-Date -Format s) + ' ' + $m) -ErrorAction SilentlyContinue } }; "
    "Note ('update of ' + $env:NX_TARGET + ' from ' + $env:NX_STAGED); "
    "$pidToWait = [int]$env:NX_PID; "
    "for ($i = 0; $i -lt 150; $i++) { "
    "if (-not (Get-Process -Id $pidToWait -ErrorAction SilentlyContinue)) { break }; "
    "Start-Sleep -Milliseconds 200 "
    "}; "
    "if (Get-Process -Id $pidToWait -ErrorAction SilentlyContinue) { "
    "Note 'the launcher was still open after 30 s: stopped'; "
    "Stop-Process -Id $pidToWait -Force -ErrorAction SilentlyContinue; "
    "for ($i = 0; $i -lt 50; $i++) { if (-not (Get-Process -Id $pidToWait -ErrorAction SilentlyContinue)) { break }; Start-Sleep -Milliseconds 200 } "
    "}; "
    "Start-Sleep -Milliseconds 400; "
    "$copy = @($env:NX_STAGED, $env:NX_TARGET, '/E', '/IS', '/IT', '/IM', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:20', '/W:1'); "
    "if ($log) { $copy += ('/LOG+:' + $log) }; "
    "& robocopy @copy | Out-Null; "
    "$rc = $LASTEXITCODE; "
    "Note ('robocopy exit code ' + $rc); "
    "$newExe = Join-Path $env:NX_TARGET $env:NX_NEW_EXE; "
    "if (($rc -lt 8) -and ($env:NX_OLD_EXE -ne $env:NX_NEW_EXE) -and (Test-Path -LiteralPath $newExe)) { "
    "$oldExe = Join-Path $env:NX_TARGET $env:NX_OLD_EXE; "
    "Remove-Item -LiteralPath $oldExe -Force -ErrorAction SilentlyContinue "
    "}; "
    "Remove-Item Env:_MEIPASS,Env:_MEIPASS2,Env:PYTHONHOME,Env:PYTHONPATH,Env:QT_PLUGIN_PATH,Env:QML2_IMPORT_PATH "
    "-ErrorAction SilentlyContinue; "
    "$launchExe = if (Test-Path -LiteralPath $newExe) { $newExe } else { Join-Path $env:NX_TARGET $env:NX_OLD_EXE }; "
    "if (Test-Path -LiteralPath $launchExe) { "
    "Start-Process -FilePath $launchExe -WorkingDirectory $env:NX_TARGET; "
    "Note ('started ' + $launchExe) "
    "}; "
    "if ($rc -ge 8) { Note 'FAILED: the staged update is kept' } "
    "elseif ($env:NX_STAGE_ROOT -and (Test-Path -LiteralPath $env:NX_STAGE_ROOT)) { "
    "Remove-Item -LiteralPath $env:NX_STAGE_ROOT -Recurse -Force -ErrorAction SilentlyContinue "
    "}"
)

#: Where the updater writes what it did (WINDOWS_RELAUNCH_PS1), beside the staging folder.
UPDATE_LOG_NAME = 'nx2apple-update.log'

#: CreateProcess flags. CREATE_NO_WINDOW gives PowerShell a console it does not show. Not DETACHED_PROCESS:
#: Windows PowerShell started without any console exits at once with code 0 and runs nothing, so every update
#: closed the launcher and left it as it was (1.4.0.17 and before; the player had to unzip each release by hand).
#: CREATE_BREAKAWAY_FROM_JOB keeps the updater alive when the launcher runs inside a job that is closed with it.
_CREATE_NO_WINDOW = 0x08000000
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def relaunch_windows_update(
    staged: StagedUpdate,
    current_exe: Path | None = None,
    pid: int | None = None,
    popen=subprocess.Popen,
    log_path: Path | None = None,
) -> bool:
    """Spawn a background process on Windows that swaps `staged` in after `pid` exits."""
    exe_path = (current_exe or Path(sys.executable)).resolve()
    target_dir = exe_path.parent
    env = os.environ.copy()
    for k in ('_MEIPASS', '_MEIPASS2', 'PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH', 'QML2_IMPORT_PATH'):
        env.pop(k, None)
    env['NX_PID'] = str(os.getpid() if pid is None else pid)
    env['NX_STAGED'] = str(staged.app_dir)
    env['NX_TARGET'] = str(target_dir)
    env['NX_OLD_EXE'] = exe_path.name
    env['NX_NEW_EXE'] = staged.exe_name
    env['NX_STAGE_ROOT'] = str(staged.staging_root)
    env['NX_LOG'] = str(log_path or Path(tempfile.gettempdir()) / UPDATE_LOG_NAME)

    kwargs: dict = {
        'stdin': subprocess.DEVNULL,
        'stdout': subprocess.DEVNULL,
        'stderr': subprocess.DEVNULL,
        'close_fds': True,
        'env': env,
    }
    cmd = ['powershell', '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-Command', WINDOWS_RELAUNCH_PS1]
    # A job that forbids breaking away refuses the flag (access denied): then without it.
    for flags in ((_CREATE_NO_WINDOW | _CREATE_BREAKAWAY_FROM_JOB, _CREATE_NO_WINDOW) if os.name == 'nt' else (None,)):
        if flags is not None:
            kwargs['creationflags'] = flags
        try:
            popen(cmd, **kwargs)
            return True
        except OSError:
            continue
    return False
