"""game_mods.py: a game's mods folder (games/<title ID>/mods), the zip and file import, switching a mod off with a dot, and what the
last build carries (the engine's main.mods.tsv in the build folder, the shell framework or a shared IPA)."""
from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nspb_qt import game_mods as gm  # noqa: E402

TID = '0100A3D008C5C000'
BID = '421c5411b487eb4d049dd065fec95477'
PCHTXT = f'@nsobid-{BID.upper()}73E8E598\n@flag offset_shift 0x100\n@enabled\n02b7a874 21008052\n@stop\n'


def make_zip(path: Path, files: dict[str, bytes | str]) -> Path:
    with zipfile.ZipFile(path, 'w') as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


class Import(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.mods = self.root / 'games' / TID / 'mods'

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_zip_of_variants_comes_in_switched_off(self):   # the layout of GameBanana's Scarlet and Violet FPS pack
        z = make_zip(self.root / 'pack.zip', {
            'Mods instructions and notes.txt': 'notes',
            '[60 FPS v4.0.0]/exefs/3.0.1-4.0.0.pchtxt': PCHTXT,
            '[Improved Graphic Quality v4.0.0]/exefs/4.0.0.pchtxt': PCHTXT,
            '[Dynamic FPS][Exlaunch]/exefs/subsdk3': b'NSO0',
            '[Dynamic FPS][Exlaunch]/exefs/main.npdm': b'META',
            '[Dynamic FPS][Exlaunch]/romfs/MaxFl4shBreath.ini': 'fps=60',
        })
        self.assertEqual(gm.import_zip(z, self.mods, TID), ['[60 FPS v4.0.0]', '[Dynamic FPS][Exlaunch]', '[Improved Graphic Quality v4.0.0]'])
        got = {m.name: m for m in gm.list_mods(self.mods, TID)}
        self.assertEqual(list(got), ['[60 FPS v4.0.0]', '[Dynamic FPS][Exlaunch]', '[Improved Graphic Quality v4.0.0]'])
        self.assertTrue(all(not m.enabled for m in got.values()))
        fps = got['[60 FPS v4.0.0]']
        self.assertEqual((fps.kind, fps.code_ids, fps.fits(BID), fps.fits('0' * 32)), ('code', {BID}, True, False))
        ex = got['[Dynamic FPS][Exlaunch]']
        self.assertEqual((ex.kind, ex.replaced), ('romfs', ['main.npdm', 'subsdk3']))
        self.assertFalse(gm.has_code_mods(self.mods, TID))
        fps = gm.set_enabled(fps, True, TID)
        self.assertTrue(fps.enabled and fps.path.name == '[60 FPS v4.0.0]')
        self.assertTrue(gm.has_code_mods(self.mods, TID))
        self.assertFalse(gm.set_enabled(fps, False, TID).enabled)
        self.assertTrue((self.mods / '.[60 FPS v4.0.0]').is_dir())

    def test_one_mod_comes_in_switched_on_and_replaces_its_old_copy(self):
        z = make_zip(self.root / 'Shadows.zip', {'exefs/a.pchtxt': PCHTXT})
        (self.mods / '.Shadows' / 'exefs').mkdir(parents=True)
        (self.mods / '.Shadows' / 'exefs' / 'old.pchtxt').write_text('old')
        self.assertEqual(gm.import_zip(z, self.mods, TID), ['Shadows'])
        self.assertEqual(sorted(p.name for p in self.mods.iterdir()), ['Shadows'])
        self.assertEqual([p.name for p in (self.mods / 'Shadows' / 'exefs').iterdir()], ['a.pchtxt'])

    def test_atmosphere_layouts_and_another_games_folder(self):
        z = make_zip(self.root / 'atmo.zip', {
            f'atmosphere/contents/{TID}/romfs/a.bin': 'x',
            'atmosphere/contents/0100000000010000/romfs/b.bin': 'y',
        })
        self.assertEqual(gm.import_zip(z, self.mods, TID), ['atmo'])
        m = gm.list_mods(self.mods, TID)[0]
        self.assertEqual(m.kind, 'romfs')
        z = make_zip(self.root / 'ips.zip', {f'atmosphere/exefs_patches/fps/{BID.upper()}.ips': b'PATCH\x00\x01\x04\x00\x01\x01EOF'})
        self.assertEqual(gm.import_zip(z, self.mods, TID), ['ips'])
        self.assertEqual(gm.read(self.mods / 'ips', TID).code_ids, {BID})

    def test_paths_outside_the_folder_are_left_out(self):
        z = make_zip(self.root / 'evil.zip', {'../escape/exefs/a.pchtxt': PCHTXT, 'good/exefs/a.pchtxt': PCHTXT})
        self.assertEqual(gm.import_zip(z, self.mods, TID), ['good'])
        self.assertFalse((self.root / 'games' / TID / 'escape').exists())

    def test_a_zip_without_a_mod(self):
        z = make_zip(self.root / 'readme.zip', {'readme.txt': 'nothing'})
        self.assertEqual(gm.import_zip(z, self.mods, TID), [])

    def test_a_single_patch_file_and_a_folder(self):
        f = self.root / '60fps.pchtxt'
        f.write_text(PCHTXT)
        self.assertEqual(gm.import_path(f, self.mods, TID), ['60fps'])
        self.assertTrue((self.mods / '60fps' / 'exefs' / '60fps.pchtxt').is_file())
        self.assertEqual(gm.import_path(self.root / 'notes.txt', self.mods, TID), [])
        src = self.root / 'Some mod'
        (src / 'romfs').mkdir(parents=True)
        (src / 'romfs' / 'a.bin').write_text('x')
        self.assertEqual(gm.import_folder(src, self.mods, TID), ['Some mod'])
        self.assertEqual(gm.read(self.mods / 'Some mod', TID).kind, 'romfs')

    def test_the_folder_of_a_game(self):
        self.assertEqual(gm.data_folder('', r'E:\Jeux\Scarlet', '', TID), Path(r'E:\Jeux\Scarlet', 'games', TID))
        self.assertEqual(gm.data_folder(r'E:\Jeux\Scarlet\games\X', '', '', TID), Path(r'E:\Jeux\Scarlet\games\X'))
        self.assertEqual(gm.data_folder('', '', r'E:\Jeux\Scarlet\base.nsp', TID), Path(r'E:\Jeux\Scarlet', 'games', TID))
        self.assertIsNone(gm.data_folder('', '', '', TID))


class LastBuild(unittest.TestCase):
    FIXUPS = f'# BUILD_ID\t{BID}\n'
    MODS = '# main: the code mods\n[60 FPS v4.0.0]\t0x2b7a874\t21008052\tx:11\n[60 FPS v4.0.0]\t0xb92780\tc10a94d2\tx:12\n'

    def test_the_shell_framework(self):
        with tempfile.TemporaryDirectory() as tmp:
            dm = Path(tmp, f'DmGame{TID}.framework', 'dm')
            dm.mkdir(parents=True)
            (dm / 'main.fixups.tsv').write_text(self.FIXUPS)
            self.assertEqual(gm.last_build(None, None, TID, tmp).mods, {})
            (dm / 'main.mods.tsv').write_text(self.MODS)
            b = gm.last_build(None, None, TID, tmp)
            self.assertEqual((b.build_id, b.mods), (BID, {'[60 FPS v4.0.0]': 2}))

    def test_a_shared_ipa_holds_every_games_framework(self):
        with tempfile.TemporaryDirectory() as tmp:
            ipa = make_zip(Path(tmp, 'NX2Apple.ipa'), {
                'Payload/DmShell.app/Frameworks/DmGame0100000000010000.framework/dm/main.fixups.tsv': '# BUILD_ID\t' + '1' * 32 + '\n',
                f'Payload/DmShell.app/Frameworks/DmGame{TID}.framework/dm/main.fixups.tsv': self.FIXUPS,
                f'Payload/DmShell.app/Frameworks/DmGame{TID}.framework/dm/main.mods.tsv': self.MODS,
            })
            b = gm.last_build(str(Path(tmp, 'none')), str(ipa), TID)
            self.assertEqual((b.build_id, b.mods), (BID, {'[60 FPS v4.0.0]': 2}))
            self.assertEqual(gm.last_build(None, str(ipa), '0100000000010000').build_id, '1' * 32)
            self.assertIsNone(gm.last_build(None, str(ipa), '0100000000020000').build_id)

    def test_the_build_folder_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp, 'patched_v786432')
            p.mkdir()
            (p / 'main.fixups.tsv').write_text(self.FIXUPS)
            (p / 'sdk.mods.tsv').write_text('# sdk\nother\t0x10\t00\tx:3\n')
            b = gm.last_build(tmp, None, TID, str(Path(tmp, 'none')))
            self.assertEqual((b.build_id, b.mods, b.where), (BID, {'other': 1}, str(p)))


if __name__ == '__main__':
    unittest.main()
