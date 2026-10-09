"""Image decoding for PhotoSelect.

RAW files are demosaiced by rawpy / LibRaw for analysis. The camera's embedded
JPEG preview is only used for fast initial thumbnails and is always labelled as
such; it is never scored. Source files are opened read-only and never modified.
"""
import io
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

# Large TIFF/PNG exports from stitched panoramas can exceed Pillow's default
# decompression-bomb limit; 400 MP covers current camera sensors with headroom.
Image.MAX_IMAGE_PIXELS = 400_000_000

RAW_FORMATS = {
    '.nef': 'Nikon NEF', '.nrw': 'Nikon NRW', '.orf': 'Olympus / OM System ORF',
    '.arw': 'Sony ARW', '.cr2': 'Canon CR2', '.cr3': 'Canon CR3', '.dng': 'DNG',
    '.raf': 'Fujifilm RAF', '.rw2': 'Panasonic RW2', '.pef': 'Pentax PEF', '.srw': 'Samsung SRW',
}
RAW = set(RAW_FORMATS)
FORMATS = RAW | {'.jpg', '.jpeg', '.png', '.tif', '.tiff'}

# LibRaw "flip" values -> Pillow transpose needed to display upright.
_FLIP = {3: Image.Transpose.ROTATE_180, 5: Image.Transpose.ROTATE_90, 6: Image.Transpose.ROTATE_270}


class DecodeError(RuntimeError):
    """A file could not be decoded; the message is shown to the user."""


def format_name(path):
    extension = Path(path).suffix.lower()
    return RAW_FORMATS.get(extension, extension.lstrip('.').upper())


def is_raw(path):
    return Path(path).suffix.lower() in RAW


def _check_readable(path):
    try:
        size = path.stat().st_size
        with path.open('rb') as f:
            f.read(16)
    except PermissionError as error:
        raise DecodeError('Permission denied. macOS has not granted PhotoSelect access to this file or folder. '
                          'Choose the folder again with "Choose folder", or allow access in System Settings → '
                          'Privacy & Security → Files and Folders.') from error
    except FileNotFoundError as error:
        raise DecodeError('The file is no longer available (moved, renamed or the drive was ejected).') from error
    except OSError as error:
        raise DecodeError(f'The file could not be read: {error.strerror or error}.') from error
    if size == 0:
        raise DecodeError('The file is empty (0 bytes). It may be an incomplete copy.')


def is_nikon_high_efficiency(path):
    """Nikon HE / HE* NEFs store the sensor data as an intoPIX TicoRAW codestream."""
    try:
        with open(path, 'rb') as f:
            return b'CONTACT_INTOPIX' in f.read(8 * 1024 * 1024)
    except OSError:
        return False


def _raw_error(path, error):
    import rawpy
    name = format_name(path)
    if isinstance(error, rawpy.LibRawFileUnsupportedError) and Path(path).suffix.lower() == '.nef' \
            and is_nikon_high_efficiency(path):
        return DecodeError('Nikon High Efficiency (HE / HE★) NEF: this compression uses a licensed codec that the '
                           'bundled LibRaw decoder cannot read. Set the camera to NEF (RAW) compression → Lossless '
                           'compressed for shoots you want to cull here. The file has not been changed.')
    if isinstance(error, rawpy.LibRawFileUnsupportedError):
        return DecodeError(f'{name}: the bundled LibRaw {libraw_version()} decoder does not recognise this file. It may be '
                           'damaged or incomplete, or come from a camera model or RAW mode that LibRaw does not support. '
                           'The file has not been changed.')
    if isinstance(error, (rawpy.LibRawDataError, rawpy.LibRawIOError)):
        return DecodeError(f'{name}: the RAW data is damaged or truncated ({error}). Check that the copy is complete.')
    if isinstance(error, MemoryError):
        return DecodeError(f'{name}: not enough memory to decode this file.')
    return DecodeError(f'{name} could not be decoded: {error}. Check that the file is complete and readable.')


