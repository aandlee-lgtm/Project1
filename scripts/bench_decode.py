"""Compare PhotoSelect's analysis decode: 1.4.0 (full-size, LibRaw's default high-quality demosaic)
against 1.5.0 (decode only as large as the scores need: half-size for 33 MP+, else fast demosaic).

Usage: python scripts/bench_decode.py OUTDIR [--count 12]   (run by .github/workflows/perf-check.yml)

For genuine camera RAW samples from raw.pixls.us it reports, per file and mode: decode and analysis
time, peak memory (each run in a fresh process), and the scores. Then, for the whole set, the rank
correlation of every score between the two modes and the mean difference of the folder-relative
0-100 scores, i.e. whether the faster decode would change rankings. Writes bench.md / bench.json.
"""
import argparse
import hashlib
import json
import os
import random
import resource
import statistics
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = 'https://raw.pixls.us/data-unique/'
KEYS = ('sharpness', 'focus', 'composition', 'exposure', 'noise')


def one(path, mode):
    """Run in a child process: decode + analyse one file in one mode, print JSON."""
    import time
    sys.path.insert(0, str(ROOT))
    import analysis
    import raw_io
    t0 = time.perf_counter()
    min_edge = {'reference': None, 'fast': analysis.FOCUS_SCALE, 'half': 1}[mode]   # 'half': half-size for every file
    full, basis, _ = raw_io.decode_photo(path, min_edge=min_edge)
    t1 = time.perf_counter()
    _, m = analysis.analyse(full)
    t2 = time.perf_counter()
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_mb = peak / 2 ** 20 if sys.platform == 'darwin' else peak / 1024
    print(json.dumps({'decode': t1 - t0, 'analyse': t2 - t1, 'peak_mb': peak_mb, 'size': list(full.size),
                      'basis': basis, **{k: m[k] for k in KEYS}}))


HIGH_RES = ('Z 8', 'Z 9', 'Z 7', 'D850', 'ILCE-7RM4', 'ILCE-7RM5', 'ILCE-7CR', 'ILCE-1', 'Z8', 'Z9', 'Z7', 'Z 7_2', 'Z 7II')


def get(url, limit=None):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'PhotoSelect-bench'}), timeout=300) as r:
        return r.read(limit + 1) if limit else r.read()


def dir_listing(url):
    import re
    html = get(url).decode('utf-8', 'replace')
    return [urllib.parse.unquote(h) for h in re.findall(r'href="([^"?/][^"]*)"', html)]


def high_res_samples(per_model=1):
    """(url, None) for RAW samples of 33 MP+ bodies from the full raw.pixls.us archive (/data/)."""
    out = []
    for make in ('Nikon/', 'NIKON CORPORATION/', 'Sony/', 'SONY/'):
        root = 'https://raw.pixls.us/data/' + urllib.parse.quote(make)
        try:
            models = dir_listing(root)
        except Exception as error:
            print('listing', root, error)
            continue
        for folder in models:
            name = folder.rstrip('/').upper().replace(' ', '')
            if not any(name.endswith(m.upper().replace(' ', '')) for m in HIGH_RES):
                continue
            try:
                files = [f for f in dir_listing(root + urllib.parse.quote(folder.rstrip('/')) + '/')
                         if f.lower().endswith(('.nef', '.arw'))]
            except Exception:
                continue
            out += [(root + urllib.parse.quote(folder.rstrip('/')) + '/' + urllib.parse.quote(f), folder.rstrip('/'))
                    for f in files[:per_model]]
    return out


def spearman(a, b):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0] * len(v)
        for rank, i in enumerate(order):
            r[i] = rank
        return r
    ra, rb = ranks(a), ranks(b)
    n = len(a)
    return 1 - 6 * sum((x - y) ** 2 for x, y in zip(ra, rb)) / (n * (n * n - 1)) if n > 2 else None


