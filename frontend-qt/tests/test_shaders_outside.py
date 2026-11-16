"""An IPA exported with the shaders outside: what it records, and the Wi-Fi share offering those shaders to the iPhone.

The iPhone app reads a game's shaders from Documents/games/<title ID>/msl when that folder exists (frontend-ios
EngineLaunchPlan), and Receive from PC writes each listed file at its path under that folder (PCTransfer.swift).
"""
from __future__ import annotations

import plistlib
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nspb_qt import wifi_share as ws  # noqa: E402
from nspb_qt.win import shell_export as se  # noqa: E402

TID = '0100000000010000'
OTHER = '01001F5010DFA000'


class FakeGame:
    def __init__(self, tid, name, archive_path=''):
        self.title_id, self.name, self.archive_path, self.output_dir, self.inputs = tid, name, archive_path, '', {}


def write_ipa(path: Path, outside: list[str] | None) -> None:
    info = {'CFBundleIdentifier': 'org.nxnative.shell'}
    if outside is not None:
        info[se.SHADERS_OUTSIDE_KEY] = outside
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr(f'Payload/{se.APP_NAME}/Info.plist', plistlib.dumps(info))


class ShadersOutsideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='shaders-outside-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / 'shell'
        self.fw = self.root / 'frameworks' / f'DmGame{TID}.framework'
        (self.fw / 'msl' / 'vk').mkdir(parents=True)
        (self.fw / 'msl' / 'b-cb2e91c138e3.img').write_bytes(b'S' * 3000)
        (self.fw / 'msl' / 'vk' / 'vk_shaders.tsv').write_text('x')
        (self.fw / 'msl' / '.wifi-share').mkdir()   # a transfer's links are never offered
        (self.fw / f'DmGame{TID}').write_bytes(b'exe')
        lib = se.ShellLibrary(games=[se.ShellGame(TID, 'Odyssey', str(self.fw))])
        lib.save(self.root)
        self.ipa = self.root / 'export' / se.IPA_NAME
        self.ipa.parent.mkdir(parents=True)
        se._outside_cache.clear()

    def test_shader_files_lists_the_msl_folder_with_paths_under_msl(self):
        self.assertEqual([r for r, _ in se.shader_files(self.fw)], ['msl/b-cb2e91c138e3.img', 'msl/vk/vk_shaders.tsv'])
        self.assertEqual(se.shader_files(self.tmp / 'none.framework'), [])

    def test_an_ipa_with_its_shaders_offers_none(self):
        write_ipa(self.ipa, None)
        self.assertEqual(se.ipa_shaders_outside(self.ipa), [])
        self.assertEqual(se.outside_shader_files(self.ipa, self.root), {})
        self.assertEqual(se.outside_shader_files(None, self.root), {})

    def test_an_ipa_without_them_offers_its_games_shaders(self):
        write_ipa(self.ipa, [TID.lower(), OTHER])   # OTHER has no framework here: nothing to offer for it
        got = se.outside_shader_files(self.ipa, self.root)
        self.assertEqual(list(got), [TID])
        self.assertEqual([r for r, _ in got[TID]], ['msl/b-cb2e91c138e3.img', 'msl/vk/vk_shaders.tsv'])

    def test_the_plist_records_the_games_and_forgets_them_when_the_shaders_are_in(self):
        app = self.tmp / 'DmShell.app'
        app.mkdir()
        (app / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'x'}))
        se._update_shell_plist(app, 'org.nxnative.shell', self.tmp, [OTHER, TID])
        self.assertEqual(plistlib.loads((app / 'Info.plist').read_bytes())[se.SHADERS_OUTSIDE_KEY], [TID, OTHER])
        se._update_shell_plist(app, 'org.nxnative.shell', self.tmp, [])
        self.assertNotIn(se.SHADERS_OUTSIDE_KEY, plistlib.loads((app / 'Info.plist').read_bytes()))

    def test_the_share_serves_the_shaders_beside_the_game_data(self):
        data = self.tmp / 'Jeux' / 'games' / TID
        data.mkdir(parents=True)
        (data / 'romfs.img').write_bytes(b'R' * 100)
        write_ipa(self.ipa, [TID])
        extras = se.outside_shader_files(self.ipa, self.root)
        games = ws.shared_games([FakeGame(TID, 'Odyssey', archive_path=str(data)), FakeGame(OTHER, 'Not built')], extras)
        self.assertEqual([g.title_id for g in games], [TID])
        self.assertEqual(games[0].files(), [('msl/b-cb2e91c138e3.img', 3000), ('msl/vk/vk_shaders.tsv', 1), ('romfs.img', 100)])

        server = ws.ShareServer(ipa=lambda: self.ipa, games=lambda: games, port=0, code='abc234')
        server.wanted_port = 18865
        server.start()
        self.addCleanup(server.stop)
        base = f'http://127.0.0.1:{server.port}/abc234/games/{TID}/'
        with urllib.request.urlopen(base + 'msl/b-cb2e91c138e3.img', timeout=10) as r:
            self.assertEqual(r.read(), b'S' * 3000)
        with urllib.request.urlopen(base + 'romfs.img', timeout=10) as r:
            self.assertEqual(r.read(), b'R' * 100)
        for rel in ('msl/../DmGame' + TID, f'DmGame{TID}', 'msl/.wifi-share'):
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(base + rel, timeout=10)

    def test_a_game_with_shaders_and_no_data_folder_is_offered_for_its_shaders(self):
        write_ipa(self.ipa, [TID])
        games = ws.shared_games([FakeGame(TID, 'Odyssey')], se.outside_shader_files(self.ipa, self.root))
        self.assertEqual(len(games), 1)
        self.assertIsNone(games[0].folder)
        self.assertEqual(games[0].path_of('msl/b-cb2e91c138e3.img'), self.fw / 'msl' / 'b-cb2e91c138e3.img')
        self.assertIsNone(games[0].path_of('romfs.img'))
        self.assertEqual(games[0].folders(), [self.fw / 'msl', self.fw / 'msl' / 'vk'])


if __name__ == '__main__':
    unittest.main()
