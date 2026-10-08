import unittest,tempfile
from pathlib import Path
from unittest.mock import patch,MagicMock
import numpy as np
import rawpy
from raw_io import decode,FORMATS,format_name

class RawFormatTests(unittest.TestCase):
    def test_nef_and_orf_case_insensitive_decoder_routing(self):
        for suffix in ('.nef','.NEF','.NeF','.nrw','.NRW','.orf','.ORF','.Orf'):
            with self.subTest(suffix=suffix):
                self.assertIn(suffix.lower(),FORMATS)
                processor=MagicMock(); processor.postprocess.return_value=np.zeros((16,24,3),dtype=np.uint8)
                context=MagicMock(); context.__enter__.return_value=processor
                with patch('rawpy.imread',return_value=context) as read:
                    result=decode(Path('photo'+suffix))
                read.assert_called_once_with('photo'+suffix)
                processor.postprocess.assert_called_once_with(use_camera_wb=True,no_auto_bright=True,output_bps=8)
                self.assertEqual(result.size,(24,16))
    def test_camera_format_names(self):
        self.assertEqual(format_name('a.NEF'),'Nikon NEF')
        self.assertEqual(format_name('a.ORF'),'Olympus / OM System ORF')
    def test_unsupported_raw_message(self):
        with patch('rawpy.imread',side_effect=rawpy.LibRawFileUnsupportedError('unsupported')):
            with self.assertRaisesRegex(RuntimeError,'Olympus / OM System ORF.*unsupported'):
                decode('a.ORF')
    def test_invalid_nef_and_orf_do_not_stop_scan(self):
        import app
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            (folder/'broken.NEF').write_bytes(b'broken')
            (folder/'broken.ORF').write_bytes(b'broken')
            Image.new('RGB',(32,32),'white').save(folder/'valid.jpg')
            app.state.update(rows=[],errors=[],running=True)
            app.scan(folder,False)
            self.assertFalse(app.state['running'])
            self.assertEqual(len(app.state['rows']),1)
            self.assertEqual(len(app.state['errors']),2)
            self.assertIn('format',app.state['rows'][0])
if __name__=='__main__':unittest.main()
