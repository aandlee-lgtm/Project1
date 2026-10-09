"""Check every Sony A7 / A9 series RAW sample on raw.pixls.us against PhotoSelect's decoder.

Usage: python scripts/sony_coverage.py OUTDIR   (run by .github/workflows/build-mac.yml, job sony-coverage)

Uses the same rawpy / LibRaw version as the app and PhotoSelect's own raw_io.decode_photo. For each
sample: Sony compression mode, whether the RAW pixels decode, the decoded size, whether a camera-
preview fallback would be available (and its size), and whether sub-second capture times are
recorded (used for burst grouping). Bodies without a public sample are listed as NOT TESTED.
Writes coverage.md and coverage.json; the exit code is 0 so the report always completes.
"""
import hashlib
import json
import os
import re
import struct
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import raw_io  # noqa: E402

BASE = 'https://raw.pixls.us/data-unique/'
PER_MODEL = 4
LIMIT = 160 * 2 ** 20
SERIES = {  # every A7 / A9 body, by its ILCE code
    'ILCE-7': 'A7', 'ILCE-7M2': 'A7 II', 'ILCE-7M3': 'A7 III', 'ILCE-7M4': 'A7 IV', 'ILCE-7M5': 'A7 V',
    'ILCE-7R': 'A7R', 'ILCE-7RM2': 'A7R II', 'ILCE-7RM3': 'A7R III', 'ILCE-7RM3A': 'A7R IIIA', 'ILCE-7RM4': 'A7R IV',
    'ILCE-7RM4A': 'A7R IVA', 'ILCE-7RM5': 'A7R V', 'ILCE-7S': 'A7S', 'ILCE-7SM2': 'A7S II', 'ILCE-7SM3': 'A7S III',
    'ILCE-7C': 'A7C', 'ILCE-7CM2': 'A7C II', 'ILCE-7CR': 'A7CR', 'ILCE-9': 'A9', 'ILCE-9M2': 'A9 II', 'ILCE-9M3': 'A9 III',
}
COMPRESSION = {1: 'uncompressed', 7: 'lossless compressed', 32767: 'compressed', 32769: 'compressed',
               32770: 'compressed', 32773: 'packbits'}


def series_code(folder):
    """ILCE code for a raw.pixls.us model folder ('ILCE-7M3', 'Sony ILCE-7M3', 'ILCE-7M3 (A7 III)', 'A7 III'…), or None."""
    text = folder.upper().replace('Α', 'A')
    m = re.search(r'ILCE[- ]?(7|9)([A-Z0-9]*)', text)
    if m:
        code = f'ILCE-{m.group(1)}{m.group(2)}'
        return code if code in SERIES else None
    name = re.sub(r'^(SONY\s+)?(ALPHA\s*)?', '', text).strip()
    for code, model in SERIES.items():
        if name.replace(' ', '') == model.upper().replace(' ', ''):
            return code
    return None


def listing(url):
    html = get(url).decode('utf-8', 'replace')
    return [urllib.parse.unquote(h) for h in re.findall(r'href="([^"?/][^"]*)"', html)]


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'PhotoSelect-sony-coverage'})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read(LIMIT + 1)


