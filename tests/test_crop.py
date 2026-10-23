"""Suggested crops (1.12): geometry, the minimum long edge, scoring and the settings."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from helpers import wait_idle
import analysis
import subject
from engine import Library
from store import Store


def small_subject_photo(path=None, size=(1200, 800), at=(.12, .7)):
    """Plain soft background and one small detailed subject near a corner (poor composition)."""
    rng = np.random.default_rng(5)
    w, h = size
    base = Image.new('RGB', size, (90, 120, 150)).filter(ImageFilter.GaussianBlur(2))
    sub = Image.fromarray((rng.random((h // 8, w // 10, 3)) * 255).astype('uint8'))
    base.paste(sub, (int(at[0] * w), int(at[1] * h)))
    if path:
        base.save(path, quality=95)
    return base


SUBJECT = (.11, .69, .12, .145)   # around the pasted subject, as the finder would return it


class CropGeometryTests(unittest.TestCase):
    def test_crop_keeps_aspect_subject_and_minimum_long_edge(self):
        preview = small_subject_photo()
        crops = analysis.crop_options(preview, SUBJECT, (6048, 4032))
        self.assertIn('3000', crops)
        c = crops['3000']
        x, y, w, h = c['box']
        self.assertAlmostEqual(w, h, 4)                                   # same aspect ratio as the photo
        self.assertGreaterEqual(c['px'][0], 3000)                          # long edge never below 3,000 px
        self.assertAlmostEqual(c['px'][0] / c['px'][1], 6048 / 4032, 2)
        sx, sy, sw, sh = SUBJECT
        self.assertTrue(x <= sx and y <= sy and x + w >= sx + sw and y + h >= sy + sh)   # subject inside
        self.assertTrue(0 <= x <= 1 - w and 0 <= y <= 1 - h)               # crop inside the frame
        full, _ = analysis._composition(analysis._gray(preview)[1])
        self.assertGreaterEqual(c['composition'], full + analysis.CROP_MIN_GAIN)

    def test_larger_minimum_edges_give_larger_or_no_crops(self):
        crops = analysis.crop_options(small_subject_photo(), SUBJECT, (6048, 4032))
        sizes = [crops[k]['px'][0] for k in ('2000', '2500', '3000', '3500', '4000') if k in crops]
        self.assertEqual(sizes, sorted(sizes))
        for k, c in crops.items():
            self.assertGreaterEqual(c['px'][0], int(k))

    def test_small_photos_cannot_be_cropped_below_the_limit(self):
        # a 3,680 px compact camera frame: 3,000 px would be 82 % of the frame, close to no crop at all
        crops = analysis.crop_options(small_subject_photo(), SUBJECT, (3680, 2760))
        self.assertNotIn('3500', crops)
        self.assertNotIn('4000', crops)
        self.assertEqual(analysis.crop_options(small_subject_photo(), SUBJECT, (2000, 1333)), {})

    def test_no_subject_no_crop(self):
        self.assertEqual(analysis.crop_options(small_subject_photo(), None, (6048, 4032)), {})


class CropEngineTests(unittest.TestCase):
    def test_settings_and_no_crop_change_the_composition_that_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photos = root / 'Photos'
            photos.mkdir()
            small_subject_photo(photos / 'corner.jpg', size=(6000, 4000))
            store = Store(root / 'db.sqlite')
            library = Library(store, root / 'cache', workers=1)
            library.find_subject = lambda p: SUBJECT
            try:
                library.start(photos, False)
                wait_idle(library)
                row = library.payload()['rows'][0]
                self.assertIsNotNone(row['crop'])
                self.assertGreaterEqual(row['crop']['px'][0], 3000)
                cropped = row['scores']['composition']
                self.assertGreater(cropped, row['metrics']['composition_full'])
                library.set_crop_settings(consider=False)
                self.assertEqual(library.payload()['rows'][0]['scores']['composition'], row['metrics']['composition_full'])
                library.set_crop_settings(consider=True, min_edge=4000)
                big = library.payload()['rows'][0]
                self.assertTrue(big['crop'] is None or big['crop']['px'][0] >= 4000)
                library.set_crop_settings(min_edge=3000)
                library.set_no_crop(library.row(row['id']), True)
                again = library.payload()['rows'][0]
                self.assertTrue(again['no_crop'])
                self.assertEqual(again['scores']['composition'], row['metrics']['composition_full'])
                self.assertTrue(store.marks()[row['path']]['no_crop'])
            finally:
                library.shutdown()
                store.close()


if __name__ == '__main__':
    unittest.main()
