import json

import httpx
import pytest

from src.immich import Immich


def test_api_search_contract_and_version_zero():
    def handler(request):
        if request.url.path.endswith('/server/version'):
            return httpx.Response(200,json={'major':3,'minor':3,'patch':0,'prerelease':0})
        assert request.headers['x-api-key']=='fake-key'
        body=json.loads(request.content)
        assert body['filter']['trashedAt']=={'eq':None}
        assert body['filter']['createdAt']=={'gte':'2026-10-01T00:00:00+00:00'}
        assert body['orderBy']['field']=='fileCreatedAt'
        assert body['cursor']=='cursor'
        return httpx.Response(200,json={'assets':{'items':[],'nextCursor':None}})
    client=Immich(api_key='fake-key',transport=httpx.MockTransport(handler))
    assert client.version()=='3.3.0-rc.0'
    assert client.search(cursor='cursor',after='2026-10-01T00:00:00+00:00')['items']==[]
    client.close()


def test_error_does_not_echo_key_or_upstream_body():
    def handler(request): return httpx.Response(403,json={'error':'fake-secret-key'})
    client=Immich(api_key='fake-secret-key',transport=httpx.MockTransport(handler))
    try:
        client.user()
    except Exception as error:
        assert 'fake-secret-key' not in str(error)
    else:
        raise AssertionError('expected denial')
    client.close()


def test_panel_blocks_external_host_and_csrf(monkeypatch,tmp_path):
    monkeypatch.setenv('STATE_DIR',str(tmp_path))
    from fastapi.testclient import TestClient
    from src.app import app
    client=TestClient(app,base_url='http://localhost:2983')
    assert client.get('/health').status_code==200
    assert client.get('/health',headers={'host':'evil.example'}).status_code==403
    assert client.get('/api/state',headers={'sec-fetch-site':'cross-site'}).status_code==403
    assert client.post('/api/stop',json={}).status_code==403
    assert client.post('/api/stop',json={},headers={'X-Local-Request':'1','origin':'http://evil.example'}).status_code==403
    assert client.post('/api/stop',json={},headers={'X-Local-Request':'1','origin':'http://localhost:2983'}).status_code==200
    response=client.get('/api/state')
    assert response.headers['cache-control']=='no-store'
    assert 'api_key' not in response.text
    response=client.post('/api/connect',json={'api_key':'a'*513},headers={'X-Local-Request':'1'})
    assert response.status_code==422
    assert 'a'*513 not in response.text


def test_restore_session_uses_pin_and_always_logs_out(monkeypatch):
    requests=[]
    def handler(request):
        path=request.url.path
        requests.append((path,request.headers.get('authorization'),request.content))
        if path.endswith('/auth/login'):
            assert json.loads(request.content)=={'email':'test@example.com','password':'local-password'}
            return httpx.Response(200,json={'accessToken':'temporary-session'})
        assert request.headers['authorization']=='Bearer temporary-session'
        assert 'x-api-key' not in request.headers
        if path.endswith('/users/me'):
            return httpx.Response(200,json={'id':'owner'})
        if path.endswith('/auth/session/unlock'):
            assert json.loads(request.content)=={'pinCode':'123456'}
        return httpx.Response(204)
    original=Immich.__init__
    transport=httpx.MockTransport(handler)
    def init(self,*args,**kwargs):
        kwargs['transport']=transport
        original(self,*args,**kwargs)
    monkeypatch.setattr(Immich,'__init__',init)
    client=Immich(api_key='key')
    with pytest.raises(ValueError):
        with client.elevated('test@example.com','local-password','123456','owner'):
            raise ValueError('simulate interrupted restoration')
    assert [r[0].split('/api/')[-1] for r in requests]==['auth/login','users/me','auth/session/unlock','auth/session/lock','auth/logout']
    client.close()


def test_wrong_restore_user_cannot_unlock_but_session_is_closed(monkeypatch):
    paths=[]
    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith('/auth/login'):
            return httpx.Response(200,json={'accessToken':'temporary-session'})
        if request.url.path.endswith('/users/me'):
            return httpx.Response(200,json={'id':'other'})
        return httpx.Response(204)
    original=Immich.__init__
    def init(self,*args,**kwargs):
        kwargs['transport']=httpx.MockTransport(handler)
        original(self,*args,**kwargs)
    monkeypatch.setattr(Immich,'__init__',init)
    client=Immich(api_key='key')
    with pytest.raises(Exception,match='恢复账号必须'):
        with client.elevated('test@example.com','local-password','123456','owner'):
            raise AssertionError('must not yield')
    assert not any(p.endswith('/unlock') for p in paths)
    assert paths[-1].endswith('/auth/logout')
    client.close()


def test_force_scan_wire_contract_and_favicon(monkeypatch):
    from fastapi.testclient import TestClient
    from src import app as module
    calls=[]
    monkeypatch.setattr(module.engine,'start',lambda limit,incremental,force:calls.append((limit,incremental,force)))
    client=TestClient(module.app,base_url='http://localhost:2983')
    response=client.post('/api/scan',json={'limit':0,'incremental':False,'force':True},headers={'X-Local-Request':'1'})
    assert response.status_code==200 and calls==[(0,False,True)]
    icon=client.get('/favicon.ico')
    assert icon.status_code==200 and icon.headers['content-type']=='image/x-icon'
    assert icon.content[:4]==b'\x00\x00\x01\x00'
