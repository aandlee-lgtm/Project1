"""Download genuine camera RAW samples for acceptance testing (never bundled in the app).

Source: raw.pixls.us, a public archive of camera RAW files (mostly CC0), used by darktable,
RawSpeed and LibRaw developers. Picks several Nikon NEF, one Nikon NRW and several Olympus /
OM System ORF files, verifies SHA-256, and writes manifest.json. Files supplied by the user can be
placed in the output folder too; they are included in the manifest as 'user'.
"""
import argparse
import hashlib
import json
import random
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE = 'https://raw.pixls.us/data-unique/'
FALLBACK_NEF = ('https://github.com/letmaik/rawpy/raw/main/test/iss030e122639.NEF',
                'NASA ISS Nikon D3S (rawpy test file, public domain)')
PREFER = {
    'nef': ['Z 8', 'Z 9', 'Z 6_2', 'Z 6III', 'Z 6', 'Z 7', 'Z 5', 'Z 50', 'Z f', 'D850', 'D500', 'D7500', 'D750'],
    'orf': ['OM-1', 'OM-1 Mark II', 'OM-5', 'E-M1 Mark III', 'E-M1X', 'E-M1 Mark II', 'E-M5 Mark III', 'E-M10 Mark IV',
            'E-M1MarkIII', 'E-M1MarkII', 'E-M5MarkIII', 'E-M1'],
    'nrw': ['P1000', 'P7800', 'P7700', 'P950', 'B700'],
}
LIMIT = 70 * 2 ** 20


def get(url, timeout=120):
    req = urllib.request.Request(url, headers={'User-Agent': 'PhotoSelect-acceptance-tests'})
    return urllib.request.urlopen(req, timeout=timeout)


def download(url, limit=LIMIT):
    """GET with a size cap; returns bytes or None if larger than the cap or unavailable."""
    try:
        with get(url) as r:
            data = r.read(limit + 1)
        return data if len(data) <= limit else None
    except Exception as error:
        print(f'  download failed: {url}: {error}')
        return None


def candidates(entries, ext, makes):
    """Files of one extension from the given makes, preferred (recent) models first, one per model."""
    cands = [e for e in entries if e['path'].lower().endswith('.' + ext) and e['path'].count('/') >= 2 and
             any(m in e['path'].split('/')[0].lower() for m in makes)]
    random.Random(7).shuffle(cands)
    order = []
    for model in PREFER[ext]:
        order += [e for e in cands if e['path'].split('/')[1].upper().replace(' ', '') .endswith(model.upper().replace(' ', ''))]
    order += cands
    seen, out = set(), []
    for e in order:
        model = e['path'].split('/')[1]
        if model not in seen:
            seen.add(model)
            out.append(e)
    print(f'{ext}: {len(cands)} files from {len(out)} models; first choices: {[e["path"] for e in out[:6]]}')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--nef', type=int, default=3)
    ap.add_argument('--orf', type=int, default=3)
    ap.add_argument('--nrw', type=int, default=1)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    try:
        listing = get(BASE + 'filelist.sha256').read().decode('utf-8', 'replace').splitlines()
        entries = []
        for line in listing:
            parts = line.strip().split(None, 1)
            if len(parts) == 2:
                entries.append({'sha256': parts[0], 'path': parts[1].lstrip('*').lstrip('./')})
        print(f'raw.pixls.us listing: {len(entries)} files; first: {listing[:2]}')
        for ext, makes, count in (('nef', ['nikon'], a.nef), ('nrw', ['nikon'], a.nrw),
                                  ('orf', ['olympus', 'om digital', 'om system'], a.orf)):
            got = 0
            for e in candidates(entries, ext, makes):
                if got >= count:
                    break
                make, model, name = e['path'].split('/')[:3]
                data = download(BASE + urllib.parse.quote(e['path']))
                if data is None:
                    continue
                digest = hashlib.sha256(data).hexdigest()
                if digest != e['sha256']:
                    print(f'checksum mismatch for {e["path"]}; skipped')
                    continue
                target = out / f"{model.replace(' ', '_')}__{name}"
                target.write_bytes(data)
                manifest.append({'file': target.name, 'make': make, 'model': model,
                                 'source': 'raw.pixls.us (CC0 sample archive)', 'sha256': digest, 'bytes': len(data)})
                print(f'  {make} / {model}: {name} ({len(data) / 2**20:.1f} MB)')
                got += 1
    except Exception as error:
        print(f'raw.pixls.us unavailable: {error}')
    if not any(m['file'].lower().endswith('.nef') for m in manifest):
        try:
            data = get(FALLBACK_NEF[0]).read()
            (out / 'D3S__iss030e122639.NEF').write_bytes(data)
            manifest.append({'file': 'D3S__iss030e122639.NEF', 'make': 'Nikon', 'model': 'D3S',
                             'source': FALLBACK_NEF[1], 'bytes': len(data)})
        except Exception as error:
            print(f'fallback NEF unavailable: {error}')
    known = {m['file'] for m in manifest}
    for p in sorted(out.iterdir()):
        if p.suffix.lower() in ('.nef', '.nrw', '.orf') and p.name not in known:
            manifest.append({'file': p.name, 'make': '?', 'model': '?', 'source': 'user', 'bytes': p.stat().st_size})
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=1))
    print(json.dumps(manifest, indent=1))
    kinds = {Path(m['file']).suffix.lower() for m in manifest}
    missing = {'.nef', '.orf', '.nrw'} - kinds
    if missing:
        print(f'WARNING: no genuine samples for {sorted(missing)}; those formats will be reported as NOT TESTED.')
    sys.exit(0 if kinds else 2)


if __name__ == '__main__':
    main()
