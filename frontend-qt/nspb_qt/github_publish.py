"""Publish the shared app's IPA to a release of the player's own private GitHub repository.

A sideloading app that signs with the player's certificate (FlareStore, for one) only needs the IPA. Uploading it to a
release lets the player fetch it on the iPhone: open the release while signed in to GitHub, download `NX2Apple.ipa`
and hand it to the signing app.

The IPA holds the player's own rewritten game code, so it only ever goes to a private repository: a missing repository
is created private, a public one is refused. The sign-in comes from GitHub CLI (`gh auth token`) or from GITHUB_TOKEN or
GH_TOKEN. Standard library only.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable

API = 'https://api.github.com'
ASSET_NAME = 'NX2Apple.ipa'
DEFAULT_REPO_NAME = 'nx2apple-ipa'
#: GitHub refuses a release asset of 2 GiB or more.
MAX_ASSET = 2 * 1024 ** 3 - 1
SETTINGS_FILE = 'github_publish.json'
_REPO_RE = re.compile(r'^(?:([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/)?([A-Za-z0-9._-]{1,100})$')


class PublishError(Exception):
    """`key` is a localization key of frontend/l10n (github.*), or '' when `detail` says it all."""

    def __init__(self, key: str = '', detail: str = '') -> None:
        super().__init__(detail or key)
        self.key = key
        self.detail = detail


@dataclass(frozen=True)
class Published:
    release_url: str
    download_url: str
    latest_url: str
    repo: str


def parse_repo(text: str) -> tuple[str, str] | None:
    """('owner', 'name') from 'owner/name', ('', 'name') from a bare name, None when it is not a repository name."""
    m = _REPO_RE.match((text or '').strip())
    if not m or m.group(2) in ('.', '..'):
        return None
    return (m.group(1) or ''), m.group(2)


def load_settings(state_dir: Path) -> dict:
    try:
        data = json.loads((Path(state_dir) / SETTINGS_FILE).read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(state_dir: Path, settings: dict) -> None:
    try:
        Path(state_dir).mkdir(parents=True, exist_ok=True)
        (Path(state_dir) / SETTINGS_FILE).write_text(json.dumps(settings, indent=2), encoding='utf-8')
    except OSError:
        pass


def find_token() -> str | None:
    """A GitHub token: GITHUB_TOKEN or GH_TOKEN, else GitHub CLI's own sign-in."""
    for var in ('GITHUB_TOKEN', 'GH_TOKEN'):
        value = os.environ.get(var, '').strip()
        if value:
            return value
    gh = shutil.which('gh')
    if not gh and sys.platform == 'win32':
        candidate = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'GitHub CLI' / 'gh.exe'
        gh = str(candidate) if candidate.is_file() else None
    if not gh:
        return None
    kwargs: dict = {}
    if sys.platform == 'win32':
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    try:
        r = subprocess.run([gh, 'auth', 'token'], capture_output=True, text=True, timeout=20, **kwargs)
    except (OSError, subprocess.SubprocessError):
        return None
    token = (r.stdout or '').strip()
    return token if r.returncode == 0 and token else None


class _Client:
    def __init__(self, token: str, opener: Callable = urllib.request.urlopen) -> None:
        self.token = token
        self.opener = opener

    def request(self, method: str, url: str, body: dict | None = None, *, data: BinaryIO | None = None,
                length: int | None = None, content_type: str = 'application/json', timeout: float = 60.0) -> tuple[int, dict]:
        headers = {
            'Accept': 'application/vnd.github+json',
            'Authorization': f'Bearer {self.token}',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': 'NX2Apple-publisher',
        }
        payload = None
        if body is not None:
            payload = json.dumps(body).encode('utf-8')
            headers['Content-Type'] = content_type
        elif data is not None:
            payload = data
            headers['Content-Type'] = content_type
            headers['Content-Length'] = str(length or 0)
        req = urllib.request.Request(url, data=payload, method=method, headers=headers)
        try:
            with self.opener(req, timeout=timeout) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raw = e.read() or b''
            try:
                return e.code, json.loads(raw) if raw else {}
            except ValueError:
                return e.code, {'message': raw.decode('utf-8', 'replace')[:300]}
        except (urllib.error.URLError, OSError) as e:
            raise PublishError('', f'GitHub unreachable: {e}') from e


def _fail(status: int, payload: dict, what: str) -> PublishError:
    message = str(payload.get('message') or '') if isinstance(payload, dict) else ''
    return PublishError('', f'{what}: HTTP {status} {message}'.strip())


class _Progress:
    """A file read in blocks by http.client, reporting how much has gone."""

    def __init__(self, path: Path, report: Callable[[int, int], None]) -> None:
        self._f = open(path, 'rb')
        self.total = path.stat().st_size
        self.sent = 0
        self._report = report

    def read(self, size: int = -1) -> bytes:
        chunk = self._f.read(size if size and size > 0 else 1024 * 1024)
        self.sent += len(chunk)
        self._report(self.sent, self.total)
        return chunk

    def close(self) -> None:
        self._f.close()


