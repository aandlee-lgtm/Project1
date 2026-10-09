"""Probe a camera model's RAW samples from raw.pixls.us against the bundled decoder.

Usage: python probe_camera.py "Z 6III" [more model substrings...]
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
    wanted = [w.upper().replace(' ', '') for w in sys.argv[1:]]
    entries = [l.split(None, 1) for l in get(BASE + 'filelist.sha256').decode().splitlines() if l.strip()]
    hits = [(h, p.lstrip('*').lstrip('./')) for h, p in entries
            if any(w in p.upper().replace(' ', '') for w in wanted)]
    print(f'{len(hits)} matching files')
    for h, path in hits:
        print('\n==', path)
        try:
            data = get(BASE + urllib.parse.quote(path))
        except Exception as e:
            print('  download failed:', e); continue
        print(f'  {len(data)/2**20:.1f} MB, sha256 ok: {hashlib.sha256(data).hexdigest() == h}')
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
