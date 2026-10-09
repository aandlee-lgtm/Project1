import hashlib
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def scene(seed=0, size=(640, 427), blur=0):
    """A textured synthetic scene; `blur` simulates missed focus."""
    rng = np.random.default_rng(seed)
    w, h = size
    y, x = np.mgrid[:h, :w]
    base = (np.sin(x / (5 + seed % 3)) * np.cos(y / 7) * 90 + 128 + rng.normal(0, 4, (h, w))).clip(0, 255)
    rgb = np.stack([base, base * .9 + 10, base * .8 + 20], -1).clip(0, 255).astype('uint8')
    im = Image.fromarray(rgb)
    return im.filter(ImageFilter.GaussianBlur(blur)) if blur else im


def make_jpeg(path, seed=0, when=None, subsec=None, blur=0, size=(640, 427), orientation=None):
    im = scene(seed, size, blur)
    exif = Image.Exif()
    if when:
        exif[0x0132] = when
        sub = exif.get_ifd(0x8769)
        sub[0x9003] = when
        if subsec is not None:
            sub[0x9291] = str(subsec)
    if orientation:
        exif[0x0112] = orientation
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    im.save(path, quality=92, exif=exif.tobytes())
    return path


def make_dng(path, size=(1200, 800), seed=0, blur=False):
    """A genuine (synthetic-scene) Bayer DNG that LibRaw demosaics. Needs the pidng package."""
    from pidng.core import RAW2DNG, DNGTags, Tag
    from pidng.defs import Orientation, PhotometricInterpretation, CFAPattern, CalibrationIlluminant, DNGVersion
    w, h = size
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[:h, :w]
    img = (np.sin(x / 6) * np.cos(y / 8) * 1400 + 2000 + rng.normal(0, 20, (h, w)))
    if blur:
        from PIL import Image as _I
        img = np.asarray(_I.fromarray(img.astype('float32')).filter(ImageFilter.GaussianBlur(4)))
    img = img.clip(0, 4095).astype(np.uint16)
    t = DNGTags()
    for tag, value in [(Tag.ImageWidth, w), (Tag.ImageLength, h), (Tag.TileWidth, w), (Tag.TileLength, h),
                       (Tag.Orientation, Orientation.Horizontal),
                       (Tag.PhotometricInterpretation, PhotometricInterpretation.Color_Filter_Array),
                       (Tag.SamplesPerPixel, 1), (Tag.BitsPerSample, 12), (Tag.CFARepeatPatternDim, [2, 2]),
                       (Tag.CFAPattern, CFAPattern.BGGR), (Tag.BlackLevel, 0), (Tag.WhiteLevel, 4095),
                       (Tag.ColorMatrix1, [[1, 1], [0, 1], [0, 1], [0, 1], [1, 1], [0, 1], [0, 1], [0, 1], [1, 1]]),
                       (Tag.CalibrationIlluminant1, CalibrationIlluminant.D65), (Tag.AsShotNeutral, [[1, 1]] * 3),
                       (Tag.Make, 'Test'), (Tag.Model, 'Synthetic'), (Tag.DNGVersion, DNGVersion.V1_4),
                       (Tag.DNGBackwardVersion, DNGVersion.V1_2)]:
        t.set(tag, value)
    r = RAW2DNG()
    r.options(t, path='', compress=False)
    stem = str(Path(path).with_suffix(''))
    r.convert(img, filename=stem)
    produced = Path(stem + '.dng')
    if produced != Path(path):
        os.replace(produced, path)
    return path


def has_pidng():
    try:
        import pidng  # noqa: F401
        return True
    except ImportError:
        return False


def fingerprint(folder):
    """sha256, size, mtime and xattr names for every file below folder."""
    out = {}
    for root, _, files in os.walk(folder):
        for f in files:
            p = Path(root) / f
            st = p.lstat()
            data = p.read_bytes() if os.access(p, os.R_OK) else b''
            try:
                xattrs = sorted(os.listxattr(p))
            except (OSError, AttributeError):
                xattrs = []
            out[str(p)] = (hashlib.sha256(data).hexdigest(), st.st_size, st.st_mtime_ns, tuple(xattrs))
    return out


def wait_idle(library, timeout=60):
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not library.snapshot()['running']:
            return True
        time.sleep(.02)
    raise TimeoutError('scan did not finish')