def main():
    if len(sys.argv) > 2 and sys.argv[1] == '--one':
        return one(sys.argv[2], sys.argv[3])
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--count', type=int, default=12)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    listing = urllib.request.urlopen(urllib.request.Request(BASE + 'filelist.sha256', headers={'User-Agent': 'PhotoSelect-bench'}),
                                     timeout=120).read().decode('utf-8', 'replace').splitlines()
    entries = []
    for line in listing:
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            p = parts[1].lstrip('*').lstrip('./')
            if p.lower().endswith(('.nef', '.arw', '.orf')) and p.count('/') >= 2:
                entries.append((p, parts[0]))
    random.Random(5).shuffle(entries)
    # prefer recent high-resolution bodies so both decode paths (half-size and fast demosaic) are measured
    prefer = ('Z 8', 'Z 9', 'Z 7', 'Z 6_3', 'Z 6', 'D850', 'ILCE-7RM', 'ILCE-7M4', 'ILCE-1', 'ILCE-9', 'OM-1', 'E-M1')
    entries.sort(key=lambda e: next((i for i, m in enumerate(prefer) if m.upper().replace(' ', '') in e[0].upper().replace(' ', '')), 99))
    results, models = [], set()
    todo = [(BASE + urllib.parse.quote(p), p.split('/')[1], d) for p, d in entries]
    todo = [(u, m, None) for u, m in high_res_samples()] + todo
    high = 0
    for url, model, digest in todo:
        if len(results) >= a.count + high:
            break
        if model in models:
            continue
        try:
            data = get(url, 150 * 2 ** 20)
        except Exception as error:
            print('download failed', url, error)
            continue
        if len(data) > 150 * 2 ** 20 or (digest and hashlib.sha256(data).hexdigest() != digest):
            continue
        if digest is None:
            high += 1
        target = out / urllib.parse.unquote(url.split('/')[-1])
        target.write_bytes(data)
        row = {'model': model, 'file': target.name, 'mb': round(len(data) / 2 ** 20, 1)}
        ok = True
        for mode in ('reference', 'fast', 'half'):
            r = subprocess.run([sys.executable, __file__, '--one', str(target), mode], capture_output=True, text=True)
            if r.returncode != 0:
                print('failed', target.name, mode, r.stderr[-400:])
                ok = False
                break
            row[mode] = json.loads(r.stdout.strip().splitlines()[-1])
        target.unlink()
        if ok and row['reference']['basis'] == 'decoded_raw':
            models.add(model)
            results.append(row)
            print(json.dumps(row), flush=True)
    # folder-relative 0-100 scores, as PhotoSelect computes them, for each mode
    sys.path.insert(0, str(ROOT))
    import analysis
    scored = {}
    for mode in ('reference', 'fast', 'half'):
        rows = [{'raw': {k: r[mode][k] for k in KEYS}, 'scores': {}} for r in results]
        analysis.normalise(rows)
        scored[mode] = rows
    lines = ['# Analysis decode: 1.4.0 (reference) vs 1.5.0 (fast)', '',
             '| Camera | MP | Fast decode | Decode s (ref → fast → half) | Analyse s | Peak MB (ref → fast → half) | Focus (ref / fast / half) |',
             '|---|---|---|---|---|---|---|']
    for r in results:
        ref, fast = r['reference'], r['fast']
        mp = ref['size'][0] * ref['size'][1] / 1e6
        how = 'half-size' if fast['size'][0] < ref['size'][0] * .75 else 'fast demosaic'
        half = r['half']
        lines.append(f"| {r['model']} | {mp:.0f} | {how} | {ref['decode']:.2f} → {fast['decode']:.2f} → {half['decode']:.2f} | "
                     f"{ref['analyse']:.2f} → {fast['analyse']:.2f} → {half['analyse']:.2f} | "
                     f"{ref['peak_mb']:.0f} → {fast['peak_mb']:.0f} → {half['peak_mb']:.0f} | "
                     f"{ref['focus']:.4g} / {fast['focus']:.4g} / {half['focus']:.4g} |")
    summary = {}
    if results:
        t_ref = sum(r['reference']['decode'] + r['reference']['analyse'] for r in results)
        t_fast = sum(r['fast']['decode'] + r['fast']['analyse'] for r in results)
        t_half = sum(r['half']['decode'] + r['half']['analyse'] for r in results)
        summary = {'files': len(results), 'speedup': round(t_ref / t_fast, 2), 'speedup_half_everything': round(t_ref / t_half, 2),
                   'peak_mb_half': round(max(r['half']['peak_mb'] for r in results)),
                   'rank_correlation_half': {k: round(spearman([r['reference'][k] for r in results], [r['half'][k] for r in results]) or 0, 3)
                                             for k in KEYS},
                   'mean_score_difference_half': {k: round(statistics.mean(abs(x['scores'][k] - y['scores'][k])
                                                                           for x, y in zip(scored['reference'], scored['half'])), 1)
                                                  for k in ('sharpness', 'focus', 'composition', 'exposure')},
                   'peak_mb_reference': round(max(r['reference']['peak_mb'] for r in results)),
                   'peak_mb_fast': round(max(r['fast']['peak_mb'] for r in results)),
                   'rank_correlation': {k: round(spearman([r['reference'][k] for r in results], [r['fast'][k] for r in results]) or 0, 3)
                                        for k in KEYS},
                   'mean_score_difference': {k: round(statistics.mean(abs(x['scores'][k] - y['scores'][k])
                                                                      for x, y in zip(scored['reference'], scored['fast'])), 1)
                                             for k in ('sharpness', 'focus', 'composition', 'exposure')}}
        lines += ['', f"Files: {summary['files']}. Total decode + analysis time: {t_ref:.1f} s → {t_fast:.1f} s "
                      f"(**{summary['speedup']}× faster**). Largest peak memory per file: {summary['peak_mb_reference']} MB → "
                      f"{summary['peak_mb_fast']} MB.",
                  f"Rank correlation between modes (1 = same order): {summary['rank_correlation']}.",
                  f"Mean difference of the folder-relative 0-100 scores: {summary['mean_score_difference']}.",
                  '', f"Alternative, half-size for every file: {t_half:.1f} s ({summary['speedup_half_everything']}× faster), peak "
                      f"{summary['peak_mb_half']} MB, rank correlation {summary['rank_correlation_half']}, mean score difference "
                      f"{summary['mean_score_difference_half']}."]
    report = '\n'.join(lines) + '\n'
    (out / 'bench.md').write_text(report)
    (out / 'bench.json').write_text(json.dumps({'summary': summary, 'results': results}, indent=1))
    print(report)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write(report)


if __name__ == '__main__':
    main()
