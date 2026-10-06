import os
from contextlib import contextmanager

import httpx


class ImmichError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class Immich:
    def __init__(self, api_key=None, token=None, transport=None):
        self.base = os.getenv('IMMICH_API_URL', 'http://host.docker.internal:2283/api').rstrip('/')
        headers = {'x-api-key': api_key} if api_key else {}
        if token:
            headers = {'Authorization': f'Bearer {token}'}
        self.http = httpx.Client(base_url=self.base+'/', headers=headers, timeout=httpx.Timeout(40,connect=10), transport=transport, follow_redirects=False)

    def close(self):
        self.http.close()

    def request(self, method, path, **kwargs):
        try:
            response = self.http.request(method, path.lstrip('/'), **kwargs)
        except httpx.HTTPError:
            raise ImmichError('Immich 请求超时或连接失败；请检查 IMMICH_API_URL 和 Immich 服务') from None
        if response.is_error or response.is_redirect:
            hints = {401:'API Key 或登录凭据无效',403:'权限不足，或锁定文件夹尚未验证 PIN',404:'照片/相册不存在或不可访问',400:'请求被拒绝，请检查版本、PIN 和资产状态'}
            raise ImmichError(f'Immich {response.status_code}：{hints.get(response.status_code,"服务错误，请在 Immich 查看日志")}', response.status_code)
        return response

    def json(self, method, path, **kwargs):
        return self.request(method,path,**kwargs).json()

    def user(self):
        return self.json('GET','users/me')

    def version(self):
        v=self.json('GET','server/version')
        return f"{v['major']}.{v['minor']}.{v['patch']}" + (f"-rc.{v['prerelease']}" if v.get('prerelease') is not None else '')

    def search(self, cursor=None, after=None):
        filters={'visibility':{'in':['timeline','archive']},'trashedAt':{'eq':None}}
        if after:
            filters['createdAt']={'gte':after}
        body={'filter':filters,'size':100,'orderBy':{'field':'fileCreatedAt','direction':'desc'},'withExif':False,'withPeople':False,'withStacked':True}
        if cursor:
            body['cursor']=cursor
        return self.json('POST','search/metadata',json=body)['assets']

    def asset(self, asset_id):
        return self.json('GET',f'assets/{asset_id}')

    def preview(self, asset_id):
        # Fetch only a generated preview; no original files or credentials are sent externally.
        with self.http.stream('GET',f'assets/{asset_id}/thumbnail',params={'size':'preview'}) as r:
            if r.status_code != 200:
                raise ImmichError(f'预览图读取失败 ({r.status_code})，请检查 asset.view 权限和缩略图任务',r.status_code)
            data=bytearray()
            for chunk in r.iter_bytes():
                data.extend(chunk)
                if len(data)>20*1024*1024:
                    raise ImmichError('预览图超过 20 MB 限制')
            return bytes(data),r.headers.get('content-type','image/jpeg')

    def albums(self, asset_id=None):
        return self.json('GET','albums',params={'assetId':asset_id} if asset_id else {})

    def visibility(self, ids, visibility):
        self.request('PUT','assets',json={'ids':ids,'visibility':visibility})

    def add_to_album(self, album_id, asset_id):
        rows=self.json('PUT',f'albums/{album_id}/assets',json={'ids':[asset_id]})
        for row in rows:
            if not row.get('success') and row.get('error') not in ('duplicate','DUPLICATE'):
                raise ImmichError('恢复相册成员失败，请检查相册权限和 asset.share 权限')

    @contextmanager
    def elevated(self, email, password, pin, expected_user):
        token=None
        client=None
        try:
            # A separate session, never persist credentials, PIN or session token.
            anonymous=Immich()
            try:
                login=anonymous.json('POST','auth/login',json={'email':email,'password':password})
            finally:
                anonymous.close()
            token=login['accessToken']
            client=Immich(token=token)
            if client.user()['id']!=expected_user:
                raise ImmichError('恢复账号必须和扫描账号一致')
            client.request('POST','auth/session/unlock',json={'pinCode':pin})
            yield client
        finally:
            if client:
                for path in ['auth/session/lock','auth/logout']:
                    try:
                        client.request('POST',path)
                    except ImmichError:
                        pass
                client.close()
