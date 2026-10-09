import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import rawpy
from PIL import Image

from helpers import make_jpeg, make_dng, has_pidng
import raw_io
from raw_io import decode, FORMATS, format_name, DecodeError


class RawFormatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_nef_and_orf_case_insensitive_decoder_routing(self):
        for suffix in ('.nef', '.NEF', '.NeF', '.nrw', '.NRW', '.orf', '.ORF', '.Orf'):
            with self.subTest(suffix=suffix):
                self.assertIn(suffix.lower(), FORMATS)
                path = self.dir / ('photo' + suffix)
                path.write_bytes(b'not really raw data')
                processor = MagicMock()
                processor.postprocess.return_value = np.zeros((16, 24, 3), dtype=np.uint8)
                context = MagicMock()
                context.__enter__.return_value = processor
                with patch('rawpy.imread', return_value=context) as read:
                    result = decode(path)
                read.assert_called_once_with(str(path))
                kwargs = processor.postprocess.call_args.kwargs
                self.assertTrue(kwargs['use_camera_wb'])
                self.assertTrue(kwargs['no_auto_bright'])
                self.assertEqual(result.size, (24, 16))

    def test_camera_format_names(self):
        self.assertEqual(format_name('a.NEF'), 'Nikon NEF')
        self.assertEqual(format_name('a.nrw'), 'Nikon NRW')
        self.assertEqual(format_name('a.ORF'), 'Olympus / OM System ORF')

    def test_unsupported_raw_message(self):
        path = self.dir / 'a.ORF'
        path.write_bytes(b'x' * 100)
        with patch('rawpy.imread', side_effect=rawpy.LibRawFileUnsupportedError('unsupported')):
            with self.assertRaisesRegex(DecodeError, 'Olympus / OM System ORF.*does not recognise'):
                decode(path)

    def test_damaged_raw_reported_not_scored(self):
        for name in ('broken.NEF', 'broken.orf'):
            path = self.dir / name
            path.write_bytes(os.urandom(4096))
            with self.assertRaises(DecodeError):
                decode(path)

    def test_nikon_high_efficiency_nef_named_in_error(self):
        # Nikon HE/HE* NEFs carry an intoPIX TicoRAW codestream (marker as found in a Z6III HE* file).
        path = self.dir / 'DSC_2094.NEF'
        path.write_bytes(b'MM\x00*' + os.urandom(5000) + b'\xff\x10\xffP\x00"CONTACT_INTOPIX_' + os.urandom(5000))
        with patch('rawpy.imread', side_effect=rawpy.LibRawFileUnsupportedError('unsupported')):
            with self.assertRaisesRegex(DecodeError, 'High Efficiency.*Lossless compressed'):
                decode(path)
        other = self.dir / 'plain.NEF'
        other.write_bytes(os.urandom(6000))
        with patch('rawpy.imread', side_effect=rawpy.LibRawFileUnsupportedError('unsupported')):
            with self.assertRaisesRegex(DecodeError, 'does not recognise'):
                decode(other)

    def test_high_efficiency_data_error_falls_back_but_damage_does_not(self):
        # Nikon Z50 II HE NEFs: LibRaw opens the file, then stops with a *data error* while decoding.
        he = self.dir / 'DSC_1312.NEF'
        he.write_bytes(b'II*\x00' + os.urandom(5000) + b'CONTACT_INTOPIX_' + os.urandom(5000))
        failed, first, second = self._contexts()
        failed.postprocess.side_effect = rawpy.LibRawDataError('Data error or unsupported file format')
        with patch('rawpy.imread', side_effect=[first, second]):
            image, source, notice = raw_io.decode_photo(he)
        self.assertEqual(source, 'camera_preview')
        failed, first, second = self._contexts()
        failed.postprocess.side_effect = rawpy.LibRawDataError('Data error or unsupported file format')
        with patch('rawpy.imread', side_effect=[first]):
            with self.assertRaisesRegex(DecodeError, 'High Efficiency.*Lossless compressed'):
                raw_io.decode_photo(he, allow_preview=False)
        # the same error on a NEF without the HE marker is damage: no fallback
        damaged = self.dir / 'damaged.NEF'
        damaged.write_bytes(os.urandom(10000))
        failed, first, second = self._contexts()
        failed.postprocess.side_effect = rawpy.LibRawDataError('Data error or unsupported file format')
        with patch('rawpy.imread', side_effect=[first, second]) as read:
            with self.assertRaisesRegex(DecodeError, 'damaged or truncated'):
                raw_io.decode_photo(damaged)
        self.assertEqual(read.call_count, 1)

    def _camera_file(self, name, preview=(2400, 1600), model=b'ILCE-7M5'):
        """A TIFF-structured file naming its camera, with an embedded JPEG, that LibRaw will not open."""
        import io as _io
        buf = _io.BytesIO()
        Image.new('RGB', preview, 'gray').save(buf, format='JPEG')
        exif = Image.Exif()
        exif[0x010F], exif[0x0110], exif[0x0112] = 'SONY', model.decode(), 6   # make, model, orientation 90° CW
        path = self.dir / name
        path.write_bytes(exif.tobytes()[6:] + os.urandom(3000) + buf.getvalue() + os.urandom(3000))
        return path

    def test_unrecognised_camera_file_falls_back_to_scanned_preview(self):
        # Sony A7 V "compressed" ARW: LibRaw 0.22.1 does not open it, but the camera stored its JPEG.
        path = self._camera_file('DSC00001.ARW')
        with patch('rawpy.imread', side_effect=rawpy.LibRawFileUnsupportedError('unsupported')):
            image, source, notice = raw_io.decode_photo(path)
            self.assertEqual((source, image.size), ('camera_preview', (1600, 2400)))   # upright
            self.assertEqual(raw_io.embedded_preview(path).size, (1600, 2400))
            with self.assertRaisesRegex(DecodeError, 'does not recognise'):
                raw_io.decode_photo(path, allow_preview=False)
            small = self._camera_file('DSC00002.ARW', preview=(640, 480))
            with self.assertRaisesRegex(DecodeError, 'no usable embedded preview'):
                raw_io.decode_photo(small)
            junk = self.dir / 'junk.ARW'          # no camera EXIF: never falls back, even with a JPEG inside
            junk.write_bytes(os.urandom(2000) + path.read_bytes()[-200000:])
            with self.assertRaisesRegex(DecodeError, 'does not recognise'):
                raw_io.decode_photo(junk)

    def test_analysis_decodes_only_as_large_as_needed(self):
        def raw(w, h, flip=0):
            r = MagicMock()
            r.sizes.width, r.sizes.height, r.sizes.flip = w, h, flip
            return r
        self.assertTrue(raw_io._render_options(raw(8256, 5504), 4000).get('half_size'))         # 45 MP: binned
        small = raw_io._render_options(raw(6048, 4024), 4000)                                   # 24 MP: fast demosaic
        self.assertNotIn('half_size', small)
        self.assertEqual(small['demosaic_algorithm'], rawpy.DemosaicAlgorithm.LINEAR)
        full = raw_io._render_options(raw(8256, 5504), None)                                    # inspection: full quality
        self.assertNotIn('half_size', full)
        self.assertNotIn('demosaic_algorithm', full)
        self.assertEqual(raw_io._native_size(raw(8256, 5504, flip=6)), (5504, 8256))
        # decode_photo reports the full-resolution size of a half-size decode
        path = self.dir / 'big.NEF'
        path.write_bytes(os.urandom(4000))
        decoded = raw(8256, 5504)
        decoded.postprocess.return_value = np.zeros((2752, 4128, 3), np.uint8)
        context = MagicMock()
        context.__enter__.return_value = decoded
        with patch('rawpy.imread', return_value=context):
            image, source, _ = raw_io.decode_photo(path, min_edge=4000)
        self.assertEqual((image.size, image.info['native_size'], source), ((4128, 2752), (8256, 5504), 'decoded_raw'))
        self.assertTrue(decoded.postprocess.call_args.kwargs['half_size'])

    def test_exif_info_reads_lazily_once(self):
        from helpers import make_jpeg
        path = self.dir / 'IMG.jpg'
        make_jpeg(path, when='2026:05:01 10:00:00', subsec='25')
        stamp, camera = raw_io.exif_info(path)
        self.assertAlmostEqual(stamp % 60, .25, places=2)
        self.assertEqual(raw_io.exif_info(self.dir / 'missing.NEF'), (None, None))

    def _contexts(self, preview_size=(1200, 800)):
        import io as _io
        buf = _io.BytesIO()
        Image.new('RGB', preview_size, 'white').save(buf, format='JPEG')
        failed = MagicMock()
        failed.postprocess.side_effect = rawpy.LibRawFileUnsupportedError('unsupported')
        preview = MagicMock()
        preview.sizes.flip = 0
        preview.extract_thumb.return_value = type('Thumb', (), {'format': rawpy.ThumbFormat.JPEG, 'data': buf.getvalue()})()
        first, second = MagicMock(), MagicMock()
        first.__enter__.return_value = failed
        second.__enter__.return_value = preview
        return failed, first, second

    def test_preview_fallback_reopens_and_reports_source(self):
        path = self.dir / 'a.NEF'
        path.write_bytes(os.urandom(4000))
        failed, first, second = self._contexts()
        with patch('rawpy.imread', side_effect=[first, second]) as read:
            image, source, notice = raw_io.decode_photo(path)
        self.assertEqual(read.call_count, 2)               # reopened after the failed decode
        failed.extract_thumb.assert_not_called()
        self.assertEqual((image.size, source), ((1200, 800), 'camera_preview'))
        self.assertIn('do not measure the original RAW', notice)

    def test_strict_decode_disallows_preview(self):
        path = self.dir / 'a.NEF'
        path.write_bytes(os.urandom(4000))
        failed, first, second = self._contexts()
        with patch('rawpy.imread', side_effect=[first, second]) as read:
            with self.assertRaises(DecodeError):
                raw_io.decode_photo(path, allow_preview=False)
        self.assertEqual(read.call_count, 1)

    def test_thumbnail_sized_preview_is_not_used(self):
        path = self.dir / 'a.ORF'
        path.write_bytes(os.urandom(4000))
        failed, first, second = self._contexts((160, 120))
        with patch('rawpy.imread', side_effect=[first, second]):
            with self.assertRaisesRegex(DecodeError, 'no usable embedded preview'):
                raw_io.decode_photo(path)

    def test_unrecognised_file_never_falls_back(self):
        path = self.dir / 'garbage.NEF'
        path.write_bytes(os.urandom(4000))
        with patch('rawpy.imread', side_effect=rawpy.LibRawFileUnsupportedError('not raw')) as read:
            with self.assertRaises(DecodeError):
                raw_io.decode_photo(path)
        self.assertEqual(read.call_count, 1)

    def test_empty_file(self):
        path = self.dir / 'empty.NEF'
        path.write_bytes(b'')
        with self.assertRaisesRegex(DecodeError, 'empty'):
            decode(path)

    @unittest.skipIf(os.name != 'posix' or os.geteuid() == 0, 'permissions are not enforced for root')
    def test_permission_denied(self):
        path = self.dir / 'locked.jpg'
        make_jpeg(path)
        path.chmod(0)
        try:
            with self.assertRaisesRegex(DecodeError, 'Permission denied'):
                decode(path)
        finally:
            path.chmod(0o644)

    def test_jpeg_orientation_applied(self):
        path = make_jpeg(self.dir / 'portrait.JPG', size=(300, 200), orientation=6)
        self.assertEqual(decode(path).size, (200, 300))

    def test_capture_time_with_subseconds(self):
        path = make_jpeg(self.dir / 'a.jpg', when='2026:05:01 10:00:00', subsec='25')
        t = raw_io.capture_time(path)
        self.assertAlmostEqual(t % 60, 0.25, places=3)
        self.assertIsNone(raw_io.capture_time(make_jpeg(self.dir / 'b.jpg')))

    def test_capture_time_from_orf_style_header(self):
        tif = self.dir / 'x.tif'
        im = Image.new('RGB', (16, 16))
        info = Image.Exif()
        info[0x0132] = '2026:05:01 10:00:07'
        im.save(tif, exif=info.tobytes())
        data = bytearray(tif.read_bytes())
        self.assertEqual(bytes(data[:4]), b'II*\x00')
        data[:4] = b'IIRO'
        orf = self.dir / 'x.ORF'
        orf.write_bytes(bytes(data))
        self.assertIsNotNone(raw_io.capture_time(orf))

    def test_hidden_files(self):
        self.assertTrue(raw_io.is_hidden('._DSC_0001.NEF'))
        self.assertTrue(raw_io.is_hidden('.DS_Store'))
        self.assertFalse(raw_io.is_hidden('DSC_0001.NEF'))

    @unittest.skipUnless(has_pidng(), 'pidng not installed')
    def test_real_libraw_decode_of_dng(self):
        path = make_dng(self.dir / 'real.DNG', size=(600, 400))
        im = decode(path)
        self.assertEqual(im.mode, 'RGB')
        self.assertEqual(sorted(im.size), [400, 600])
        a = np.asarray(im, dtype=float)
        self.assertGreater(a.std(), 5)          # actual image content, not a blank frame
        self.assertIsNone(raw_io.embedded_preview(self.dir / 'missing.NEF'))


if __name__ == '__main__':
    unittest.main()
