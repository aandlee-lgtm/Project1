"""Diagnostic report for testing on the user's own Mac (Help → Create Diagnostic Report…).

The report is plain text meant to be read by the user and shared on request. It contains no image
data and no absolute paths: files are identified by their name relative to the analysed folder,
and the folder by its last path component only.
"""
import json
import platform
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import analysis
import raw_io
import store as store_module

ORIENTATION_SAMPLE = 200   # embedded previews checked against the decode (fast, but not free)
FILE_ROWS = 400            # per-file lines included


def _sysctl(name):
    try:
        return subprocess.run(['/usr/sbin/sysctl', '-n', name], capture_output=True, text=True,
                              timeout=5).stdout.strip()
    except Exception:
        return ''


def system_info():
    info = {'python': sys.version.split()[0], 'platform': platform.platform(),
            'frozen_app': bool(getattr(sys, 'frozen', False))}
    if sys.platform == 'darwin':
        info.update(macos=platform.mac_ver()[0], model=_sysctl('hw.model'),
                    chip=_sysctl('machdep.cpu.brand_string'), cpus=_sysctl('hw.ncpu'),
                    memory_gb=round(int(_sysctl('hw.memsize') or 0) / 2 ** 30, 1),
                    arch=platform.machine())
    return info


def peak_memory_mb():
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(peak / (2 ** 20 if sys.platform == 'darwin' else 2 ** 10))
    except Exception:
        return None


def recent_log_problems(limit=25):
    path = store_module.log_dir() / 'photoselect.log'
    try:
        lines = path.read_text(errors='replace').splitlines()
    except OSError:
        return []
    home = str(Path.home())
    return [l.replace(home, '~')[:300] for l in lines if re.search(r' (ERROR|WARNING|CRITICAL) ', l)][-limit:]


def _orientation_checks(rows):
    """Compare the orientation of the camera's embedded preview with LibRaw's decode."""
    checked, mismatches = 0, []
    for r in rows:
        if checked >= ORIENTATION_SAMPLE:
            break
        if not (r['is_raw'] and r['status'] == 'analysed' and r.get('size')):
            continue
        im = raw_io.embedded_preview(r['path'])
        if im is None:
            continue
        checked += 1
        w, h = r['size']
        if (im.width > im.height) != (w > h) and abs(im.width - im.height) > 10 and abs(w - h) > 10:
            mismatches.append(f"{r['name']}: embedded preview {im.width}×{im.height}, decoded {w}×{h}")
    return checked, mismatches


