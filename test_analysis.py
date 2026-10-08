import unittest,tempfile,time
from pathlib import Path
import numpy as np
from PIL import Image,ImageFilter
from analysis import metrics,normalise,group_bursts

class AnalysisTests(unittest.TestCase):
    def setUp(self):
        y,x=np.mgrid[:256,:256]
        a=((x//8+y//8)%2*255).astype('uint8')
        self.image=Image.fromarray(a).convert('RGB')
    def test_blur_reduces_detail(self):
        sharp=metrics(self.image); soft=metrics(self.image.filter(ImageFilter.GaussianBlur(3)))
        self.assertGreater(sharp['sharpness'],soft['sharpness']*3)
    def test_region_distinguishes_subject(self):
        im=self.image.copy(); im.paste(Image.new('RGB',(128,256),(125,125,125)),(128,0))
        self.assertGreater(metrics(im,[0,0,.4,1])['focus'],metrics(im,[.6,0,.4,1])['focus'])
    def test_uniform_scores_are_finite(self):
        rows=[{'raw':metrics(Image.new('RGB',(100,100),'gray')),'scores':{}} for _ in range(3)]
        normalise(rows)
        self.assertTrue(all(r['scores']['sharpness']==50 for r in rows))
    def test_grouping_uses_time_and_similarity(self):
        raw=metrics(self.image)
        rows=[{'name':str(i),'timestamp':t,'raw':dict(raw)} for i,t in enumerate([100,100.1,120,None])]
        group_bursts(rows)
        self.assertEqual(rows[0]['group'],rows[1]['group'])
        self.assertNotEqual(rows[1]['group'],rows[2]['group'])
        self.assertNotEqual(rows[2]['group'],rows[3]['group'])
        rows[1]['raw']={**raw,'hash':[1-v for v in raw['hash']]}
        group_bursts(rows)
        self.assertNotEqual(rows[0]['group'],rows[1]['group'])

class AppTests(unittest.TestCase):
    def test_import_preview_region_and_auth(self):
        import app
        client=app.app.test_client(); headers={'X-Session':app.TOKEN}; base='http://127.0.0.1:8765'
        self.assertEqual(client.get('/api/state',base_url=base).status_code,403)
        self.assertEqual(client.get('/',base_url='http://bad.example').status_code,403)
        self.assertEqual(client.get('/',base_url=base).status_code,200)
        with tempfile.TemporaryDirectory() as folder:
            im=Image.fromarray(np.random.default_rng(1).integers(0,255,(256,256,3),dtype='uint8'))
            im.save(Path(folder)/'test.jpg'); (Path(folder)/'bad.nef').write_bytes(b'broken')
            r=client.post('/api/scan',base_url=base,headers=headers,json={'folder':folder})
            self.assertEqual(r.status_code,200)
            deadline=time.monotonic()+20
            while app.state['running'] and time.monotonic()<deadline: time.sleep(.02)
            self.assertFalse(app.state['running'])
            state=client.get('/api/state',base_url=base,headers=headers).get_json()
            self.assertEqual(len(state['rows']),1); self.assertEqual(len(state['errors']),1)
            id=state['rows'][0]['id']
            response=client.get('/api/image/'+id,base_url=base,headers=headers)
            self.assertEqual(response.status_code,200); response.close()
            self.assertEqual(client.get('/api/image/'+id+'?full=1',base_url=base,headers=headers).status_code,200)
            self.assertEqual(client.post('/api/roi',base_url=base,headers=headers,json={'id':id,'roi':[0,0,.5,.5]}).status_code,200)
            self.assertEqual(client.post('/api/roi',base_url=base,headers=headers,json={'id':id,'roi':[.9,0,.5,.5]}).status_code,400)
            self.assertEqual(client.post('/api/groups',base_url=base,headers=headers,json={'gap':1,'similarity':10}).status_code,200)
if __name__=='__main__': unittest.main()
