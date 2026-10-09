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


def _raw_error(path, error, preview_tried=False):
    import rawpy
    name = format_name(path)
    no_preview = ' No usable embedded camera preview was found either.' if preview_tried else ''
    if isinstance(error, (rawpy.LibRawFileUnsupportedError, rawpy.LibRawDataError)) \
            and Path(path).suffix.lower() == '.nef' and is_nikon_high_efficiency(path):
        return DecodeError('Nikon High Efficiency (HE / HE★) NEF: this compression uses a licensed codec that the '
                           f'bundled LibRaw decoder cannot read.{no_preview} Set the camera to NEF (RAW) compression → '
                           'Lossless compressed for shoots you want to cull here. The file has not been changed.')
    if isinstance(error, rawpy.LibRawFileUnsupportedError) and preview_tried:
        return DecodeError(f'{name}: this camera model or RAW encoding is unsupported by the bundled LibRaw '
                           f'{libraw_version()} decoder, and no usable embedded preview was available. '
                           'The file has not been changed.')
    if isinstance(error, rawpy.LibRawFileUnsupportedError):
        return DecodeError(f'{name}: the bundled LibRaw {libraw_version()} decoder does not recognise this file. It may be '
                           'damaged or incomplete, or come from a camera model or RAW mode that LibRaw does not support. '
                           'The file has not been changed.')
    if isinstance(error, (rawpy.LibRawDataError, rawpy.LibRawIOError)):
        return DecodeError(f'{name}: the RAW data is damaged or truncated ({error}). Check that the copy is complete.')
    if isinstance(error, MemoryError):
        return DecodeError(f'{name}: not enough memory to decode this file.')
    return DecodeError(f'{name} could not be decoded: {error}. Check that the file is complete and readable.')


PREVIEW_NOTICE = ('RAW pixels could not be decoded. Scores and inspection use the embedded camera JPEG, including '
                  'camera sharpening and noise reduction; they do not measure the original RAW pixels.')
MIN_PREVIEW_EDGE = 1000   # a thumbnail-sized preview is not useful for judging focus


class _PixelsUnsupported(Exception):
    """LibRaw recognised the RAW container but cannot decode its pixel data (e.g. Nikon HE/HE*)."""


def decode_photo(path, allow_preview=True):
    """Decode a photo. Returns (upright 8-bit sRGB image, source, notice).

    source is 'decoded_raw' (LibRaw demosaic), 'image' (JPEG/PNG/TIFF) or 'camera_preview': the
    camera's embedded JPEG, used only when LibRaw recognises the file as RAW but cannot decode its
    pixels and the camera stored a usable preview. Damaged or non-RAW files never fall back.
    """
    path = Path(path)
    _check_readable(path)
    if path.suffix.lower() not in RAW:
        try:
            with Image.open(path) as im:
                im = ImageOps.exif_transpose(im)
                if im.mode in ('I;16', 'I;16B', 'I;16L', 'I'):
                    im = im.point(lambda v: v / 256).convert('L')
                return im.convert('RGB'), 'image', ''
        except Image.DecompressionBombError as error:
            raise DecodeError('The image is larger than 400 megapixels and was skipped.') from error
        except OSError as error:
            raise DecodeError(f'{format_name(path)} could not be decoded: {error}. The file may be damaged or use an '
                              'unsupported encoding.') from error
    try:
        import rawpy
    except ImportError as error:  # pragma: no cover - packaging fault
        raise DecodeError('The RAW decoder is missing from this build of PhotoSelect.') from error
    try:
        with rawpy.imread(str(path)) as raw:
            try:
                # Camera white balance, sRGB output, no per-image auto brightening so that
                # exposure is rendered consistently across a burst. LibRaw applies orientation.
                rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=8,
                                      output_color=rawpy.ColorSpace.sRGB)
            except rawpy.LibRawFileUnsupportedError as error:
                raise _PixelsUnsupported() from error
            except rawpy.LibRawDataError as error:
                # Some cameras' High Efficiency NEFs (e.g. Nikon Z50 II) make LibRaw start decoding and
                # stop with a data error instead of reporting the format as unsupported. Only a NEF that
                # carries the HE codec marker is treated as undecodable; other data errors mean damage.
                if path.suffix.lower() == '.nef' and is_nikon_high_efficiency(path):
                    raise _PixelsUnsupported() from error
                raise
        return Image.fromarray(rgb), 'decoded_raw', ''
    except rawpy.LibRawFileUnsupportedError as error:
        # LibRaw does not recognise the file at all: a camera model or RAW mode newer than the bundled
        # decoder (e.g. Sony A7 V "compressed"), or not a RAW file. Only a genuine camera file with its own
        # full-size JPEG falls back.
        camera_file = allow_preview and bool(camera_model(path))
        if camera_file:
            preview = scanned_preview(path)
            if preview is not None:
                return preview, 'camera_preview', PREVIEW_NOTICE
        raise _raw_error(path, error, preview_tried=camera_file) from error
    except _PixelsUnsupported as wrapped:
        original = wrapped.__cause__
        if allow_preview:
            # A failed decode leaves LibRaw unusable for this handle; embedded_preview reopens the file.
            preview = embedded_preview(path)
            if preview is not None and max(preview.size) >= MIN_PREVIEW_EDGE:
                return preview, 'camera_preview', PREVIEW_NOTICE
        raise _raw_error(path, original, preview_tried=allow_preview) from original
    except DecodeError:
        raise
    except Exception as error:
        raise _raw_error(path, error) from error


