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
        rows[1]['raw'] = {**raw, 'hash': [1 - v for v in raw['hash']]}
        group_bursts(rows)
        self.assertNotEqual(rows[0]['group'], rows[1]['group'])

    def test_valid_region(self):
        self.assertTrue(analysis.valid_region([0, 0, .5, .5]))
        for bad in (None, [.9, 0, .5, .5], [0, 0, .01, .5], [0, 0, 1], ['a', 0, .5, .5]):
            self.assertFalse(analysis.valid_region(bad))


if __name__ == '__main__':
    unittest.main()
