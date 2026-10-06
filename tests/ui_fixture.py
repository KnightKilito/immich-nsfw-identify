"""Synthetic-only UI fixture. Run separately; never mounts the production state."""
import io
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw

app=FastAPI()
app.mount('/static',StaticFiles(directory='/app/static'),name='static')
assets=[{'id':f'00000000-0000-4000-8000-{i:012d}','name':f'示例色块 {i:02d}.png','score':0.9,'status':'review','reason':None} for i in range(1,51)]
assets[3]['status']='locked'
assets[4]['status']='unsupported'
job={'running':False,'phase':'合成色块测试','processed':0,'skipped':0,'errors':0,'error':None}


@app.get('/')
def home():return FileResponse(Path('/app/static/index.html'))


@app.get('/health')
def health():return {'ok':True}


@app.get('/api/state')
def state():
    totals={'all':len(assets),'candidates':sum(a['status']=='review' for a in assets)}
    return {'connection':{'name':'交互测试','email':'test@example.com','version':'3.3.0-rc.0','pin_ready':True},
            'settings':{'mode':'review','review_threshold':0.7,'auto_threshold':0.95,'scheduled':False,'interval_minutes':15},
            'job':job,'stats':{'review':totals['candidates'],'locked':1,'unsupported':1},'result_totals':totals,
            'model':'合成测试，不读取用户照片','operations':[]}


@app.get('/api/assets')
def results(status:str='candidates',offset:int=0,limit:int=48):
    rows=[a for a in assets if status=='all' or (status=='candidates' and a['status']=='review') or a['status']==status]
    return {'total':len(rows),'items':rows[offset:offset+limit]}


@app.get('/api/preview/{asset_id}')
def preview(asset_id:str):
    color=int(asset_id.rsplit('-',1)[-1])
    image=Image.new('RGB',(320,200),(40+color*3,80+color,140))
    ImageDraw.Draw(image).rectangle((30,30,150,160),fill=(230,190,70))
    buffer=io.BytesIO();image.save(buffer,format='PNG')
    return Response(buffer.getvalue(),media_type='image/png')


@app.post('/test/advance')
def advance():
    i=len(assets)+1
    assets.append({'id':f'00000000-0000-4000-8000-{i:012d}','name':f'新增色块 {i:02d}.png','score':0.9,'status':'review','reason':None})
    job.update(running=True,phase='模拟扫描',processed=job['processed']+1)
    return {'ok':True}


@app.post('/test/finish')
def finish():
    job.update(running=False,phase='模拟扫描完成')
    return {'ok':True}
