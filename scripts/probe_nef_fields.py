"""Print the NEF fields that identify the compression mode, for local files or URLs."""
import io, sys, urllib.request
import exifread

KEYS = ('Image Software', 'EXIF SubIFD1 Compression', 'EXIF SubIFD1 BitsPerSample', 'EXIF SubIFD1 StripByteCounts',
        'EXIF SubIFD1 ImageWidth', 'MakerNote NEFCompression', 'MakerNote Tag 0x0093', 'MakerNote Tag 0x0051',
        'MakerNote Tag 0x0053', 'MakerNote NEFBitDepth', 'MakerNote Tag 0x0045', 'MakerNote ImageSizeRAW')


def load(src):
    if src.startswith('http'):
        return urllib.request.urlopen(urllib.request.Request(src, headers={'User-Agent': 'probe'}), timeout=180).read()
    return open(src, 'rb').read()


for src in sys.argv[1:]:
    data = load(src)
    tags = exifread.process_file(io.BytesIO(data), details=True)
    print(f'== {src.rsplit("/", 1)[-1]}  ({len(data) / 2**20:.1f} MB)')
    for k in KEYS:
        if k in tags:
            v = tags[k]
            print(f'   {k}: {v.printable[:70]}  raw={list(v.values)[:24] if hasattr(v.values, "__iter__") and not isinstance(v.values, str) else v.values}')
    offs = tags.get('EXIF SubIFD1 StripOffsets')
    if offs:
        o = offs.values[0]
        print(f'   first 16 bytes of RAW data: {data[o:o + 16].hex()}')
