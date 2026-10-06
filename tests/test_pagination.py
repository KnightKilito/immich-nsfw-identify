import uuid

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from src.store import Store


def test_store_paging_total_and_non_overlapping_offsets(tmp_path):
    store=Store(tmp_path)
    for i in range(10):
        asset={'id':f'00000000-0000-4000-8000-{i:012d}','ownerId':'owner','checksum':'hash','originalFileName':'sample'}
        store.save_asset(asset,0.8,'review',None,'test')
    first=store.list_assets('candidates',offset=0,limit=4,threshold=0.7)
    last=store.list_assets('candidates',offset=8,limit=4,threshold=0.7)
    assert first['total']==last['total']==10
    assert len(first['items'])==4 and len(last['items'])==2
    assert not {a['id'] for a in first['items']} & {a['id'] for a in last['items']}


def test_api_page_limit_and_invalid_bounds(monkeypatch,tmp_path):
    monkeypatch.setenv('STATE_DIR',str(tmp_path))
    from src import app as module
    calls=[]
    def listing(status,offset,limit,threshold):
        calls.append((status,offset,limit))
        return {'total':0,'items':[]}
    monkeypatch.setattr(module.store,'list_assets',listing)
    client=TestClient(module.app,base_url='http://localhost:2983')
    assert client.get('/api/assets?offset=192&limit=192').status_code==200
    assert calls[-1]==('candidates',192,192)
    for query in ['limit=0','limit=193','offset=-1','offset=2147483648']:
        assert client.get('/api/assets?'+query).status_code==422


def test_full_page_selection_accepts_192_and_rejects_larger_batch():
    from src.app import Selection
    ids=[uuid.uuid4() for _ in range(193)]
    assert len(Selection(ids=ids[:192]).ids)==192
    with pytest.raises(ValidationError):Selection(ids=ids)
