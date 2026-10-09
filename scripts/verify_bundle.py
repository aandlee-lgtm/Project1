"""Inspect every Mach-O binary in PhotoSelect.app (macOS only).

* --thin: strip non-arm64 slices from universal binaries (signature must be redone afterwards).
* Reports architectures, the highest minimum-macOS requirement, and any library linked from
  outside the bundle or the OS (e.g. a developer's Python or Homebrew), which would break on a
  clean Mac.
Writes a JSON report and exits non-zero on any problem.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

MAGIC = {b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca', b'\xce\xfa\xed\xfe'}


def run(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def machos(app):
    for p in sorted(app.rglob('*')):
        if p.is_file() and not p.is_symlink():
            with p.open('rb') as f:
                if f.read(4) in MAGIC:
                    yield p


def version_key(v):
    return tuple(int(x) for x in v.split('.'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('app')
    ap.add_argument('--thin', action='store_true')
    ap.add_argument('--report', default='bundle-report.json')
    a = ap.parse_args()
    app = Path(a.app)
    report = {'files': [], 'problems': [], 'min_macos': '0.0', 'min_macos_file': None}
    for p in machos(app):
        rel = str(p.relative_to(app))
        archs = run('lipo', '-archs', str(p)).split()
        if 'arm64' not in archs:
            report['problems'].append(f'{rel}: no arm64 slice ({archs})')
            continue
        if a.thin and archs != ['arm64']:
            subprocess.run(['lipo', str(p), '-thin', 'arm64', '-output', str(p) + '.thin'], check=True)
            Path(str(p) + '.thin').replace(p)
            archs = run('lipo', '-archs', str(p)).split()
        loads = run('otool', '-arch', 'arm64', '-l', str(p))
        mins = re.findall(r'cmd LC_BUILD_VERSION.*?minos (\S+)', loads, re.S) + \
            re.findall(r'cmd LC_VERSION_MIN_MACOSX.*?version (\S+)', loads, re.S)
        minos = max(mins, key=version_key) if mins else None
        if minos and version_key(minos) > version_key(report['min_macos']):
            report['min_macos'], report['min_macos_file'] = minos, rel
        libs = [l.strip().split(' (')[0] for l in run('otool', '-arch', 'arm64', '-L', str(p)).splitlines()[1:]]
        external = [l for l in libs if l.startswith('/') and not l.startswith(('/System/', '/usr/lib/'))]
        for l in external:
            report['problems'].append(f'{rel}: links outside bundle/OS: {l}')
        report['files'].append({'file': rel, 'archs': archs, 'minos': minos})
    non_arm = [f['file'] for f in report['files'] if f['archs'] != ['arm64']]
    report['summary'] = {'macho_files': len(report['files']), 'arm64_only': len(report['files']) - len(non_arm),
                         'with_extra_slices': non_arm}
    Path(a.report).write_text(json.dumps(report, indent=1))
    print(json.dumps({k: v for k, v in report.items() if k != 'files'}, indent=1))
    sys.exit(1 if report['problems'] else 0)


if __name__ == '__main__':
    main()
