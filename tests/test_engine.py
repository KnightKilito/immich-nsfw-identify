import copy
import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from src.engine import Engine, EXPECTED_VERSION
from src.immich import Immich, ImmichError
from src.store import Store

OWNER=str(uuid.uuid4())
OTHER=str(uuid.uuid4())


def photo(**kwargs):
    return {'id':str(uuid.uuid4()),'checksum':'hash','originalFileName':'test.jpg','ownerId':OWNER,'type':'IMAGE','visibility':'timeline','isTrashed':False,'isOffline':False,'createdAt':datetime.now(timezone.utc).isoformat(),'duration':None,**kwargs}


class FakeClassifier:
    state='test'
    def load(self): pass
    def predict(self,data): return 0.98


class FakeImmich:
    def __init__(self,assets=(),pages=None):
        self.assets={a['id']:copy.deepcopy(a) for a in assets}
        self.pages=pages or [{'items':list(assets),'nextCursor':None}]
        self.calls=[]
        self.album_map={}
        self.fault=None
        self.current_version=EXPECTED_VERSION
        self.pin=True
    def close(self): pass
    def version(self): return self.current_version
    def user(self): return {'id':OWNER,'name':'test','email':'test@example.com'}
    def search(self,cursor=None,after=None):
        self.calls.append(('search',cursor,after))
        return copy.deepcopy(self.pages[int(cursor or 0)])
    def preview(self,asset_id): return b'preview','image/jpeg'
    def asset(self,asset_id): return copy.deepcopy(self.assets[asset_id])
    def albums(self,asset_id=None):
        if self.fault=='albums': raise ImmichError('album.read 权限不足',403)
        return self.album_map.get(asset_id,[])
    def json(self,*args,**kwargs): return {'pinCode':self.pin}
    def visibility(self,ids,visibility):
        self.calls.append(('visibility',ids,visibility))
        for asset_id in ids: self.assets[asset_id]['visibility']=visibility
        if self.fault=='timeout': raise ImmichError('请求超时')
    def add_to_album(self,album_id,asset_id):
        self.calls.append(('add',album_id,asset_id))
        if self.fault=='restore_album': raise ImmichError('相册不存在',404)
    @contextmanager
    def elevated(self,email,password,pin,expected_user): yield self


@pytest.fixture
def setup(tmp_path):
    store=Store(tmp_path)
    store.set_setting('connection',{'user_id':OWNER,'name':'test','version':EXPECTED_VERSION})
    (tmp_path/'credentials.json').write_text(json.dumps({'api_key':'fake'}))
    client=FakeImmich()
    engine=Engine(store,FakeClassifier(),lambda **kwargs:client)
    return engine,client


def run(engine,client,assets,pages=None,incremental=False,limit=0,force=False):
    client.assets={a['id']:copy.deepcopy(a) for a in assets}
    client.pages=pages or [{'items':assets,'nextCursor':None}]
    engine.op_lock.acquire()
    engine._set_job(running=True,processed=0,skipped=0,errors=0)
    engine._run(limit,incremental,force)


def test_review_scans_without_mutations(setup):
    engine,client=setup; a=photo()
    run(engine,client,[a])
    assert engine.store.asset(a['id'])['score']==0.98
    assert not any(c[0]=='visibility' for c in client.calls)


def test_other_users_never_enter_results(setup):
    engine,client=setup; a=photo(ownerId=OTHER)
    run(engine,client,[a])
    assert engine.store.asset(a['id']) is None


def test_video_and_animation_not_classified(setup):
    engine,client=setup; a=photo(type='VIDEO'); b=photo(duration=12)
    run(engine,client,[a,b])
    assert engine.job['processed']==0
    assert engine.store.stats()=={'unsupported':2}


def test_manual_keep_survives_future_scans(setup):
    engine,client=setup; a=photo(); run(engine,client,[a]); engine.keep([a['id']]); run(engine,client,[a])
    assert engine.store.asset(a['id'])['status']=='keep'
    assert engine.job['processed']==0


def test_auto_only_future_uploads_and_paging_before_writes(setup):
    engine,client=setup
    boundary=datetime.now(timezone.utc)
    engine.store.set_setting('preferences',{'mode':'auto','auto_from':boundary.isoformat()})
    old=photo(createdAt=(boundary-timedelta(days=5)).isoformat())
    new1=photo(); new2=photo()
    pages=[{'items':[old,new1],'nextCursor':'1'},{'items':[new2],'nextCursor':None}]
    run(engine,client,[old,new1,new2],pages)
    assert engine.store.asset(old['id'])['status']=='review'
    assert engine.store.asset(new1['id'])['status']=='locked'
    assert engine.store.asset(new2['id'])['status']=='locked'
    first_write=next(i for i,c in enumerate(client.calls) if c[0]=='visibility')
    assert all(c[0]!='search' for c in client.calls[first_write:])


