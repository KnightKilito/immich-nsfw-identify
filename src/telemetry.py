"""Structured, allowlisted events for Docker stdout. Never log request bodies."""
import json
import logging
import os
import sys
from datetime import datetime, timezone


FIELDS = frozenset({
    'job_id', 'operation_id', 'mode', 'limit', 'incremental', 'model', 'revision',
    'device', 'processed', 'skipped', 'errors', 'review_count', 'selected_count',
    'success_count', 'failed_count', 'elapsed_seconds', 'interval_minutes',
    'http_status', 'error_type', 'phase', 'scheduled', 'reason_code', 'force',
})


class EventFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            'timestamp': datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec='milliseconds'),
            'level': record.levelname,
            'event': record.getMessage(),
            **getattr(record, 'event_fields', {}),
        }
        return json.dumps(payload, ensure_ascii=False, allow_nan=False)


logger = logging.getLogger('immich-nsfw-identify')
logger.propagate = False
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(EventFormatter())
    logger.addHandler(handler)
level = os.getenv('LOG_LEVEL', 'INFO').upper()
logger.setLevel(level if level in ('DEBUG', 'INFO', 'WARNING', 'ERROR') else 'INFO')


def emit(event, level='INFO', **fields):
    values = {key: value for key, value in fields.items()
              if key in FIELDS and (value is None or isinstance(value, (str, int, float, bool)))}
    logger.log(getattr(logging, level), event, extra={'event_fields': values})


def error_fields(error):
    # Exception messages may contain credentials, album names or remote response data.
    fields = {'error_type': type(error).__name__}
    status = getattr(error, 'status', None)
    if isinstance(status, int):
        fields['http_status'] = status
    return fields
