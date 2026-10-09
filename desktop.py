"""PhotoSelect desktop entry point: a native macOS window (WKWebView via pywebview)
showing the review interface served from an in-process Waitress server on loopback.

Window, server and analysis workers live in one process. Closing the window or choosing
Quit stops the run loop; we then cancel work and exit the process, so nothing keeps running
in the background.
"""
import json
import logging
import logging.handlers
import os
import subprocess
import sys
import threading
import traceback


def _alert(title, message):
    """Show a native alert even when the GUI toolkit failed to load."""
    log = logging.getLogger('photoselect')
    log.error('%s: %s', title, message)
    if sys.platform == 'darwin':
        script = ('on run argv\n display alert (item 1 of argv) message (item 2 of argv) as critical\nend run')
        subprocess.run(['/usr/bin/osascript', '-e', script, title, message], check=False)
    else:
        print(f'{title}: {message}', file=sys.stderr)


def _setup_logging():
    from store import log_dir
    directory = log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(directory / 'photoselect.log', maxBytes=2_000_000, backupCount=2,
                                                   encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if not getattr(sys, 'frozen', False):
        root.addHandler(logging.StreamHandler())
    for noisy in ('waitress', 'PIL'):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return directory


def main():
    log_directory = _setup_logging()
    log = logging.getLogger('photoselect')
    try:
        import webview
        from webview.menu import Menu, MenuAction, MenuSeparator
        import app as app_module
        import store as store_module
        from engine import Library
    except Exception:
        _alert('PhotoSelect could not start', 'A required component failed to load.\n\n' + traceback.format_exc(limit=3))
        return 1

    log.info('starting PhotoSelect %s (python %s, %s)', app_module.APP_VERSION, sys.version.split()[0],
             'frozen' if getattr(sys, 'frozen', False) else 'source')
    try:
        store = store_module.Store()
        library = Library(store, store_module.cache_dir())
        application = app_module.create_app(library, store)
        server, port = app_module.serve(application)
    except Exception as error:
        _alert('PhotoSelect could not start',
               f'{error}\n\nDetails were written to {log_directory / "photoselect.log"}.')
        log.exception('startup failed')
        return 1
    threading.Thread(target=server.run, name='http', daemon=True).start()
    url = f'http://127.0.0.1:{port}/'
    log.info('serving on %s with %d analysis workers', url, library.workers)

    window = webview.create_window('PhotoSelect', url, width=1440, height=920, min_size=(960, 640),
                                   background_color='#111518', text_select=True)
    folder_dialog, save_dialog = webview.FileDialog.FOLDER, webview.FileDialog.SAVE

    def pick_folder():
        chosen = window.create_file_dialog(folder_dialog, directory=store.prefs().get('folder') or '')
        return (chosen[0] if isinstance(chosen, (list, tuple)) else chosen) if chosen else None

    def save_file(name):
        chosen = window.create_file_dialog(save_dialog, save_filename=name)
        return (chosen[0] if isinstance(chosen, (list, tuple)) else chosen) if chosen else None

    application.config.update(DESKTOP=True, PICK_FOLDER=pick_folder, SAVE_FILE=save_file)

    def run_js(code):
        def go():
            try:
                window.run_js(code)  # native evaluateJavaScript; not subject to the page's CSP
            except Exception:
                log.exception('menu action failed')
        threading.Thread(target=go, daemon=True).start()

    def open_path(path):
        subprocess.run(['/usr/bin/open', str(path)], check=False)

    notices = app_module.resource_dir() / 'THIRD_PARTY_NOTICES.txt'
    menu = [
        Menu('File', [
            MenuAction('Choose Folder…', lambda: run_js("document.getElementById('browse').click()")),
            MenuAction('Analyse Photos', lambda: run_js("document.getElementById('scan').click()")),
            MenuAction('Cancel Analysis', lambda: run_js("document.getElementById('cancel').click()")),
            MenuSeparator(),
            MenuAction('Export Decisions…', lambda: run_js("document.getElementById('export').click()")),
        ]),
        Menu('Help', [
            MenuAction('About PhotoSelect', lambda: run_js("openAbout()")),
            MenuAction('Open Log Folder', lambda: open_path(log_directory)),
            MenuAction('Third-Party Notices', lambda: open_path(notices)),
        ]),
    ]

    automation = os.environ.get('PHOTOSELECT_AUTOMATION_FILE')

    def ready():
        log.info('window shown')
        if automation:  # used only by the automated acceptance tests
            info = {'port': port, 'token': application.config['TOKEN'], 'pid': os.getpid()}
            tmp = automation + '.tmp'
            with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as f:
                json.dump(info, f)
            os.replace(tmp, automation)

    try:
        webview.start(ready, menu=menu, private_mode=True)
    except Exception as error:
        _alert('PhotoSelect could not open its window', f'{error}\n\nSee {log_directory / "photoselect.log"}.')
        log.exception('window failed')
    finally:
        log.info('window closed; shutting down')
        library.shutdown()
        try:
            server.close()
        except Exception:
            pass
        store.close()
        logging.shutdown()
        # Exit without waiting for an in-flight RAW decode: no background work survives the window.
        os._exit(0)


if __name__ == '__main__':
    sys.exit(main())