def _owner_and_repo(client: _Client, repo: str) -> tuple[str, str, str]:
    parsed = parse_repo(repo or DEFAULT_REPO_NAME)
    if parsed is None:
        raise PublishError('', f'not a repository name: {repo!r}')
    status, me = client.request('GET', f'{API}/user')
    if status != 200:
        raise _fail(status, me, 'GitHub sign-in')
    login = str(me.get('login') or '')
    owner, name = parsed
    return (owner or login), name, login


def ensure_private_repo(client: _Client, owner: str, name: str, login: str) -> None:
    status, repo = client.request('GET', f'{API}/repos/{owner}/{name}')
    if status == 200:
        if not repo.get('private'):
            raise PublishError('github.publicRefused')
        return
    if status != 404:
        raise _fail(status, repo, 'repository')
    body = {'name': name, 'private': True, 'auto_init': True,
            'description': 'Personal NX2Apple builds (private: they hold my own game code).'}
    url = f'{API}/user/repos' if owner.lower() == login.lower() else f'{API}/orgs/{owner}/repos'
    status, made = client.request('POST', url, body)
    if status not in (200, 201):
        raise _fail(status, made, 'creating the private repository')
    if not made.get('private'):
        raise PublishError('github.publicRefused')


def release_notes(games: list[str], when: _dt.datetime) -> str:
    lines = [f'NX2Apple shared app, built {when:%Y-%m-%d %H:%M}.', '']
    if games:
        lines.append('Games inside:')
        lines += [f'- {g}' for g in games]
        lines.append('')
    lines += [
        'Install: download NX2Apple.ipa on the iPhone (signed in to GitHub) and open it in your signing app.',
        'Game data (romfs.img) goes to the app in the Files app, as the Windows launcher explains.',
        '',
        'Keep this repository private: the IPA holds your own game code.',
    ]
    return '\n'.join(lines)


def publish(ipa: str | os.PathLike, repo: str, *, games: list[str] | None = None, token: str | None = None,
            progress: Callable[[int, int], None] = lambda sent, total: None,
            now: Callable[[], _dt.datetime] = _dt.datetime.now, opener: Callable = urllib.request.urlopen) -> Published:
    """Upload `ipa` to a new release of the private repository `repo` ('owner/name' or a bare name under the
    signed-in account) and mark it the latest. Raises PublishError."""
    path = Path(ipa)
    if not path.is_file():
        raise PublishError('github.noIpa')
    size = path.stat().st_size
    if size > MAX_ASSET:
        raise PublishError('', f'{path.name} is {size / 1024 ** 3:.2f} GB, GitHub takes files under 2 GB')
    token = token or find_token()
    if not token:
        raise PublishError('github.noToken')
    client = _Client(token, opener)
    owner, name, login = _owner_and_repo(client, repo)
    ensure_private_repo(client, owner, name, login)

    when = now()
    tag = f'ipa-{when:%Y%m%d-%H%M%S}'
    count = len(games or [])
    title = f'NX2Apple {when:%Y-%m-%d %H:%M}' + (f' ({count} game{"s" if count != 1 else ""})' if count else '')
    status, release = client.request('POST', f'{API}/repos/{owner}/{name}/releases', {
        'tag_name': tag, 'name': title, 'body': release_notes(games or [], when),
        'draft': False, 'prerelease': False, 'make_latest': 'true',
    })
    if status not in (200, 201):
        raise _fail(status, release, 'creating the release')

    upload = str(release.get('upload_url') or '').split('{', 1)[0]
    if not upload:
        raise PublishError('', 'GitHub gave no upload address')
    stream = _Progress(path, progress)
    try:
        status, asset = client.request('POST', f'{upload}?name={urllib.parse.quote(ASSET_NAME)}', data=stream,  # type: ignore[arg-type]
                                       length=size, content_type='application/octet-stream', timeout=600.0)
    finally:
        stream.close()
    if status not in (200, 201):
        # Leave no empty release behind. A failure here changes nothing for the player: the upload failed either way.
        for url in (f'{API}/repos/{owner}/{name}/releases/{release.get("id")}', f'{API}/repos/{owner}/{name}/git/refs/tags/{tag}'):
            try:
                client.request('DELETE', url)
            except PublishError:
                pass
        raise _fail(status, asset, 'uploading the IPA')

    return Published(
        release_url=str(release.get('html_url') or f'https://github.com/{owner}/{name}/releases/tag/{tag}'),
        download_url=str(asset.get('browser_download_url') or ''),
        latest_url=f'https://github.com/{owner}/{name}/releases/latest/download/{ASSET_NAME}',
        repo=f'{owner}/{name}',
    )
