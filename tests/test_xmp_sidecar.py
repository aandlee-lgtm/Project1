"""XMP sidecars for Lightroom without the plug-in (1.11)."""
import os
import tempfile
import time
import unittest
from pathlib import Path

import helpers  # noqa: F401  (adds the project folder to sys.path)
import xmp_sidecar as xs

ADOBE = '''<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 7.0-c000 1.000000">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:lr="http://ns.adobe.com/lightroom/1.0/"
   xmp:Rating="4"
   crs:Exposure2012="+0.35"
   crs:Shadows2012="+40">
   <dc:subject><rdf:Bag><rdf:li>Regatta</rdf:li></rdf:Bag></dc:subject>
   <lr:hierarchicalSubject><rdf:Bag><rdf:li>Events|Regatta</rdf:li></rdf:Bag></lr:hierarchicalSubject>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
'''


class SidecarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.photos = self.root / 'DCIM'
        self.photos.mkdir()
        self.support = self.root / 'support'
        for name in ('DSC_0001.NEF', 'DSC_0002.NEF', 'P1.ORF', 'IMG.JPG', 'X.DNG'):
            (self.photos / name).write_bytes(b'original ' + name.encode())

    def tearDown(self):
        self.tmp.cleanup()

    def row(self, name, rating, keywords=('Keep',)):
        return {'path': str(self.photos / name), 'name': name, 'rating': rating, 'keywords': list(keywords)}

    def doc(self, name):
        return xs.parse((self.photos / name).read_text())

    def test_new_sidecars_for_raw_files_only(self):
        before = {p.name: p.read_bytes() for p in self.photos.iterdir()}
        out = xs.write_all(self.support, [self.row('DSC_0001.NEF', 3, ['Keep', 'Burst 007']), self.row('P1.ORF', 1, ['Drop']),
                                          self.row('IMG.JPG', 3), self.row('X.DNG', 2)])
        self.assertEqual((out['created'], out['written'], out['skipped']), (2, 2, ['IMG.JPG', 'X.DNG']))
        root = self.doc('DSC_0001.xmp')
        self.assertEqual(xs.rating_of(root), 3)
        self.assertEqual(xs.keywords_of(root), ['Keep', 'Burst 007', 'From PhotoSelect'])
        text = (self.photos / 'DSC_0001.xmp').read_text()
        self.assertIn('PhotoSelect|Keep', text)
        self.assertIn('x:xmptk="PhotoSelect"', text)
        self.assertEqual(xs.rating_of(self.doc('P1.xmp')), 1)
        for name, data in before.items():                          # the photos themselves are untouched
            self.assertEqual((self.photos / name).read_bytes(), data)
        self.assertFalse(list(self.photos.glob('*.photoselect-tmp')))

    def test_existing_sidecar_is_merged_and_its_stars_kept(self):
        (self.photos / 'DSC_0002.xmp').write_text(ADOBE)
        out = xs.write_all(self.support, [self.row('DSC_0002.NEF', 1, ['Drop'])])
        self.assertEqual((out['updated'], out['kept']), (1, 1))
        text = (self.photos / 'DSC_0002.xmp').read_text()
        root = xs.parse(text)
        self.assertEqual(xs.rating_of(root), 4)                    # stars set elsewhere are kept
        self.assertIn('crs:Shadows2012="+40"', text)               # edits and other metadata stay
        self.assertIn('Events|Regatta', text)
        self.assertIn('PhotoSelect|Drop', text)
        self.assertNotIn('ns0:', text)
        # a later send replaces PhotoSelect's keywords only
        xs.write_all(self.support, [self.row('DSC_0002.NEF', 3, ['Keep'])])
        root = self.doc('DSC_0002.xmp')
        self.assertEqual(xs.keywords_of(root), ['Keep', 'From PhotoSelect'])
        # removing leaves the file (it was not PhotoSelect's) without PhotoSelect's keywords
        self.assertEqual(xs.remove_all(self.support)['cleaned'], 1)
        text = (self.photos / 'DSC_0002.xmp').read_text()
        self.assertNotIn('PhotoSelect|', text)
        self.assertIn('Events|Regatta', text)
        self.assertEqual(xs.rating_of(xs.parse(text)), 4)

    def test_own_rating_is_updated_and_unchanged_files_not_rewritten(self):
        xs.write_all(self.support, [self.row('DSC_0001.NEF', 2, ['Consider'])])
        stamp = (self.photos / 'DSC_0001.xmp').stat().st_mtime_ns
        out = xs.write_all(self.support, [self.row('DSC_0001.NEF', 2, ['Consider'])])
        self.assertEqual(out['unchanged'], 1)
        self.assertEqual((self.photos / 'DSC_0001.xmp').stat().st_mtime_ns, stamp)
        out = xs.write_all(self.support, [self.row('DSC_0001.NEF', 3, ['Keep'])])
        self.assertEqual((out['updated'], out['kept']), (1, 0))
        self.assertEqual(xs.rating_of(self.doc('DSC_0001.xmp')), 3)

    def test_remove_deletes_only_unchanged_photoselect_sidecars(self):
        xs.write_all(self.support, [self.row('DSC_0001.NEF', 3), self.row('P1.ORF', 1, ['Drop'])])
        # Lightroom rewrote one of them (it sets its own toolkit)
        side = self.photos / 'P1.xmp'
        side.write_text(side.read_text().replace('x:xmptk="PhotoSelect"', 'x:xmptk="Adobe XMP Core 7.0"'))
        out = xs.remove_all(self.support)
        self.assertEqual((out['deleted'], out['cleaned']), (1, 1))
        self.assertFalse((self.photos / 'DSC_0001.xmp').exists())
        self.assertTrue(side.exists())
        self.assertEqual(xs.load_ledger(self.support), {})

    def test_star_changes_written_back_by_lightroom_are_read(self):
        xs.write_all(self.support, [self.row('DSC_0001.NEF', 1, ['Drop']), self.row('P1.ORF', 3)])
        self.assertEqual(xs.star_changes(self.support), [])
        side = self.photos / 'DSC_0001.xmp'
        side.write_text(side.read_text().replace('xmp:Rating="1"', 'xmp:Rating="3"'))
        os.utime(side, (time.time() + 5, time.time() + 5))
        self.assertEqual(xs.star_changes(self.support), [(1, 3, str(self.photos / 'DSC_0001.NEF'))])
        self.assertEqual(xs.star_changes(self.support), [])         # reported once

    def test_read_only_folder_reported(self):
        if os.geteuid() == 0:
            self.skipTest('root can write anywhere')
        self.photos.chmod(0o555)
        try:
            out = xs.write_all(self.support, [self.row('DSC_0001.NEF', 3)])
        finally:
            self.photos.chmod(0o755)
        self.assertIn('read-only', out['failed'][0][1])

    def test_crop_mapped_to_the_stored_orientation(self):
        box = (.1, .2, .3, .4)                                      # upright photo: x, y, w, h
        self.assertEqual(xs.stored_crop(box, 1), (.1, .2, .4, .6))
        self.assertEqual(xs.stored_crop(box, 3), (.6, .4, .9, .8))
        # a portrait frame stored landscape and turned 90° clockwise to display (EXIF 6)
        self.assertEqual(xs.stored_crop(box, 6), (.2, .6, .6, .9))
        self.assertEqual(xs.stored_crop(box, 8), (.4, .1, .8, .4))
        self.assertIsNone(xs.stored_crop(box, 5))
        # check orientation 6 with a real rotation: a marked block in the upright image
        import numpy as np
        up = np.zeros((40, 30), bool)                                # upright: 30 wide, 40 high
        up[8:24, 3:12] = True                                        # x .1-.4, y .2-.6
        stored = np.rot90(up, 1)                                     # what the camera stored (turned back)
        ys, xs_ = np.nonzero(stored)
        h, w = stored.shape
        self.assertEqual((xs_.min() / w, ys.min() / h, (xs_.max() + 1) / w, (ys.max() + 1) / h),
                         xs.stored_crop((3 / 30, 8 / 40, 9 / 30, 16 / 40), 6))

    def test_crop_written_kept_when_set_elsewhere_and_removed(self):
        row = dict(self.row('DSC_0001.NEF', 3), crop=[.1, .2, .5, .5], orientation=1)
        out = xs.write_all(self.support, [row])
        self.assertEqual(out['cropped'], 1)
        text = (self.photos / 'DSC_0001.xmp').read_text()
        self.assertIn('crs:HasCrop="True"', text)
        self.assertEqual(xs.crop_of(xs.parse(text)), (.1, .2, .6, .7))
        # a new suggestion replaces PhotoSelect's own crop
        xs.write_all(self.support, [dict(row, crop=[.2, .2, .5, .5])])
        self.assertEqual(xs.crop_of(self.doc('DSC_0001.xmp')), (.2, .2, .7, .7))
        # no crop any more: PhotoSelect's crop is removed
        xs.write_all(self.support, [dict(row, crop=None)])
        self.assertIsNone(xs.crop_of(self.doc('DSC_0001.xmp')))
        # a crop set in Lightroom (sidecar from elsewhere) is never replaced
        (self.photos / 'DSC_0002.xmp').write_text(ADOBE.replace('crs:Shadows2012="+40"', 'crs:Shadows2012="+40" crs:HasCrop="True" '
            'crs:CropLeft="0.05" crs:CropTop="0.05" crs:CropRight="0.95" crs:CropBottom="0.95" crs:CropAngle="0"'))
        xs.write_all(self.support, [dict(self.row('DSC_0002.NEF', 3), crop=[.1, .1, .5, .5], orientation=1)])
        self.assertEqual(xs.crop_of(self.doc('DSC_0002.xmp')), (.05, .05, .95, .95))

    def test_smart_collection_files(self):
        folder = xs.smart_collection_files(self.support)
        names = sorted(p.name for p in folder.iterdir())
        self.assertEqual(names, ['PhotoSelect 1 Rescue.lrsmcol', 'PhotoSelect 2 Confirm.lrsmcol', 'PhotoSelect 3 Decide.lrsmcol',
                                 'PhotoSelect Borderline.lrsmcol', 'PhotoSelect Liked.lrsmcol'])
        text = (folder / 'PhotoSelect 1 Rescue.lrsmcol').read_text()
        self.assertIn('criteria = "rating"', text)
        self.assertIn('value = 1,', text)
        self.assertIn('value = "From PhotoSelect"', text)
        self.assertIn('combine = "intersect"', text)
        try:
            from lupa import lua51
        except ImportError:
            return
        lua = lua51.LuaRuntime()
        lua.execute(text)                                           # valid Lua, as Lightroom reads it
        s = lua.globals().s
        self.assertEqual((s.title, s.value.combine, s.value[1].value), ('1 Rescue', 'intersect', 1))


if __name__ == '__main__':
    unittest.main()
