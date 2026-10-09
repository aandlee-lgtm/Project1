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
import subprocess
import sys
from pathlib import Path

from flask import Flask, request, jsonify, send_file, abort, Response

import analysis
import raw_io
import store as store_module
from engine import Library

APP_VERSION = '1.0.0'
log = logging.getLogger('photoselect.app')


def resource_dir():
    """Directory holding static/ both from source and inside a PyInstaller bundle."""
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))


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
            if data['decision'] not in (None, 'Keep', 'Consider', 'Skip'):
                return jsonify(error='Unknown decision.'), 400
            fields['decision'] = data['decision']
        if 'liked' in data:
            fields['liked'] = bool(data['liked'])
        store.set_mark(row['path'], **fields)
        library.version += 1
        return jsonify(ok=True)

    @app.post('/api/groups')
    def groups():
        data = request.get_json(force=True) or {}
        library.regroup(data.get('gap', 2), data.get('similarity', 14))
        return jsonify(ok=True)

    @app.post('/api/export')
    def export():
        data = request.get_json(force=True) or {}
        table = data.get('rows') or []
        if not table or not all(isinstance(r, list) for r in table):
            return jsonify(error='Nothing to export.'), 400
        out = io.StringIO()
        csv.writer(out, lineterminator='\r\n').writerows(table)
        text = out.getvalue()
        filename = 'PhotoSelect-decisions.csv'
        if app.config['EXPORT_DIR']:
            target = Path(app.config['EXPORT_DIR']) / filename
        elif app.config['SAVE_FILE']:
            chosen = app.config['SAVE_FILE'](filename)
            if not chosen:
                return jsonify(cancelled=True)
            target = Path(chosen)
        else:
            return jsonify(csv=text)  # plain-browser development mode: client downloads it
        originals = {Path(r['path']).resolve() for r in library.payload()['rows']}
        if target.resolve() in originals:
            return jsonify(error='Refusing to overwrite an original photo.'), 400
        target.write_text(text, encoding='utf-8-sig')
        return jsonify(saved=str(target))

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
    app.config['PORT'] = server.effective_port
    return server, server.effective_port


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
