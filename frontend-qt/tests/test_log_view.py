"""The build log: what is an error or a warning, the lines that say why a build failed, and a log that stays where the reader
is (log_lines.py, log_view.py). The lines are from a real queue on Windows (Pokémon Legends: Z-A, Super Mario Bros. Wonder)."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nspb_qt import log_lines  # noqa: E402

try:
    from PySide6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

ZA_FAILURE = """\
[14:06:42] [5/8] shader split · checking the inputs …
[14:06:42] [5/8] shader split · building the Mac host for the game's Oodle decoder …
[14:11:30] [5/8] shader split · splitting: 99%, 83/83 files, 4:48 · ETA 0:00
[14:11:31] ✗ [5/8] shader split (4:49)
[RED] arc/data.trpfs: the game's decoder in the Mac host failed on a 25265873 → 72893492 byte stream; ---- host output ----
[RED] DM_OODLE_SERVE: request 5: emulated heap full (96 MB)
[RED] DM_OODLE_SERVE: request 5 (25265873 -> 72893492 bytes) failed
the game's own Oodle or LZ5 decoder, run in the Windows emulator (nspb_qt/win/oodle_emu.py), could not decode this game's shader archives (each file in E:\\Switch\\Jeux\\0100F43008C44000_build\\logs\\shader_split.log)
"""


class LogLinesTests(unittest.TestCase):
    def test_errors_warnings_and_plain_lines(self):
        k = log_lines.kind
        for line in ('[RED] arc/data.trpfs: the game\'s decoder in the Mac host failed on a 21009849 → 70786896 byte stream',
                     '[dm] [RED] DM_OODLE_SERVE: request 9895: emulated heap full (96 MB)',
                     '[11:50:26] ✗ [6/9] shader split (9:49)',
                     'Traceback (most recent call last):',
                     'OSError: [Errno 28] No space left on device',
                     'subprocess.CalledProcessError: Command returned non-zero exit status 1.',
                     'export-shell: ERROR: pack_ipa.py failed: disk full',
                     'clang: error: no such file or directory'):
            self.assertEqual(k(line), log_lines.ERROR, line)
        for line in ('[16:46:05] ⚠ [6/8] iOS shaders (52:21): no pipeline archive',
                     'warning: unused variable',
                     'DeprecationWarning: the old call',
                     '[shim] could not prepare the Windows shim: denied'):
            self.assertEqual(k(line), log_lines.WARNING, line)
        for line in ('[12:21:31] ✓ [7/9] iOS shaders (29:16): 16,268 of 16,268 shaders ready (0 from the cache)',
                     '[11:40:37] [6/9] shader split · splitting …',
                     'export-shell:   IPA created successfully!',
                     'export-shell-after-archive: ===== Export finished: ok=True =====',
                     'packed: 324 entries, stored 0.00 GB, deflated 57.63 GB',
                     'File de compilation : Pokémon Violet (1 sur 8)',
                     ''):
            self.assertEqual(k(line), log_lines.PLAIN, line)

    def test_the_failure_lines_start_at_the_stage_that_failed_and_say_why(self):
        self.assertEqual(log_lines.failure_lines(ZA_FAILURE), [
            '✗ [5/8] shader split (4:49)',
            'arc/data.trpfs: the game\'s decoder in the Mac host failed on a 25265873 → 72893492 byte stream; ---- host output ----',
            'DM_OODLE_SERVE: request 5: emulated heap full (96 MB)',
            'DM_OODLE_SERVE: request 5 (25265873 -> 72893492 bytes) failed',
        ])

    def test_without_a_failed_stage_the_last_error_lines(self):
        text = '[RED] an early one\nsomething\nTraceback (most recent call last):\n  File "x.py"\nOSError: [Errno 28] No space left\n'
        self.assertEqual(log_lines.failure_lines(text, limit=2), ['Traceback (most recent call last):', 'OSError: [Errno 28] No space left'])
        self.assertEqual(log_lines.failure_lines('all went well\n'), [])
        self.assertEqual(log_lines.failure_lines('[RED] ' + 'x' * 500, width=50), ['x' * 49 + '…'])


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class LogViewTests(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        self.app = QApplication.instance() or QApplication([])
        from nspb_qt.log_view import LogView, LogWindow
        self.LogWindow = LogWindow
        self.view = LogView()
        self.view.resize(500, 200)
        self.view.show()
        self.addCleanup(self.view.deleteLater)

    def _fill(self, n=200):
        for i in range(n):
            self.view.append_text(f'[12:00:{i % 60:02d}] line {i}\n')
        self.app.processEvents()

    def _color(self, block_number):
        b = self.view.document().findBlockByNumber(block_number)
        return b.begin().fragment().charFormat().foreground().color().name()

    def test_it_follows_the_end_only_from_the_end(self):
        self._fill()
        sb = self.view.verticalScrollBar()
        self.assertEqual(sb.value(), sb.maximum(), 'at the end it follows the new lines')
        sb.setValue(10)
        for beat in ('[12:01:00] [6/9] shader split · splitting: 10%', '[12:01:01] [6/9] shader split · splitting: 11%'):
            self.view.replace_beat(beat + '\n')
        self.view.append_text('[12:01:02] a new line\n')
        self.app.processEvents()
        self.assertEqual(sb.value(), 10, 'scrolled up, the reader stays where they are')
        sb.setValue(sb.maximum())
        self.view.append_text('[12:01:03] another\n')
        self.app.processEvents()
        self.assertEqual(sb.value(), sb.maximum(), 'back at the end, it follows again')

    def test_a_selection_survives_new_lines(self):
        self._fill(20)
        c = self.view.textCursor()
        c.setPosition(5)
        c.setPosition(15, c.MoveMode.KeepAnchor)
        self.view.setTextCursor(c)
        self.view.append_text('[12:01:02] a new line\n')
        self.view.replace_beat('[12:01:03] [6/9] shader split · splitting: 11%\n')
        self.assertEqual((self.view.textCursor().selectionStart(), self.view.textCursor().selectionEnd()), (5, 15))

    def test_errors_are_red_warnings_amber_and_a_beat_still_replaces_the_last_one(self):
        from nspb_qt import style
        self.view.append_text(ZA_FAILURE)
        self.view.append_text('[16:46:05] ⚠ [6/8] iOS shaders (52:21)\n')
        lines = self.view.toPlainText().splitlines()
        self.assertEqual(self._color(lines.index('[14:11:31] ✗ [5/8] shader split (4:49)')), style.RED.lower())
        self.assertEqual(self._color(lines.index('[RED] DM_OODLE_SERVE: request 5: emulated heap full (96 MB)')), style.RED.lower())
        self.assertEqual(self._color(len(lines) - 1), style.AMBER.lower())
        plain = self._color(0)
        self.assertNotIn(plain, (style.RED.lower(), style.AMBER.lower()))
        self.view.replace_beat('[17:00:00] [7/8] game framework: 0:01\n')
        self.view.replace_beat('[17:00:01] [7/8] game framework: 0:02\n')
        self.assertEqual(self.view.toPlainText().splitlines()[-2:], ['[16:46:05] ⚠ [6/8] iOS shaders (52:21)', '[17:00:01] [7/8] game framework: 0:02'])
        self.assertNotEqual(self._color(len(lines)), style.AMBER.lower(), 'a line after a warning is not amber')

    def test_the_larger_window_shows_the_same_log_and_goes_to_an_error(self):
        self._fill(50)
        self.view.append_text(ZA_FAILURE)
        self._fill(50)
        win = self.LogWindow(lambda key, *a: key, self.view)
        self.addCleanup(win.deleteLater)
        win.show_log()
        self.app.processEvents()
        self.assertEqual(win.view.toPlainText(), self.view.toPlainText())
        self.assertEqual(win.windowTitle(), 'build.log')
        first = self.view.first_error_block(0)
        self.assertEqual(self.view.document().findBlockByNumber(first).text(), '[14:11:31] ✗ [5/8] shader split (4:49)')
        win.show_log(first)
        self.app.processEvents()
        self.assertEqual(win.view.textCursor().selectedText(), '[14:11:31] ✗ [5/8] shader split (4:49)')
        win.previous_error()
        self.assertEqual(win.view.textCursor().blockNumber(), win.view.last_error_block(), 'before the first: around from the end')
        win.previous_error()
        self.assertEqual(win.view.textCursor().selectedText(), '[RED] DM_OODLE_SERVE: request 5: emulated heap full (96 MB)')
        win.close()


if __name__ == '__main__':
    unittest.main()
