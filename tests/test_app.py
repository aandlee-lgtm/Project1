import csv
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from helpers import make_jpeg, fingerprint
import app as app_module
from engine import Library
from store import Store


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.photos = root / 'My Photos'
        make_jpeg(self.photos / 'a.jpg', seed=1, when='2026:05:01 10:00:00', subsec='1')
        make_jpeg(self.photos / 'b.JPG', seed=1, when='2026:05:01 10:00:00', subsec='3', blur=2)
        (self.photos / 'bad.NEF').write_bytes(b'broken')
        self.store = Store(root / 'db.sqlite')
        self.library = Library(self.store, root / 'cache', workers=1)
        self.app = app_module.create_app(self.library, self.store, token='secret')
        self.app.config.update(PORT=5555, EXPORT_DIR=str(root / 'exports'))
        (root / 'exports').mkdir()
        self.exports = root / 'exports'
        self.client = self.app.test_client()
        self.base = 'http://127.0.0.1:5555'
        self.h = {'X-Session': 'secret'}

    def tearDown(self):
        self.library.shutdown()
        self.store.close()
        self.tmp.cleanup()

    def get(self, path, **kw):
        return self.client.get(path, base_url=self.base, headers=self.h, **kw)

    def post(self, path, json):
        return self.client.post(path, base_url=self.base, headers=self.h, json=json)

    def wait(self):
        deadline = time.monotonic() + 30
        while self.get('/api/state').get_json()['running'] and time.monotonic() < deadline:
            time.sleep(.02)

    def test_security(self):
        self.assertEqual(self.client.get('/api/state', base_url=self.base).status_code, 403)
        self.assertEqual(self.client.get('/api/state', base_url=self.base, headers={'X-Session': 'nope'}).status_code, 403)
        self.assertEqual(self.client.get('/', base_url='http://evil.example:5555').status_code, 403)
        self.assertEqual(self.client.get('/', base_url='http://127.0.0.1:9999').status_code, 403)
        page = self.client.get('/', base_url=self.base)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"TOKEN='secret'", page.data)
        self.assertIn('Content-Security-Policy', page.headers)

    def test_workflow(self):
        before = fingerprint(self.photos)
        self.assertEqual(self.post('/api/scan', {'folder': str(self.photos / 'nope')}).status_code, 400)
        self.assertEqual(self.post('/api/scan', {'folder': str(self.photos)}).status_code, 200)
        self.wait()
        payload = self.get('/api/rows').get_json()
        self.assertEqual(len(payload['rows']), 2)
        self.assertEqual([e['name'] for e in payload['errors']], ['bad.NEF'])
        rid = payload['rows'][0]['id']
        for kind in ('thumb', 'preview', 'full'):
            r = self.get(f'/api/{kind}/{rid}')
            self.assertEqual(r.status_code, 200, kind)
            self.assertEqual(r.mimetype, 'image/jpeg')
        # image URLs work with the token as a query parameter (for <img src>)
        self.assertEqual(self.client.get(f'/api/thumb/{rid}?t=secret', base_url=self.base).status_code, 200)
        self.assertEqual(self.get(f'/api/crop/{rid}?roi=0,0,.5,.5').status_code, 200)
        self.assertEqual(self.get(f'/api/crop/{rid}?roi=.9,0,.5,.5').status_code, 400)
        self.assertEqual(self.post('/api/roi', {'id': rid, 'roi': [0, 0, .5, .5]}).status_code, 200)
        self.assertEqual(self.post('/api/roi', {'id': rid, 'roi': [.9, 0, .5, .5]}).status_code, 400)
        self.assertEqual(self.post('/api/mark', {'id': rid, 'decision': 'Keep', 'liked': True}).status_code, 200)
        self.assertEqual(self.post('/api/mark', {'id': rid, 'decision': 'Delete'}).status_code, 400)
        row = next(r for r in self.get('/api/rows').get_json()['rows'] if r['id'] == rid)
        self.assertEqual((row['decision'], row['liked']), ('Keep', True))
        self.assertEqual(self.post('/api/groups', {'gap': 1, 'similarity': 10}).status_code, 200)   # 1.2 client
        self.assertEqual(self.get('/api/prefs').get_json()['likeness'], 79)
        self.assertEqual(self.post('/api/groups', {'gap': 1.5, 'likeness': 75, 'near_identical': 95,
                                                   'near_window': 500}).status_code, 200)
        p = self.get('/api/prefs').get_json()
        self.assertEqual((p['gap'], p['likeness'], p['near_identical'], p['near_window']), (1.5, 75, 95, 120))
        self.assertEqual(self.post('/api/prefs', {'keep': 81}).get_json()['keep'], 81)
        self.assertEqual(self.get('/api/prefs').get_json()['keep'], 81)
        r = self.post('/api/export', {'rows': [['filename', 'decision'], ['a.jpg', 'Keep']]})
        saved = Path(r.get_json()['saved'])
        self.assertEqual(saved.parent, self.exports)
        self.assertEqual(list(csv.reader(saved.open(encoding='utf-8-sig'))), [['filename', 'decision'], ['a.jpg', 'Keep']])
        about = self.get('/api/about').get_json()
        self.assertIn('libraw', about)
        self.assertEqual(self.post('/api/cancel', {}).status_code, 200)
        self.assertEqual(fingerprint(self.photos), before)

    def test_diagnostic_report(self):
        self.post('/api/scan', {'folder': str(self.photos)})
        self.wait()
        r = self.post('/api/diagnostics', {})
        path = Path(r.get_json()['saved'])
        self.assertTrue(path.name.startswith('PhotoSelect-diagnostics-'))
        text = path.read_text()
        for heading in ('## This Mac', '## Last scan', '## Files that could not be analysed', '## Bursts',
                        '## Orientation cross-check', '## Files (first'):
            self.assertIn(heading, text)
        self.assertIn('bad.NEF', text)
        self.assertIn('bursts: 1', text)                      # a.jpg + b.JPG, 0.02 s apart
        self.assertNotIn(str(self.photos.parent), text)       # no absolute paths

    def test_similarity_pref_from_1_2_becomes_likeness(self):
        self.store.db.execute("INSERT OR REPLACE INTO prefs VALUES('similarity', '7')")
        self.assertEqual(self.store.prefs()['likeness'], 85)
        self.store.set_prefs({'likeness': 60})
        self.assertEqual(self.store.prefs()['likeness'], 60)

    def test_best_of_each_series_setting(self):
        self.assertEqual(self.get('/api/prefs').get_json()['best_of'], 1)        # 1.9 default: keep the best frame
        self.assertIs(self.get('/api/prefs').get_json()['show_focus'], True)     # 1.10: focus area outlines on
        self.post('/api/prefs', {'best_of': 0})
        self.assertEqual(self.get('/api/prefs').get_json()['best_of'], 0)

    def test_profiles_and_folder_settings_persist(self):
        settings = {'weights': {'sharpness': 10, 'focus': 70, 'composition': 10, 'exposure': 10}, 'keep': 80, 'consider': 40}
        self.post('/api/prefs', {'profiles': {'Sailing': settings}, 'folder_settings': {'/x': settings},
                                 'undo_settings': settings})
        p = Store(self.store.path).prefs()
        self.assertEqual((p['profiles']['Sailing'], p['folder_settings']['/x'], p['undo_settings']), (settings,) * 3)

    def test_lightroom_selections_and_plugin_install(self):
        home = Path(self.tmp.name) / 'home'
        modules = Path(self.tmp.name) / 'Adobe' / 'Lightroom' / 'Modules'
        with patch.dict(os.environ, {'PHOTOSELECT_HOME': str(home), 'PHOTOSELECT_LR_MODULES': str(modules)}):
            before = fingerprint(self.photos)
            self.assertEqual(self.post('/api/lightroom', {'folder': str(self.photos), 'rows': []}).status_code, 400)
            self.assertEqual(self.post('/api/lightroom', {'rows': [{'path': 'x', 'name': 'x', 'rating': 9}]}).status_code, 400)
            rows = [{'path': str(self.photos / 'a.jpg'), 'name': 'a.jpg', 'capture': '2026-05-01 10:00:00', 'rating': 5,
                     'keywords': ['Keep', 'Liked', 'Burst 001'], 'decision': 'Keep', 'suggestion': 'Consider'},
                    {'path': str(self.photos / 'b.JPG'), 'name': 'b.JPG', 'capture': '', 'rating': 1,
                     'keywords': ['Drop'], 'decision': '', 'suggestion': 'Drop'}]
            r = self.post('/api/lightroom', {'folder': str(self.photos), 'rows': rows}).get_json()
            self.assertEqual((r['count'], r['plugin_installed']), (2, False))
            saved = Path(r['saved'])
            self.assertEqual(saved.parent, home / 'support' / 'Lightroom')
            lines = saved.read_text(encoding='utf-8').splitlines()
            self.assertTrue(lines[0].startswith('# PhotoSelect selections\t1\t'))
            self.assertEqual(lines[1], 'path\tname\tcapture\trating\tkeywords\tdecision\tsuggestion')
            self.assertEqual(lines[2].split('\t')[1:], ['a.jpg', '2026-05-01 10:00:00', '5', 'Keep|Liked|Burst 001', 'Keep', 'Consider'])
            self.assertEqual(fingerprint(self.photos), before, 'nothing is written into the photo folder')

            r = self.post('/api/lightroom/install', {}).get_json()
            plugin = modules / 'PhotoSelect.lrplugin'
            self.assertEqual(Path(r['installed']), plugin)
            self.assertEqual(sorted(p.name for p in plugin.iterdir()),
                             ['ApplySelections.lua', 'Config.lua', 'Info.lua', 'Init.lua', 'LightroomOps.lua',
                              'SelectionsCore.lua', 'Shutdown.lua'])
            self.assertIn(str(home / 'support' / 'Lightroom'), (plugin / 'Config.lua').read_text())
            self.assertTrue(self.post('/api/lightroom', {'folder': '', 'rows': rows}).get_json()['plugin_installed'])
            self.assertEqual(self.post('/api/lightroom/install', {}).status_code, 200)   # reinstall replaces

    def test_open_in_lightroom(self):
        home = Path(self.tmp.name) / 'home'
        fake_app = Path(self.tmp.name) / 'Adobe Lightroom Classic.app'
        handed = []
        self.app.config['OPEN_IN_LIGHTROOM'] = lambda app_path, paths: handed.append((app_path, list(paths)))
        rows = [{'path': str(self.photos / 'a.jpg'), 'name': 'a.jpg', 'capture': '2026-05-01 10:00:00', 'rating': 3,
                 'keywords': ['Keep'], 'decision': '', 'suggestion': 'Keep'},
                {'path': str(self.photos / 'b.JPG'), 'name': 'b.JPG', 'capture': '2026-05-01 10:00:00', 'rating': 1,
                 'keywords': ['Drop'], 'decision': '', 'suggestion': 'Drop'}]
        pending = home / 'support' / 'Lightroom' / 'pending.import'
        with patch.dict(os.environ, {'PHOTOSELECT_HOME': str(home), 'PHOTOSELECT_LR_APP': str(fake_app),
                                     'PHOTOSELECT_LR_MODULES': str(Path(self.tmp.name) / 'Modules')}):
            status = self.get('/api/lightroom/status').get_json()
            self.assertEqual((status['plugin_installed'], status['lightroom']), (False, ''))
            # Lightroom not installed: explained, selections still saved, nothing handed over
            r = self.post('/api/lightroom', {'folder': str(self.photos), 'rows': rows, 'open': [rows[0]['path']]})
            self.assertEqual((r.status_code, r.get_json()['lightroom_missing']), (200, True))
            self.assertIn('not found on this Mac', r.get_json()['error'])
            self.assertTrue(Path(r.get_json()['saved']).exists())
            self.assertEqual(handed, [])
            fake_app.mkdir()
            self.assertEqual(self.get('/api/lightroom/status').get_json()['lightroom'], str(fake_app))
            # only the chosen group (Keep) is handed over; the automatic rating covers just those
            r = self.post('/api/lightroom', {'folder': str(self.photos), 'rows': rows, 'open': [rows[0]['path']],
                                             'auto_apply': True}).get_json()
            self.assertEqual((r['opened'], r['count']), (1, 2))
            self.assertEqual(handed, [(str(fake_app), [rows[0]['path']])])
            lines = pending.read_text().splitlines()
            self.assertEqual((len(lines), lines[2].split('\t')[1]), (3, 'a.jpg'))
            # without automatic rating, an older request is withdrawn
            self.post('/api/lightroom', {'folder': str(self.photos), 'rows': rows, 'open': [rows[1]['path']]})
            self.assertFalse(pending.exists())
            # paths that were not part of the selections, or no longer exist, are never handed over
            r = self.post('/api/lightroom', {'folder': str(self.photos), 'rows': rows, 'open': ['/etc/passwd']})
            self.assertEqual(r.status_code, 400)
            with patch.object(app_module, 'OPEN_IN_LIGHTROOM_MAX', 1):
                r = self.post('/api/lightroom', {'folder': str(self.photos), 'rows': rows, 'open': [x['path'] for x in rows]})
                self.assertIn('more than PhotoSelect hands to Lightroom', r.get_json()['error'])
            self.assertEqual(len(handed), 2)

    def test_plugin_status_reported_from_lightroom(self):
        home = Path(self.tmp.name) / 'home'
        modules = Path(self.tmp.name) / 'Modules'
        with patch.dict(os.environ, {'PHOTOSELECT_HOME': str(home), 'PHOTOSELECT_LR_MODULES': str(modules),
                                     'PHOTOSELECT_LR_APP': ''}):
            s = self.get('/api/lightroom/status').get_json()
            self.assertEqual((s['plugin_installed'], s['plugin_running'], s['bundled_version']), (False, False, '1.8.0'))
            self.post('/api/lightroom/install', {})
            folder = home / 'support' / 'Lightroom'
            (folder / 'plugin-status.txt').write_text(
                f'version\t1.4.0\nstarted\t{time.time() - 60:.0f}\nchecked\t{time.time() - 5:.0f}\n'
                f'applied_at\t{time.time() - 30:.0f}\napplied_count\t27\nwaiting\t3\n')
            s = self.get('/api/lightroom/status').get_json()
            self.assertEqual((s['installed_version'], s['plugin_running'], s['running_version'], s['last_applied_count'],
                              s['waiting']), ('1.8.0', True, '1.4.0', 27, 3))
            (folder / 'plugin-status.txt').write_text(
                f'version\t1.8.0\nchecked\t{time.time() - 5:.0f}\nlast_search\tfile names (2): 2 photos\n'
                f'last_error\tsearch by capture date: unsupported\nerror_at\t{time.time() - 60:.0f}\n')
            s = self.get('/api/lightroom/status').get_json()
            self.assertEqual((s['last_search'], s['last_error']), ('file names (2): 2 photos', 'search by capture date: unsupported'))
            self.assertGreater(s['error_at'], 0)
            (folder / 'plugin-status.txt').write_text(f'version\t1.5.0\nchecked\t{time.time() - 600:.0f}\n')
            self.assertFalse(self.get('/api/lightroom/status').get_json()['plugin_running'])   # Lightroom closed

    def test_star_changes_in_lightroom_flow_back(self):
        home = Path(self.tmp.name) / 'home'
        with patch.dict(os.environ, {'PHOTOSELECT_HOME': str(home)}):
            self.assertEqual(self.post('/api/lightroom/sync', {}).get_json()['changed'], 0)    # nothing reported
            self.post('/api/scan', {'folder': str(self.photos)})
            self.wait()
            # the paths PhotoSelect sent to Lightroom (resolved: /var → /private/var on macOS)
            paths = {x['name']: x['path'] for x in self.get('/api/rows').get_json()['rows']}
            a, b = paths['a.jpg'], paths['b.JPG']
            folder = home / 'support' / 'Lightroom'
            folder.mkdir(parents=True)
            # written by the plug-in: time, stars before, stars now, PhotoSelect path
            (folder / 'lightroom-changes.tsv').write_text(
                f'1\t1\t3\t{a}\n2\t3\t5\t{b}\n3\t5\t4\t{b}\n4\t2\t0\t/elsewhere/c.NEF\nnot a change\n')
            version = self.get('/api/state').get_json()['version']
            r = self.post('/api/lightroom/sync', {}).get_json()
            self.assertEqual(r['changed'], 3)
            self.assertEqual(r['summary'], 'From Lightroom: 1 Drop → Keep')   # b: Keep → Liked → Keep (no change)
            self.assertFalse((folder / 'lightroom-changes.tsv').exists())        # each change handled once
            rows = {x['name']: x for x in self.get('/api/rows').get_json()['rows']}
            self.assertEqual((rows['a.jpg']['decision'], rows['a.jpg']['liked']), ('Keep', False))
            self.assertEqual((rows['b.JPG']['decision'], rows['b.JPG']['liked']), ('Keep', False))
            self.assertGreater(self.get('/api/state').get_json()['version'], version)
            (folder / 'lightroom-changes.tsv').write_text(f'5\t3\t1\t{a}\n6\t3\t5\t{b}\n')
            self.assertEqual(self.post('/api/lightroom/sync', {}).get_json()['summary'],
                             'From Lightroom: 1 Keep → Drop, 1 Keep → Liked')
            rows = {x['name']: x for x in self.get('/api/rows').get_json()['rows']}
            self.assertEqual((rows['a.jpg']['decision'], rows['b.JPG']['liked']), ('Drop', True))

    def test_export_never_overwrites_an_original(self):
        self.post('/api/scan', {'folder': str(self.photos)})
        self.wait()
        self.app.config.update(EXPORT_DIR=None, SAVE_FILE=lambda name: str(self.photos / 'a.jpg'))
        r = self.post('/api/export', {'rows': [['x']]})
        self.assertEqual(r.status_code, 400)


if __name__ == '__main__':
    unittest.main()
