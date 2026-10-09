"""Check whether macOS's own RAW engine (Core Image CIRAWFilter) decodes given RAW sample URLs.

Run on a Mac: python probe_apple_raw.py URL [URL...]
"""
import io, sys, tempfile, urllib.request
import numpy as np
from PIL import Image
import Quartz
from Foundation import NSURL


def main():
    models = [str(m) for m in (Quartz.CIRAWFilter.supportedCameraModels() or [])]
    print(f'macOS RAW engine lists {len(models)} camera models; Nikon Z: {[m for m in models if "Z" in m and "Nikon" in m.title()][:40]}')
    ctx = Quartz.CIContext.contextWithOptions_(None)
    for url in sys.argv[1:]:
        data = urllib.request.urlopen(url, timeout=180).read()
        path = tempfile.mktemp(suffix='.NEF')
        open(path, 'wb').write(data)
        name = url.rsplit('/', 1)[-1]
        f = Quartz.CIRAWFilter.filterWithImageURL_(NSURL.fileURLWithPath_(path))
        if f is None:
            print(f'{name}: CIRAWFilter could not open it'); continue
        print(f'{name}: supported decoder versions {list(f.supportedDecoderVersions() or [])[:3]}, native size {f.nativeSize()}')
        img = f.outputImage()
        if img is None:
            print('   no output image'); continue
        ext = img.extent()
        cg = ctx.createCGImage_fromRect_(img, ext)
        w, h = Quartz.CGImageGetWidth(cg), Quartz.CGImageGetHeight(cg)
        out = tempfile.mktemp(suffix='.png')
        dest = Quartz.CGImageDestinationCreateWithURL(NSURL.fileURLWithPath_(out), 'public.png', 1, None)
        Quartz.CGImageDestinationAddImage(dest, cg, None); Quartz.CGImageDestinationFinalize(dest)
        a = np.asarray(Image.open(out).convert('L').resize((300, 200)), np.float32)
        import rawpy
        with rawpy.imread(path) as r:
            t = r.extract_thumb()
        b = np.asarray(Image.open(io.BytesIO(t.data)).convert('L').resize((300, 200)), np.float32)
        print(f'   DECODED by macOS: {w}x{h}, mean {a.mean()/255:.3f}, correlation with embedded JPEG {np.corrcoef(a.ravel(), b.ravel())[0,1]:.3f}')


if __name__ == '__main__':
    main()
