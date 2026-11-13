"""The amiibo the in-game menu offers (nspb_qt/win/amiibo_db.py, patch 0127): AmiiboAPI's list, compact, and each game's dm/amiibo.tsv."""
from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

QT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(QT))

from nspb_qt.win import amiibo_db  # noqa: E402

ODYSSEY = '0100000000010000'


def rows(text: str) -> list[list[str]]:
    return [line.split('\t') for line in text.splitlines() if not line.startswith('#')]


class GameListTests(unittest.TestCase):
    def test_every_amiibo_once_with_what_it_does_in_this_game(self):
        got = rows(amiibo_db.game_list(ODYSSEY))
        self.assertEqual(len(got), len(amiibo_db.load()['amiibo']))
        self.assertTrue(all(len(r) == 4 and re.fullmatch(r'[0-9a-f]{16}', r[0]) and r[1] for r in got), 'ID, name, series, use: no tab inside a field')
        self.assertEqual(len({r[0] for r in got}), len(got))
        wedding = next(r for r in got if r[0] == '0000000003710102')
        self.assertEqual((wedding[1], wedding[2]), ('Mario - Wedding', 'Super Mario Bros.'))
        self.assertIn('costume', wedding[3])
        self.assertGreaterEqual(sum(1 for r in got if r[3]), 25, 'Super Mario Odyssey uses about thirty')

    def test_a_game_the_list_does_not_know_still_gets_every_amiibo(self):
        got = rows(amiibo_db.game_list('0400486024DEC000'))
        self.assertEqual(len(got), len(amiibo_db.load()['amiibo']))
        self.assertFalse(any(r[3] for r in got))

    def test_the_file_names_its_source_and_the_count_it_returns(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / 'amiibo.tsv'
            used = amiibo_db.write_game_list(ODYSSEY, out)
            text = out.read_bytes().decode('utf-8')
        self.assertNotIn('\r', text)
        self.assertIn('AmiiboAPI', text.splitlines()[1])
        self.assertEqual(used, sum(1 for r in rows(text) if r[3]))


class FrenchTests(unittest.TestCase):
    """AmiiboAPI is in English; amiibo_i18n.json has the French (the player asked for it)."""

    def test_every_series_edition_and_use_has_its_french(self):
        db, fr = amiibo_db.load(), amiibo_db.translations()['fr']
        uses = {part for text in db['texts'] for part in text.split('; ')}
        self.assertEqual(uses - set(fr['uses']), set())
        self.assertEqual(set(db['series'].values()) - set(fr['series']), set())
        editions = {name.partition(' - ')[2] for _, name in db['amiibo'] if ' - ' in name}
        self.assertEqual(editions - set(fr['suffixes']), set())

    def test_the_french_list_of_odyssey(self):
        got = {r[0]: r for r in rows(amiibo_db.game_list(ODYSSEY, tr=amiibo_db.translations()['fr']))}
        self.assertEqual(got['0000000003710102'][1:], ['Mario - Mariage', 'Super Mario Bros.',
                                                       'Recevoir un costume du personnage ; Devenir invincible un moment'])
        self.assertEqual(got['01810000037d0002'][1], 'Marie', 'Isabelle (Super Smash Bros. series) is Marie')
        self.assertEqual(got['3740000103741402'][1:3], ['Céréales Super Mario', 'Autres'])

    def test_each_language_gets_its_file_beside_the_english_one(self):
        with tempfile.TemporaryDirectory() as td:
            used = amiibo_db.write_game_lists(ODYSSEY, Path(td))
            names = sorted(p.name for p in Path(td).iterdir())
            fr = (Path(td) / 'amiibo.fr.tsv').read_text(encoding='utf-8')
        self.assertEqual(names, ['amiibo.fr.tsv', 'amiibo.tsv'])
        self.assertIn('Mario - Mariage', fr)
        self.assertGreaterEqual(used, 25)


class GenerateTests(unittest.TestCase):
    def test_uses_are_merged_per_game_and_their_texts_kept_once(self):
        amiibo = {'amiibos': {'0x0000000003710102': {'name': 'Mario - Wedding'}, '0x0002000003720102': {'name': 'Peach - Wedding'}},
                  'amiibo_series': {'0x01': 'Super Mario Bros.'}}
        games = {'amiibos': {
            '0x0000000003710102': {'gamesSwitch': [
                {'gameName': 'Super Mario Odyssey', 'gameID': ['0100000000010000'], 'amiiboUsage': [{'Usage': 'Costume', 'write': False}]},
                {'gameName': 'Super Mario Odyssey', 'gameID': ['0100000000010000'], 'amiiboUsage': [{'Usage': 'Invincibility', 'write': False}]}]},
            '0x0002000003720102': {'gamesSwitch': [
                {'gameName': 'Super Mario Odyssey', 'gameID': ['0100000000010000'], 'amiiboUsage': [{'Usage': 'Costume', 'write': False}]}],
                'gamesSwitch2': [{'gameName': 'Other', 'gameID': ['0400000000000000'], 'amiiboUsage': []}]},
        }}
        db = amiibo_db.generate(amiibo, games, 'MIT')
        self.assertEqual(db['series'], {'01': 'Super Mario Bros.'})
        self.assertEqual(db['texts'], ['Costume', 'Costume; Invincibility'])
        odyssey = next(g for g in db['games'] if g['name'] == 'Super Mario Odyssey')
        self.assertEqual(odyssey['uses'], {'0000000003710102': 1, '0002000003720102': 0})
        got = {r[0]: r for r in rows(amiibo_db.game_list('0100000000010000', db))}
        self.assertEqual(got['0000000003710102'][3], 'Costume; Invincibility')
        self.assertEqual(got['0002000003720102'][2], 'Super Mario Bros.')


class WiringTests(unittest.TestCase):
    def test_the_build_writes_the_list_the_menu_reads(self):
        build = (QT / 'nspb_qt/win/build_app.py').read_text(encoding='utf-8')
        menu = (QT / 'nspb_qt/win/ios/Launcher.m').read_text(encoding='utf-8')
        self.assertIn("amiibo_db.write_game_lists(gp('title_id') or game, dmres)", build)
        self.assertIn('@"amiibo.tsv"', menu)
        self.assertIn('@"amiibo.%@.tsv"', menu, "the iPhone's language first")
        for call in ('dm_amiibo_offered()', 'dm_amiibo_place(', 'dm_amiibo_remove()', 'dm_amiibo_placed('):
            self.assertIn(call, menu)


if __name__ == '__main__':
    unittest.main()
