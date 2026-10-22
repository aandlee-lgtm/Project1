"""Automatic subject finding (1.11): choosing the area from Vision's boxes, measuring focus there, and
switching the setting without re-analysis. Vision itself only runs on macOS (checked in the macOS
acceptance tests); here a stand-in finder plays its part."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from helpers import make_jpeg, wait_idle
import analysis
import subject
from engine import Library
from store import Store


class ChooseTests(unittest.TestCase):
    def test_nothing_found(self):
        self.assertIsNone(subject.choose([]))
        self.assertIsNone(subject.choose([(.1, .1, 0, .2, .9)]))            # empty box
        self.assertIsNotNone(subject.choose([(.1, .1, .2, .2, .05)]))       # Vision's confidences are often low: still used
        self.assertIsNotNone(subject.choose([(.1, .1, .2, .2, 0.0)]))

    def test_one_box_is_padded(self):
        x, y, w, h = subject.choose([(.6, .3, .2, .2, .9)])
        self.assertAlmostEqual(x, .58, 3)
        self.assertAlmostEqual(w, .24, 3)
        self.assertAlmostEqual(y, .28, 3)

    def test_confident_boxes_are_combined_weak_ones_ignored(self):
        x, y, w, h = subject.choose([(.1, .4, .1, .1, .8), (.5, .45, .1, .1, .7), (.9, .0, .05, .05, .2)])
        self.assertLess(x, .1)
        self.assertGreater(x + w, .6)
        self.assertLess(y + h, .6)                                       # the weak corner box is left out

    def test_area_covering_most_of_the_frame_is_not_a_subject(self):
        self.assertIsNone(subject.choose([(.04, 0, .96, .92, .5)]))          # what attention saliency often returns
        self.assertIsNone(subject.choose([(.05, .1, .3, .3, .9), (.5, .4, .45, .55, .8)]))   # combined: too large
        self.assertIsNotNone(subject.choose([(.42, .33, .19, .29, .9)]))

    def test_tiny_subject_gets_minimum_size_inside_the_frame(self):
        x, y, w, h = subject.choose([(.98, .0, .01, .01, .9)])
        self.assertAlmostEqual(w, subject.MIN_SIDE, 3)
        self.assertAlmostEqual(h, subject.MIN_SIDE, 3)
        self.assertLessEqual(x + w, 1.0)
        self.assertGreaterEqual(y, 0.0)
        self.assertTrue(analysis.valid_region((x, y, w, h)))

    def test_vision_unavailable_off_macos_means_no_subject(self):
        if subject.available():
            self.skipTest('Vision is available here')
        self.assertIsNone(subject.vision_find_subject(Image.new('RGB', (64, 48))))
        self.assertEqual(subject.finder_name(), 'unavailable')

    def test_vision_runs_on_macos(self):
        if not subject.available():
            self.skipTest('Vision is only on macOS')
        with tempfile.TemporaryDirectory() as tmp:
            off_centre_photo(Path(tmp) / 'a.jpg')
            box = subject.vision_find_subject(Image.open(Path(tmp) / 'a.jpg'))
        self.assertTrue(box is None or analysis.valid_region(box), box)


def off_centre_photo(path):
    """Soft background everywhere, with one sharp, detailed subject in the upper-left corner."""
    rng = np.random.default_rng(3)
    base = Image.fromarray((rng.random((427, 640, 3)) * 255).astype('uint8')).filter(ImageFilter.GaussianBlur(6))
    sharp = Image.fromarray((rng.random((90, 120, 3)) * 255).astype('uint8'))
    base.paste(sharp, (30, 30))
    base.save(path, quality=95)


class FocusOnSubjectTests(unittest.TestCase):
    BOX = (0.03, 0.05, 0.22, 0.26)

    def test_focus_measured_on_the_subject(self):
        with tempfile.TemporaryDirectory() as tmp:
            off_centre_photo(Path(tmp) / 'a.jpg')
            full = Image.open(Path(tmp) / 'a.jpg')
            _, m = analysis.analyse(full, finder=lambda p: self.BOX)
            self.assertEqual(m['subject'], list(self.BOX))
            self.assertGreater(m['focus_subject'], m['focus_centre'] * 3)   # the centre is only soft background
            self.assertEqual(m['focus'], m['focus_subject'])
            _, off = analysis.analyse(full, finder=lambda p: self.BOX, auto_subject=False)
            self.assertEqual(off['focus'], off['focus_centre'])
            _, none = analysis.analyse(full, finder=lambda p: None)
            self.assertIsNone(none['subject'])
            self.assertEqual(none['focus_subject'], none['focus_centre'])
            _, mine = analysis.analyse(full, region=(.6, .6, .3, .3), finder=lambda p: self.BOX)
            self.assertNotEqual(mine['focus'], mine['focus_subject'])       # your region always wins


class EngineSubjectTests(unittest.TestCase):
    def test_setting_switches_without_reanalysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photos = root / 'Photos'
            photos.mkdir()
            off_centre_photo(photos / 'subject.jpg')
            make_jpeg(photos / 'plain.jpg', seed=2)
            store = Store(root / 'db.sqlite')
            library = Library(store, root / 'cache', workers=1)
            calls = []
            library.find_subject = lambda p: calls.append(1) or FocusOnSubjectTests.BOX
            try:
                library.start(photos, False)
                wait_idle(library)
                rows = {r['name']: r for r in library.payload()['rows']}
                self.assertEqual(rows['subject.jpg']['subject'], list(FocusOnSubjectTests.BOX))
                on = rows['subject.jpg']['scores']['focus']
                version = library.payload()['version']
                library.set_auto_subject(False)
                rows = {r['name']: r for r in library.payload()['rows']}
                self.assertGreater(library.payload()['version'], version)
                self.assertNotEqual(rows['subject.jpg']['scores']['focus'], on)
                self.assertEqual(len(calls), 2)                              # no re-analysis
                library.set_auto_subject(True)
                self.assertEqual({r['name']: r for r in library.payload()['rows']}['subject.jpg']['scores']['focus'], on)
            finally:
                library.shutdown()
                store.close()


if __name__ == '__main__':
    unittest.main()
