"""Persistent state in standard per-user locations (never inside the app bundle).

macOS:  ~/Library/Application Support/PhotoSelect/photoselect.db  (decisions, likes, regions,
        preferences, analysis results)
        ~/Library/Caches/PhotoSelect/                              (thumbnails and previews)
        ~/Library/Logs/PhotoSelect/                                (log file)
PHOTOSELECT_HOME overrides all three (used by automated tests).
"""
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import threading
import time
from pathlib import Path

APP_NAME = 'PhotoSelect'


def _base(kind):
    override = os.environ.get('PHOTOSELECT_HOME')
    if override:
        return Path(override) / kind
    home = Path.home()
    if sys.platform == 'darwin':
        return home / 'Library' / {'support': 'Application Support', 'cache': 'Caches', 'logs': 'Logs'}[kind] / APP_NAME
    if sys.platform == 'win32':
        root = Path(os.environ.get('LOCALAPPDATA', home / 'AppData' / 'Local')) / APP_NAME
        return root / kind
    xdg = {'support': ('XDG_DATA_HOME', '.local/share'), 'cache': ('XDG_CACHE_HOME', '.cache'),
           'logs': ('XDG_STATE_HOME', '.local/state')}[kind]
    return Path(os.environ.get(xdg[0], home / xdg[1])) / APP_NAME


def support_dir():
    return _base('support')


def cache_dir():
    return _base('cache')


def log_dir():
    return _base('logs')


def path_id(path):
    return hashlib.sha1(str(path).encode('utf-8', 'surrogatepass')).hexdigest()[:16]


def file_key(path, stat, version):
    """Identity of one version of a file: path, size, modification time and analysis version."""
    raw = f'{path}|{stat.st_size}|{stat.st_mtime_ns}|{version}'
    return hashlib.sha1(raw.encode('utf-8', 'surrogatepass')).hexdigest()[:24]


DEFAULT_PREFS = {
    'weights': {'sharpness': 30, 'focus': 50, 'composition': 15, 'exposure': 5},
    'keep': 75, 'consider': 45, 'gap': 2.0, 'likeness': 70, 'near_identical': 90, 'near_window': 10.0,
    'recursive': False, 'folder': '', 'page_size': 120,
    # 1.9: how many frames of each burst / near-identical series may be suggested Keep (0 = all)
    'best_of': 1,
    # 1.10: outline the area where subject focus is measured on every photo
    'show_focus': True,
    # 1.11: find the subject automatically; 'sidecar' (XMP files, no plug-in) or 'plugin' for Lightroom
    'auto_subject': True, 'lr_route': 'sidecar',
    # 1.12: suggested crops: count the cropped composition, minimum long edge after a crop, send crops to Lightroom
    'consider_crop': True, 'crop_min_edge': 3000, 'send_crops': True, 'show_crop': True,
    # 1.3: named settings profiles, settings remembered per folder, and the settings before the last
    # "learn from my decisions" change (for Undo).
    'profiles': {}, 'folder_settings': {}, 'undo_settings': None,
}


class Store:
    def __init__(self, path=None):
        self.path = Path(path) if path else support_dir() / 'photoselect.db'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None, timeout=10)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=NORMAL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS analysis(key TEXT PRIMARY KEY, path TEXT, data TEXT, created REAL);
            CREATE INDEX IF NOT EXISTS analysis_path ON analysis(path);
            CREATE TABLE IF NOT EXISTS marks(path TEXT PRIMARY KEY, decision TEXT, liked INTEGER DEFAULT 0,
                roi TEXT, roi_key TEXT, roi_focus REAL, updated REAL);
            CREATE TABLE IF NOT EXISTS prefs(key TEXT PRIMARY KEY, value TEXT);
        ''')
        # 1.12: "No crop" per photo, and the suggested crops around a region you drew
        for column in ('no_crop INTEGER DEFAULT 0', 'roi_crops TEXT'):
            try:
                self.db.execute(f'ALTER TABLE marks ADD COLUMN {column}')
            except sqlite3.OperationalError:
                pass   # already there
        # 1.2: the Skip bucket was renamed Drop; carry over decisions saved by earlier versions.
        self.db.execute("UPDATE marks SET decision='Drop' WHERE decision='Skip'")

    def close(self):
        with self.lock:
            try:
                self.db.close()
            except Exception:
                pass

    # analysis cache -------------------------------------------------------
    def get_analysis(self, key):
        with self.lock:
            row = self.db.execute('SELECT data FROM analysis WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put_analysis(self, key, path, data):
        """Store results for one file version; returns keys of superseded versions of that file."""
        with self.lock:
            old = [k for (k,) in self.db.execute('SELECT key FROM analysis WHERE path=? AND key<>?', (str(path), key))]
            self.db.execute('DELETE FROM analysis WHERE path=? AND key<>?', (str(path), key))
            self.db.execute('INSERT OR REPLACE INTO analysis VALUES(?,?,?,?)',
                            (key, str(path), json.dumps(data), time.time()))
        return old

    def clear_analysis(self):
        with self.lock:
            self.db.execute('DELETE FROM analysis')

    # decisions, likes and focus regions, keyed by original path ------------
    def marks(self, paths=None):
        with self.lock:
            rows = self.db.execute('SELECT path,decision,liked,roi,roi_key,roi_focus,no_crop,roi_crops FROM marks').fetchall()
        wanted = set(map(str, paths)) if paths is not None else None
        return {p: {'decision': d, 'liked': bool(l), 'roi': json.loads(r) if r else None, 'roi_key': k, 'roi_focus': f,
                    'no_crop': bool(n), 'roi_crops': json.loads(c) if c else None}
                for p, d, l, r, k, f, n, c in rows if wanted is None or p in wanted}

    def set_mark(self, path, **fields):
        allowed = {'decision', 'liked', 'roi', 'roi_key', 'roi_focus', 'no_crop', 'roi_crops'}
        fields = {k: v for k, v in fields.items() if k in allowed}
        for key in ('roi', 'roi_crops'):
            if key in fields:
                fields[key] = json.dumps(fields[key]) if fields[key] is not None else None
        if 'no_crop' in fields:
            fields['no_crop'] = int(bool(fields['no_crop']))
        if 'liked' in fields:
            fields['liked'] = int(bool(fields['liked']))
        with self.lock:
            self.db.execute('INSERT OR IGNORE INTO marks(path) VALUES(?)', (str(path),))
            for k, v in fields.items():
                self.db.execute(f'UPDATE marks SET {k}=?, updated=? WHERE path=?', (v, time.time(), str(path)))

    # preferences ----------------------------------------------------------
    def prefs(self):
        out = json.loads(json.dumps(DEFAULT_PREFS))
        with self.lock:
            stored = {k: json.loads(v) for k, v in self.db.execute('SELECT key,value FROM prefs')}
        for k, v in stored.items():
            if k in out:
                out[k] = v
        if 'likeness' not in stored and 'similarity' in stored:   # 1.2 'similarity tolerance' → likeness %
            import analysis
            out['likeness'] = analysis.similarity_to_likeness(stored['similarity'])
        return out

    def set_prefs(self, values):
        with self.lock:
            for k, v in values.items():
                if k in DEFAULT_PREFS:
                    self.db.execute('INSERT OR REPLACE INTO prefs VALUES(?,?)', (k, json.dumps(v)))
        return self.prefs()


def clear_cache_files(root):
    for name in ('thumbs', 'previews', 'embedded', 'full'):
        shutil.rmtree(Path(root) / name, ignore_errors=True)


def directory_size(root):
    total = 0
    for dirpath, _, files in os.walk(root):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total
