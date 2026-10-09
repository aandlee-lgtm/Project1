import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from helpers import make_jpeg, make_dng, has_pidng, fingerprint, wait_idle
import raw_io
from engine import Library
from store import Store


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.photos = root / 'Photo Drive' / 'Regatta 2026'
        self.photos.mkdir(parents=True)
        self.home = root / 'home'
        self.store = Store(self.home / 'support' / 'db.sqlite')
        self.library = Library(self.store, self.home / 'cache', workers=2)

    def tearDown(self):
        self.library.shutdown()
        self.store.close()
        self.tmp.cleanup()

    def scan(self, recursive=False, library=None):
        library = library or self.library
        library.start(self.photos, recursive)
        wait_idle(library)
        return library.payload()

    def make_burst(self):
        # Three frames 0.1 s apart of the same scene (one soft) and an unrelated later frame.
        make_jpeg(self.photos / 'DSC_0001.JPG', seed=1, when='2026:05:01 10:00:00', subsec='10')
        make_jpeg(self.photos / 'DSC_0002.jpg', seed=1, when='2026:05:01 10:00:00', subsec='20', blur=2)
        make_jpeg(self.photos / 'DSC_0003.Jpeg', seed=1, when='2026:05:01 10:00:00', subsec='30')
        make_jpeg(self.photos / 'DSC_0100.jpg', seed=7, when='2026:05:01 10:05:00')

    def test_scan_mixed_folder_with_failures(self):
        self.make_burst()
        (self.photos / 'broken.NEF').write_bytes(os.urandom(5000))
        (self.photos / 'broken.ORF').write_bytes(os.urandom(5000))
        (self.photos / 'empty.nrw').write_bytes(b'')
        (self.photos / '._DSC_0001.JPG').write_bytes(b'AppleDouble junk')
        (self.photos / 'notes.txt').write_text('ignored')
        sub = self.photos / 'Day 2'
        make_jpeg(sub / 'IMG_1.PNG'.replace('PNG', 'jpg'), seed=3)
        before = fingerprint(self.photos)

        p = self.scan()
        names = sorted(r['name'] for r in p['rows'])
        self.assertEqual(names, ['DSC_0001.JPG', 'DSC_0002.jpg', 'DSC_0003.Jpeg', 'DSC_0100.jpg'])
        self.assertEqual(sorted(e['name'] for e in p['errors']), ['broken.NEF', 'broken.ORF', 'empty.nrw'])
        self.assertTrue(all(r['status'] == 'analysed' and r['scores'] for r in p['rows']))
        by = {r['name']: r for r in p['rows']}
        # burst grouping by sub-second capture time and similarity
        self.assertEqual(by['DSC_0001.JPG']['group'], by['DSC_0003.Jpeg']['group'])
        self.assertNotEqual(by['DSC_0001.JPG']['group'], by['DSC_0100.jpg']['group'])
        self.assertGreater(by['DSC_0001.JPG']['scores']['focus'], by['DSC_0002.jpg']['scores']['focus'])

        p = self.scan(recursive=True)
        self.assertIn(os.path.join('Day 2', 'IMG_1.jpg'), [r['name'] for r in p['rows']])
        self.assertEqual(fingerprint(self.photos), before, 'originals must not change')

    def test_cache_reuse_and_invalidation(self):
        self.make_burst()
        self.scan()
        calls = []
        real = raw_io.decode_photo
        with patch('raw_io.decode_photo', side_effect=lambda p, allow_preview=True: calls.append(p) or real(p)):
            p = self.scan()
            self.assertEqual(calls, [])
            self.assertTrue(all(r['source'] == 'cache' for r in p['rows']))
            # Same results after a full app restart (new Store/Library on the same files).
            library2 = Library(Store(self.home / 'support' / 'db.sqlite'), self.home / 'cache', workers=1)
            p2 = self.scan(library=library2)
            library2.shutdown()
            self.assertEqual(calls, [])
            self.assertEqual({r['id']: r['scores'] for r in p['rows']}, {r['id']: r['scores'] for r in p2['rows']})
            target = self.photos / 'DSC_0100.jpg'
            os.utime(target, ns=(time.time_ns(), time.time_ns() + 5_000_000_000))
            p = self.scan()
            self.assertEqual([Path(c).name for c in calls], ['DSC_0100.jpg'])
            self.assertEqual({r['name']: r['source'] for r in p['rows']}['DSC_0100.jpg'], 'decoded')

    def test_cancellation_keeps_partial_results(self):
        for i in range(40):
            make_jpeg(self.photos / f'IMG_{i:03}.jpg', seed=i, size=(200, 150))
        real = raw_io.decode_photo
        gate = threading.Event()

        def slow(p, allow_preview=True):
            gate.wait(5)
            time.sleep(.05)
            return real(p)
        with patch('raw_io.decode_photo', side_effect=slow):
            self.library.start(self.photos, False)
            time.sleep(.2)
            self.assertTrue(self.library.snapshot()['running'])
            # API stays responsive while workers are busy
            t = time.perf_counter()
            self.library.snapshot()
            self.assertLess(time.perf_counter() - t, .2)
            gate.set()
            time.sleep(.2)
            self.library.cancel()
            started = time.monotonic()
            wait_idle(self.library, 10)
            self.assertLess(time.monotonic() - started, 3)
        s = self.library.snapshot()
        self.assertEqual(s['phase'], 'cancelled')
        done = sum(r['status'] == 'analysed' for r in self.library.payload()['rows'])
        self.assertGreater(done, 0)
        self.assertLess(done, 40)
        p = self.scan()   # resumes, reusing the cached part
        self.assertEqual(sum(r['source'] == 'cache' for r in p['rows']), done)
        self.assertEqual(sum(r['status'] == 'analysed' for r in p['rows']), 40)

    def test_marks_regions_and_prefs_persist(self):
        self.make_burst()
        p = self.scan()
        row = next(r for r in p['rows'] if r['name'] == 'DSC_0001.JPG')
        self.store.set_mark(row['path'], decision='Keep', liked=True)
        self.library.set_roi(row['id'], [.1, .1, .3, .3])
        deadline = time.monotonic() + 10
        while self.library.row(row['id'])['roi_state'] != 'full' and time.monotonic() < deadline:
            time.sleep(.02)
        measured = self.library.row(row['id'])['raw']['focus']
        self.store.set_prefs({'weights': {'sharpness': 10, 'focus': 70, 'composition': 10, 'exposure': 10}, 'keep': 80})

        store2 = Store(self.home / 'support' / 'db.sqlite')
        library2 = Library(store2, self.home / 'cache', workers=1)
        p2 = self.scan(library=library2)
        r2 = next(r for r in p2['rows'] if r['id'] == row['id'])
        self.assertEqual((r2['decision'], r2['liked'], r2['roi'], r2['roi_state']), ('Keep', True, [.1, .1, .3, .3], 'full'))
        self.assertAlmostEqual(r2['metrics']['focus'], measured)
        self.assertEqual(store2.prefs()['keep'], 80)
        self.assertEqual(store2.prefs()['weights']['focus'], 70)
        library2.shutdown()
        store2.close()

    @unittest.skipUnless(has_pidng(), 'pidng not installed')
    def test_raw_files_are_fully_decoded(self):
        make_dng(self.photos / 'frame.DNG', size=(1200, 800))
        p = self.scan()
        r = p['rows'][0]
        self.assertEqual((r['status'], r['source'], r['is_raw']), ('analysed', 'decoded', True))
        self.assertEqual(sorted(r['size']), [800, 1200])
        self.assertTrue(self.library.full_jpeg(self.library.row(r['id'])).startswith(b'\xff\xd8'))

    def test_camera_preview_basis_is_labelled_and_cached(self):
        make_jpeg(self.photos / 'tmp.jpg', seed=1, size=(1500, 1000))
        os.replace(self.photos / 'tmp.jpg', self.photos / 'DSC_0001.NEF')   # stands in for an HE NEF
        real = raw_io.decode_photo

        def fake(path, allow_preview=True):
            if str(path).endswith('.NEF'):
                from PIL import Image
                return Image.open(path).convert('RGB'), 'camera_preview', raw_io.PREVIEW_NOTICE
            return real(path, allow_preview)
        with patch('raw_io.decode_photo', side_effect=fake):
            p = self.scan()
        r = p['rows'][0]
        self.assertEqual((r['status'], r['basis'], r['is_raw']), ('analysed', 'camera_preview', True))
        self.assertIn('embedded camera JPEG', r['notice'])
        p = self.scan()                                    # restored from cache with the same label
        self.assertEqual((p['rows'][0]['source'], p['rows'][0]['basis']), ('cache', 'camera_preview'))

    @unittest.skipIf(os.name != 'posix' or os.geteuid() == 0, 'permissions are not enforced for root')
    def test_unreadable_subfolder_reported(self):
        make_jpeg(self.photos / 'ok.jpg')
        locked = self.photos / 'Locked'
        make_jpeg(locked / 'x.jpg')
        locked.chmod(0)
        try:
            p = self.scan(recursive=True)
        finally:
            locked.chmod(0o755)
        self.assertEqual([r['name'] for r in p['rows']], ['ok.jpg'])
        self.assertTrue(any('Permission denied' in e['error'] for e in p['errors']))


if __name__ == '__main__':
    unittest.main()
