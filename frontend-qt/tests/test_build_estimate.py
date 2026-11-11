"""Build time estimates: from the profile's shader count and this PC's measured rate, shorter for a game built before."""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nspb_qt import build_estimate as be  # noqa: E402

TID = '0100000000010000'


class FakeGame:
    def __init__(self, tid, base):
        self.title_id, self.output_dir, self.inputs = tid, '', {'base': [str(base)]}


class BuildEstimateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='estimate-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        prof = self.tmp / 'engine' / 'dm' / 'games' / TID
        prof.mkdir(parents=True)
        (prof / 'shader_map.tsv').write_text('# header\n' + ''.join(f'k{i}\tv\n' for i in range(1000)) + '\n')
        self.base = self.tmp / 'Jeux' / f'Mario [{TID}].nsp'
        self.base.parent.mkdir()
        self.base.write_bytes(b'')
        self.game = FakeGame(TID, self.base)

    def test_shaders_come_from_the_profile(self):
        self.assertEqual(be.shader_count(self.tmp / 'engine', TID), 1000)
        self.assertIsNone(be.shader_count(self.tmp / 'engine', '0100000000020000'))

    def test_a_first_build_counts_every_shader_and_a_rebuild_a_share(self):
        first = be.estimate_seconds(self.tmp / 'engine', self.game, 0.5)
        self.assertEqual(first, be.OVERHEAD_SEC + 500)
        (self.base.parent / f'{TID}_build' / 'shader').mkdir(parents=True)
        (self.base.parent / f'{TID}_build' / 'shader' / 'lib.metallib').write_bytes(b'x')
        again = be.estimate_seconds(self.tmp / 'engine', self.game, 0.5)
        self.assertEqual(again, be.OVERHEAD_SEC + int(500 * be.REBUILD_FACTOR))

    def test_the_rate_follows_this_pc(self):
        self.assertAlmostEqual(be.rate_after(0.1, be.OVERHEAD_SEC + 300, 1000), 0.2)   # half old 0.1, half measured 0.3
        self.assertEqual(be.rate_after(0.1, 10, 1000), 0.1, 'a build shorter than the fixed part teaches nothing')

    def test_durations_read_as_an_estimate(self):
        self.assertEqual(be.format_duration(81 * 60), '≈ 1 h 20')
        self.assertEqual(be.format_duration(44 * 60), '≈ 45 min')
        self.assertEqual(be.format_duration(30), '≈ 5 min')
        self.assertEqual(be.format_duration(6 * 3600 + 20 * 60), '≈ 6 h 20')
        self.assertEqual(be.format_duration(None), '')


if __name__ == '__main__':
    unittest.main()