def build(library, prefs, app_version):
    with library.lock:
        library._recompute()
        rows = [dict(r) for r in library.rows]
        errors = list(library.errors)
        status = dict(library.status)
    analysed = [r for r in rows if r['status'] == 'analysed']
    weights = prefs['weights']
    total_w = sum(weights.values()) or 1

    def score(r):
        return sum(weights[k] * r['scores'].get(k, 0) for k in weights) / total_w

    out = []
    w = out.append
    w(f'# PhotoSelect diagnostic report\n')
    w(f'Created {datetime.now().strftime("%Y-%m-%d %H:%M")} · PhotoSelect {app_version} · '
      f'LibRaw {raw_io.libraw_version()} · analysis v{analysis.ANALYSIS_VERSION}')
    w('Contains no image data and no full paths. Review before sharing.\n')

    w('## This Mac')
    for k, v in system_info().items():
        w(f'- {k}: {v}')
    w(f'- analysis workers: {library.workers}')
    w(f'- peak app memory so far: {peak_memory_mb()} MB')
    w(f'- cache size: {library.cache_size() / 2 ** 20:.0f} MB\n')

    w('## Last scan')
    folder = Path(status.get('folder') or '')
    started, finished = status.get('started'), status.get('finished')
    w(f"- folder: …/{folder.name}  (subfolders: {'yes' if status.get('recursive') else 'no'}; "
      f"location: {'external volume' if str(folder).startswith('/Volumes/') else 'this Mac'})")
    w(f"- state: {status.get('phase')}; files found: {status.get('total')}; analysed: {len(analysed)}; "
      f"reused from cache: {status.get('cached')}; could not be analysed: {len(errors)}")
    if started and status.get('previews_done'):
        w(f"- time until all embedded previews shown: {status['previews_done'] - started:.1f} s")
    if started and status.get('first_result'):
        w(f"- time until the first photo was fully analysed: {status['first_result'] - started:.1f} s")
    if started and finished:
        w(f'- total scan time: {finished - started:.1f} s')
    fresh = [r for r in analysed if r.get('source') == 'decoded' and r.get('timing')]
    if fresh:
        dec = sorted(r['timing']['decode'] for r in fresh)
        ana = sorted(r['timing']['analyse'] for r in fresh)
        w(f'- per file (newly decoded, n={len(fresh)}): decode median {dec[len(dec) // 2]:.2f} s '
          f'(max {dec[-1]:.2f}), analysis median {ana[len(ana) // 2]:.2f} s')
        if started and finished:
            w(f'- throughput: {len(fresh) / max(finished - started, .1):.2f} files/s')
        if status.get('cpu_seconds') is not None:
            w(f"- CPU time: {status['cpu_seconds']:.0f} s in total, {status['cpu_seconds'] / len(fresh):.2f} s per newly analysed file "
              f"({library.workers} analysis workers at background priority)")
    w('')

    w('## Formats and cameras')
    by = Counter((r['format'], r.get('camera') or '(no camera EXIF)') for r in analysed)
    for (fmt, cam), n in sorted(by.items()):
        sizes = {tuple(r['size']) for r in analysed if r['format'] == fmt and (r.get('camera') or '(no camera EXIF)') == cam and r.get('size')}
        w(f'- {fmt} · {cam}: {n} file(s), decoded size {", ".join(f"{a}×{b}" for a, b in sorted(sizes)[:3])}')
    basis = Counter(r.get('basis') or '?' for r in analysed)
    w(f"- analysed from: {dict(basis)}  (camera_preview = embedded camera JPEG, RAW pixels not decodable)")
    exts = Counter(Path(r['name']).suffix for r in rows)
    w(f'- extensions seen: {dict(exts)}')
    no_time = [r for r in analysed if r['timestamp'] is None]
    subsec = [r for r in analysed if r['timestamp'] is not None and r['timestamp'] % 1]
    w(f'- capture time missing: {len(no_time)}; with sub-second precision: {len(subsec)} of {len(analysed)}\n')

    w('## Files that could not be analysed')
    if not errors:
        w('- none')
    reasons = defaultdict(list)
    for e in errors:
        reasons[e['error']].append(e['name'])
    for reason, names in reasons.items():
        w(f'- {len(names)} × {reason}')
        w(f'    e.g. {", ".join(names[:8])}')
    w('')

    w('## Orientation cross-check (embedded camera preview vs RAW decode)')
    checked, mismatches = _orientation_checks(analysed)
    w(f'- RAW files checked: {checked}; orientation disagreements: {len(mismatches)}')
    for m in mismatches[:20]:
        w(f'    {m}')
    w('')

    w('## Settings')
    w(f"- weights: {json.dumps(weights)}; keep ≥ {prefs['keep']}; consider ≥ {prefs['consider']}; "
      f"burst gap {prefs['gap']} s; similarity ≥ {prefs['likeness']} %; near-identical ≥ {prefs['near_identical']} % "
      f"within {prefs['near_window']} s; best of each series: {prefs.get('best_of', 1) or 'all'}")
    marks = library.store.marks([r['path'] for r in rows])
    decided = [m for m in marks.values() if m.get('decision')]
    w(f"- manual decisions: {len(decided)} ({dict(Counter(m['decision'] for m in decided))}); "
      f"liked: {sum(1 for m in marks.values() if m.get('liked'))}; focus regions: {sum(1 for m in marks.values() if m.get('roi'))}\n")

    w('## Bursts (groups with more than one frame)')
    groups = defaultdict(list)
    for r in analysed:
        groups[r['group']].append(r)
    bursts = sorted((g for g in groups.values() if len(g) > 1), key=lambda g: min(x['name'] for x in g))
    singles = sum(1 for g in groups.values() if len(g) == 1)
    w(f'- bursts: {len(bursts)}; single frames: {singles}; burst sizes: {dict(sorted(Counter(len(g) for g in bursts).items()))}')
    w(f"- bursts containing near-identical frames: {sum(1 for g in bursts if any(x.get('near_identical') for x in g))}")
    w('- columns: burst · frames · time span · average likeness to top frame · near-identical frames · '
      'top frame (score) · runner-up (gap) · first … last file')
    for g in bursts[:80]:
        g.sort(key=score, reverse=True)
        times = [x['timestamp'] for x in g if x['timestamp'] is not None]
        span = f'{max(times) - min(times):.2f}s' if times else '?'
        names = sorted(x['name'] for x in g)
        alike = average_likeness(g)
        w(f"  {g[0]['group']} · {len(g)} · {span} · {'-' if alike is None else f'{alike:.0f} %'} · "
          f"{sum(1 for x in g if x.get('near_identical'))} · {g[0]['name']} ({score(g[0]):.1f}) · "
          f"{g[1]['name']} (−{score(g[0]) - score(g[1]):.1f}) · {names[0]} … {names[-1]}")
    if len(bursts) > 80:
        w(f'  … {len(bursts) - 80} more')
    w('')

    w(f'## Files (first {FILE_ROWS}, by name)')
    w('- columns: name · format · status · size · capture time · burst · score · sharp/focus/comp/expo · noise flag · decode s')
    for r in sorted(rows, key=lambda x: x['name'])[:FILE_ROWS]:
        if r['status'] == 'error':
            continue
        ts = datetime.fromtimestamp(r['timestamp']).strftime('%H:%M:%S.%f')[:-4] if r['timestamp'] else '-'
        sc = r['scores']
        w(f"  {r['name']} · {r['format']} · {r['status']}/{r.get('source')} · "
          f"{'×'.join(map(str, r['size'])) if r.get('size') else '-'} · {ts} · {r['group']} · "
          f"{score(r):.1f} · {sc.get('sharpness', '-')}/{sc.get('focus', '-')}/{sc.get('composition', '-')}/{sc.get('exposure', '-')} · "
          f"{'noise' if r.get('noise_flag') else '-'} · {(r.get('timing') or {}).get('decode', '-')}")
    w('')

    w('## Recent warnings and errors in the log')
    problems = recent_log_problems()
    w('\n'.join(f'  {p}' for p in problems) if problems else '- none')
    return '\n'.join(out) + '\n'


def average_likeness(burst):
    """Mean % likeness of a burst's other frames to its first (top-ranked) frame, or None if unknown."""
    top = burst[0]
    values = [x['likeness'][top['id']] for x in burst[1:] if top['id'] in (x.get('likeness') or {})]
    return sum(values) / len(values) if values else None


def filename():
    return f'PhotoSelect-diagnostics-{time.strftime("%Y%m%d-%H%M")}.txt'
