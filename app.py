"""Local HTTP API and review interface for PhotoSelect.

Served by Waitress on 127.0.0.1 with an OS-assigned port. Every API request must carry the
per-launch session token, and the Host header must name the loopback address and port, which
blocks other web pages (including DNS-rebinding attacks) from reading the API.
"""
import csv
import io
import logging
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

from flask import Flask, request, jsonify, send_file, abort, Response

import analysis
import raw_io
import store as store_module
from engine import Library

APP_VERSION = '1.4.0'
log = logging.getLogger('photoselect.app')


def resource_dir():
    """Directory holding static/ both from source and inside a PyInstaller bundle."""
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))


LIGHTROOM_PLUGIN = 'PhotoSelect.lrplugin'
LIGHTROOM_FIELDS = ('path', 'name', 'capture', 'rating', 'keywords', 'decision', 'suggestion')


def lightroom_dir():
    """Where "Send to Lightroom" saves selections for the Lightroom Classic plug-in to read."""
    return store_module.support_dir() / 'Lightroom'


def lightroom_modules_dir():
    """Lightroom Classic loads plug-ins placed here automatically (no Plug-in Manager step)."""
    override = os.environ.get('PHOTOSELECT_LR_MODULES')
    if override:
        return Path(override)
    return Path.home() / 'Library' / 'Application Support' / 'Adobe' / 'Lightroom' / 'Modules'


LIGHTROOM_BUNDLE_ID = 'com.adobe.LightroomClassicCC7'
OPEN_IN_LIGHTROOM_MAX = 2000   # files handed to Lightroom's Import window in one go


def lightroom_app():
    """Path of Adobe Lightroom Classic on this Mac, or None."""
    override = os.environ.get('PHOTOSELECT_LR_APP')
    if override is not None:
        return override if override and Path(override).exists() else None
    if sys.platform != 'darwin':
        return None
    default = Path('/Applications/Adobe Lightroom Classic/Adobe Lightroom Classic.app')
    if default.exists():
        return str(default)
    try:
        found = subprocess.run(['/usr/bin/mdfind', f"kMDItemCFBundleIdentifier == '{LIGHTROOM_BUNDLE_ID}'"],
                               capture_output=True, text=True, timeout=10).stdout.split('\n')
    except (OSError, subprocess.SubprocessError):
        return None
    return next((p for p in found if p.endswith('.app')), None)


def plugin_version(folder):
    """'major.minor.revision' from a PhotoSelect.lrplugin folder's Info.lua, or ''."""
    import re
    try:
        m = re.search(r'VERSION\s*=\s*\{\s*major\s*=\s*(\d+),\s*minor\s*=\s*(\d+),\s*revision\s*=\s*(\d+)',
                      (Path(folder) / 'Info.lua').read_text(encoding='utf-8'))
    except OSError:
        return ''
    return '.'.join(m.groups()) if m else ''


def plugin_report():
    """What the plug-in last reported from inside Lightroom (plugin-status.txt), or {}."""
    try:
        lines = (lightroom_dir() / 'plugin-status.txt').read_text(encoding='utf-8').splitlines()
    except OSError:
        return {}
    out = dict(line.split('\t', 1) for line in lines if '\t' in line)
    for k in ('started', 'checked', 'applied_at', 'applied_count', 'waiting'):
        try:
            out[k] = float(out[k])
        except (KeyError, ValueError):
            out[k] = 0
    return out


