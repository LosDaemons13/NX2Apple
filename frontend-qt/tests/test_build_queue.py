"""Games built one after the other (build_queue.py and the window's steps): leave the PC on at night and the queue goes on."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nspb_qt.build_queue import BuildQueue, queue_rows  # noqa: E402


class FakeGame:
    def __init__(self, tid, name, inputs=True, built=False):
        self.title_id, self.name, self.can_rebuild, self.has_any_build = tid, name, inputs, built


class BuildQueueTests(unittest.TestCase):
    def test_order_each_game_once_and_the_outcomes(self):
        q = BuildQueue()
        q.set(['A', 'B', 'a', 'C'])
        self.assertEqual(q.waiting, ['A', 'B', 'C'])
        self.assertEqual(q.next(), 'A')
        q.extend(['A', 'D'])
        self.assertEqual(q.waiting, ['B', 'C', 'D'], 'the game being built is not queued twice')
        self.assertEqual(q.position(), (1, 4))
        q.finish_current('ok')
        self.assertEqual((q.next(), q.position()), ('B', (2, 4)))
        q.finish_current('failed')
        q.next()
        q.finish_current('skipped')
        self.assertEqual(q.counts(), {'ok': 1, 'failed': 1, 'skipped': 1})
        self.assertTrue(q.active)
        q.clear()
        self.assertFalse(q.active)
        self.assertIsNone(q.next())

    def test_rows_tick_new_games_and_leave_out_built_unsupported_and_missing_ones(self):
        games = [FakeGame('1', 'New'), FakeGame('2', 'Built', built=True), FakeGame('3', 'Old version'),
                 FakeGame('4', 'Gone', inputs=False), FakeGame('5', 'Running'), FakeGame('6', 'Waiting', built=True)]
        q = BuildQueue(waiting=['6'])
        rows = queue_rows(games, running_id='5', queue=q,
                          unsupported=lambda g: ('1.4.1',) if g.title_id == '3' else None)
        got = {r.name: (r.status, r.checked, r.enabled, r.supported) for r in rows}
        self.assertEqual(got, {
            'New': ('new', True, True, ''),
            'Built': ('built', False, True, ''),
            'Old version': ('version', False, True, '1.4.1'),
            'Gone': ('missing', False, False, ''),
            'Running': ('running', False, False, ''),
            'Waiting': ('queued', True, True, ''),
        })


try:
    import PySide6  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class QueueInTheWindowTests(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication
        from nspb_qt import library as lib
        from nspb_qt.model import Model
        from nspb_qt.ui import MainWindow

        self.app = QApplication.instance() or QApplication([])
        self.tmp = Path(tempfile.mkdtemp(prefix='build-queue-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.m = Model()
        self.w = MainWindow(self.m)

        def cleanup():
            self.w.close()
            self.w.deleteLater()
            self.m.deleteLater()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)
            self.app.processEvents()

        self.addCleanup(cleanup)
        games = []
        for tid, name in (('0100000000010000', 'Mario'), ('0400486024DEC000', 'Zelda'), ('0400A3A01EE4C000', 'Pokopia')):
            base = self.tmp / f'{name} [{tid}].nsp'
            base.write_bytes(b'')
            games.append(lib.LibraryGame(title_id=tid, name=name, inputs={'base': [str(base)]}))
        self.saved_games = self.m.library.games
        self.m.library.games = games
        self.addCleanup(setattr, self.m.library, 'games', self.saved_games)
        self.started: list[str] = []
        self.fail_to_start: set[str] = set()

    def _patch(self, target, name, value):
        p = mock.patch.object(target, name, value)
        p.start()
        self.addCleanup(p.stop)

    def _settle(self):
        for _ in range(5):
            self.app.processEvents()

    def _finish(self, ok=True):
        self.m.running = False
        self.w._on_finished(ok, '')
        self._settle()

    def _wire(self):
        def fake_build(**kw):
            tid = self.m.library.selected_id
            self.started.append(tid)
            if tid not in self.fail_to_start:
                self.m.running = True
        self._patch(self.w, '_build_clicked', fake_build)
        self._patch(self.m, 'load_game_from_library', lambda g: None)
        self._patch(self.m, 'cancel_build', mock.Mock())
        self._patch(self.m.library, 'save', lambda: None)

    def test_each_game_starts_when_the_one_before_ends_even_after_a_failure(self):
        self._wire()
        q = self.m.queue
        q.set(['0100000000010000', '0400486024DEC000', '0400A3A01EE4C000'])
        self.w._queue_start_next()
        self.assertEqual(self.started, ['0100000000010000'])
        self._finish(ok=False)
        self.assertEqual(self.started, ['0100000000010000', '0400486024DEC000'], 'a failed build does not stop the night')
        self._finish(ok=True)
        self._finish(ok=True)
        self.assertEqual(len(self.started), 3)
        self.assertFalse(q.active)
        self.assertEqual(q.counts(), {'ok': 2, 'failed': 1, 'skipped': 0})
        self.assertEqual(self.w.footer.text(), self.m.t('queue.done', 2, 1))

    def test_a_build_that_does_not_start_is_counted_failed_and_the_next_one_starts(self):
        self._wire()
        self.fail_to_start = {'0100000000010000'}
        self.m.queue.set(['0100000000010000', '0400486024DEC000'])
        self.w._queue_start_next()
        self.assertEqual(self.started, ['0100000000010000', '0400486024DEC000'])
        self.assertEqual(self.m.queue.results, [('0100000000010000', 'failed')])

    def test_stop_ends_the_queue_with_the_build(self):
        self._wire()
        self.m.queue.set(['0100000000010000', '0400486024DEC000'])
        self.w._queue_start_next()
        self.w._stop_build()
        self.m.cancel_build.assert_called_once()
        self._finish(ok=False)
        self.assertEqual(self.started, ['0100000000010000'], 'nothing more starts after Stop')
        self.assertFalse(self.m.queue.active)

    def test_a_build_started_by_hand_is_not_counted_as_queued(self):
        self._wire()
        self.assertFalse(self.w._queue_after_build(True))

    def test_the_dialog_builds_in_the_order_shown_and_the_arrows_change_it(self):
        from nspb_qt.build_queue import QueueRow
        from nspb_qt.queue_dialog import BuildQueueDialog
        rows = [QueueRow('A', 'Alpha', 'new', True, True), QueueRow('B', 'Bravo', 'built', False, True),
                QueueRow('C', 'Charlie', 'new', True, True), QueueRow('R', 'Running', 'running', False, False),
                QueueRow('D', 'Delta', 'queued', True, True)]
        dlg = BuildQueueDialog(self.m, rows, adding=True, waiting=['D'])
        self.addCleanup(dlg.deleteLater)
        self.assertEqual([r.title_id for r in dlg.rows], ['D', 'A', 'B', 'C', 'R'], 'waiting first, the fixed rows last')
        self.assertEqual(dlg.chosen, ['D', 'A', 'C'])
        dlg._move('C', -1)
        self._settle()
        self.assertEqual(dlg.chosen, ['D', 'A', 'C'], 'C passed B, which is not ticked')
        dlg._move('C', -1)
        self._settle()
        self.assertEqual(dlg.chosen, ['D', 'C', 'A'])
        dlg._move('D', -1)   # already first: nothing moves
        dlg._move('R', 1)    # the game being built does not move
        self._settle()
        self.assertEqual([r.title_id for r in dlg.rows], ['D', 'C', 'A', 'B', 'R'])
        dlg._toggle('B', True)
        self._settle()
        self.assertEqual(dlg.chosen, ['D', 'C', 'A', 'B'])
        self.assertEqual(dlg.start_btn.text(), self.m.t('queue.add', 4))


if __name__ == '__main__':
    unittest.main()