def raw_ifd(data):
    """(compression, width, height) of the largest image in a TIFF-based RAW (Sony ARW)."""
    order = '<' if data[:2] == b'II' else '>'
    best = (None, 0, 0)
    seen, queue = set(), [struct.unpack(order + 'I', data[4:8])[0]]
    while queue:
        off = queue.pop()
        if not off or off in seen or off + 2 > len(data):
            continue
        seen.add(off)
        n = struct.unpack(order + 'H', data[off:off + 2])[0]
        tags = {}
        for i in range(n):
            e = off + 2 + 12 * i
            tag, typ, count = struct.unpack(order + 'HHI', data[e:e + 8])
            size = {3: 2, 4: 4}.get(typ)
            if size is None:
                continue
            if count > 64:   # only small tags are needed (sizes, compression, SubIFD offsets)
                continue
            try:
                if count * size <= 4:
                    vals = struct.unpack(order + ('H' if typ == 3 else 'I') * count, data[e + 8:e + 8 + count * size])
                else:
                    p = struct.unpack(order + 'I', data[e + 8:e + 12])[0]
                    vals = struct.unpack(order + ('H' if typ == 3 else 'I') * count, data[p:p + count * size])
            except struct.error:
                continue
            tags[tag] = vals
        w, h = tags.get(0x0100, (0,))[0], tags.get(0x0101, (0,))[0]
        if w > best[1]:
            best = (tags.get(0x0103, (None,))[0], w, h)
        queue += list(tags.get(0x014A, ()))
        nxt = off + 2 + 12 * n
        if nxt + 4 <= len(data):
            queue.append(struct.unpack(order + 'I', data[nxt:nxt + 4])[0])
    return best


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    print('rawpy', __import__('rawpy').__version__, 'LibRaw', raw_io.libraw_version())
    listing = get(BASE + 'filelist.sha256').decode('utf-8', 'replace').splitlines()
    entries, folders = [], set()
    for line in listing:
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            path = parts[1].lstrip('*').lstrip('./')
            bits = path.split('/')
            if len(bits) >= 3 and 'sony' in bits[0].lower() and path.lower().endswith('.arw'):
                folders.add(bits[1])
                code = series_code(bits[1])
                if code:
                    entries.append((code, BASE + urllib.parse.quote(path), parts[0]))
    print(f'Sony model folders in data-unique: {sorted(folders)}')
    # data-unique keeps one file per camera and mode; the full archive (/data/) may have bodies it lacks
    for make in ('Sony/', 'SONY/'):
        root = 'https://raw.pixls.us/data/' + urllib.parse.quote(make)
        try:
            models = listing(root)
        except Exception as error:
            print(f'listing {root}: {error}')
            continue
        print(f'{make} folders: {models}')
        for folder in models:
            code = series_code(folder.rstrip('/'))
            if not code or any(e[0] == code for e in entries):
                continue
            try:
                files = [f for f in listing(root + urllib.parse.quote(folder.rstrip('/')) + '/') if f.lower().endswith('.arw')]
            except Exception as error:
                print(f'listing {folder}: {error}')
                continue
            entries += [(code, root + urllib.parse.quote(folder.rstrip('/')) + '/' + urllib.parse.quote(f), None)
                        for f in files[:PER_MODEL]]
    print(f'{len(entries)} A7/A9 samples on raw.pixls.us: {sorted({c for c, _, _ in entries})}')
    results = []
    for code in SERIES:
        for _, url, digest in [e for e in entries if e[0] == code][:PER_MODEL]:
            name = urllib.parse.unquote(url.split('/')[-1])
            item = {'code': code, 'model': SERIES[code], 'file': name}
            try:
                data = get(url)
            except Exception as error:
                item.update(result='download failed', error=str(error))
                results.append(item)
                continue
            if len(data) > LIMIT or (digest and hashlib.sha256(data).hexdigest() != digest):
                item.update(result='skipped (too large or checksum mismatch)')
                results.append(item)
                continue
            target = out / name
            target.write_bytes(data)
            comp, w, h = raw_ifd(data)
            item.update(mb=round(len(data) / 2 ** 20, 1), mode=COMPRESSION.get(comp, f'code {comp}'), raw_size=[w, h])
            t = time.time()
            try:
                image, source, _ = raw_io.decode_photo(target, allow_preview=False)
                item.update(result='RAW decoded', decoded_size=list(image.size), seconds=round(time.time() - t, 1))
            except Exception as error:
                item.update(result='RAW NOT decoded', error=str(error))
                try:
                    image, source, _ = raw_io.decode_photo(target)
                    item.update(fallback=f'{source} {image.size[0]}×{image.size[1]}')
                except Exception as e2:
                    item.update(fallback=f'none: {e2}')
            preview = raw_io.embedded_preview(target)
            item['embedded_preview'] = list(preview.size) if preview else None
            stamp = raw_io.capture_time(target)
            item['capture_time'] = stamp
            item['subseconds'] = bool(stamp and stamp % 1)
            results.append(item)
            print(json.dumps(item), flush=True)
            target.unlink()
    lines = ['# Sony A7 / A9 RAW coverage', '',
             f'Decoder: rawpy {__import__("rawpy").__version__}, LibRaw {raw_io.libraw_version()} (the versions bundled in PhotoSelect).', '',
             '| Body | Sample | Mode | RAW size | Result | Embedded JPEG | Sub-second times |', '|---|---|---|---|---|---|---|']
    for code, model in SERIES.items():
        mine = [r for r in results if r['code'] == code]
        if not mine:
            lines.append(f'| {model} ({code}) | — | — | — | NOT TESTED (no public sample) | — | — |')
        for r in mine:
            prev = r.get('embedded_preview')
            lines.append(f"| {model} ({code}) | {r['file']} | {r.get('mode', '?')} | "
                         f"{'×'.join(map(str, r.get('raw_size', []))) or '?'} | {r['result']}"
                         f"{(' — ' + r['error']) if r.get('error') and r['result'] != 'RAW decoded' else ''}"
                         f"{(' → fallback: ' + r['fallback']) if r.get('fallback') else ''} | "
                         f"{'×'.join(map(str, prev)) if prev else 'none'} | {'yes' if r.get('subseconds') else 'no'} |")
    tested = {r['code'] for r in results if r['result'].startswith('RAW')}
    failed = sorted({f"{r['model']} {r.get('mode', '')}" for r in results if r['result'] == 'RAW NOT decoded'})
    lines += ['', f'Bodies with samples: {len(tested)} of {len(SERIES)}. '
              f'RAW decode failures: {", ".join(failed) if failed else "none"}.']
    report = '\n'.join(lines) + '\n'
    (out / 'coverage.md').write_text(report)
    (out / 'coverage.json').write_text(json.dumps(results, indent=1))
    print(report)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as f:
            f.write(report)


if __name__ == '__main__':
    main()
