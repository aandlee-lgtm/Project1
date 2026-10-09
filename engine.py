"""Folder scanning and analysis away from the UI.

A scan runs in three phases on a coordinator thread:

1. listing   – walk the folder; restore any still-valid cached analysis immediately.
2. previews  – extract embedded camera previews from RAW files for fast thumbnails
               (labelled "embedded preview", never scored).
3. analysing – full decode + metrics on a bounded thread pool. rawpy/LibRaw, NumPy and
               Pillow release the GIL during heavy work, so threads give real parallelism
               without child processes that could outlive the app.

Everything is keyed by file identity (path, size, mtime) so rescans reuse earlier work, and
a single failing file is recorded as an error without stopping the scan.
"""
import io
import logging
import os
import threading
import time
import traceback
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path

from PIL import Image

import analysis
import raw_io
from store import file_key, path_id, clear_cache_files, directory_size

log = logging.getLogger('photoselect.engine')

THUMB_EDGE = 512
METRIC_KEYS = ('sharpness', 'focus', 'focus_default', 'composition', 'exposure', 'clip_low', 'clip_high', 'noise')


def default_workers():
    cpus = os.cpu_count() or 2
    try:
        ram_gb = os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE') / 2 ** 30
    except (ValueError, OSError, AttributeError):
        ram_gb = 8
    # A 45 MP RAW needs roughly 0.5 GB while being demosaiced; keep a generous margin.
    return max(1, min(4, cpus // 2, int(ram_gb // 4)))


class LRU:
    def __init__(self, size):
        self.size, self.items, self.lock = size, OrderedDict(), threading.Lock()

    def get(self, key):
        with self.lock:
            if key in self.items:
                self.items.move_to_end(key)
                return self.items[key]
        return None

    def put(self, key, value):
        with self.lock:
            self.items[key] = value
            self.items.move_to_end(key)
            while len(self.items) > self.size:
                self.items.popitem(last=False)

    def clear(self):
        with self.lock:
            self.items.clear()


def _save_jpeg(image, path, quality=88):
    tmp = path.with_suffix('.tmp')
    image.save(tmp, format='JPEG', quality=quality)
    os.replace(tmp, path)


def list_files(folder, recursive, cancel):
    files, errors = [], []

    def onerror(error):
        where = getattr(error, 'filename', '') or str(folder)
        if isinstance(error, PermissionError):
            message = ('Permission denied. Choose this folder with "Choose folder" so macOS can grant access, or allow '
                       'PhotoSelect in System Settings → Privacy & Security → Files and Folders.')
        else:
            message = f'Could not read folder: {error.strerror or error}'
        errors.append({'name': os.path.relpath(where, folder) if where != str(folder) else Path(where).name,
                       'path': where, 'error': message})

    for root, dirs, names in os.walk(folder, onerror=onerror):
        if cancel.is_set():
            break
        dirs[:] = sorted(d for d in dirs if not raw_io.is_hidden(d)) if recursive else []
        for name in names:
            if raw_io.is_hidden(name) or Path(name).suffix.lower() not in raw_io.FORMATS:
                continue
            files.append(Path(root) / name)
    files.sort(key=lambda p: str(p.relative_to(folder)).lower())
    return files, errors


class Library:
    def __init__(self, store, cache_root, workers=None):
        self.store = store
        self.cache = Path(cache_root)
        for name in ('thumbs', 'previews', 'embedded'):
            (self.cache / name).mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.rows, self.by_id, self.errors = [], {}, []
        self.status = {'phase': 'idle', 'running': False, 'done': 0, 'total': 0, 'previews': 0, 'cached': 0,
                       'folder': '', 'recursive': False, 'started': None, 'finished': None, 'elapsed': None}
        self.version = 0
        self.dirty = False
        self.cancel_event = threading.Event()
        self.workers = workers or default_workers()
        self.pool = ThreadPoolExecutor(self.workers, thread_name_prefix='analyse')
        self.side_pool = ThreadPoolExecutor(2, thread_name_prefix='inspect')
        self.full_images = LRU(2)
        self.full_jpegs = LRU(3)
        self.full_lock = threading.Semaphore(2)
        self.closed = False

    # ------------------------------------------------------------------ helpers
    def _bump(self):
        self.version += 1
        self.dirty = True

    def _error(self, row_or_path, message, folder=None):
        path = row_or_path['path'] if isinstance(row_or_path, dict) else str(row_or_path)
        name = row_or_path['name'] if isinstance(row_or_path, dict) else Path(path).name
        with self.lock:
            self.errors.append({'name': name, 'path': path, 'error': message})
            if isinstance(row_or_path, dict):
                row_or_path['status'] = 'error'
                row_or_path['error'] = message
            self._bump()

    def thumb_path(self, row):
        if row['status'] == 'analysed':
            return self.cache / 'thumbs' / f"{row['key']}.jpg"
        if row['status'] == 'preview':
            return self.cache / 'embedded' / f"{row['key']}_t.jpg"
        return None

    def preview_path(self, row):
        if row['status'] == 'analysed':
            return self.cache / 'previews' / f"{row['key']}.jpg"
        if row['status'] == 'preview':
            return self.cache / 'embedded' / f"{row['key']}.jpg"
        return None

    def _apply_marks(self, row, mark):
        roi = mark.get('roi') if mark else None
        row['roi'] = roi if analysis.valid_region(roi) else None
        row['roi_state'] = None
        if row['raw'] is None:
            return
        row['raw']['focus'] = row['raw']['focus_default']
        if row['roi']:
            if mark.get('roi_key') == row['key'] and mark.get('roi_focus') is not None:
                row['raw']['focus'] = mark['roi_focus']
                row['roi_state'] = 'full'
            else:
                row['roi_state'] = 'pending'

    # ------------------------------------------------------------------ scanning
    def start(self, folder, recursive):
        folder = Path(folder).expanduser()
        with self.lock:
            if self.status['running']:
                raise RuntimeError('A scan is already running. Cancel it first.')
            self.cancel_event = threading.Event()
            self.rows, self.by_id, self.errors = [], {}, []
            self.full_images.clear()
            self.full_jpegs.clear()
            self.status.update(phase='listing', running=True, done=0, total=0, previews=0, cached=0,
                               folder=str(folder), recursive=bool(recursive), started=time.time(), finished=None,
                               elapsed=None)
            self._bump()
        threading.Thread(target=self._scan, args=(folder, bool(recursive), self.cancel_event),
                         name='scan', daemon=True).start()

    def cancel(self):
        with self.lock:
            if self.status['running']:
                self.cancel_event.set()
                self.status['phase'] = 'cancelling'
                self._bump()

    def _scan(self, folder, recursive, cancel):
        try:
            files, list_errors = list_files(folder, recursive, cancel)
            marks = self.store.marks()
            rows = []
            for path in files:
                if cancel.is_set():
                    break
                try:
                    stat = path.stat()
                except OSError as error:
                    self._error(path, f'Could not read file information: {error.strerror or error}')
                    continue
                key = file_key(path, stat, analysis.ANALYSIS_VERSION)
                row = {'id': path_id(path), 'name': str(path.relative_to(folder)), 'path': str(path),
                       'format': raw_io.format_name(path), 'is_raw': raw_io.is_raw(path), 'key': key,
                       'status': 'pending', 'source': None, 'timestamp': None, 'camera': None, 'size': None,
                       'raw': None, 'scores': {}, 'group': 0, 'roi': None, 'roi_state': None, 'noise_flag': False}
                cached = self.store.get_analysis(key)
                if cached and (self.cache / 'thumbs' / f'{key}.jpg').exists() and \
                        (self.cache / 'previews' / f'{key}.jpg').exists():
                    self._fill(row, cached, 'cache')
                self._apply_marks(row, marks.get(str(path)))
                rows.append(row)
            with self.lock:
                self.errors.extend(list_errors)
                self.rows = rows
                self.by_id = {r['id']: r for r in rows}
                cached = sum(r['status'] == 'analysed' for r in rows)
                self.status.update(total=len(rows), done=cached, cached=cached, phase='previews')
                self._bump()

            pending = [r for r in rows if r['status'] == 'pending']
            self._run([r for r in pending if r['is_raw']], self._embedded, cancel, 'previews')
            with self.lock:
                if not cancel.is_set():
                    self.status['phase'] = 'analysing'
                    self._bump()
            self._run(pending, self._analyse_row, cancel, 'done')
            # Rows that were already analysed but have a region not yet measured at full resolution.
            for row in rows:
                if not cancel.is_set() and row['status'] == 'analysed' and row['roi_state'] == 'pending':
                    self._measure_roi(row)
        except Exception as error:  # pragma: no cover - defensive
            log.exception('scan failed')
            self._error(folder, f'The scan stopped unexpectedly: {error}')
        finally:
            with self.lock:
                self.status.update(running=False, finished=time.time(),
                                   phase='cancelled' if cancel.is_set() else 'complete')
                self.status['elapsed'] = round(self.status['finished'] - (self.status['started'] or 0), 2)
                self._bump()

    def _run(self, rows, fn, cancel, counter):
        """Run fn over rows with at most 2 x workers tasks in flight (bounds memory)."""
        queue = list(rows)
        running = set()
        while (queue or running) and not self.closed:
            while queue and len(running) < self.workers * 2 and not cancel.is_set():
                running.add(self.pool.submit(fn, queue.pop(0), cancel))
            if cancel.is_set():
                queue.clear()
                for f in running:
                    f.cancel()
            if not running:
                break
            finished, running = wait(running, timeout=0.5, return_when=FIRST_COMPLETED)
            with self.lock:
                for f in finished:
                    if not f.cancelled():
                        self.status[counter] += 1
                self._bump()

    def _fill(self, row, data, source):
        row['raw'] = {k: data[k] for k in METRIC_KEYS if k in data}
        row['raw']['hash'] = data['hash']
        row['raw']['colour'] = data['colour']
        row['raw']['look'] = data.get('look')
        row['size'] = data.get('size')
        row['timestamp'] = data.get('timestamp')
        row['camera'] = data.get('camera')
        row['status'] = 'analysed'
        row['source'] = source

    def _embedded(self, row, cancel):
        if cancel.is_set() or row['status'] != 'pending':
            return
        im = raw_io.embedded_preview(row['path'])
        if im is None:
            return
        im.thumbnail((analysis.PREVIEW_EDGE, analysis.PREVIEW_EDGE))
        _save_jpeg(im, self.cache / 'embedded' / f"{row['key']}.jpg", 85)
        im.thumbnail((THUMB_EDGE, THUMB_EDGE))
        _save_jpeg(im, self.cache / 'embedded' / f"{row['key']}_t.jpg", 82)
        with self.lock:
            if row['status'] == 'pending':
                row['status'] = 'preview'
                row['source'] = 'embedded'

    def _analyse_row(self, row, cancel):
        if cancel.is_set() or self.closed:
            return
        path = Path(row['path'])
        try:
            full = raw_io.decode(path)
            region = row['roi']
            preview, m = analysis.analyse(full, region)
            data = {k: v for k, v in m.items() if k != 'focus'}
            data['focus'] = m['focus_default']
            data.update(size=list(full.size), timestamp=raw_io.capture_time(path), camera=raw_io.camera_model(path),
                        decoder=('LibRaw ' + raw_io.libraw_version()) if row['is_raw'] else 'Pillow')
            thumb = preview.copy()
            thumb.thumbnail((THUMB_EDGE, THUMB_EDGE))
            _save_jpeg(preview, self.cache / 'previews' / f"{row['key']}.jpg", 88)
            _save_jpeg(thumb, self.cache / 'thumbs' / f"{row['key']}.jpg", 82)
            for old in self.store.put_analysis(row['key'], path, data):
                self._remove_cached(old)
            if region:
                self.store.set_mark(path, roi_key=row['key'], roi_focus=m['focus'])
            del full
        except raw_io.DecodeError as error:
            self._error(row, str(error))
            return
        except MemoryError:
            self._error(row, 'Not enough memory to decode this file. Close other apps or reduce the number of files.')
            return
        except Exception as error:
            log.error('analysis failed for %s\n%s', path, traceback.format_exc())
            self._error(row, f'Unexpected analysis error: {error}')
            return
        with self.lock:
            self._fill(row, data, 'decoded')
            row['raw']['focus'] = m['focus'] if region else m['focus_default']
            row['roi_state'] = 'full' if region else None
            self._bump()

    def _remove_cached(self, key):
        for name in (f'thumbs/{key}.jpg', f'previews/{key}.jpg', f'embedded/{key}.jpg', f'embedded/{key}_t.jpg'):
            try:
                (self.cache / name).unlink()
            except OSError:
                pass

    # ------------------------------------------------------------------ results
    def _recompute(self):
        if not self.dirty:
            return
        prefs = self.store.prefs()
        done = [r for r in self.rows if r['status'] == 'analysed']
        analysis.normalise(done)
        analysis.group_bursts(done, max(.1, min(10, float(prefs['gap']))), max(0, min(64, int(prefs['similarity']))))
        top = max((r['group'] for r in done), default=0)
        for r in self.rows:
            if r['status'] != 'analysed':
                top += 1
                r['group'] = top
                r['scores'] = {}
        self.dirty = False

    def snapshot(self):
        with self.lock:
            self._recompute()
            return dict(self.status, version=self.version, errors=len(self.errors), workers=self.workers,
                        libraw=raw_io.libraw_version())

    def payload(self):
        with self.lock:
            self._recompute()
            marks = self.store.marks()
            rows = []
            for r in self.rows:
                if r['status'] == 'error':
                    continue
                mark = marks.get(r['path'], {})
                rows.append({
                    'id': r['id'], 'name': r['name'], 'path': r['path'], 'format': r['format'], 'is_raw': r['is_raw'],
                    'status': r['status'], 'source': r['source'], 'timestamp': r['timestamp'], 'camera': r['camera'],
                    'size': r['size'], 'scores': r['scores'], 'group': r['group'], 'roi': r['roi'],
                    'roi_state': r['roi_state'], 'noise_flag': r['noise_flag'],
                    'metrics': {k: r['raw'][k] for k in METRIC_KEYS if r['raw'] and k in r['raw']},
                    'decision': mark.get('decision'), 'liked': bool(mark.get('liked')),
                })
            return {'version': self.version, 'rows': rows, 'errors': list(self.errors)}

    def regroup(self, gap, similarity):
        self.store.set_prefs({'gap': max(.1, min(10, float(gap))), 'similarity': max(0, min(64, int(similarity)))})
        with self.lock:
            self._bump()

    def row(self, id):
        with self.lock:
            return self.by_id.get(id)

    # ------------------------------------------------------------------ inspection
    def full_image(self, row):
        im = self.full_images.get(row['key'])
        if im is None:
            with self.full_lock:
                im = self.full_images.get(row['key'])
                if im is None:
                    im = raw_io.decode(row['path'])
                    self.full_images.put(row['key'], im)
        return im

    def full_jpeg(self, row):
        data = self.full_jpegs.get(row['key'])
        if data is None:
            out = io.BytesIO()
            self.full_image(row).save(out, format='JPEG', quality=93, subsampling=0)
            data = out.getvalue()
            self.full_jpegs.put(row['key'], data)
        return data

    def crop_jpeg(self, row, region):
        im = self.full_image(row)
        x, y, w, h = region
        crop = im.crop((int(x * im.width), int(y * im.height), int((x + w) * im.width), int((y + h) * im.height)))
        if max(crop.size) > 4000:
            crop.thumbnail((4000, 4000))
        out = io.BytesIO()
        crop.save(out, format='JPEG', quality=93, subsampling=0)
        return out.getvalue()

    def set_roi(self, id, region):
        row = self.row(id)
        if row is None:
            raise KeyError(id)
        if region is not None and not analysis.valid_region(region):
            raise ValueError('Draw a larger region inside the photo.')
        self.store.set_mark(row['path'], roi=region, roi_key=None, roi_focus=None)
        with self.lock:
            row['roi'] = region
            if row['raw'] is not None:
                row['raw']['focus'] = row['raw']['focus_default']
            row['roi_state'] = 'measuring' if region and row['status'] == 'analysed' else (
                'pending' if region else None)
            self._bump()
        if region and row['status'] == 'analysed':
            self.side_pool.submit(self._measure_roi, row)

    def _measure_roi(self, row):
        region = row['roi']
        try:
            with self.lock:
                row['roi_state'] = 'measuring'
                self._bump()
            value = analysis.focus_detail(self.full_image(row), region)
        except Exception as error:
            log.warning('region measurement failed: %s', error)
            with self.lock:
                row['roi_state'] = 'error'
                self._bump()
            return
        with self.lock:
            if row['roi'] != region:   # superseded by a newer region
                return
            self.store.set_mark(row['path'], roi_key=row['key'], roi_focus=value)
            row['raw']['focus'] = value
            row['roi_state'] = 'full'
            self._bump()

    # ------------------------------------------------------------------ maintenance
    def clear_cache(self):
        with self.lock:
            if self.status['running']:
                raise RuntimeError('Cancel the running scan before clearing the cache.')
            self.store.clear_analysis()
            clear_cache_files(self.cache)
            for name in ('thumbs', 'previews', 'embedded'):
                (self.cache / name).mkdir(parents=True, exist_ok=True)
            self.rows, self.by_id, self.errors = [], {}, []
            self.status.update(phase='idle', done=0, total=0, previews=0, cached=0)
            self._bump()

    def cache_size(self):
        return directory_size(self.cache)

    def shutdown(self):
        self.closed = True
        self.cancel_event.set()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.side_pool.shutdown(wait=False, cancel_futures=True)