def lightroom_running():
    if sys.platform != 'darwin':
        return False
    try:
        return subprocess.run(['/usr/bin/pgrep', '-x', 'Adobe Lightroom Classic'], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _open_in_lightroom(app_path, paths):
    """Hand files to Lightroom Classic like dropping them on its icon: it opens its Import window with them."""
    subprocess.run(['/usr/bin/open', '-a', app_path, *paths], check=True, capture_output=True, timeout=60)


def _tsv_field(value):
    return ' '.join(str(value).replace('\t', ' ').splitlines())


def lightroom_selections(folder, rows, auto=False):
    """Tab-separated selections file read by the plug-in's SelectionsCore.lua (format version 1).
    auto: the plug-in applies these selections by itself once the photos are in the catalog."""
    lines = [f'# PhotoSelect selections\t1\t{time.time():.3f}\t{_tsv_field(folder)}\t{1 if auto else 0}',
             '\t'.join(LIGHTROOM_FIELDS)]
    for r in rows:
        rating = int(r['rating'])
        keywords = '|'.join(_tsv_field(k).replace('|', '/') for k in r.get('keywords') or [])
        lines.append('\t'.join(_tsv_field(v) for v in (r['path'], r['name'], r.get('capture') or '', rating, keywords,
                                                         r.get('decision') or '', r.get('suggestion') or '')))
    return '\n'.join(lines) + '\n'


def _default_pick_folder():
    if sys.platform == 'darwin':
        script = ('try\nPOSIX path of (choose folder with prompt "Choose your photo folder")\n'
                  'on error number -128\nreturn ""\nend try')
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, check=True)
        return result.stdout.strip() or None
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    folder = filedialog.askdirectory(title='Choose your photo folder')
    root.destroy()
    return folder or None


