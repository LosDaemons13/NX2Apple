"""Progress lines arrive each second and take the place of the stage's previous one in the window; the file keeps one in 30."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

BEATS = ['[19:00:58] [4/7] shader split · splitting: 80%, 63/79 files, 0:31 · ETA 0:08',
         '[19:00:59] [4/7] shader split · splitting: 81%, 64/79 files, 0:32 · ETA 0:07',
         '[19:01:00] [4/7] shader split · splitting: 82%, 65/79 files, 0:33 · ETA 0:07']


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class ProgressBeatTests(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from nspb_qt import model as model_mod
        from nspb_qt.ui import MainWindow
        self.model_mod = model_mod
        self.app = QApplication.instance() or QApplication([])
        self.tmp = Path(tempfile.mkdtemp(prefix='beat-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.m = model_mod.Model()
        self.w = MainWindow(self.m)
        self.m.log_path = str(self.tmp / 'last-run.log')

        def cleanup():
            self.w.close()
            self.w.deleteLater()
            self.m.deleteLater()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)
            self.app.processEvents()

        self.addCleanup(cleanup)
        self.w.log.clear()

    def test_what_counts_as_a_beat(self):
        beat = self.model_mod._is_progress_beat
        self.assertTrue(beat('[4/7] shader split · splitting: 80%, 63/79 files, 0:31 · ETA 0:08'))
        self.assertTrue(beat('[5/7] shader build · compiling: 1:02:31'))
        for other in ('[4/7] shader split · splitting …', '[4/7] shader split …', '✓ [4/7] shader split (1:41)',
                      '✗ [4/7] shader split (1:41)', 'app name: Pokemon Pokopia; version: 1.0', 'progress: 63/79'):
            self.assertFalse(beat(other), other)

    def test_the_window_shows_one_live_line_per_stage_and_the_file_one_in_30_seconds(self):
        self.m._on_line('[19:00:28] [4/7] shader split · splitting …')
        for line in BEATS:
            self.m._on_line(line)
        self.app.processEvents()
        lines = self.w.log.toPlainText().splitlines()
        self.assertEqual(lines, ['[19:00:28] [4/7] shader split · splitting …', BEATS[-1]])
        self.m._on_line('[19:02:08] ✓ [4/7] shader split (1:41)')
        self.m._on_line('[19:02:09] [5/7] shader build: 0:01')
        self.app.processEvents()
        lines = self.w.log.toPlainText().splitlines()
        self.assertEqual(lines[1:], [BEATS[-1], '[19:02:08] ✓ [4/7] shader split (1:41)', '[19:02:09] [5/7] shader build: 0:01'],
                         'a line in between ends the replacing: the next beat starts a line of its own')
        written = Path(self.m.log_path).read_text(encoding='utf-8').splitlines()
        self.assertEqual([ln for ln in written if 'splitting:' in ln], [BEATS[0]], 'one beat in the file within 30 s')


if __name__ == '__main__':
    unittest.main()
