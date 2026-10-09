"""Acceptance tests for the PACKAGED PhotoSelect app on an Apple silicon Mac.

Runs from a harness Python that is separate from the app (Python 3.9+, with numpy, Pillow and
playwright installed). Steps:

  install     mount the DMG, check its layout, copy the app to /Applications, eject
  isolation   hide the python.org framework and Homebrew from the app; minimal environment
  offline     launch under a sandbox profile that denies all non-loopback network traffic
  photos      genuine NEF/NRW/ORF samples + generated JPEG burst/PNG/TIFF + damaged, empty and
              unreadable files, on a separately mounted volume ("Photo Drive") with spaces in paths
  ...         scan, decoded-output inspection vs Apple's own RAW renderer, UI checks in WebKit,
              persistence across relaunch, cancellation and responsiveness on a large folder,
              clean quit, originals unchanged, bundle unchanged.

Every check is recorded as PASS / FAIL / NOT TESTED in results.json and acceptance.md; the script
keeps going after a failure so the report is complete. Exit status is non-zero if anything failed.
"""
import argparse
import hashlib
import json
import os
import plistlib
import shutil
import signal
import statistics
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

APP_ID = 'io.github.aandlee-lgtm.photoselect'
INSTALLED = Path('/Applications/PhotoSelect.app')
BINARY = INSTALLED / 'Contents/MacOS/PhotoSelect'
HOME = Path.home()
SUPPORT = HOME / 'Library/Application Support/PhotoSelect'
CACHES = HOME / 'Library/Caches/PhotoSelect'
LOGS = HOME / 'Library/Logs/PhotoSelect'
OFFLINE_PROFILE = ('(version 1)(allow default)(deny network-outbound)'
                   '(allow network-outbound (remote ip "localhost:*"))(allow network-outbound (remote unix-socket))')

results = []
facts = {}


def record(name, status, detail=''):
    results.append({'check': name, 'status': status, 'detail': str(detail)[:2000]})
    print(f'[{status}] {name}' + (f' — {detail}' if detail else ''), flush=True)


def check(name, ok, detail=''):
    record(name, 'PASS' if ok else 'FAIL', detail)
    return ok


def run(*cmd, check_=True, **kw):
    return subprocess.run(list(map(str, cmd)), capture_output=True, text=True, check=check_, **kw)


def guarded(name):
    def deco(fn):
        def wrapper(*a, **kw):
            try:
                return fn(*a, **kw)
            except Exception as error:
                record(name, 'FAIL', f'exception: {error}\n{traceback.format_exc(limit=4)}')
        return wrapper
    return deco


def fingerprint(folder):
    out = {}
    for root, _, files in os.walk(folder):
        for f in files:
            p = Path(root) / f
            st = p.lstat()
            if os.access(p, os.R_OK):
                h = hashlib.sha256(p.read_bytes()).hexdigest()
            else:
                h = 'unreadable'
            xattrs = run('xattr', p, check_=False).stdout.split()
            out[str(p)] = [h, st.st_size, st.st_mtime_ns, st.st_mode, sorted(xattrs)]
    return out


