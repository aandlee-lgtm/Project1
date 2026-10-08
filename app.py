import io,json,secrets,threading,time,webbrowser,tempfile,csv,sys,subprocess
from pathlib import Path
from datetime import datetime
from PIL import Image,ImageOps
from flask import Flask,request,jsonify,send_file,abort
from analysis import metrics,normalise,group_bursts

app=Flask(__name__); TOKEN=secrets.token_urlsafe(32)
CACHE=Path(tempfile.mkdtemp(prefix='photoselect-'))
state={'running':False,'done':0,'total':0,'rows':[],'errors':[],'folder':'','version':'0.3.0'}
lock=threading.RLock()
from raw_io import RAW,FORMATS,decode,format_name
APP_VERSION='0.3.0'

def capture_time(path):
    try:
        import exifread
        with path.open('rb') as f: tags=exifread.process_file(f,details=False,stop_tag='UNDEF')
        date=str(tags.get('EXIF DateTimeOriginal',''))
        sub=str(tags.get('EXIF SubSecTimeOriginal','0'))
        return datetime.strptime(date,'%Y:%m:%d %H:%M:%S').timestamp()+float('0.'+''.join(c for c in sub if c.isdigit()))
    except Exception: return None

@app.before_request
def secure():
    if request.host not in ('127.0.0.1:8765','localhost:8765'): abort(403)
    if request.path.startswith('/api/') and request.headers.get('X-Session')!=TOKEN: abort(403)

@app.get('/')
def home():
    return (Path(__file__).parent/'static/index.html').read_text().replace('__TOKEN__',TOKEN)

@app.post('/api/pick')
def pick():
    try:
        if sys.platform == 'darwin':
            result=subprocess.run(['osascript','-e','try\nPOSIX path of (choose folder with prompt "Choose your photo folder")\non error number -128\nreturn ""\nend try'],capture_output=True,text=True,check=True)
            return jsonify(folder=result.stdout.strip())
        import tkinter as tk
        from tkinter import filedialog
        root=tk.Tk(); root.withdraw(); root.attributes('-topmost',True)
        folder=filedialog.askdirectory(title='Choose your photo folder'); root.destroy()
        return jsonify(folder=folder)
    except Exception: return jsonify(error='Folder chooser unavailable. Paste the full folder path instead.'),400

def scan(folder,recursive):
    try:
        files=sorted(p for p in (folder.rglob('*') if recursive else folder.iterdir()) if p.is_file() and p.suffix.lower() in FORMATS)
        with lock: state['total']=len(files)
        for i,path in enumerate(files):
            try:
                im=decode(path); original=im.size
                im.thumbnail((1600,1600)); raw=metrics(im)
                im.save(CACHE/f'{i}.jpg',quality=92)
                row={'id':str(i),'name':str(path.relative_to(folder)),'path':str(path),'timestamp':capture_time(path),'size':original,'raw':raw,'scores':{},'group':i+1,'roi':None,'format':format_name(path),'decoded_raw':path.suffix.lower() in RAW}
                with lock: state['rows'].append(row)
            except Exception as e:
                with lock: state['errors'].append({'name':path.name,'error':str(e)})
            with lock: state['done']=i+1
        with lock: normalise(state['rows']); group_bursts(state['rows'])
    except Exception as e:
        with lock: state['errors'].append({'name':'Folder','error':str(e)})
    finally:
        with lock: state['running']=False

@app.post('/api/scan')
def start():
    data=request.get_json(); folder=Path(data.get('folder','')).expanduser().resolve()
    if not folder.is_dir(): return jsonify(error='Enter an existing folder path.'),400
    with lock:
        if state['running']: return jsonify(error='A scan is already running.'),409
        state.update(running=True,done=0,total=0,rows=[],errors=[],folder=str(folder))
    threading.Thread(target=scan,args=(folder,bool(data.get('recursive'))),daemon=True).start()
    return jsonify(ok=True)

@app.get('/api/state')
def status():
    with lock: return jsonify(state)

@app.get('/api/image/<id>')
def image(id):
    with lock: row=next((r.copy() for r in state['rows'] if r['id']==id),None)
    if row is None: abort(404)
    if request.args.get('full')=='1':
        im=decode(Path(row['path'])); out=io.BytesIO(); im.save(out,format='JPEG',quality=96); out.seek(0)
        return send_file(out,mimetype='image/jpeg')
    return send_file(CACHE/f'{id}.jpg',mimetype='image/jpeg')

@app.post('/api/roi')
def roi():
    data=request.get_json(); box=data.get('roi')
    if box is not None and (len(box)!=4 or not all(isinstance(v,(int,float)) and 0<=v<=1 for v in box) or box[2]<.02 or box[3]<.02 or box[0]+box[2]>1.001 or box[1]+box[3]>1.001): return jsonify(error='Draw a larger region inside the photo.'),400
    with lock:
        if state['running']: return jsonify(error='Wait for analysis to finish.'),409
        row=next((r for r in state['rows'] if r['id']==data['id']),None)
        if row is None: abort(404)
        with Image.open(CACHE/f"{row['id']}.jpg") as im: row['raw']=metrics(im,box)
        row['roi']=box; normalise(state['rows'])
    return jsonify(ok=True)

@app.post('/api/groups')
def groups():
    data=request.get_json()
    with lock:
        if state['running']: return jsonify(error='Wait for analysis to finish.'),409
        group_bursts(state['rows'],max(.1,min(10,float(data.get('gap',2)))),max(0,min(64,int(data.get('similarity',14)))))
    return jsonify(ok=True)

if __name__=='__main__':
    threading.Timer(1,lambda:webbrowser.open('http://127.0.0.1:8765')).start()
    print('PhotoSelect is running at http://127.0.0.1:8765 — Ctrl+C to stop.')
    app.run(host='127.0.0.1',port=8765,debug=False,threaded=True)
