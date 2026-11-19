"""Games in alphabetical order: the collection, the build queue's dialog (and so the queue), and the games picked for the
shared IPA (title_order.py). The names are a real library's, as the dumps and shell.json give them."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nspb_qt.build_queue import QueueRow  # noqa: E402
from nspb_qt.title_order import alphabetical, sort_key  # noqa: E402

try:
    from PySide6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

LIBRARY = [   # (title ID, name), in the order the library had them: the last one added first
    ('01008DB008C2C000', 'Pokémon Shield'),
    ('0100ABF008968000', 'Pokémon Sword'),
    ('0100A3D008C5C000', 'Pokémon™ Scarlet'),
    ('0100F43008C44000', 'Pokémon Legends: Z-A'),
    ('040074A01BF12000', 'Donkey Kong Bananza'),
    ('010015100B514000', 'Super Mario Bros. Wonder'),
    ('01008F6008C5E000', 'Pokémon Violet'),
    ('0100DCA0064A6000', "Luigi's Mansion 3"),
    ('0100000000010000', 'SUPER MARIO ODYSSEY'),
    ('0400A3A01EE4C000', 'Pokemon Pokopia'),
    ('0400486024DEC000', 'The Legend of Zelda: Ocarina of Time'),
    ('0400C3F00006E000', 'Mario Kart World'),
]
ALPHABETICAL = ['Donkey Kong Bananza', "Luigi's Mansion 3", 'Mario Kart World', 'Pokémon Legends: Z-A', 'Pokemon Pokopia',
                'Pokémon™ Scarlet', 'Pokémon Shield', 'Pokémon Sword', 'Pokémon Violet', 'Super Mario Bros. Wonder',
                'SUPER MARIO ODYSSEY', 'The Legend of Zelda: Ocarina of Time']


class Game:
    def __init__(self, tid, name):
        self.title_id, self.name = tid, name


class TitleOrderTests(unittest.TestCase):
    def test_accents_case_and_trademarks_do_not_count_and_numbers_are_numbers(self):
        self.assertEqual([g.name for g in alphabetical(Game(t, n) for t, n in LIBRARY)], ALPHABETICAL)
        self.assertLess(sort_key('Mario Kart 8 Deluxe'), sort_key('Mario Kart 10'))
        self.assertLess(sort_key('Mario Kart 10'), sort_key('Mario Kart World'))
        self.assertEqual(sort_key('Pokémon™ Violet')[0], sort_key('POKEMON VIOLET')[0])
        self.assertLess(sort_key('Same', 'A'), sort_key('Same', 'B'), 'the title ID breaks a tie')
        self.assertEqual(sort_key('', '0100000000010000')[0], sort_key('0100000000010000')[0], 'no name: the title ID')

    def test_the_queue_dialog_lists_every_game_in_alphabetical_order(self):
        from nspb_qt.queue_dialog import initial_order
        rows = [QueueRow(t, n, 'new', True, True) for t, n in LIBRARY]
        rows[3] = QueueRow(LIBRARY[3][0], LIBRARY[3][1], 'running', False, False)
        waiting = [LIBRARY[0][0], LIBRARY[5][0]]
        self.assertEqual([r.name for r in initial_order(rows, waiting)], ALPHABETICAL,
                         'waiting games and the one being built take their alphabetical place')


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class TitleOrderInTheWindowTests(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        self.app = QApplication.instance() or QApplication([])
        self.tmp = Path(tempfile.mkdtemp(prefix='title-order-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_the_collection_is_alphabetical_and_the_filter_keeps_the_order(self):
        from PySide6.QtCore import QEvent
        from nspb_qt import library as lib
        from nspb_qt.model import Model
        from nspb_qt.ui import MainWindow
        m = Model()
        w = MainWindow(m)

        def cleanup():
            w.close()
            w.deleteLater()
            m.deleteLater()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)
            self.app.processEvents()

        self.addCleanup(cleanup)
        saved = m.library.games
        self.addCleanup(setattr, m.library, 'games', saved)
        m.library.games = [lib.LibraryGame(title_id=t, name=n) for t, n in LIBRARY]
        self.assertEqual([g.name for g in w._filtered_games()], ALPHABETICAL)
        w._search_query = 'pok'
        self.assertEqual([g.name for g in w._filtered_games()], [n for n in ALPHABETICAL if 'pok' in n.lower()])
        self.assertEqual([g.title_id for g in m.library.games], [t for t, _ in LIBRARY], 'the library file keeps its order')

    def test_the_games_for_the_shared_ipa_are_alphabetical(self):
        from nspb_qt.queue_dialog import ShellIpaSelectionDialog
        from nspb_qt.win import shell_export as se
        shell = se.ShellLibrary()
        for tid, name in LIBRARY:
            fw = self.tmp / 'frameworks' / f'DmGame{tid}.framework'
            fw.mkdir(parents=True)
            shell.games.append(se.ShellGame(title_id=tid, name=name, framework=str(fw)))
        shell.save(self.tmp)

        class FakeModel:
            shell_cache_path = str(self.tmp)

            @staticmethod
            def t(key, *a):
                return key

            @staticmethod
            def log(_s):
                pass

        dlg = ShellIpaSelectionDialog(FakeModel())
        self.addCleanup(dlg.deleteLater)
        self.assertEqual([r.name for r in dlg.rows], ALPHABETICAL)
        self.assertEqual([r.name for r in dlg.chosen], ALPHABETICAL, 'the IPA packs the picked games in this order')


if __name__ == '__main__':
    unittest.main()
