import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .engine import Engine
from .immich import ImmichError
from .store import Store
from .telemetry import emit, error_fields

store=Store(os.getenv('STATE_DIR','/state'))
engine=Engine(store)


@asynccontextmanager
async def lifespan(app):
    engine.start_scheduler()
    emit('service.started',device='cpu',mode=engine.settings()['mode'],scheduled=engine.settings()['scheduled'])
    yield
    engine.cancel.set()
    engine.shutdown.set()
    emit('service.stopping')


app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)


@app.middleware('http')
async def local_only(request:Request,call_next):
    host=request.headers.get('host','')
    hostname=urlsplit('http://'+host).hostname
    if hostname not in ('127.0.0.1','localhost'):
        return JSONResponse({'detail':'此管理页面只允许从本机访问'},status_code=403)
    if request.headers.get('sec-fetch-site')=='cross-site':
        return JSONResponse({'detail':'不允许外部网站加载本机审核内容'},status_code=403)
    if request.method not in ('GET','HEAD'):
        origin=request.headers.get('origin')
        if request.headers.get('x-local-request')!='1' or (origin and origin!=f'http://{host}'):
            return JSONResponse({'detail':'请求来源验证失败'},status_code=403)
    response=await call_next(request)
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Content-Security-Policy']="default-src 'self'; img-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response


@app.exception_handler(ValueError)
async def invalid(request,exc):
    return JSONResponse({'detail':str(exc)},status_code=400)


@app.exception_handler(ImmichError)
async def upstream_error(request,exc):
    emit('api.upstream_error',level='WARNING',**error_fields(exc))
    return JSONResponse({'detail':str(exc)},status_code=502)


@app.exception_handler(RequestValidationError)
async def validation_error(request,exc):
    # FastAPI's default errors may echo input values, including API keys/passwords.
    return JSONResponse({'detail':'请求参数无效，请检查输入格式'},status_code=422)


@app.get('/health')
def health():
    return {'ok':True}


@app.get('/')
def home():
    return FileResponse(Path('/app/static/index.html'))


@app.get('/favicon.ico')
def favicon():
    return FileResponse(Path('/app/static/favicon.ico'),media_type='image/x-icon')


app.mount('/static',StaticFiles(directory='/app/static'),name='static')


@app.get('/api/state')
def state():
    return engine.snapshot()


class Connection(BaseModel):
    api_key:str=Field(min_length=1,max_length=512)


@app.post('/api/connect')
def connect(body:Connection):
    return engine.connect(body.api_key.strip())


@app.post('/api/settings')
def settings(body:dict):
    return engine.save_settings(body)


class Scan(BaseModel):
    limit:int=Field(default=100,ge=0,le=100000)
    incremental:bool=False
    force:bool=False


@app.post('/api/scan')
def scan(body:Scan):
    engine.start(body.limit,body.incremental,body.force)
    return {'started':True}


@app.post('/api/stop')
def stop():
    engine.cancel.set()
    emit('scan.stop_requested',job_id=engine.job.get('job_id'))
    return {'stopping':True}


@app.get('/api/assets')
def assets(status:str='candidates',offset:int=Query(default=0,ge=0,le=2147483647),limit:int=Query(default=48,ge=1,le=192)):
    if status not in ('candidates','all','locked','keep','error','unsupported','uncertain','review','scored') or offset<0:
        raise ValueError('筛选无效')
    return store.list_assets(status,offset,limit=limit,threshold=engine.settings()['review_threshold'])


@app.get('/api/preview/{asset_id}')
def preview(asset_id:UUID):
    row=store.asset(str(asset_id))
    if not row or row['status'] in ('locked','uncertain','unsupported'):
        raise HTTPException(404,'预览不可用；锁定照片请在 Immich 中验证 PIN 后查看')
    client=engine.client()
    try:
        asset=client.asset(str(asset_id))
        if asset['ownerId']!=store.get_setting('connection')['user_id'] or asset.get('visibility')=='locked':
            raise HTTPException(403,'预览不可用')
        data,mime=client.preview(str(asset_id))
        if mime.lower().split(';')[0] not in ('image/jpeg','image/png','image/webp'):
            raise HTTPException(502,'上游不是图片')
        return Response(data,media_type=mime)
    finally:
        client.close()


class Selection(BaseModel):
    ids:list[UUID]=Field(min_length=1,max_length=192)


@app.post('/api/lock')
def lock(body:Selection):
    return {'results':engine.lock_assets([str(x) for x in body.ids])}


@app.post('/api/keep')
def keep(body:Selection):
    engine.keep([str(x) for x in body.ids])
    return {'ok':True}


class Restore(BaseModel):
    email:str=Field(min_length=1,max_length=256)
    password:str=Field(min_length=1,max_length=1024)
    pin:str=Field(pattern=r'^\d{6}$')


@app.post('/api/restore/{operation_id}')
def restore(operation_id:UUID,body:Restore):
    return engine.restore(str(operation_id),body.email,body.password,body.pin)