def test_auto_keeps_album_and_live_assets_for_review(setup):
    engine,client=setup
    engine.store.set_setting('preferences',{'mode':'auto','auto_from':(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()})
    a=photo(); b=photo(livePhotoVideoId=str(uuid.uuid4()))
    client.album_map[a['id']]=[{'id':'album','albumName':'Family'}]
    run(engine,client,[a,b])
    assert not any(c[0]=='visibility' for c in client.calls)
    assert engine.store.asset(a['id'])['status']=='review'


def test_lock_journals_before_write_and_restores_albums(setup):
    engine,client=setup; a=photo(visibility='archive'); run(engine,client,[a])
    client.album_map[a['id']]=[{'id':'album','albumName':'Family'}]
    original=client.visibility
    def write(ids,visibility):
        assert engine.store.operations()[0]['stage']=='prepared'
        original(ids,visibility)
    client.visibility=write
    result=engine.lock_assets([a['id']])[0]
    assert result['success']
    client.visibility=original
    engine.restore(result['operation_id'],'test','password','123456')
    assert client.assets[a['id']]['visibility']=='archive'
    assert ('add','album',a['id']) in client.calls
    assert engine.store.asset(a['id'])['status']=='keep'


def test_album_read_failure_prevents_lock(setup):
    engine,client=setup; a=photo();run(engine,client,[a]);client.fault='albums'
    assert not engine.lock_assets([a['id']])[0]['success']
    assert client.assets[a['id']]['visibility']=='timeline'


def test_timeout_preserves_unknown_state_and_snapshot(setup):
    engine,client=setup
    engine.store.set_setting('preferences',{'mode':'auto','auto_from':(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()})
    a=photo();client.fault='timeout';run(engine,client,[a])
    assert engine.store.asset(a['id'])['status']=='uncertain'
    assert engine.store.operations()[0]['stage']=='uncertain'


def test_restart_recovers_prepared_operations(setup):
    engine,client=setup;a=photo();run(engine,client,[a]);operation_id=str(uuid.uuid4())
    engine.store.begin_operation(operation_id,a['id'],[])
    engine.store.recover_interrupted()
    assert engine.store.operation(operation_id)['stage']=='uncertain'
    assert engine.store.asset(a['id'])['status']=='uncertain'


def test_partial_restore_can_retry_without_losing_snapshot(setup):
    engine,client=setup;a=photo();run(engine,client,[a]);client.album_map[a['id']]=[{'id':'album','albumName':'Family'}]
    op=engine.lock_assets([a['id']])[0]['operation_id'];client.fault='restore_album'
    result=engine.restore(op,'test','password','123456')
    assert not result['success']
    assert engine.store.operation(op)['stage']=='restore_partial'
    client.fault=None
    assert engine.restore(op,'test','password','123456')['success']


def test_changed_owner_or_deleted_asset_prevents_restore(setup):
    engine,client=setup;a=photo();run(engine,client,[a]);op=engine.lock_assets([a['id']])[0]['operation_id']
    client.assets[a['id']]['ownerId']=OTHER
    with pytest.raises(ValueError):engine.restore(op,'test','password','123456')
    assert client.assets[a['id']]['visibility']=='locked'


def test_live_photo_locks_both_and_records_both(setup):
    engine,client=setup;motion=photo(type='VIDEO');a=photo(livePhotoVideoId=motion['id'])
    run(engine,client,[a,motion]);op=engine.lock_assets([a['id']])[0]['operation_id']
    assert client.assets[motion['id']]['visibility']=='locked'
    assert len(engine.store.operation(op)['snapshot'])==2


def test_no_pin_no_lock(setup):
    engine,client=setup;a=photo();run(engine,client,[a]);client.pin=False
    assert not engine.lock_assets([a['id']])[0]['success']
    assert not engine.store.operations()


def test_incremental_uses_upload_time_checkpoint_and_bounded_scan_does_not_advance(setup):
    engine,client=setup;checkpoint=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
    engine.store.set_setting('last_complete_scan',checkpoint)
    run(engine,client,[photo()],incremental=True,limit=1)
    after=next(c[2] for c in client.calls if c[0]=='search')
    assert datetime.fromisoformat(after)<datetime.fromisoformat(checkpoint)
    assert engine.store.get_setting('last_complete_scan')==checkpoint


def test_version_change_disables_scan_and_writes(setup):
    engine,client=setup;client.current_version='9.0.0';a=photo();run(engine,client,[a])
    assert engine.job['phase']=='任务失败'
    assert not engine.store.stats()


def test_auto_requires_explicit_confirmation(setup):
    engine,client=setup
    with pytest.raises(ValueError):engine.save_settings({'mode':'auto'})
    assert engine.save_settings({'mode':'auto','confirm_auto':True})['auto_from']


def test_force_reclassifies_cached_scores_and_preserves_protected_states(setup):
    engine,client=setup
    rows=[photo() for _ in range(5)]
    run(engine,client,rows)
    for a,status in zip(rows,['scored','review','keep','locked','uncertain']):
        engine.store.status(a['id'],status)
    engine.classifier.predict=lambda _:0.2
    run(engine,client,rows,force=True)
    assert engine.job['processed']==2
    assert [engine.store.asset(a['id'])['status'] for a in rows]==['scored','scored','keep','locked','uncertain']
    assert all(engine.store.asset(a['id'])['score']==0.2 for a in rows[:2])


def test_force_scan_is_review_only_even_if_global_mode_is_auto(setup):
    engine,client=setup
    engine.store.set_setting('preferences',{'mode':'auto','auto_from':(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()})
    a=photo();run(engine,client,[a],force=True)
    assert engine.store.asset(a['id'])['status']=='review'
    assert not any(c[0]=='visibility' for c in client.calls)


def test_force_incremental_and_bounded_request_rejected(setup):
    engine,_=setup
    with pytest.raises(ValueError):engine.start(limit=0,incremental=True,force=True)
    with pytest.raises(ValueError):engine.start(limit=100,force=True)
    assert not engine.op_lock.locked()


def test_candidate_totals_include_scored_rows_at_current_threshold(setup):
    engine,client=setup;a=photo();b=photo();run(engine,client,[a,b])
    engine.store.status(a['id'],'keep')
    engine.store.status(b['id'],'scored')
    assert engine.snapshot()['result_totals']['candidates']==1
    assert engine.snapshot()['result_totals']['all']==2
