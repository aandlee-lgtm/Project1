import csv
import tempfile
import time
import unittest
from pathlib import Path

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
        self.assertEqual(self.post('/api/groups', {'gap': 1, 'similarity': 10}).status_code, 200)
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

    def test_export_never_overwrites_an_original(self):
        self.post('/api/scan', {'folder': str(self.photos)})
        self.wait()
        self.app.config.update(EXPORT_DIR=None, SAVE_FILE=lambda name: str(self.photos / 'a.jpg'))
        r = self.post('/api/export', {'rows': [['x']]})
        self.assertEqual(r.status_code, 400)


if __name__ == '__main__':
    unittest.main()
