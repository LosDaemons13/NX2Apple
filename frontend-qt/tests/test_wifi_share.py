"""The Wi-Fi share serves the IPA and the games' data folders, nothing else, and lets a build replace a file mid-download."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nspb_qt import wifi_share as ws  # noqa: E402

TID = '0100000000010000'


class FakeGame:
    def __init__(self, tid, name, base='', output_dir='', archive_path=''):
        self.title_id, self.name, self.output_dir, self.archive_path = tid, name, output_dir, archive_path
        self.inputs = {'base': [base]} if base else {}


class WifiShareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='wifi-share-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ipa = self.tmp / 'export' / 'NX2Apple.ipa'
        self.ipa.parent.mkdir()
        self.ipa.write_bytes(b'IPA' * 1000)
        self.data = self.tmp / 'Jeux' / 'games' / TID
        (self.data / 'aoc' / '0100000000011001').mkdir(parents=True)
        (self.data / 'romfs.img').write_bytes(bytes(range(256)) * 400)
        (self.data / 'romfs.img.id').write_text('{"title": "x"}')
        (self.data / 'aoc' / '0100000000011001' / 'romfs.img').write_bytes(b'D' * 50)
        (self.data / 'romfs.img.part').write_bytes(b'half')   # a copy in progress is not offered
        (self.tmp / 'Jeux' / 'secret.txt').write_text('not offered')
        base = self.tmp / 'Jeux' / f'Super Mario Odyssey [{TID}][v0].nsp'
        base.write_bytes(b'')
        self.games = ws.shared_games([FakeGame(TID, 'Super Mario Odyssey', base=str(base)),
                                      FakeGame('0100000000020000', 'Not built yet')])
        self.server = ws.ShareServer(ipa=lambda: self.ipa, games=lambda: self.games, port=0, code='abc234')
        self.server.wanted_port = 18765
        self.server.start()
        self.addCleanup(self.server.stop)
        self.base = f'http://127.0.0.1:{self.server.port}/abc234/'

    def get(self, rel, headers=None):
        req = urllib.request.Request(self.base + rel, headers=headers or {})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()

    def status_of(self, url):
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_only_built_games_are_found_with_their_data_folder(self):
        self.assertEqual([(g.title_id, g.folder) for g in self.games], [(TID, self.data)])
        self.assertEqual(self.games[0].files(), [('aoc/0100000000011001/romfs.img', 50), ('romfs.img', 102400),
                                                 ('romfs.img.id', 14)])

    def test_the_catalog_lists_the_ipa_and_each_file(self):
        status, _, body = self.get('catalog.json')
        cat = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(cat['ipa']['size'], 3000)
        self.assertEqual(cat['games'][0]['title_id'], TID)
        self.assertEqual(cat['games'][0]['bytes'], 102400 + 14 + 50)

    def test_files_come_whole_or_from_a_byte_on(self):
        status, headers, body = self.get(f'games/{TID}/romfs.img')
        self.assertEqual((status, len(body)), (200, 102400))
        self.assertEqual(headers['Accept-Ranges'], 'bytes')
        status, headers, body = self.get(f'games/{TID}/romfs.img', {'Range': 'bytes=100000-'})
        self.assertEqual((status, body), (206, (bytes(range(256)) * 400)[100000:]))
        self.assertEqual(headers['Content-Range'], 'bytes 100000-102399/102400')
        status, headers, body = self.get('NX2Apple.ipa')
        self.assertEqual((status, body), (200, b'IPA' * 1000))
        self.assertIn('NX2Apple.ipa', headers['Content-Disposition'])

    def test_nothing_unlisted_and_nothing_without_the_code(self):
        port = self.server.port
        for url in (f'http://127.0.0.1:{port}/NX2Apple.ipa', f'http://127.0.0.1:{port}/zzzzzz/NX2Apple.ipa',
                    self.base + f'games/{TID}/romfs.img.part', self.base + f'games/{TID}/../../secret.txt',
                    self.base + 'games/0100000000020000/romfs.img', self.base + 'secret.txt'):
            self.assertEqual(self.status_of(url), 404, url)

    def test_the_page_offers_the_ipa_address_for_flarestore(self):
        status, headers, body = self.get('')
        page = body.decode('utf-8')
        self.assertEqual(status, 200)
        self.assertIn('href="NX2Apple.ipa"', page)
        self.assertIn(self.base + 'NX2Apple.ipa', page)
        self.assertIn('Super Mario Odyssey', page)

    def test_a_build_can_replace_the_ipa_while_it_is_being_sent(self):
        f, link = ws.open_snapshot(self.ipa)
        try:
            first = f.read(3)
            new = self.ipa.with_name('.NX2Apple.ipa.tmp')
            new.write_bytes(b'NEW')
            os.replace(new, self.ipa)   # the export's own step; with the IPA itself open it failed (access denied)
            self.assertEqual(first + f.read(), b'IPA' * 1000, 'the copy being sent stays whole')
        finally:
            f.close()
            if link is not None:
                link.unlink()
        self.assertEqual(self.ipa.read_bytes(), b'NEW')

    def test_a_transfer_leaves_no_link_behind(self):
        self.get('NX2Apple.ipa')
        self.get(f'games/{TID}/romfs.img')
        snaps = [p for d in (self.ipa.parent, self.data) for p in (d / ws.SNAPSHOTS).glob('*')]
        self.assertEqual(snaps, [])

    def test_the_exported_app_may_reach_the_pc_on_the_local_network(self):
        import plistlib
        from nspb_qt.win import shell_export as se
        app = self.tmp / 'DmShell.app'
        app.mkdir()
        with open(app / 'Info.plist', 'wb') as f:
            plistlib.dump({'CFBundleIdentifier': 'x', 'NSAppTransportSecurity': {'NSExceptionDomains': {}}}, f)
        se._update_shell_plist(app, 'org.nxnative.shell', self.tmp / 'engine')
        with open(app / 'Info.plist', 'rb') as f:
            info = plistlib.load(f)
        self.assertIn('Wi-Fi', info['NSLocalNetworkUsageDescription'])
        self.assertIs(info['NSAppTransportSecurity']['NSAllowsLocalNetworking'], True)
        self.assertEqual(info['NSAppTransportSecurity']['NSExceptionDomains'], {}, 'what the template had stays')

    def test_an_ipa_says_which_iphone_app_it_carries(self):
        """An IPA exported by an older launcher has an older iPhone app (no Receive from PC): the window offers to make it again."""
        import plistlib
        import zipfile
        from nspb_qt.win import shell_export as se
        app = self.tmp / 'DmShell.app'
        app.mkdir()
        (app / 'DmShell').write_bytes(b'\xcf\xfa\xed\xfe shell v2')
        with open(app / 'Info.plist', 'wb') as f:
            plistlib.dump({'CFBundleIdentifier': 'x'}, f)
        se._update_shell_plist(app, 'org.nxnative.shell', self.tmp / 'engine')
        ipa = self.tmp / 'new.ipa'
        with zipfile.ZipFile(ipa, 'w') as z:
            z.write(app / 'Info.plist', 'Payload/DmShell.app/Info.plist')
        self.assertEqual(se.ipa_template_id(ipa), se.shell_template_id(app))
        from nspb_qt import app_update
        self.assertEqual(se.ipa_app_version(ipa), app_update.APP_VERSION, 'the version the app shows in its settings')
        with open(app / 'Info.plist', 'rb') as f:
            self.assertRegex(plistlib.load(f)['DMExportedAt'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')
        old = self.tmp / 'old.ipa'
        with zipfile.ZipFile(old, 'w') as z:
            z.writestr('Payload/DmShell.app/Info.plist', plistlib.dumps({'CFBundleIdentifier': 'x'}))
        self.assertIsNone(se.ipa_template_id(old), 'exported before the id was recorded')
        self.assertIsNone(se.ipa_app_version(old))
        self.assertIsNone(se.ipa_template_id(self.tmp / 'missing.ipa'))
        self.assertIsNone(se.ipa_app_version(self.tmp / 'missing.ipa'))

    def test_addresses_are_local_ipv4(self):
        for a in ws.local_addresses():
            self.assertRegex(a, r'^\d+\.\d+\.\d+\.\d+$')
            self.assertFalse(a.startswith('127.'))


if __name__ == '__main__':
    unittest.main()
