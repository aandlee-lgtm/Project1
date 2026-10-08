import numpy as np
from PIL import Image

def metrics(image, roi=None):
    image=image.convert('RGB'); image.thumbnail((1600,1600))
    rgb=np.asarray(image,dtype=np.float32)/255
    gray=rgb @ np.array([.299,.587,.114],dtype=np.float32)
    def detail(g):
        if min(g.shape)<8: return 0.
        lap=4*g[1:-1,1:-1]-g[:-2,1:-1]-g[2:,1:-1]-g[1:-1,:-2]-g[1:-1,2:]
        # Local contrast normalisation limits exposure dependence, but noise still affects this cue.
        return float(np.var(lap)/(np.var(g)+.01))
    h,w=gray.shape
    if roi:
        x,y,rw,rh=roi
        crop=gray[int(y*h):max(int((y+rh)*h),int(y*h)+8),int(x*w):max(int((x+rw)*w),int(x*w)+8)]
    else: crop=gray[h//4:3*h//4,w//4:3*w//4]
    gy,gx=np.gradient(gray); energy=np.hypot(gx,gy)
    total=float(energy.sum())+1e-8
    yy,xx=np.mgrid[0:h,0:w]
    cx=float((energy*xx).sum()/total)/w; cy=float((energy*yy).sum()/total)/h
    distance=min(np.hypot(cx-a,cy-b) for a in (1/3,2/3) for b in (1/3,2/3))
    framing=float(energy[:max(1,h//20)].sum()+energy[-max(1,h//20):].sum()+energy[:,:max(1,w//20)].sum()+energy[:,-max(1,w//20):].sum())/total
    composition=float(np.clip(100-distance*130-framing*60,0,100))
    clipping=float(((gray<.015)|(gray>.985)).mean())
    small=np.asarray(image.resize((9,8)).convert('L'))
    return {'sharpness':round(detail(gray),5),'focus':round(detail(crop),5),'composition':round(composition,1),'exposure':round(100*(1-clipping),1),'hash':(small[:,1:]>small[:,:-1]).flatten().astype(int).tolist(),'colour':rgb.mean(axis=(0,1)).tolist(),'centre':[cx,cy]}

def normalise(rows):
    for key in ('sharpness','focus'):
        values=[r['raw'][key] for r in rows]
        if not values: continue
        lo,hi=np.percentile(values,[10,90])
        for r in rows:
            r['scores'][key]=round(float(np.clip(50 if hi-lo<1e-8 else 15+80*(r['raw'][key]-lo)/(hi-lo),0,100)),1)
    for r in rows:
        for key in ('composition','exposure'): r['scores'][key]=r['raw'][key]

def group_bursts(rows,gap=2,similarity=14):
    ordered=sorted(rows,key=lambda r:(r['timestamp'] if r['timestamp'] is not None else float('inf'),r['name']))
    group=0; previous=None; anchor=None
    for row in ordered:
        similar=False
        if previous and row['timestamp'] is not None and previous['timestamp'] is not None:
            dt=row['timestamp']-previous['timestamp']
            distance=sum(a!=b for a,b in zip(row['raw']['hash'],anchor['raw']['hash']))
            colour=np.linalg.norm(np.array(row['raw']['colour'])-anchor['raw']['colour'])
            similar=0<=dt<=gap and distance<=similarity and colour<.18
        if not similar: group+=1; anchor=row
        row['group']=group; previous=row
    return rows
