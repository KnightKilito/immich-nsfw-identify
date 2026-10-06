import io
import json
import logging

import pytest

from src.engine import Engine
from src.immich import ImmichError
from src.store import Store
from src.telemetry import EventFormatter, emit, error_fields, logger
from test_engine import FakeClassifier, FakeImmich, OWNER, photo, run


@pytest.fixture
def events(monkeypatch):
    stream=io.StringIO()
    handler=logging.StreamHandler(stream)
    handler.setFormatter(EventFormatter())
    monkeypatch.setattr(logger,'handlers',[handler])
    monkeypatch.setattr(logger,'level',logging.INFO)
    return stream


def test_log_allowlist_and_exception_messages_never_echo_secrets(events):
    secret='PRIVATE-KEY-PASSWORD-PIN'
    error=ImmichError(secret,403)
    emit('scan.item_failed',level='WARNING',api_key=secret,email=secret,
         filename=secret,body=secret,password=secret,pin=secret,**error_fields(error))
    record=json.loads(events.getvalue())
    assert secret not in events.getvalue()
    assert record['level']=='WARNING'
    assert record['error_type']=='ImmichError'
    assert record['http_status']==403
    assert record['timestamp'].endswith('+00:00')


def test_progress_is_throttled_and_summary_keeps_counts(tmp_path,events):
    store=Store(tmp_path)
    store.set_setting('connection',{'user_id':OWNER})
    (tmp_path/'credentials.json').write_text(json.dumps({'api_key':'DO_NOT_LOG_API_KEY'}))
    client=FakeImmich()
    engine=Engine(store,FakeClassifier(),lambda **kwargs:client)
    engine._last_progress_time=__import__('time').monotonic()
    run(engine,client,[photo(originalFileName='DO_NOT_LOG_FILENAME.jpg') for _ in range(52)])
    records=[json.loads(line) for line in events.getvalue().splitlines()]
    assert len([r for r in records if r['event']=='scan.progress'])==2
    completed=next(r for r in records if r['event']=='scan.completed')
    assert completed['processed']==52 and completed['errors']==0
    assert 'DO_NOT_LOG' not in events.getvalue()


def test_scan_failure_logs_exception_type_without_sensitive_value(tmp_path,events):
    store=Store(tmp_path);store.set_setting('connection',{'user_id':OWNER})
    (tmp_path/'credentials.json').write_text(json.dumps({'api_key':'DO_NOT_LOG_KEY'}))
    client=FakeImmich();client.current_version='unverified'
    engine=Engine(store,FakeClassifier(),lambda **kwargs:client)
    run(engine,client,[photo()])
    failed=next(json.loads(line) for line in events.getvalue().splitlines() if json.loads(line)['event']=='scan.failed')
    assert failed['level']=='ERROR' and failed['error_type']=='ValueError'
    assert 'DO_NOT_LOG' not in events.getvalue()
