"""Full RAW decoding; camera JPEG previews are not used for scoring."""
from pathlib import Path
from PIL import Image, ImageOps

RAW_FORMATS={'.nef':'Nikon NEF','.nrw':'Nikon NRW','.orf':'Olympus / OM System ORF',
             '.arw':'Sony ARW','.cr2':'Canon CR2','.cr3':'Canon CR3','.dng':'DNG',
             '.raf':'Fujifilm RAF','.rw2':'Panasonic RW2','.pef':'Pentax PEF','.srw':'Samsung SRW'}
RAW=set(RAW_FORMATS)
FORMATS=RAW|{'.jpg','.jpeg','.png','.tif','.tiff'}

def format_name(path):
    extension=Path(path).suffix.lower()
    return RAW_FORMATS.get(extension,extension.lstrip('.').upper())

def decode(path):
    path=Path(path)
    if path.suffix.lower() in RAW:
        try:
            import rawpy
        except ImportError as error:
            raise RuntimeError('The RAW decoder is not installed. Restart using the Mac launcher to complete setup.') from error
        try:
            with rawpy.imread(str(path)) as raw:
                return Image.fromarray(raw.postprocess(use_camera_wb=True,no_auto_bright=True,output_bps=8))
        except rawpy.LibRawFileUnsupportedError as error:
            raise RuntimeError(f'{format_name(path)}: this camera model or RAW encoding is unsupported by the installed decoder. The file has not been changed.') from error
        except Exception as error:
            raise RuntimeError(f'{format_name(path)} could not be decoded: {error}. Check that the file is complete and readable.') from error
    with Image.open(path) as im:
        return ImageOps.exif_transpose(im).convert('RGB')
