"""Probe a camera model's RAW samples from raw.pixls.us against the bundled decoder.

Usage: python probe_camera.py "Z 6III" [more model substrings...]  (run by .github/workflows/probe-camera.yml)
Prints, per sample file: size, whether rawpy/LibRaw decodes it (and the error if not), the
NEF compression tag when present, and the size of the embedded camera JPEG.
"""
import hashlib, io, sys, urllib.parse, urllib.request
BASE = 'https://raw.pixls.us/data-unique/'

def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'PhotoSelect-probe'}), timeout=180).read()

def main():
    import rawpy, exifread
    from PIL import Image
    print('rawpy', rawpy.__version__, 'LibRaw', '.'.join(map(str, rawpy.libraw_version)))
    import re
    wanted = [w.upper().replace(' ', '').replace('_', '') for w in sys.argv[1:]]

    def listing(url):
        html = get(url).decode('utf-8', 'replace')
        return [urllib.parse.unquote(h) for h in re.findall(r'href="([^"?/][^"]*)"', html)]
    hits = []
    for make in ('Nikon/', 'NIKON CORPORATION/'):
        root = 'https://raw.pixls.us/data/' + urllib.parse.quote(make)
        try:
            models = listing(root)
        except Exception as e:
            print('listing failed', root, e); continue
        print(make, 'models:', [m for m in models if 'Z' in m.upper()][:60])
        for m in models:
            if any(w in m.upper().replace(' ', '').replace('_', '').rstrip('/') for w in wanted):
                for f in listing(root + urllib.parse.quote(m)):
                    if not f.endswith('/'):
                        hits.append((None, 'https://raw.pixls.us/data/' + urllib.parse.quote(make + m + f)))
    print(f'{len(hits)} matching files')
    for h, path in hits:
        print('\n==', path)
        try:
            data = get(path)
        except Exception as e:
            print('  download failed:', e); continue
        print(f'  {len(data)/2**20:.1f} MB')
        try:
            tags = exifread.process_file(io.BytesIO(data), details=True)
            for k in ('Image Model', 'MakerNote NEFCompression', 'MakerNote Quality', 'EXIF CompressedBitsPerPixel', 'Image BitsPerSample'):
                if k in tags: print(f'  {k}: {tags[k]}')
        except Exception as e:
            print('  exif error:', e)
        try:
            with rawpy.imread(io.BytesIO(data)) as raw:
                rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=8)
            print(f'  DECODE OK {rgb.shape[1]}x{rgb.shape[0]} mean {rgb.mean()/255:.3f}')
        except Exception as e:
            print(f'  DECODE FAILED: {type(e).__name__}: {e}')
        try:
            with rawpy.imread(io.BytesIO(data)) as raw:
                t = raw.extract_thumb()
            if t.format == rawpy.ThumbFormat.JPEG:
                im = Image.open(io.BytesIO(t.data)); print(f'  embedded JPEG {im.width}x{im.height}')
            else:
                print('  embedded thumb format', t.format)
        except Exception as e:
            print(f'  embedded preview: {type(e).__name__}: {e}')

if __name__ == '__main__':
    main()
