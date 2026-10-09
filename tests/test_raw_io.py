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