def create_app(library=None, store=None, token=None):
    store = store or store_module.Store()
    library = library or Library(store, store_module.cache_dir())
    app = Flask(__name__, static_folder=None)
    app.config.update(TOKEN=token or secrets.token_urlsafe(32), PORT=None, PICK_FOLDER=None, SAVE_FILE=None,
                      OPEN_IN_LIGHTROOM=_open_in_lightroom,
                      DESKTOP=False, EXPORT_DIR=os.environ.get('PHOTOSELECT_EXPORT_DIR'))
    app.library, app.store = library, store

    def row_or_404(id):
        row = library.row(id)
        if row is None:
            abort(404)
        return row

    @app.before_request
    def secure():
        port = app.config['PORT']
        if port is not None and request.host not in (f'127.0.0.1:{port}', f'localhost:{port}'):
            abort(403)
        if request.path.startswith('/api/'):
            supplied = request.headers.get('X-Session') or request.args.get('t', '')
            if not secrets.compare_digest(supplied, app.config['TOKEN']):
                abort(403)

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        if request.path == '/':
            response.headers['Content-Security-Policy'] = (
                "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; "
                "script-src 'self' 'unsafe-inline'; connect-src 'self'")
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(Exception)
    def failure(error):
        from werkzeug.exceptions import HTTPException
        if isinstance(error, HTTPException):
            return jsonify(error=error.description), error.code
        log.exception('request failed')
        return jsonify(error=f'Unexpected error: {error}'), 500

    @app.get('/')
    def home():
        html = (resource_dir() / 'static' / 'index.html').read_text(encoding='utf-8')
        return Response(html.replace('__TOKEN__', app.config['TOKEN']).replace('__VERSION__', APP_VERSION)
                        .replace('__DESKTOP__', 'true' if app.config['DESKTOP'] else 'false'), mimetype='text/html')

    @app.get('/api/state')
    def state():
        return jsonify(library.snapshot())

    @app.get('/api/rows')
    def rows():
        return jsonify(library.payload())

    @app.get('/api/prefs')
    def get_prefs():
        return jsonify(store.prefs())

    @app.post('/api/prefs')
    def set_prefs():
        data = request.get_json(force=True) or {}
        return jsonify(store.set_prefs(data))

    @app.post('/api/pick')
    def pick():
        try:
            folder = (app.config['PICK_FOLDER'] or _default_pick_folder)()
        except Exception:
            log.exception('folder chooser failed')
            return jsonify(error='The folder chooser is unavailable. Paste the full folder path instead.'), 400
        return jsonify(folder=folder or '')

    @app.post('/api/scan')
    def scan():
        data = request.get_json(force=True) or {}
        raw = str(data.get('folder', '')).strip()
        if not raw:
            return jsonify(error='Choose a folder first.'), 400
        folder = Path(raw).expanduser()
        try:
            if not folder.is_dir():
                return jsonify(error='That folder does not exist or is not available. Check the drive is connected.'), 400
            os.listdir(folder)
        except PermissionError:
            return jsonify(error='macOS has not given PhotoSelect access to that folder. Use "Choose folder" to select '
                                 'it, or allow access in System Settings → Privacy & Security → Files and Folders.'), 403
        recursive = bool(data.get('recursive'))
        try:
            library.start(folder.resolve(), recursive)
        except RuntimeError as error:
            return jsonify(error=str(error)), 409
        store.set_prefs({'folder': str(folder.resolve()), 'recursive': recursive})
        return jsonify(ok=True)

    @app.post('/api/cancel')
    def cancel():
        library.cancel()
        return jsonify(ok=True)

    def image_file(path):
        if path is None or not path.exists():
            abort(404)
        response = send_file(path, mimetype='image/jpeg', max_age=3600)
        response.headers['Cache-Control'] = 'private, max-age=3600'
        return response

    @app.get('/api/thumb/<id>')
    def thumb(id):
        return image_file(library.thumb_path(row_or_404(id)))

    @app.get('/api/preview/<id>')
    def preview(id):
        return image_file(library.preview_path(row_or_404(id)))

    @app.get('/api/full/<id>')
    def full(id):
        row = row_or_404(id)
        try:
            data = library.full_jpeg(row)
        except raw_io.DecodeError as error:
            return jsonify(error=str(error)), 422
        return Response(data, mimetype='image/jpeg', headers={'Cache-Control': 'private, max-age=600'})

    @app.post('/api/prefetch')
    def prefetch():
        ids = (request.get_json(force=True) or {}).get('ids') or []
        library.prefetch([i for i in ids if isinstance(i, str)])
        return jsonify(ok=True)

    @app.get('/api/crop/<id>')
    def crop(id):
        row = row_or_404(id)
        try:
            region = [float(v) for v in request.args.get('roi', '').split(',')]
        except ValueError:
            region = None
        if not analysis.valid_region(region):
            return jsonify(error='Invalid region.'), 400
        try:
            data = library.crop_jpeg(row, region)
        except raw_io.DecodeError as error:
            return jsonify(error=str(error)), 422
        return Response(data, mimetype='image/jpeg', headers={'Cache-Control': 'private, max-age=600'})

    @app.post('/api/roi')
    def roi():
        data = request.get_json(force=True) or {}
        try:
            library.set_roi(data.get('id'), data.get('roi'))
        except KeyError:
            abort(404)
        except ValueError as error:
            return jsonify(error=str(error)), 400
        return jsonify(ok=True)

    @app.post('/api/mark')
    def mark():
        data = request.get_json(force=True) or {}
        row = row_or_404(data.get('id'))
        fields = {}
        if 'decision' in data:
            decision = 'Drop' if data['decision'] == 'Skip' else data['decision']   # 'Skip' was renamed 'Drop' in 1.2
            if decision not in (None, 'Keep', 'Consider', 'Drop'):
                return jsonify(error='Unknown decision.'), 400
            fields['decision'] = decision
        if 'liked' in data:
            fields['liked'] = bool(data['liked'])
        store.set_mark(row['path'], **fields)
        library.version += 1
        return jsonify(ok=True)

    @app.post('/api/groups')
    def groups():
        data = request.get_json(force=True) or {}
        settings = {k: data[k] for k in ('gap', 'likeness', 'near_identical', 'near_window') if k in data}
        if 'likeness' not in settings and 'similarity' in data:   # 1.2 clients
            settings['likeness'] = analysis.similarity_to_likeness(data['similarity'])
        library.regroup(**settings)
        return jsonify(ok=True)

    def save_text(text, filename, encoding='utf-8'):
        """Write a user-requested file via the native save dialog (or EXPORT_DIR in tests)."""
        if app.config['EXPORT_DIR']:
            target = Path(app.config['EXPORT_DIR']) / filename
        elif app.config['SAVE_FILE']:
            chosen = app.config['SAVE_FILE'](filename)
            if not chosen:
                return jsonify(cancelled=True)
            target = Path(chosen)
        else:
            return jsonify(text=text, filename=filename)  # plain-browser development mode: client downloads it
        originals = {Path(r['path']).resolve() for r in library.payload()['rows']}
        if target.resolve() in originals:
            return jsonify(error='Refusing to overwrite an original photo.'), 400
        target.write_text(text, encoding=encoding)
        return jsonify(saved=str(target))

    @app.post('/api/export')
    def export():
        data = request.get_json(force=True) or {}
        table = data.get('rows') or []
        if not table or not all(isinstance(r, list) for r in table):
            return jsonify(error='Nothing to export.'), 400
        out = io.StringIO()
        csv.writer(out, lineterminator='\r\n').writerows(table)
        return save_text(out.getvalue(), 'PhotoSelect-decisions.csv', 'utf-8-sig')

    @app.post('/api/diagnostics')
    def make_diagnostics():
        import diagnostics
        return save_text(diagnostics.build(library, store.prefs(), APP_VERSION), diagnostics.filename())

    def plugin_path():
        return lightroom_modules_dir() / LIGHTROOM_PLUGIN

    @app.get('/api/lightroom/status')
    def lightroom_status():
        installed = (plugin_path() / 'Info.lua').exists()
        report = plugin_report()
        return jsonify(plugin_installed=installed, plugin_path=str(plugin_path()) if installed else '',
                       installed_version=plugin_version(plugin_path()) if installed else '',
                       bundled_version=plugin_version(resource_dir() / 'lightroom' / LIGHTROOM_PLUGIN),
                       lightroom=lightroom_app() or '', lightroom_running=lightroom_running(),
                       # the plug-in writes its status about every 30 s while Lightroom is open
                       plugin_running=bool(report) and time.time() - report['checked'] < 120,
                       running_version=report.get('version', ''), checked_ago=round(time.time() - report['checked'])
                       if report else None, last_applied=report.get('applied_at') or None,
                       last_applied_count=int(report.get('applied_count') or 0), waiting=int(report.get('waiting') or 0))

    @app.post('/api/lightroom/reveal')
    def lightroom_reveal():
        target = plugin_path() if (plugin_path() / 'Info.lua').exists() else resource_dir() / 'lightroom' / LIGHTROOM_PLUGIN
        if sys.platform != 'darwin':
            return jsonify(error='Show in Finder is only available on macOS.', path=str(target)), 400
        subprocess.run(['/usr/bin/open', '-R', str(target)], check=False)
        return jsonify(ok=True, path=str(target))

    @app.post('/api/lightroom')
    def lightroom():
        data = request.get_json(force=True) or {}
        table = data.get('rows')
        if not isinstance(table, list) or not table:
            return jsonify(error='No photos have a decision, suggestion or like to send to Lightroom.'), 400
        try:
            for r in table:
                if not (isinstance(r, dict) and isinstance(r.get('path'), str) and isinstance(r.get('name'), str)
                        and 0 <= int(r.get('rating')) <= 5):
                    raise ValueError
        except (TypeError, ValueError):
            return jsonify(error='Invalid Lightroom selections.'), 400
        folder = str(data.get('folder') or '')
        target = lightroom_dir() / f'{store_module.path_id(folder or "-")}.tsv'
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix('.tmp')
        auto = bool(data.get('auto_apply'))
        tmp.write_text(lightroom_selections(folder, table, auto), encoding='utf-8')
        os.replace(tmp, target)
        log.info('Lightroom selections for %d photos saved to %s', len(table), target)
        result = {'saved': str(target), 'count': len(table), 'plugin_installed': (plugin_path() / 'Info.lua').exists()}
        wanted = data.get('open')
        if wanted is None:
            return jsonify(result)
        # "Open in Lightroom": hand only the chosen photos to Lightroom's Import window.
        known = {r['path']: r for r in table}
        paths = [p for p in wanted if isinstance(p, str) and p in known and os.path.isfile(p)]
        if not paths:
            return jsonify(error='None of the chosen photos could be found. Check that the drive is connected.', **result), 400
        if len(paths) > OPEN_IN_LIGHTROOM_MAX:
            return jsonify(error=f'{len(paths)} photos is more than PhotoSelect hands to Lightroom at once '
                                 f'({OPEN_IN_LIGHTROOM_MAX}). Choose fewer groups, or import the folder in Lightroom.',
                           **result), 400
        app_path = lightroom_app()
        if not app_path:
            # An expected outcome, not a failed request (the page reports it in the Lightroom window).
            return jsonify(lightroom_missing=True, error='Adobe Lightroom Classic was not found on this Mac. Your '
                           'selections are saved; import the folder in Lightroom, then use Apply PhotoSelect '
                           'Selections.', **result)
        pending = target.parent / 'pending.import'
        if data.get('auto_apply'):
            tmp = pending.with_suffix('.tmp')
            tmp.write_text(lightroom_selections(folder, [known[p] for p in paths], True), encoding='utf-8')
            os.replace(tmp, pending)
        else:
            pending.unlink(missing_ok=True)
        try:
            app.config['OPEN_IN_LIGHTROOM'](app_path, paths)
        except (OSError, subprocess.SubprocessError) as error:
            log.exception('opening Lightroom failed')
            return jsonify(error=f'Lightroom Classic could not be opened: {error}', **result), 500
        log.info('handed %d photos to Lightroom Classic (%s), auto-apply %s', len(paths), app_path, bool(data.get('auto_apply')))
        return jsonify(opened=len(paths), lightroom=app_path, **result)

    @app.post('/api/lightroom/install')
    def install_lightroom_plugin():
        source = resource_dir() / 'lightroom' / LIGHTROOM_PLUGIN
        target = lightroom_modules_dir() / LIGHTROOM_PLUGIN
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
            selections = str(lightroom_dir())
            (target / 'Config.lua').write_text(
                '-- Written by PhotoSelect when the plug-in was installed.\n'
                f'return {{ selectionsFolder = [==[{selections}]==] }}\n', encoding='utf-8')
        except OSError as error:
            log.exception('Lightroom plug-in install failed')
            return jsonify(error=f'Could not install the Lightroom plug-in in {target.parent}: {error.strerror or error}'), 500
        lightroom_dir().mkdir(parents=True, exist_ok=True)
        log.info('Lightroom plug-in installed in %s', target)
        return jsonify(installed=str(target))

    @app.get('/api/about')
    def about():
        import numpy, PIL, flask
        try:
            import rawpy
            rawpy_version = rawpy.__version__
        except ImportError:
            rawpy_version = 'unavailable'
        return jsonify(version=APP_VERSION, libraw=raw_io.libraw_version(), rawpy=rawpy_version,
                       numpy=numpy.__version__, pillow=PIL.__version__, flask=flask.__version__,
                       python=sys.version.split()[0], workers=library.workers,
                       support=str(store_module.support_dir()), cache=str(library.cache),
                       logs=str(store_module.log_dir()), cache_bytes=library.cache_size(),
                       analysis_version=analysis.ANALYSIS_VERSION)

    @app.post('/api/clear-cache')
    def clear_cache():
        try:
            library.clear_cache()
        except RuntimeError as error:
            return jsonify(error=str(error)), 409
        return jsonify(ok=True)

    @app.post('/api/reveal')
    def reveal():
        row = row_or_404((request.get_json(force=True) or {}).get('id'))
        if sys.platform == 'darwin':
            subprocess.run(['/usr/bin/open', '-R', row['path']], check=False)
            return jsonify(ok=True)
        return jsonify(error='Reveal in Finder is only available on macOS.'), 400

    return app


def serve(app, port=0):
    """Start Waitress on loopback; returns (server, port). Call server.run() in a thread."""
    from waitress.server import create_server
    server = create_server(app, host='127.0.0.1', port=port, threads=8, ident='PhotoSelect',
                           clear_untrusted_proxy_headers=True, channel_timeout=60)
    port = int(server.effective_port)
    app.config['PORT'] = port
    return server, port


if __name__ == '__main__':  # development mode: serve and open the default browser
    import threading
    import webbrowser
    logging.basicConfig(level=logging.INFO)
    application = create_app()
    server, port = serve(application, int(os.environ.get('PHOTOSELECT_PORT', '0')))
    threading.Timer(1, lambda: webbrowser.open(f'http://127.0.0.1:{port}/')).start()
    print(f'PhotoSelect (development mode) at http://127.0.0.1:{port}/ — Ctrl+C to stop.')
    try:
        server.run()
    finally:
        application.library.shutdown()
