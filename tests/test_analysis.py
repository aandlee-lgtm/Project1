import unittest

import numpy as np
from PIL import Image, ImageFilter

from helpers import scene  # noqa: F401  (adds project root to sys.path)
import analysis
from analysis import metrics, normalise, group_bursts, focus_detail


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        y, x = np.mgrid[:256, :256]
        self.image = Image.fromarray(((x // 8 + y // 8) % 2 * 255).astype('uint8')).convert('RGB')

    def test_blur_reduces_detail(self):
        sharp = metrics(self.image)
        soft = metrics(self.image.filter(ImageFilter.GaussianBlur(3)))
        self.assertGreater(sharp['sharpness'], soft['sharpness'] * 3)
        self.assertGreater(sharp['focus'], soft['focus'] * 3)

    def test_region_distinguishes_subject(self):
        im = self.image.copy()
        im.paste(Image.new('RGB', (128, 256), (125, 125, 125)), (128, 0))
        self.assertGreater(metrics(im, [0, 0, .4, 1])['focus'], metrics(im, [.6, 0, .4, 1])['focus'])

    def test_focus_uses_full_resolution_and_is_scale_comparable(self):
        big = scene(1, (6000, 4000))
        small = big.resize((4500, 3000), Image.Resampling.BOX)
        a, b = focus_detail(big), focus_detail(small)
        # Both are measured at the same 4,000 px-equivalent scale.
        self.assertLess(abs(a - b) / max(a, b), 0.15)

    def test_sensor_noise_does_not_masquerade_as_focus(self):
        rng = np.random.default_rng(0)
        y, x = np.mgrid[:4000, :6000]
        edges = ((x // 40 + y // 40) % 2 * 120 + 60).astype(np.float32)
        soft = np.asarray(Image.fromarray(edges.astype('uint8')).filter(ImageFilter.GaussianBlur(4)), np.float32)
        make = lambda a: Image.fromarray(a.clip(0, 255).astype('uint8')).convert('RGB')
        for sigma in (6, 15):
            noise = lambda: rng.normal(0, sigma, edges.shape).astype(np.float32)
            sharp, blurred, flat = (focus_detail(make(edges + noise())), focus_detail(make(soft + noise())),
                                    focus_detail(make(128 + noise())))
            self.assertGreater(sharp, blurred * 5, sigma)
            self.assertGreater(blurred, flat, sigma)
        self.assertGreater(metrics(make(128 + rng.normal(0, 15, (400, 600))))['noise'], 10)

    def test_uniform_scores_are_finite(self):
        rows = [{'raw': metrics(Image.new('RGB', (100, 100), 'gray')), 'scores': {}} for _ in range(3)]
        normalise(rows)
        self.assertTrue(all(r['scores']['sharpness'] == 50 for r in rows))
        self.assertTrue(all(np.isfinite(r['scores']['focus']) for r in rows))

    def test_clipping_reported(self):
        im = Image.new('RGB', (100, 100), 'white')
        im.paste(Image.new('RGB', (50, 100), 'gray'), (0, 0))
        m = metrics(im)
        self.assertAlmostEqual(m['clip_high'], 50, delta=1)
        self.assertAlmostEqual(m['exposure'], 50, delta=1)

    def test_noise_flag_only_for_high_noise_frames(self):
        rows = [{'raw': {'sharpness': 1, 'focus': 1, 'composition': 50, 'exposure': 90, 'noise': n}, 'scores': {}}
                for n in (1, 1.2, 1.1, 0.9, 9.0)]
        normalise(rows)
        self.assertEqual([r['noise_flag'] for r in rows], [False, False, False, False, True])

    def test_grouping_uses_time_and_similarity(self):
        raw = metrics(self.image)
        rows = [{'name': str(i), 'timestamp': t, 'raw': dict(raw)} for i, t in enumerate([100, 100.1, 120, None])]
        group_bursts(rows)
        self.assertEqual(rows[0]['group'], rows[1]['group'])
        self.assertNotEqual(rows[1]['group'], rows[2]['group'])
        self.assertNotEqual(rows[2]['group'], rows[3]['group'])
        rows[1]['raw'] = {**raw, 'look': [0.05] * 96 + [0.95] * 96}   # dark top, bright bottom
        group_bursts(rows)
        self.assertNotEqual(rows[0]['group'], rows[1]['group'])

    def test_low_contrast_burst_frames_group_together(self):
        # Near-identical frames of fine texture (like water) must not be split by noise.
        rng = np.random.default_rng(3)
        y, x = np.mgrid[:1000, :1500]
        base = ((x // 15 + y // 15) % 2 * 140 + 50).astype(np.float32)
        rows = []
        for k, blur in enumerate([0, 0, 3, 1]):
            im = Image.fromarray((base + rng.normal(0, 3, base.shape)).clip(0, 255).astype('uint8')).convert('RGB')
            if blur:
                im = im.filter(ImageFilter.GaussianBlur(blur))
            rows.append({'name': str(k), 'timestamp': 100 + k * .1, 'raw': metrics(im)})
        group_bursts(rows)
        self.assertEqual(len({r['group'] for r in rows}), 1)
        # a genuinely different scene 0.1 s later starts a new group
        other = np.full((1000, 1500), 230, np.uint8)
        other[:, :500] = 20                         # different composition: dark third on the left
        rows.append({'name': 'x', 'timestamp': 100.5, 'raw': metrics(Image.fromarray(other).convert('RGB'))})
        group_bursts(rows)
        self.assertNotEqual(rows[-1]['group'], rows[0]['group'])

    def test_likeness_percent(self):
        raw = metrics(self.image)
        self.assertEqual(analysis.likeness(raw, raw), 100)
        dark = {**raw, 'look': [v * .5 for v in raw['look']]}
        self.assertLess(analysis.likeness(raw, dark), 100)
        self.assertGreaterEqual(analysis.likeness(raw, {**raw, 'look': [1 - v for v in raw['look']]}), 0)
        # the 1.2 default tolerance (14) is the 1.3 default likeness (70 %)
        self.assertEqual(analysis.similarity_to_likeness(14), 70)
        shifted = {**raw, 'look': [min(1, v + .07) for v in raw['look']]}
        self.assertAlmostEqual(analysis.likeness(raw, shifted), 70, delta=6)

    def test_bursts_by_likeness_threshold(self):
        raw = metrics(self.image)
        near = {**raw, 'look': [min(1, v + .05) for v in raw['look']]}      # about 79 % alike
        rows = [{'name': 'a', 'timestamp': 100, 'raw': raw}, {'name': 'b', 'timestamp': 100.5, 'raw': near}]
        group_bursts(rows, min_likeness=70)
        self.assertEqual(rows[0]['group'], rows[1]['group'])
        self.assertEqual(rows[0]['likeness']['b'], rows[1]['likeness']['a'])
        self.assertTrue(70 <= rows[0]['likeness']['b'] < 90)
        group_bursts(rows, min_likeness=90)
        self.assertNotEqual(rows[0]['group'], rows[1]['group'])
        self.assertEqual(rows[0]['likeness'], {})

    def test_near_identical_frames_seconds_apart(self):
        raw = metrics(self.image)
        other = {**raw, 'look': [0.05] * 96 + [0.95] * 96, 'colour': [.1, .2, .9]}   # dark top, bright bottom, blue
        rows = [{'name': 'a', 'timestamp': 100, 'raw': raw},
                {'name': 'x', 'timestamp': 103, 'raw': other},       # a different shot in between
                {'name': 'b', 'timestamp': 106, 'raw': dict(raw)},   # same scene again, 6 s after a
                {'name': 'c', 'timestamp': 130, 'raw': dict(raw)}]   # same scene, but 24 s later
        group_bursts(rows, gap=2, near_identical=90, near_window=10)
        g = {r['name']: r for r in rows}
        self.assertEqual(g['a']['group'], g['b']['group'])
        self.assertTrue(g['a']['near_identical'] and g['b']['near_identical'])
        self.assertEqual(g['b']['likeness']['a'], 100)
        self.assertNotEqual(g['x']['group'], g['a']['group'])
        self.assertNotEqual(g['c']['group'], g['a']['group'])
        self.assertFalse(g['x']['near_identical'] or g['c']['near_identical'])
        group_bursts(rows, gap=2, near_identical=90, near_window=0)         # window 0 = off
        self.assertNotEqual(g['a']['group'], g['b']['group'])
        # an ordinary burst is not marked near-identical
        burst = [{'name': str(k), 'timestamp': 100 + k * .1, 'raw': dict(raw)} for k in range(4)]
        group_bursts(burst)
        self.assertEqual(len({r['group'] for r in burst}), 1)
        self.assertFalse(any(r['near_identical'] for r in burst))

    def test_valid_region(self):
        self.assertTrue(analysis.valid_region([0, 0, .5, .5]))
        for bad in (None, [.9, 0, .5, .5], [0, 0, .01, .5], [0, 0, 1], ['a', 0, .5, .5]):
            self.assertFalse(analysis.valid_region(bad))


if __name__ == '__main__':
    unittest.main()