def decode(path):
    """Fully decode an image to an upright 8-bit sRGB PIL image."""
    path = Path(path)
    _check_readable(path)
    if path.suffix.lower() in RAW:
        try:
            import rawpy
        except ImportError as error:  # pragma: no cover - packaging fault
            raise DecodeError('The RAW decoder is missing from this build of PhotoSelect.') from error
        try:
            with rawpy.imread(str(path)) as raw:
                # Camera white balance, sRGB output, no per-image auto brightening so that
                # exposure is rendered consistently across a burst. LibRaw applies orientation.
                rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=8,
                                      output_color=rawpy.ColorSpace.sRGB)
            return Image.fromarray(rgb)
        except DecodeError:
            raise
        except Exception as error:
            raise _raw_error(path, error) from error
    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode in ('I;16', 'I;16B', 'I;16L', 'I'):
                im = im.point(lambda v: v / 256).convert('L')
            return im.convert('RGB')
    except Image.DecompressionBombError as error:
        raise DecodeError('The image is larger than 400 megapixels and was skipped.') from error
    except OSError as error:
        raise DecodeError(f'{format_name(path)} could not be decoded: {error}. The file may be damaged or use an '
                          'unsupported encoding.') from error


def embedded_preview(path):
    """Return the camera's embedded preview of a RAW file (upright), or None.

    Used only for fast initial thumbnails, never for scoring.
    """
    path = Path(path)
    if path.suffix.lower() not in RAW:
        return None
    try:
        import rawpy
        with rawpy.imread(str(path)) as raw:
            flip = raw.sizes.flip
            thumb = raw.extract_thumb()
        if thumb.format == rawpy.ThumbFormat.JPEG:
            im = Image.open(io.BytesIO(thumb.data))
            im.load()
            if im.getexif().get(0x0112, 1) not in (0, 1):
                return ImageOps.exif_transpose(im).convert('RGB')
            im = im.convert('RGB')
        elif thumb.format == rawpy.ThumbFormat.BITMAP:
            im = Image.fromarray(thumb.data).convert('RGB')
        else:
            return None
        return im.transpose(_FLIP[flip]) if flip in _FLIP else im
    except Exception:
        return None


def _exif_file(path):
    """Open a file for ExifRead; ORF uses a TIFF variant with a non-standard magic number."""
    with open(path, 'rb') as f:
        head = f.read(4)
        f.seek(0)
        if head in (b'IIRO', b'IIRS', b'MMOR'):
            data = bytearray(f.read(4 * 1024 * 1024))
            data[0:4] = b'II*\x00' if head.startswith(b'II') else b'MM\x00*'
            return io.BytesIO(bytes(data))
        return io.BytesIO(f.read(4 * 1024 * 1024))


def capture_time(path):
    """Capture time in seconds (with sub-seconds when recorded), or None."""
    try:
        import exifread
        tags = exifread.process_file(_exif_file(path), details=False, stop_tag='SubSecTimeOriginal')
        date = str(tags.get('EXIF DateTimeOriginal') or tags.get('Image DateTime') or '').strip()
        if not date:
            return None
        stamp = datetime.strptime(date[:19], '%Y:%m:%d %H:%M:%S').timestamp()
        sub = ''.join(c for c in str(tags.get('EXIF SubSecTimeOriginal', '')) if c.isdigit())
        return stamp + (float('0.' + sub) if sub else 0.0)
    except Exception:
        return None


def camera_model(path):
    try:
        import exifread
        tags = exifread.process_file(_exif_file(path), details=False, stop_tag='Model')
        return ' '.join(str(tags.get(k, '')).strip() for k in ('Image Make', 'Image Model')).strip() or None
    except Exception:
        return None


def is_hidden(name):
    """Skip AppleDouble ('._x.NEF') files that macOS writes on non-APFS drives, and dot-files."""
    return name.startswith('.')


def libraw_version():
    try:
        import rawpy
        return '.'.join(map(str, rawpy.libraw_version))
    except Exception:
        return 'unavailable'


__all__ = ['RAW', 'RAW_FORMATS', 'FORMATS', 'DecodeError', 'format_name', 'is_raw', 'decode',
           'embedded_preview', 'capture_time', 'camera_model', 'is_hidden', 'libraw_version']
