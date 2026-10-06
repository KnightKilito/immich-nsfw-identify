import json
import math
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from .classifier import Classifier, MODEL_FINGERPRINT
from .immich import Immich, ImmichError
from .store import now
from .telemetry import emit, error_fields

EXPECTED_VERSION='3.3.0-rc.0'
DEFAULTS={'review_threshold':0.7,'auto_threshold':0.95,'mode':'review','scheduled':False,'interval_minutes':15,'auto_from':None}


class Engine:
    def __init__(self, store, classifier=None, client_factory=Immich):
        self.store=store
        self.classifier=classifier or Classifier()
        self.client_factory=client_factory
        self.op_lock=threading.Lock()
        self.state_lock=threading.Lock()
        self.cancel=threading.Event()
        self.shutdown=threading.Event()
        self.job={'running':False,'phase':'空闲','processed':0,'skipped':0,'errors':0,'error':None}
        self.store.recover_interrupted()
        self.scheduler_thread=None
        self._last_progress_count=0
        self._last_progress_time=0

    def settings(self):
        return {**DEFAULTS,**self.store.get_setting('preferences',{})}

    def credentials(self):
        path=self.store.directory/'credentials.json'
        if not path.exists():
            raise ValueError('请先在页面连接 Immich API Key')
        return json.loads(path.read_text(encoding='utf-8'))

    def client(self):
        return self.client_factory(api_key=self.credentials()['api_key'])

    def connect(self, api_key):
        if not api_key or len(api_key)>512:
            raise ValueError('请输入有效的 API Key')
        if not self.op_lock.acquire(blocking=False):
            raise ValueError('正在执行任务，请先停止并等待完成')
        client=self.client_factory(api_key=api_key)
        try:
            version=client.version()
            if version!=EXPECTED_VERSION:
                raise ValueError(f'当前只验证了 Immich {EXPECTED_VERSION}；检测到 {version}，请先核对兼容性')
            user=client.user()
            old=self.store.get_setting('connection')
            if old and old['user_id']!=user['id']:
                raise ValueError('本实例已绑定其他账号；每个 Immich 用户请使用独立扫描实例')
            # Verify the search shape and album permission before accepting a key.
            client.search()
            client.albums()
            auth=client.json('GET','auth/status')
            connection={'user_id':user['id'],'name':user.get('name',''),'email':user.get('email',''),'version':version,'pin_ready':bool(auth.get('pinCode'))}
            temporary=self.store.directory/'credentials.tmp'
            temporary.write_text(json.dumps({'api_key':api_key}),encoding='utf-8')
            os.chmod(temporary,0o600)
            os.replace(temporary,self.store.directory/'credentials.json')
            self.store.set_setting('connection',connection)
            emit('connection.ready')
            return connection
        finally:
            client.close()
            self.op_lock.release()

    def save_settings(self, data):
        if self.job['running']:
            raise ValueError('扫描进行中，请先停止任务再修改设置')
        old=self.settings()
        review=float(data.get('review_threshold',old['review_threshold']))
        automatic=float(data.get('auto_threshold',old['auto_threshold']))
        if not (0.05<=review<=automatic<=1):
            raise ValueError('阈值需满足 0.05 ≤ 审核阈值 ≤ 自动阈值 ≤ 1')
        mode=data.get('mode',old['mode'])
        if mode not in ['review','auto']:
            raise ValueError('模式无效')
        if mode=='auto' and old['mode']!='auto' and data.get('confirm_auto') is not True:
            raise ValueError('开启自动模式需要确认；只作用于启用之后上传的照片')
        interval=int(data.get('interval_minutes',old['interval_minutes']))
        if not (5<=interval<=1440):
            raise ValueError('扫描间隔为 5–1440 分钟')
        value={**old,'review_threshold':review,'auto_threshold':automatic,'mode':mode,'scheduled':bool(data.get('scheduled',old['scheduled'])),'interval_minutes':interval}
        if mode=='auto' and old['mode']!='auto':
            value['auto_from']=now()
        self.store.set_setting('preferences',value)
        emit('settings.saved',mode=mode,scheduled=value['scheduled'],interval_minutes=interval)
        return value

    def snapshot(self):
        with self.state_lock:
            job=dict(self.job)
        settings=self.settings()
        stats=self.store.stats()
        totals={**stats,'all':sum(stats.values()),'candidates':self.store.candidate_count(settings['review_threshold'])}
        return {'connection':self.store.get_setting('connection'),'settings':settings,'job':job,'stats':stats,'result_totals':totals,'model':self.classifier.state,'operations':self.store.operations()}

    def _set_job(self, **values):
        with self.state_lock:
            self.job.update(values)

    def start(self, limit=100, incremental=False, force=False):
        if force and (incremental or limit):
            raise ValueError('重新识别必须使用整库范围，不可同时选择增量或限量扫描')
        self.credentials()
        if not self.op_lock.acquire(blocking=False):
            raise ValueError('已有扫描或操作正在进行')
        self.cancel.clear()
        self._last_progress_count=0
        self._last_progress_time=time.monotonic()
        job_id=str(uuid.uuid4())
        self._set_job(running=True,phase='核对连接',processed=0,skipped=0,errors=0,error=None,job_id=job_id,force=force)
        emit('scan.started',job_id=job_id,mode='review' if force else self.settings()['mode'],limit=limit,incremental=incremental,force=force)
        thread=threading.Thread(target=self._run,args=(limit,incremental,force),daemon=True)
        thread.start()

    def _run(self, limit, incremental, force=False):
        client=None
        started=now()
        timer=time.monotonic()
        review_count=0
        auto_candidates=[]
        preferences=self.settings()
        if force:
            preferences={**preferences,'mode':'review'}
        try:
            client=self.client()
            self.verify(client)
            self.classifier.load()
            connection=self.store.get_setting('connection')
            after=None
            if incremental:
                checkpoint=self.store.get_setting('last_complete_scan')
                if checkpoint:
                    after=(datetime.fromisoformat(checkpoint)-timedelta(minutes=10)).isoformat()
            cursor=None
            visited=0
            exhausted=True
            # Never change visibility while paging: the API cursor is an offset.
            while not self.cancel.is_set():
                page=client.search(cursor=cursor,after=after)
                self._set_job(phase='扫描预览图')
                for asset in page.get('items',[]):
                    if self.cancel.is_set():
                        break
                    if asset.get('ownerId')!=connection['user_id']:
                        self._set_job(skipped=self.job['skipped']+1)
                        continue
                    visited+=1
                    previous=self.store.asset(asset['id'])
                    protected=previous and previous['status'] in ['keep','locked','uncertain']
                    same_cached=previous and previous['checksum']==asset.get('checksum','') and previous['status']!='error' and previous['model']==MODEL_FINGERPRINT
                    reclassify=force and previous and previous['status'] in ['review','scored']
                    if protected or (same_cached and not reclassify):
                        self._set_job(skipped=self.job['skipped']+1)
                    elif asset.get('type')!='IMAGE' or asset.get('duration') or asset.get('originalMimeType')=='image/gif':
                        self.store.save_asset(asset,None,'unsupported','视频/动画未检测',MODEL_FINGERPRINT)
                        self._set_job(skipped=self.job['skipped']+1)
                    elif asset.get('isOffline') or asset.get('isTrashed') or asset.get('visibility') not in ['timeline','archive']:
                        self._set_job(skipped=self.job['skipped']+1)
                    else:
                        try:
                            preview,_=client.preview(asset['id'])
                            score=self.classifier.predict(preview)
                            if not math.isfinite(score) or not (0<=score<=1):
                                raise ValueError('模型分数无效')
                            status='review' if score>=preferences['review_threshold'] else 'scored'
                            review_count+=int(status=='review')
                            self.store.save_asset(asset,score,status,None,MODEL_FINGERPRINT)
                            self._set_job(processed=self.job['processed']+1)
                            if preferences['mode']=='auto' and preferences['auto_from'] and asset.get('createdAt') and datetime.fromisoformat(asset['createdAt'].replace('Z','+00:00'))>=datetime.fromisoformat(preferences['auto_from']) and score>=preferences['auto_threshold']:
                                auto_candidates.append(asset['id'])
                        except Exception as e:
                            self.store.save_asset(asset,None,'error',self.safe_error(e),MODEL_FINGERPRINT)
                            self._set_job(errors=self.job['errors']+1)
                            emit('scan.item_failed',level='WARNING',job_id=self.job.get('job_id'),phase='preview_or_classification',**error_fields(e))
                    self._log_progress()
                    if limit and visited>=limit:
                        exhausted=False
                        break
                if self.cancel.is_set() or not exhausted:
                    break
                cursor=page.get('nextCursor')
                if not cursor:
                    break
            if exhausted and not self.cancel.is_set() and not self.job['errors']:
                self.store.set_setting('last_complete_scan',started)
            if not self.cancel.is_set():
                for asset_id in auto_candidates:
                    if self.cancel.is_set():
                        break
                    self._set_job(phase='锁定新增高分照片')
                    try:
                        self._lock_asset(client,asset_id,automatic=True)
                    except Exception as e:
                        if self.store.asset(asset_id)['status']!='uncertain':
                            self.store.status(asset_id,'review',self.safe_error(e))
                        emit('lock.deferred',level='WARNING',job_id=self.job.get('job_id'),**error_fields(e))
            self._set_job(phase='已停止' if self.cancel.is_set() else '扫描完成')
            emit('scan.stopped' if self.cancel.is_set() else 'scan.completed',job_id=self.job.get('job_id'),processed=self.job['processed'],skipped=self.job['skipped'],errors=self.job['errors'],review_count=review_count,elapsed_seconds=round(time.monotonic()-timer,2))
        except Exception as e:
            self._set_job(phase='任务失败',error=self.safe_error(e))
            emit('scan.failed',level='ERROR',job_id=self.job.get('job_id'),elapsed_seconds=round(time.monotonic()-timer,2),**error_fields(e))
        finally:
            if client:
                client.close()
            self._set_job(running=False)
            self.op_lock.release()

    def _log_progress(self):
        count=self.job['processed']+self.job['skipped']+self.job['errors']
        current=time.monotonic()
        if count-self._last_progress_count>=25 or current-self._last_progress_time>=30:
            emit('scan.progress',job_id=self.job.get('job_id'),processed=self.job['processed'],skipped=self.job['skipped'],errors=self.job['errors'])
            self._last_progress_count=count
            self._last_progress_time=current

    @staticmethod
    def safe_error(error):
        if isinstance(error,(ImmichError,ValueError)):
            return str(error)[:240]
        return f'{type(error).__name__}：处理失败，原图未删除；请查看服务日志/稍后重试'

    def verify(self, client):
        if client.version()!=EXPECTED_VERSION:
            raise ValueError('Immich 版本发生变化，任务已停止，请重新核对兼容性')
        if client.user()['id']!=self.store.get_setting('connection')['user_id']:
            raise ValueError('API Key 所属用户改变，操作已停止')

    def _lock_asset(self, client, asset_id, automatic=False):
        row=self.store.asset(asset_id)
        if not row or row['status'] not in ['review','scored']:
            raise ValueError('此照片不是待审核状态')
        auth=client.json('GET','auth/status')
        if not auth.get('pinCode'):
            raise ValueError('请先在 Immich 设置锁定文件夹 PIN，再执行锁定')
        asset=client.asset(asset_id)
        owner=self.store.get_setting('connection')['user_id']
        if asset['ownerId']!=owner or asset.get('isTrashed') or asset.get('checksum','')!=row['checksum']:
            raise ValueError('照片所有权或内容发生变化，请重新扫描')
        if asset.get('visibility') not in ['timeline','archive']:
            raise ValueError('照片已被隐藏或锁定，请到 Immich 检查')
        members=[asset]
        if asset.get('livePhotoVideoId'):
            if automatic:
                raise ValueError('实况照片需手动审核；动态部分未分类')
            motion=client.asset(asset['livePhotoVideoId'])
            if motion['ownerId']!=owner or motion.get('isTrashed') or motion.get('visibility') not in ['timeline','archive']:
                raise ValueError('实况视频状态不同，已停止锁定')
            members.append(motion)
        snapshots=[]
        for member in members:
            albums=client.albums(member['id'])
            if automatic and (albums or member.get('stack')):
                raise ValueError('相册/堆叠内照片留待手动审核，避免改变组织结构')
            snapshots.append({'id':member['id'],'checksum':member.get('checksum',''),'visibility':member['visibility'],'albums':[{'id':a['id'],'name':a.get('albumName','')} for a in albums]})
        operation_id=str(uuid.uuid4())
        self.store.begin_operation(operation_id,asset_id,snapshots)
        try:
            client.visibility([a['id'] for a in members],'locked')
        except Exception as e:
            rejected=isinstance(e,ImmichError) and e.status and 400<=e.status<500
            stage='rejected' if rejected else 'uncertain'
            self.store.update_operation(operation_id,stage,self.safe_error(e))
            if not rejected:
                self.store.status(asset_id,'uncertain','请求结果未知，请使用操作记录的恢复功能验证')
            emit('lock.rejected' if rejected else 'lock.uncertain',level='ERROR',operation_id=operation_id,**error_fields(e))
            raise
        self.store.update_operation(operation_id,'locked')
        self.store.status(asset_id,'locked')
        emit('lock.completed',operation_id=operation_id,selected_count=len(members))
        return operation_id

    def lock_assets(self, ids):
        if not self.op_lock.acquire(blocking=False):
            raise ValueError('请等待扫描完成，或先停止扫描')
        client=None
        try:
            client=self.client()
            self.verify(client)
            results=[]
            emit('lock.batch_started',selected_count=len(ids))
            for asset_id in ids:
                try:
                    op=self._lock_asset(client,asset_id)
                    results.append({'id':asset_id,'success':True,'operation_id':op})
                except Exception as e:
                    results.append({'id':asset_id,'success':False,'error':self.safe_error(e)})
                    emit('lock.item_failed',level='WARNING',**error_fields(e))
            emit('lock.batch_completed',success_count=sum(r['success'] for r in results),failed_count=sum(not r['success'] for r in results))
            return results
        finally:
            if client:
                client.close()
            self.op_lock.release()

    def keep(self, ids):
        if not self.op_lock.acquire(blocking=False):
            raise ValueError('请等待扫描完成，或先停止扫描')
        try:
            kept=0
            for asset_id in ids:
                row=self.store.asset(asset_id)
                if row and row['status'] in ['review','scored']:
                    self.store.status(asset_id,'keep','人工保留，后续增量扫描不自动锁定')
                    kept+=1
            emit('review.kept',success_count=kept)
        finally:
            self.op_lock.release()

    def restore(self, operation_id, email, password, pin):
        if not self.op_lock.acquire(blocking=False):
            raise ValueError('请等待扫描/操作完成')
        client=None
        try:
            op=self.store.operation(operation_id)
            if op['stage'] not in ['locked','uncertain','restore_partial']:
                raise ValueError('此操作不需要恢复')
            client=self.client()
            self.verify(client)
            emit('restore.started',operation_id=operation_id)
            with client.elevated(email,password,pin,self.store.get_setting('connection')['user_id']) as elevated:
                return self._restore_with_session(elevated,op)
        except Exception as e:
            emit('restore.failed',level='ERROR',operation_id=operation_id,**error_fields(e))
            raise
        finally:
            if client:
                client.close()
            self.op_lock.release()

    def _restore_with_session(self, client, op):
        # Validate every asset before the first write, then journal progress for retries.
        owner=self.store.get_setting('connection')['user_id']
        for item in op['snapshot']:
            current=client.asset(item['id'])
            if current['ownerId']!=owner or current.get('isTrashed') or current.get('checksum','')!=item['checksum']:
                raise ValueError('照片被删除、所有权或内容改变，已停止恢复')
            if current['visibility'] not in ['locked',item['visibility']]:
                raise ValueError('照片显示状态被其他操作改变，已停止恢复')
        self.store.update_operation(op['id'],'restore_partial','恢复进行中；中断后可重试')
        errors=[]
        for item in op['snapshot']:
            try:
                client.visibility([item['id']],item['visibility'])
                for album in item['albums']:
                    try:
                        client.add_to_album(album['id'],item['id'])
                    except Exception as e:
                        errors.append(f"相册 {album['name']}：{self.safe_error(e)}")
            except Exception as e:
                errors.append(self.safe_error(e))
        stage='restore_partial' if errors else 'restored'
        self.store.update_operation(op['id'],stage,'；'.join(errors)[:1000] if errors else None)
        if not errors:
            self.store.status(op['asset_id'],'keep','已恢复并人工保留，避免再次自动锁定')
        emit('restore.partial' if errors else 'restore.completed',level='WARNING' if errors else 'INFO',operation_id=op['id'],errors=len(errors))
        return {'success':not errors,'errors':errors}

    def scheduler(self):
        next_run=None
        while not self.shutdown.wait(5):
            settings=self.settings()
            if not settings['scheduled'] or not self.store.get_setting('connection'):
                next_run=None
                continue
            current=datetime.now(timezone.utc)
            if next_run is None:
                next_run=current+timedelta(minutes=settings['interval_minutes'])
            if current>=next_run and not self.job['running']:
                try:
                    emit('scheduler.triggered',interval_minutes=settings['interval_minutes'])
                    self.start(limit=0,incremental=True)
                except ValueError:
                    pass
                next_run=current+timedelta(minutes=settings['interval_minutes'])

    def start_scheduler(self):
        self.scheduler_thread=threading.Thread(target=self.scheduler,daemon=True)
        self.scheduler_thread.start()
