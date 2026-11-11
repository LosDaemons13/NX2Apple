"""The GitHub publisher (nspb_qt/github_publish.py) against a fake GitHub: no network."""
from __future__ import annotations

import datetime as dt
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nspb_qt import github_publish as gp  # noqa: E402


class _Resp(io.BytesIO):
    def __init__(self, status: int, body: dict) -> None:
        super().__init__(json.dumps(body).encode())
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeGitHub:
    """Answers the calls publish() makes, and records them."""

    def __init__(self, *, repo_status: int = 200, private: bool = True, upload_status: int = 201) -> None:
        self.repo_status = repo_status
        self.private = private
        self.upload_status = upload_status
        self.calls: list[tuple[str, str, dict, int]] = []

    def __call__(self, req, timeout=None):
        body = req.data
        uploaded = 0
        if hasattr(body, 'read'):
            while True:
                chunk = body.read(8192)
                if not chunk:
                    break
                uploaded += len(chunk)
            body_json = {}
        else:
            body_json = json.loads(body) if body else {}
        self.calls.append((req.get_method(), req.full_url, body_json, uploaded))
        url, method = req.full_url, req.get_method()
        if url.endswith('/user') and method == 'GET':
            return _Resp(200, {'login': 'player'})
        if '/repos/player/' in url and method == 'GET':
            if self.repo_status != 200:
                raise urllib.error.HTTPError(url, self.repo_status, 'nope', {}, io.BytesIO(b'{"message": "Not Found"}'))
            return _Resp(200, {'private': self.private})
        if url.endswith('/user/repos') and method == 'POST':
            return _Resp(201, {'private': body_json.get('private', False)})
        if url.endswith('/releases') and method == 'POST':
            return _Resp(201, {'id': 7, 'html_url': 'https://github.com/player/nx2apple-ipa/releases/tag/t',
                               'upload_url': 'https://uploads.github.com/repos/player/nx2apple-ipa/releases/7/assets{?name,label}'})
        if url.startswith('https://uploads.github.com/'):
            if self.upload_status != 201:
                raise urllib.error.HTTPError(url, self.upload_status, 'bad', {}, io.BytesIO(b'{"message": "boom"}'))
            return _Resp(201, {'browser_download_url': 'https://github.com/player/nx2apple-ipa/releases/download/t/NX2Apple.ipa'})
        if method == 'DELETE':
            return _Resp(204, {})
        raise AssertionError(f'unexpected call {method} {url}')


class GitHubPublishTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.ipa = Path(self.tmp.name) / 'NX2Apple.ipa'
        self.ipa.write_bytes(b'PK' + bytes(50_000))
        self.when = lambda: dt.datetime(2026, 11, 11, 12, 30, 5)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_parse_repo(self) -> None:
        self.assertEqual(gp.parse_repo('player/nx2apple-ipa'), ('player', 'nx2apple-ipa'))
        self.assertEqual(gp.parse_repo('nx2apple-ipa'), ('', 'nx2apple-ipa'))
        self.assertIsNone(gp.parse_repo('a/b/c'))
        self.assertIsNone(gp.parse_repo(''))
        self.assertIsNone(gp.parse_repo('player/..'))

    def test_publishes_to_an_existing_private_repository(self) -> None:
        fake = FakeGitHub()
        sent: list[int] = []
        out = gp.publish(self.ipa, 'nx2apple-ipa', games=['Game A'], token='t', opener=fake, now=self.when,
                         progress=lambda s, total: sent.append(s))
        self.assertEqual(out.repo, 'player/nx2apple-ipa')
        self.assertEqual(out.latest_url, 'https://github.com/player/nx2apple-ipa/releases/latest/download/NX2Apple.ipa')
        self.assertTrue(out.download_url.endswith('/NX2Apple.ipa'))
        release = next(c for c in fake.calls if c[1].endswith('/releases') and c[0] == 'POST')
        self.assertEqual(release[2]['tag_name'], 'ipa-20261111-123005')
        self.assertEqual(release[2]['make_latest'], 'true')
        self.assertIn('- Game A', release[2]['body'])
        upload = next(c for c in fake.calls if c[1].startswith('https://uploads.github.com/'))
        self.assertTrue(upload[1].endswith('/assets?name=NX2Apple.ipa'))
        self.assertEqual(upload[3], self.ipa.stat().st_size)
        self.assertEqual(sent[-1], self.ipa.stat().st_size)

    def test_creates_a_missing_repository_private(self) -> None:
        fake = FakeGitHub(repo_status=404)
        gp.publish(self.ipa, 'player/nx2apple-ipa', token='t', opener=fake, now=self.when)
        create = next(c for c in fake.calls if c[1].endswith('/user/repos'))
        self.assertIs(create[2]['private'], True)
        self.assertIs(create[2]['auto_init'], True)

    def test_refuses_a_public_repository(self) -> None:
        fake = FakeGitHub(private=False)
        with self.assertRaises(gp.PublishError) as ctx:
            gp.publish(self.ipa, 'player/nx2apple-ipa', token='t', opener=fake, now=self.when)
        self.assertEqual(ctx.exception.key, 'github.publicRefused')
        self.assertFalse(any(c[1].endswith('/releases') for c in fake.calls))

    def test_a_failed_upload_removes_its_release(self) -> None:
        fake = FakeGitHub(upload_status=500)
        with self.assertRaises(gp.PublishError):
            gp.publish(self.ipa, 'player/nx2apple-ipa', token='t', opener=fake, now=self.when)
        deletes = [c[1] for c in fake.calls if c[0] == 'DELETE']
        self.assertEqual(len(deletes), 2)
        self.assertTrue(deletes[0].endswith('/releases/7'))
        self.assertTrue(deletes[1].endswith('/git/refs/tags/ipa-20261111-123005'))

    def test_missing_ipa_and_missing_token(self) -> None:
        with self.assertRaises(gp.PublishError) as ctx:
            gp.publish(Path(self.tmp.name) / 'none.ipa', 'r', token='t', opener=FakeGitHub())
        self.assertEqual(ctx.exception.key, 'github.noIpa')


if __name__ == '__main__':
    unittest.main()