def decode(path):
    """Upright 8-bit sRGB image of a photo (embedded camera JPEG for undecodable RAW, see decode_photo)."""
    return decode_photo(path)[0]


def embedded_preview(path):
    """Return the camera's embedded preview of a RAW file (upright), or None.

    Used for fast initial thumbnails, and by decode_photo as a labelled fallback when LibRaw
    cannot decode the RAW pixels.
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
        return scanned_preview(path)


_ORIENT = {3: Image.Transpose.ROTATE_180, 6: Image.Transpose.ROTATE_270, 8: Image.Transpose.ROTATE_90}


def scanned_preview(path, max_bytes=400 * 2 ** 20):
    """Largest camera JPEG embedded anywhere in a RAW file that LibRaw cannot open (upright), or None.

    For camera models or RAW modes newer than the bundled LibRaw (e.g. Sony A7 V "compressed"), the
    camera still stores its own JPEG preview. Only genuine camera files qualify: the file must name its
    camera model in EXIF, and the JPEG must be at least MIN_PREVIEW_EDGE pixels on its long edge.
    """
    path = Path(path)
    if path.suffix.lower() not in RAW or not camera_model(path):
        return None
    try:
        if path.stat().st_size > max_bytes:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    best, start = None, 0
    while True:
        at = data.find(b'\xff\xd8\xff', start)
        if at < 0:
            break
        start = at + 3
        try:
            with Image.open(io.BytesIO(data[at:at + 64 * 2 ** 20])) as candidate:
                if candidate.format == 'JPEG' and (best is None or candidate.size[0] * candidate.size[1] > best[1]):
                    best = (at, candidate.size[0] * candidate.size[1], max(candidate.size))
        except Exception:
            continue
    if best is None or best[2] < MIN_PREVIEW_EDGE:
        return None
    try:
        im = Image.open(io.BytesIO(data[best[0]:best[0] + 64 * 2 ** 20]))
        im.load()
        im = im.convert('RGB')
    except Exception:
        return None
    try:
        import exifread
        tags = exifread.process_file(_exif_file(path), details=False, stop_tag='Orientation')
        orientation = getattr(tags.get('Image Orientation'), 'values', [1])[0]
    except Exception:
        orientation = 1
    return im.transpose(_ORIENT[orientation]) if orientation in _ORIENT else im


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


__all__ = ['RAW', 'RAW_FORMATS', 'FORMATS', 'DecodeError', 'format_name', 'is_raw', 'decode', 'decode_photo',
           'embedded_preview', 'capture_time', 'camera_model', 'is_hidden', 'libraw_version']