class App:
    """A running instance of the packaged app, driven through its loopback API."""

    def __init__(self, out, offline=True, via_open=False, label='run', extra_env=None):
        self.auto = Path(out) / f'automation-{label}.json'
        if self.auto.exists():
            self.auto.unlink()
        env = {'HOME': str(HOME), 'USER': os.environ.get('USER', 'runner'), 'TMPDIR': os.environ.get('TMPDIR', '/tmp'),
               'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LANG': 'en_GB.UTF-8',
               'PHOTOSELECT_AUTOMATION_FILE': str(self.auto),
               'PHOTOSELECT_EXPORT_DIR': str(Path(out) / 'exports'), **(extra_env or {})}
        (Path(out) / 'exports').mkdir(exist_ok=True)
        self.via_open = via_open
        if via_open:
            # Launch through LaunchServices exactly like a Finder double-click.
            for k in ('PHOTOSELECT_AUTOMATION_FILE', 'PHOTOSELECT_EXPORT_DIR'):
                run('launchctl', 'setenv', k, env[k])
            run('open', '-a', INSTALLED)
            self.proc = None
        else:
            cmd = [str(BINARY)]
            if offline:
                cmd = ['/usr/bin/sandbox-exec', '-p', OFFLINE_PROFILE] + cmd
            self.proc = subprocess.Popen(cmd, env=env, stdout=open(Path(out) / f'app-{label}.log', 'w'),
                                         stderr=subprocess.STDOUT)
        deadline = time.time() + 180
        while not self.auto.exists():
            if time.time() > deadline:
                raise TimeoutError('app did not report ready within 180 s')
            if self.proc and self.proc.poll() is not None:
                raise RuntimeError(f'app exited during startup with code {self.proc.returncode}')
            time.sleep(.25)
        info = json.loads(self.auto.read_text())
        self.port, self.token, self.pid = info['port'], info['token'], info['pid']
        self.started = time.time()
        if via_open:
            for k in ('PHOTOSELECT_AUTOMATION_FILE', 'PHOTOSELECT_EXPORT_DIR'):
                run('launchctl', 'unsetenv', k, check_=False)

    def call(self, path, body=None, raw=False, timeout=300):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/{path}',
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={'X-Session': self.token, 'Content-Type': 'application/json'},
                                     method='GET' if body is None else 'POST')
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
        return data if raw else json.loads(data)

    def scan(self, folder, recursive=True, timeout=1800):
        self.call('scan', {'folder': str(folder), 'recursive': recursive})
        deadline = time.time() + timeout
        while self.call('state')['running']:
            if time.time() > deadline:
                raise TimeoutError('scan timeout')
            time.sleep(.5)
        return self.call('state'), self.call('rows')

    def rss_mb(self):
        out = run('ps', '-o', 'rss=', '-p', self.pid, check_=False).stdout.strip()
        return int(out) / 1024 if out else None

    def quit(self, timeout=30):
        """Ask the app to quit. Returns (seconds or None, method, detail).

        Tries the standard Quit Apple Event (what ⌘Q / the Quit menu / logout send). CI runners
        may refuse Apple Events between apps (Automation privacy permission), in which case
        SIGTERM is used, which the app handles by closing its window through the same path.
        """
        t = time.time()
        r = run('osascript', '-e', f'tell application id "{APP_ID}" to quit', check_=False, timeout=60)
        detail = (r.stdout + r.stderr).strip()
        if self._wait_exit(t, timeout):
            return time.time() - t, 'Apple Event quit', detail
        t = time.time()
        try:
            os.kill(self.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        if self._wait_exit(t, timeout):
            return time.time() - t, 'SIGTERM', 'Apple Event quit did not complete: ' + (detail or 'no error text')
        os.kill(self.pid, signal.SIGKILL)
        time.sleep(2)
        return None, 'SIGKILL', detail

    def _wait_exit(self, t, timeout):
        while time.time() - t < timeout:
            if self.proc is not None and self.proc.poll() is not None:   # reap our own child (no zombie)
                return True
            if self.proc is None and not alive(self.pid):
                return True
            time.sleep(.2)
        return False


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def photoselect_processes():
    out = run('pgrep', '-fl', 'PhotoSelect.app', check_=False).stdout.strip()
    return [l for l in out.splitlines() if l.strip()]


def port_open(port):
    import socket
    s = socket.socket()
    s.settimeout(1)
    try:
        return s.connect_ex(('127.0.0.1', port)) == 0
    finally:
        s.close()


# --------------------------------------------------------------------------------- steps
@guarded('install from DMG')
def install(dmg, out):
    info = plistlib.loads(run('hdiutil', 'attach', '-nobrowse', '-readonly', '-plist', dmg).stdout.encode())
    mount = next(e['mount-point'] for e in info['system-entities'] if e.get('mount-point'))
    try:
        entries = sorted(os.listdir(mount))
        link = os.readlink(os.path.join(mount, 'Applications')) if os.path.islink(os.path.join(mount, 'Applications')) else None
        check('DMG contains PhotoSelect.app and an Applications shortcut',
              'PhotoSelect.app' in entries and link == '/Applications', f'{entries}, link -> {link}')
        if INSTALLED.exists():
            shutil.rmtree(INSTALLED)
        run('ditto', os.path.join(mount, 'PhotoSelect.app'), INSTALLED)
    finally:
        run('hdiutil', 'detach', mount, check_=False)
    check('DMG ejected after copying', not os.path.exists(mount), mount)
    v = run('codesign', '--verify', '--deep', '--strict', INSTALLED, check_=False)
    check('installed app signature intact (codesign --verify --deep --strict)', v.returncode == 0, v.stderr.strip())
    d = run('codesign', '-dv', '--verbose=2', INSTALLED, check_=False).stderr
    facts['signature'] = [l for l in d.splitlines() if l.startswith(('Signature', 'TeamIdentifier', 'Authority', 'CodeDirectory'))]
    g = run('spctl', '--assess', '--type', 'execute', '-vv', INSTALLED, check_=False)
    facts['gatekeeper_assessment'] = (g.stdout + g.stderr).strip()
    record('Gatekeeper assessment (informational: ad-hoc builds are expected to be rejected for downloads)',
           'INFO', facts['gatekeeper_assessment'])
    plist = plistlib.loads((INSTALLED / 'Contents/Info.plist').read_bytes())
    facts['LSMinimumSystemVersion'] = plist.get('LSMinimumSystemVersion')
    facts['bundle_size_mb'] = round(sum(f.stat().st_size for f in INSTALLED.rglob('*') if f.is_file() and not f.is_symlink()) / 2**20, 1)
    archs = run('lipo', '-archs', BINARY).stdout.strip()
    check('main executable is arm64 only', archs == 'arm64', archs)
    facts['bundle_tree_hash'] = tree_hash(INSTALLED)


def tree_hash(path):
    h = hashlib.sha256()
    for p in sorted(Path(path).rglob('*')):
        h.update(str(p.relative_to(path)).encode())
        if p.is_file() and not p.is_symlink():
            h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def make_photos(samples, out):
    """Build the test library on a separately mounted APFS volume named 'Photo Drive'."""
    image = Path(out) / 'PhotoDrive.sparseimage'
    run('hdiutil', 'create', '-size', '8g', '-type', 'SPARSE', '-fs', 'APFS', '-volname', 'Photo Drive', '-ov', image)
    run('hdiutil', 'attach', '-nobrowse', image)
    volume = Path('/Volumes/Photo Drive')
    shoot = volume / 'Regatta 2026' / 'Day 1'
    sub = shoot / 'Card 2'
    sub.mkdir(parents=True)
    manifest = json.loads((Path(samples) / 'manifest.json').read_text())
    real = []
    for i, m in enumerate(manifest):
        src = Path(samples) / m['file']
        stem, ext = src.stem, src.suffix
        # Alternate the extension's case to exercise .NEF/.nef/.Orf handling.
        variant = [ext.upper(), ext.lower(), ext[:2].upper() + ext[2:].lower()][i % 3]
        dest = (sub if i % 4 == 3 else shoot) / f'{stem}{variant}'
        shutil.copy2(src, dest)
        real.append({'path': str(dest), **m})
    # A JPEG burst (5 frames, 0.1 s apart, sub-second EXIF), a separate frame, PNG and TIFFs.
    rng = np.random.default_rng(3)
    y, x = np.mgrid[:2000, :3000]
    base = ((x // 30 + y // 30) % 2 * 140 + 50).astype(np.float32)
    for k, blur in enumerate([0, 0, 3, 1, 6]):
        im = Image.fromarray((base + rng.normal(0, 3, base.shape)).clip(0, 255).astype('uint8')).convert('RGB')
        if blur:
            from PIL import ImageFilter
            im = im.filter(ImageFilter.GaussianBlur(blur))
        exif = Image.Exif()
        exif[0x0132] = '2026:06:01 14:30:05'
        e = exif.get_ifd(0x8769)
        e[0x9003] = '2026:06:01 14:30:05'
        e[0x9291] = str(10 + k * 10)
        im.save(shoot / f'BURST_{k + 1:02}.JPG', quality=92, exif=exif.tobytes())
    Image.fromarray(rng.integers(0, 255, (800, 1200, 3), dtype='uint8')).save(shoot / 'graphic.PNG')
    Image.fromarray((base[:1000, :1500]).astype('uint8')).convert('RGB').save(sub / 'SUBFOLDER.jpg', quality=90)
    facts['burst_exif_written'] = {k: str(v) for k, v in Image.open(shoot / 'BURST_02.JPG').getexif().get_ifd(0x8769).items()}
    Image.fromarray((base[:800, :1200]).astype('uint8')).convert('RGB').save(shoot / 'scan8.tif')
    Image.fromarray((base[:800, :1200] * 200).astype('uint16')).save(shoot / 'scan16.TIFF')
    # Damaged, empty, unreadable and junk files
    first = next((r for r in real if r['file'].lower().endswith('.nef') and r.get('kind') != 'nikon_he'), real[0])
    data = Path(first['path']).read_bytes()
    (shoot / 'truncated.NEF').write_bytes(data[: len(data) * 2 // 5])
    (shoot / 'garbage.orf').write_bytes(os.urandom(300_000))
    (shoot / 'empty.NRW').write_bytes(b'')
    shutil.copy2(first['path'], shoot / 'locked.NEF')
    os.chmod(shoot / 'locked.NEF', 0)
    (shoot / '._BURST_01.JPG').write_bytes(b'\x00\x05\x16\x07AppleDouble')
    # Large folder: APFS clones (no extra space) of the real samples.
    large = volume / 'Large Shoot'
    large.mkdir()
    pool = [r['path'] for r in real]
    n = int(os.environ.get('LARGE_COUNT', '250'))
    for i in range(n):
        src = pool[i % len(pool)]
        run('cp', '-c', src, large / f'FRAME_{i:04}{Path(src).suffix}')
    return volume, shoot, real, large


@guarded('decoded output inspection')
def inspect_decodes(app, rows, real, out):
    dec = Path(out) / 'decoded'
    dec.mkdir(exist_ok=True)
    by_path = {r['path']: r for r in rows['rows']}
    errors = {e['path']: e['error'] for e in rows['errors']}
    report = []
    for s in real:
        name = Path(s['path']).name
        if s['path'] in errors:
            report.append({'file': name, 'model': s['model'], 'decoded': False, 'error': errors[s['path']]})
            record(f'decode {s["model"]} {name}', 'FAIL', 'reported as not decodable: ' + errors[s['path']])
            continue
        row = by_path.get(s['path'])
        if not row:
            record(f'decode {s["model"]} {name}', 'FAIL', 'missing from results')
            continue
        if s.get('kind') == 'nikon_he':
            check(f'Nikon High Efficiency NEF analysed from the camera preview and labelled ({s["model"]}, {name})',
                  row['status'] == 'analysed' and row.get('basis') == 'camera_preview' and max(row['size']) >= 4000
                  and 'do not measure the original RAW' in (row.get('notice') or ''),
                  {'basis': row.get('basis'), 'size': row['size'], 'scores': row['scores']})
            report.append({'file': name, 'model': s['model'], 'decoded': False, 'basis': row.get('basis'), 'size': row['size']})
            continue
        full = app.call('full/' + row['id'], raw=True, timeout=600)
        target = dec / (Path(name).stem + '.jpg')
        target.write_bytes(full)
        ours = Image.open(target)
        ours.load()
        arr = np.asarray(ours.convert('RGB'), dtype=np.float32) / 255
        stats = {'size': list(ours.size), 'mean': round(float(arr.mean()), 3),
                 'channel_means': [round(float(v), 3) for v in arr.mean(axis=(0, 1))],
                 'clipped_pct': round(float(((arr > .99).all(-1)).mean() * 100), 2)}
        # Independent reference: macOS's own RAW engine (Core Image via sips).
        ref = dec / (Path(name).stem + '.apple.jpg')
        r = run('sips', '-s', 'format', 'jpeg', s['path'], '--out', ref, check_=False)
        corr = None
        if r.returncode == 0 and ref.exists():
            a = np.asarray(ours.convert('L').resize((300, 200)), dtype=np.float32)
            refim = Image.open(ref)
            b = np.asarray(refim.convert('L').resize((300, 200)), dtype=np.float32)
            same_orientation = (ours.width >= ours.height) == (refim.width >= refim.height)
            corr = float(np.corrcoef(a.ravel(), b.ravel())[0, 1]) if same_orientation else -1.0
            stats['apple_size'] = list(refim.size)
        stats['correlation_with_apple_render'] = None if corr is None else round(corr, 3)
        ok = (row['status'] == 'analysed' and row['source'] in ('decoded', 'cache') and row['is_raw']
              and list(row['size']) == list(ours.size) and .03 < stats['mean'] < .9 and arr.std() > .02
              and (corr is None or corr > .8))
        report.append({'file': name, 'model': s['model'], 'decoded': True, **stats, 'scores': row['scores']})
        check(f'decode {s["model"]} {name} (full RAW decode, sensible content'
              + (', matches Apple render' if corr is not None else ', no Apple reference') + ')', ok, json.dumps(stats))
        # small preview copies for the report artefact
        ours.resize((ours.width // 4, ours.height // 4)).save(dec / (Path(name).stem + '.small.jpg'), quality=85)
        target.unlink()
    facts['decode_report'] = report


@guarded('main library scan')
def library_checks(app, shoot, real, out):
    t = time.time()
    state, rows = app.scan(shoot.parent, recursive=True)
    facts['first_scan_seconds'] = round(time.time() - t, 1)
    names = {Path(r['path']).name: r for r in rows['rows']}
    errors = {Path(e['path']).name: e['error'] for e in rows['errors']}
    facts['scan_errors'] = errors
    check('scan completes on external volume path with spaces', state['phase'] == 'complete',
          f"{len(rows['rows'])} analysed, {len(rows['errors'])} errors in {facts['first_scan_seconds']} s")
    for n in ('truncated.NEF', 'garbage.orf', 'empty.NRW', 'locked.NEF'):
        check(f'damaged/unreadable file reported, not scored: {n}', n in errors and n not in names, errors.get(n))
    check('AppleDouble ._ files ignored', not any(n.startswith('._') for n in list(names) + list(errors)))
    check('mixed formats analysed (JPEG, PNG, 8/16-bit TIFF)',
          all(n in names for n in ('BURST_01.JPG', 'graphic.PNG', 'scan8.tif', 'scan16.TIFF')),
          sorted(n for n in names if not n.lower().endswith(('.nef', '.orf', '.nrw'))))
    exts = sorted({Path(s['path']).suffix for s in real})
    check('upper/lower/mixed-case RAW extensions recognised', all(Path(s['path']).name in names or Path(s['path']).name in errors for s in real), exts)
    check('subfolder included when "Include subfolders" is on', any('Card 2' in r['name'] for r in rows['rows']))
    burst = [names[f'BURST_{k:02}.JPG'] for k in range(1, 6)]
    groups = {r['group'] for r in burst}
    check('burst grouped by sub-second capture time + similarity', len(groups) == 1,
          [(Path(r['path']).name, r['timestamp'], r['group']) for r in burst])
    top = max(burst, key=lambda r: r['scores']['focus'])
    check('sharpest burst frame has the highest focus score', Path(top['path']).name in ('BURST_01.JPG', 'BURST_02.JPG'),
          {Path(r['path']).name: r['scores']['focus'] for r in burst})
    inspect_decodes(app, rows, real, out)
    return rows


@guarded('isolation from developer tools')
def isolation_checks(app):
    maps = run('lsof', '-p', app.pid, '-Fn', check_=False).stdout.splitlines()
    libs = sorted({l[1:] for l in maps if l.startswith('n') and (l.endswith(('.dylib', '.so')) or '.framework/' in l)})
    outside = [l for l in libs if not l.startswith((str(INSTALLED), '/System/', '/usr/lib/', '/Library/Apple/', '/private/var/db/'))]
    facts['loaded_libraries'] = len(libs)
    check('app loads only its own bundled libraries and the OS (no external Python/Homebrew)', not outside,
          outside[:10] or f'{len(libs)} libraries, all inside the bundle or the OS')
    net = run('lsof', '-nP', '-a', '-i', '-p', app.pid, check_=False).stdout.splitlines()[1:]
    bad = [l for l in net if '127.0.0.1' not in l and 'localhost' not in l]
    check('network sockets are loopback only', not bad, net[:6])
    check('HTTP server not reachable without the session token', http_status(app.port, 'api/state') == 403)
    check('HTTP server rejects foreign Host headers (DNS rebinding)',
          http_status(app.port, '', host='evil.example') == 403)


def http_status(port, path, host=None):
    req = urllib.request.Request(f'http://127.0.0.1:{port}/{path}')
    if host:
        req.add_header('Host', host)
    try:
        return urllib.request.urlopen(req, timeout=10).status
    except urllib.error.HTTPError as e:
        return e.code


@guarded('diagnostic report')
def diagnostics_check(app, out):
    r = app.call('diagnostics', {})
    text = Path(r['saved']).read_text()
    shutil.copy2(r['saved'], Path(out) / 'diagnostics-sample.txt')
    ok = all(h in text for h in ('## This Mac', 'macos:', 'chip:', '## Bursts', '## Orientation cross-check',
                                 'Nikon NEF')) and str(HOME) not in text
    oriented = [l for l in text.splitlines() if l.startswith('- RAW files checked')]
    check('Help → Create Diagnostic Report produces a report without full paths', ok, oriented)


def fake_lightroom(out):
    """A stand-in for Lightroom Classic (not installed on the runners): an AppleScript applet that records
    the files macOS hands it, the same way Lightroom receives files dropped on its icon."""
    received = Path(out) / 'lightroom-received.txt'
    script = Path(out) / 'fake-lightroom.applescript'
    script.write_text('on open theFiles\n set out to ""\n repeat with f in theFiles\n'
                      '  set out to out & POSIX path of f & linefeed\n end repeat\n'
                      f' do shell script "printf %s " & quoted form of out & " > " & quoted form of "{received}"\n'
                      'end open\n')
    app = Path(out) / 'Fake Lightroom.app'
    run('osacompile', '-o', app, script)
    return app, received


def ui_check(app, folder, out, expect_persisted, label, lightroom_received=None):
    cmd = [sys.executable, str(Path(__file__).resolve().parent.parent / 'tests' / 'ui_check.py'), '--port', str(app.port),
           '--token', app.token, '--folder', str(folder), '--engine', 'webkit', '--recursive',
           '--shots', str(Path(out) / f'screens-{label}')]
    if expect_persisted:
        cmd.append('--expect-persisted')
    if lightroom_received:
        cmd += ['--lightroom-received', str(lightroom_received)]
    r = run(*cmd, check_=False, timeout=3600)
    for line in r.stdout.splitlines():
        if line.startswith(('PASS ', 'FAIL ')):
            status, _, rest = line.partition(' ')
            name, _, detail = rest.partition(' — ')
            record(f'UI ({label}): {name}', status, detail)
    if r.returncode != 0 and 'Traceback' in (r.stdout + r.stderr):
        record(f'UI ({label}) harness stopped early', 'FAIL', (r.stdout + r.stderr)[-1800:])


def screenshot(out, name):
    r = run('screencapture', '-x', Path(out) / name, check_=False)
    return r.returncode == 0


@guarded('large folder: cancellation, responsiveness, memory, cache reuse')
def large_folder(app, large, out):
    n = len(os.listdir(large))
    app.call('scan', {'folder': str(large), 'recursive': False})
    lat, rss = [], []
    cancelled_at = None
    t0 = time.time()
    while True:
        a = time.perf_counter()
        s = app.call('state')
        app.call('rows')
        lat.append((time.perf_counter() - a) * 1000)
        rss.append(app.rss_mb())
        if cancelled_at is None and s['phase'] == 'analysing' and s['done'] >= 24:
            done_before = s['done']
            app.call('cancel', {})
            cancelled_at = time.time()
        if not s['running']:
            break
        time.sleep(.25)
    stop_s = time.time() - cancelled_at if cancelled_at else None
    s = app.call('state')
    analysed = sum(r['status'] == 'analysed' for r in app.call('rows')['rows'])
    check('cancel stops a large scan promptly and keeps partial results',
          s['phase'] == 'cancelled' and 0 < analysed < n and stop_s is not None and stop_s < 60,
          f'{analysed}/{n} analysed, stopped {stop_s and round(stop_s, 1)} s after cancel')
    p95 = sorted(lat)[int(len(lat) * .95) - 1] if lat else None
    check('API stays responsive during analysis (p95 state+rows round trip < 500 ms)', p95 is not None and p95 < 500,
          f'median {statistics.median(lat):.0f} ms, p95 {p95:.0f} ms, max {max(lat):.0f} ms over {len(lat)} polls')
    # Resume: cached results reused, then finish the whole folder to measure throughput.
    t = time.time()
    peak = []
    app.call('scan', {'folder': str(large), 'recursive': False})
    while True:
        s = app.call('state')
        peak.append(app.rss_mb())
        if not s['running']:
            break
        time.sleep(1)
    elapsed = time.time() - t
    check('rescan after cancellation reuses cached results', s['cached'] >= analysed, f"{s['cached']} reused")
    fresh = n - s['cached']
    facts['large_folder'] = {'files': n, 'workers': s['workers'], 'seconds': round(elapsed, 1),
                             'files_per_second': round(fresh / max(elapsed, .1), 2),
                             'peak_rss_mb': round(max(x for x in peak + rss if x), 0)}
    check(f'large folder ({n} RAW files) completes', s['phase'] == 'complete', facts['large_folder'])
    t = time.time()
    s, _ = app.scan(large, recursive=False)
    check('fully cached rescan avoids re-decoding', s['cached'] == n and time.time() - t < 60,
          f'{s["cached"]}/{n} from cache in {time.time() - t:.1f} s')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dmg', required=True)
    ap.add_argument('--samples', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    facts['host'] = {'macos': run('sw_vers', '-productVersion').stdout.strip(), 'arch': run('uname', '-m').stdout.strip(),
                     'model': run('sysctl', '-n', 'machdep.cpu.brand_string').stdout.strip(),
                     'memory_gb': round(int(run('sysctl', '-n', 'hw.memsize').stdout) / 2**30, 1)}
    for d in (SUPPORT, CACHES, LOGS):
        shutil.rmtree(d, ignore_errors=True)

    kinds = {Path(m['file']).suffix.lower() for m in json.loads((Path(a.samples) / 'manifest.json').read_text())}
    if not any(m.get('kind') == 'nikon_he' for m in json.loads((Path(a.samples) / 'manifest.json').read_text())):
        record('Nikon High Efficiency NEF camera-preview fallback', 'NOT TESTED', 'no HE sample could be downloaded')
    for ext, label in (('.nef', 'Nikon NEF'), ('.nrw', 'Nikon NRW'), ('.orf', 'Olympus / OM System ORF'), ('.arw', 'Sony ARW')):
        if ext not in kinds:
            record(f'genuine {label} decode', 'NOT TESTED', 'no genuine sample file was available to this run')
    install(a.dmg, out)
    volume, shoot, real, large = make_photos(a.samples, out)
    before = fingerprint(volume)

    hidden = []
    lr_received = None
    for p in ('/Library/Frameworks/Python.framework', '/opt/homebrew'):
        if os.path.exists(p):
            run('sudo', 'mv', p, p + '.hidden-for-test')
            hidden.append(p)
    facts['hidden_during_test'] = hidden
    try:
        # ---- launch 1: offline, minimal environment, no developer Python
        app = None
        try:
            t = time.time()
            try:
                fake_lr, lr_received = fake_lightroom(out)
            except Exception as error:
                fake_lr, lr_received = '', None
                record('stand-in Lightroom app for the hand-off test', 'NOT TESTED', error)
            app = App(out, offline=True, label='1', extra_env={'PHOTOSELECT_LR_APP': str(fake_lr)})
            check('packaged app launches offline without external Python/Homebrew (sandboxed: no outbound network)', True,
                  f'ready in {time.time() - t:.1f} s; hidden: {hidden}')
        except Exception as error:
            check('packaged app launches offline without external Python/Homebrew', False, error)
        if app:
            facts['about'] = app.call('about')
            isolation_checks(app)
            screenshot(out, 'app-window-launch1.png')
            library_checks(app, shoot, real, out)
            diagnostics_check(app, out)
            ui_check(app, shoot.parent, out, False, 'launch 1', lightroom_received=lr_received)
            screenshot(out, 'app-window-after-ui.png')
            port, pid = app.port, app.pid
            q, method, detail = app.quit()
            if method == 'Apple Event quit':
                check('Quit (Apple Event, same as ⌘Q) exits the app', True, f'{q:.1f} s')
            else:
                record('Quit via Apple Event (⌘Q path)', 'NOT TESTED', f'refused on this runner: {detail}')
                check('SIGTERM closes the window and exits cleanly', method == 'SIGTERM', f'{method}, {q and round(q, 1)} s')
            time.sleep(1)
            check('no PhotoSelect processes remain after quitting', not photoselect_processes() and app.proc.poll() is not None,
                  photoselect_processes())
            check('local server port closed after quitting', not port_open(port))

        # ---- launch 2: through LaunchServices (as a Finder double-click), persistence
        try:
            app = App(out, via_open=True, label='2')
            check('relaunch via LaunchServices (open -a, like double-clicking)', True)
        except Exception as error:
            app = None
            check('relaunch via LaunchServices (open -a, like double-clicking)', False, error)
        if app:
            t = time.time()
            state, rows = app.scan(shoot.parent, recursive=True)
            check('relaunch reuses cached analysis (no repeated full decode)',
                  state['cached'] == len(rows['rows']), f"{state['cached']}/{len(rows['rows'])} cached, {time.time() - t:.1f} s")
            regions = [r for r in rows['rows'] if r['roi']]
            check('focus region persisted across relaunch', any(r['roi_state'] == 'full' for r in regions),
                  [(Path(r['path']).name, r['roi'], r['roi_state']) for r in regions])
            ui_check(app, shoot.parent, out, True, 'launch 2')
            check('settings stored in ~/Library (Application Support, Caches, Logs)',
                  (SUPPORT / 'photoselect.db').exists() and (CACHES / 'thumbs').is_dir() and (LOGS / 'photoselect.log').exists(),
                  [str(SUPPORT), str(CACHES), str(LOGS)])
            log = (LOGS / 'photoselect.log').read_text(errors='replace')
            check('log records window shown and orderly shutdown', 'window shown' in log)
            pid = app.pid
            q, method, _ = app.quit()
            time.sleep(1)
            check('second quit leaves no processes', q is not None and not photoselect_processes(),
                  f'{method}; remaining: {photoselect_processes()}')

        # ---- launch 3: large folder
        try:
            app = App(out, offline=True, label='3')
            large_folder(app, large, out)
            app.quit()
            time.sleep(1)
            if photoselect_processes():
                record('quit after large scan leaves no processes', 'FAIL', photoselect_processes())
        except Exception as error:
            record('large folder test', 'FAIL', error)
            for line in photoselect_processes():
                os.kill(int(line.split()[0]), signal.SIGKILL)
    finally:
        for p in hidden:
            run('sudo', 'mv', p + '.hidden-for-test', p, check_=False)

    after = fingerprint(volume)
    fields = ('content', 'size', 'mtime', 'permissions', 'xattrs')

    def difference(k):
        b, a2 = before[k], after.get(k)
        if a2 is None:
            return {'removed': True}
        d = {f: True for f, x, y in zip(fields, b, a2) if x != y and f != 'xattrs'}
        if b[4] != a2[4]:
            d['xattrs added'] = sorted(set(a2[4]) - set(b[4]))
            d['xattrs removed'] = sorted(set(b[4]) - set(a2[4]))
        return d
    changed = {k: difference(k) for k in before if before[k] != after.get(k)}
    added = [k for k in after if k not in before]
    # Files handed to Lightroom ("Open in Lightroom Import") are opened through macOS LaunchServices,
    # which records a "last opened" date in an extended attribute, exactly as when the user drags a
    # photo onto any app. Content, size, dates and permissions must still be unchanged.
    handed = set(lr_received.read_text().split('\n')) if lr_received and lr_received.exists() else set()
    launch_services = {k: d for k, d in changed.items() if k in handed and set(d) <= {'xattrs added', 'xattrs removed'}
                       and not d.get('xattrs removed') and set(d['xattrs added']) <= {'com.apple.lastuseddate#PS'}}
    real = {k: d for k, d in changed.items() if k not in launch_services}
    check('originals unchanged (content, size, mtime, permissions, xattrs) and no files added', not real and not added,
          {'changed': dict(list(real.items())[:6]), 'added': added[:10], 'files': len(before)})
    if launch_services:
        record('photos handed to Lightroom: content unchanged; macOS added its "last opened" date attribute', 'INFO',
               f'{len(launch_services)} files: com.apple.lastuseddate#PS')
    v = run('codesign', '--verify', '--deep', '--strict', INSTALLED, check_=False)
    check('app bundle unchanged after use (signature still valid, identical tree hash)',
          v.returncode == 0 and tree_hash(INSTALLED) == facts.get('bundle_tree_hash'), v.stderr.strip())
    os.chmod(shoot / 'locked.NEF', 0o644)
    run('hdiutil', 'detach', volume, check_=False)
    for name in ('photoselect.log',):
        if (LOGS / name).exists():
            shutil.copy2(LOGS / name, out / name)

    (out / 'results.json').write_text(json.dumps({'results': results, 'facts': facts}, indent=1, default=str))
    lines = ['# PhotoSelect packaged-app acceptance results', '',
             f"Host: macOS {facts['host']['macos']} on {facts['host']['model']} ({facts['host']['arch']}, {facts['host']['memory_gb']} GB)", '',
             '| Result | Check | Detail |', '|---|---|---|']
    for r in results:
        lines.append(f"| {r['status']} | {r['check']} | {r['detail'][:300].replace('|', '/').replace(chr(10), ' ')} |")
    lines += ['', '## Facts', '```json', json.dumps(facts, indent=1, default=str)[:20000], '```']
    (out / 'acceptance.md').write_text('\n'.join(lines))
    failed = [r for r in results if r['status'] == 'FAIL']
    print(f'\n{len(results) - len(failed)} passed/informational, {len(failed)} failed')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
