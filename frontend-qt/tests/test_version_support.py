"""A build from a version the game's profile was not brought up on is asked about before the build and marked in the IPA.

Super Mario Odyssey 1.0.0 (the base game without its update) built with only a log line saying so, then crashed at start on
an iPhone; its profile registers 1.4.1. See nspb_qt/version_support.py.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nspb_qt import version_support as vs  # noqa: E402

TID = '0100000000010000'
GAME_TSV = (
    '# Super Mario Odyssey\n'
    f'title_id\t{TID}\n'
    'name\tSuper Mario Odyssey\n'
    'build\tv393216\t1.4.1\tmain=b424be150a8e7d78701cbe7a439d9ebf\tsdk=fcf93a41b08c5193a1410d262602dc62\n'
    'package\tv393216\n'
)


class VersionSupportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix='version-support-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.engine = self.tmp / 'engine'
        (self.engine / 'dm' / 'games' / TID).mkdir(parents=True)
        (self.engine / 'dm' / 'games' / TID / 'game.tsv').write_text(GAME_TSV, encoding='utf-8')

    def _framework(self, package_version: str, **extra) -> Path:
        fw = self.tmp / f'fw-{package_version}' / f'DmGame{TID}.framework'
        fw.mkdir(parents=True)
        data = {'schema': 1, 'title_id': TID, 'name': 'SUPER MARIO ODYSSEY', 'display_version': '1.0.0',
                'package_version': package_version, **extra}
        (fw / 'game.manifest.json').write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
        return fw

    def test_registered_reads_the_build_rows(self) -> None:
        self.assertEqual(vs.registered(self.engine, TID), [(393216, '1.4.1')])
        self.assertEqual(vs.registered(self.engine, TID.lower()), [(393216, '1.4.1')])
        self.assertEqual(vs.registered(self.engine, '0100000000020000'), [])
        self.assertEqual(vs.registered('', TID), [])

    def test_check_names_the_supported_versions_only_on_a_mismatch(self) -> None:
        self.assertIsNone(vs.check(self.engine, TID, 393216))
        self.assertIsNone(vs.check(self.engine, TID, None), 'an unknown version says nothing')
        self.assertIsNone(vs.check(self.engine, '0100000000020000', 0), 'a profile without build rows says nothing')
        m = vs.check(self.engine, TID, 0)
        self.assertEqual((m.title_id, m.have, m.supported), (TID, 0, ('1.4.1',)))

    def test_annotate_marks_the_manifest_and_rewrites_only_on_a_change(self) -> None:
        old = self._framework('v0')
        self.assertIs(vs.annotate_manifest(old, self.engine), False)
        data = json.loads((old / 'game.manifest.json').read_text(encoding='utf-8'))
        self.assertIs(data['version_supported'], False)
        self.assertEqual(data['supported_versions'], ['1.4.1'])
        self.assertEqual(data['display_version'], '1.0.0', 'the other keys stay')
        stamp = (old / 'game.manifest.json').stat().st_mtime_ns
        os.utime(old / 'game.manifest.json', ns=(stamp - 10**9, stamp - 10**9))
        self.assertIs(vs.annotate_manifest(old, self.engine), False)
        self.assertEqual((old / 'game.manifest.json').stat().st_mtime_ns, stamp - 10**9, 'same verdict: not rewritten')

        good = self._framework('v393216')
        self.assertIs(vs.annotate_manifest(good, self.engine), True)
        self.assertIs(json.loads((good / 'game.manifest.json').read_text(encoding='utf-8'))['version_supported'], True)

    def test_a_game_whose_shaders_are_captured_by_running_it_needs_a_mac(self) -> None:
        self.assertFalse(vs.needs_mac(self.engine, TID))
        (self.engine / 'dm' / 'games' / TID / 'vk_capture.tsv').write_text('# run-time capture list\n')
        self.assertTrue(vs.needs_mac(self.engine, TID))
        self.assertFalse(vs.needs_mac('', TID))

    def test_annotate_drops_an_old_verdict_when_the_profile_registers_nothing(self) -> None:
        fw = self._framework('v0', version_supported=False, supported_versions=['1.4.1'])
        (self.engine / 'dm' / 'games' / TID / 'game.tsv').write_text(f'title_id\t{TID}\n', encoding='utf-8')
        self.assertIsNone(vs.annotate_manifest(fw, self.engine))
        data = json.loads((fw / 'game.manifest.json').read_text(encoding='utf-8'))
        self.assertNotIn('version_supported', data)
        self.assertNotIn('supported_versions', data)
        self.assertIsNone(vs.annotate_manifest(self.tmp / 'missing.framework', self.engine))


try:
    import PySide6  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class PlannedVersionTests(unittest.TestCase):
    """Model.planned_version follows start_build's staging: the chosen update, else the newest one beside the base."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix='planned-version-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _plan(self, base: str, update: str = '', beside: tuple[str, ...] = ()):
        from nspb_qt.model import Model
        for name in (base, *beside):
            (self.tmp / name).write_bytes(b'')
        fake = types.SimpleNamespace(game_folder=None, base_path=str(self.tmp / base),
                                     update_path=str(self.tmp / update) if update else '')
        return Model.planned_version(fake)

    def test_base_alone_is_version_zero(self) -> None:
        self.assertEqual(self._plan(f'Super Mario Odyssey [{TID}][v0].nsp'), (TID, 0))

    def test_the_newest_update_beside_the_base_is_the_one_built(self) -> None:
        self.assertEqual(self._plan(f'Super Mario Odyssey [{TID}][v0].nsp', beside=(
            'Super Mario Odyssey™ [0100000000010800][v393216][1.4.1].nsp',
            'Super Mario Odyssey [0100000000010800][v65536].nsp',
            'Other Game [0100000000020800][v999999].nsp')), (TID, 393216))

    def test_the_chosen_update_wins_and_a_nameless_version_is_unknown(self) -> None:
        base = f'Super Mario Odyssey [{TID}][v0].nsp'
        self.assertEqual(self._plan(base, update='SMO [0100000000010800][v65536].nsp'), (TID, 65536))
        self.assertEqual(self._plan(base, update='SMO update.nsp'), (TID, None))

    def test_a_cartridge_image_may_carry_its_update(self) -> None:
        self.assertEqual(self._plan(f'Animal Crossing [{"01006F8002326000"}].xci'), ('01006F8002326000', None))
        self.assertIsNone(self._plan('Animal Crossing New Horizons.xci'), 'no title ID in the name: nothing known')


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class BuildButtonVersionPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication
        from nspb_qt.model import Model
        from nspb_qt.ui import MainWindow

        self.app = QApplication.instance() or QApplication([])
        self.m = Model()
        self.w = MainWindow(self.m)

        def cleanup() -> None:
            self.w.close()
            self.w.deleteLater()
            self.m.deleteLater()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)
            self.app.processEvents()

        self.addCleanup(cleanup)
        self.starts: list = []
        for target, value in (('start_build', lambda **k: self.starts.append(k)),
                              ('should_prompt_defender_before_build', lambda **k: False)):
            p = mock.patch.object(self.m, target, value)
            p.start()
            self.addCleanup(p.stop)

    def _click(self, mismatch, answer: bool) -> list:
        asked: list = []
        with mock.patch.object(self.m, 'unsupported_version', lambda title_id=None: mismatch), \
                mock.patch.object(self.w, '_confirm_unsupported_version', lambda mm: asked.append(mm) or answer):
            self.w._build_clicked()
        return asked

    def test_an_unsupported_version_asks_and_cancel_does_not_build(self) -> None:
        mm = vs.Mismatch(title_id=TID, have=0, supported=('1.4.1',))
        self.assertEqual(self._click(mm, answer=False), [mm])
        self.assertEqual(self.starts, [])

    def test_build_anyway_builds_once(self) -> None:
        mm = vs.Mismatch(title_id=TID, have=0, supported=('1.4.1',))
        self.assertEqual(self._click(mm, answer=True), [mm])
        self.assertEqual(len(self.starts), 1)

    def test_a_supported_version_builds_without_asking(self) -> None:
        self.assertEqual(self._click(None, answer=False), [])
        self.assertEqual(len(self.starts), 1)

    def test_the_dialog_names_the_game_the_versions_and_what_the_files_give(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        seen = {}

        def fake_exec(box):
            seen['text'] = box.informativeText()
            seen['buttons'] = [b.text() for b in box.buttons()]
            return 0

        with mock.patch.object(QMessageBox, 'exec', fake_exec):
            ok = self.w._confirm_unsupported_version(vs.Mismatch(title_id=TID, have=0, supported=('1.4.1',)))
        self.assertFalse(ok, 'closing the dialog is not a yes')
        self.assertIn('1.4.1', seen['text'])
        self.assertIn(self.m.t('build.version.base'), seen['text'])
        self.assertIn(self.m.t('build.version.anyway'), seen['buttons'])


if __name__ == '__main__':
    unittest.main()
