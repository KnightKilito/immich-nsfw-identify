import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.directory / 'scanner.sqlite', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS assets (
                id TEXT PRIMARY KEY, checksum TEXT NOT NULL, name TEXT NOT NULL,
                owner_id TEXT NOT NULL, score REAL, status TEXT NOT NULL,
                reason TEXT, created_at TEXT, scanned_at TEXT NOT NULL, model TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS operations (
                id TEXT PRIMARY KEY, asset_id TEXT NOT NULL, stage TEXT NOT NULL,
                snapshot TEXT NOT NULL, details TEXT, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS assets_status ON assets(status,score);
        ''')
        self.db.commit()
        os.chmod(self.directory / 'scanner.sqlite', 0o600)

    def get_setting(self, key, default=None):
        with self.lock:
            row = self.db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.lock, self.db:
            self.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, json.dumps(value)))

    def asset(self, asset_id):
        with self.lock:
            row = self.db.execute('SELECT * FROM assets WHERE id=?', (asset_id,)).fetchone()
            return dict(row) if row else None

    def save_asset(self, asset, score, status, reason, model):
        with self.lock, self.db:
            self.db.execute('INSERT OR REPLACE INTO assets VALUES (?,?,?,?,?,?,?,?,?,?)', (
                asset['id'], asset.get('checksum',''), asset.get('originalFileName',''),
                asset['ownerId'], score, status, reason, asset.get('createdAt'), now(), model))

    def status(self, asset_id, status, reason=None):
        with self.lock, self.db:
            self.db.execute('UPDATE assets SET status=?,reason=? WHERE id=?', (status, reason, asset_id))

    def list_assets(self, status, offset=0, limit=48, threshold=0):
        where, args = '1=1', []
        if status == 'candidates':
            where, args = "status IN ('review','scored') AND score>=?", [threshold]
        elif status != 'all':
            where, args = 'status=?', [status]
        with self.lock:
            total = self.db.execute(f'SELECT count(*) FROM assets WHERE {where}', args).fetchone()[0]
            rows = self.db.execute(f'SELECT * FROM assets WHERE {where} ORDER BY score DESC,id LIMIT ? OFFSET ?', (*args, limit, offset)).fetchall()
            return {'total':total,'items':[dict(r) for r in rows]}

    def stats(self):
        with self.lock:
            return {r[0]:r[1] for r in self.db.execute('SELECT status,count(*) FROM assets GROUP BY status')}

    def candidate_count(self, threshold):
        with self.lock:
            return self.db.execute("SELECT count(*) FROM assets WHERE status IN ('review','scored') AND score>=?",(threshold,)).fetchone()[0]

    def begin_operation(self, operation_id, asset_id, snapshot):
        with self.lock, self.db:
            self.db.execute('INSERT INTO operations VALUES (?,?,?,?,?,?)', (operation_id, asset_id, 'prepared', json.dumps(snapshot), None, now()))

    def update_operation(self, operation_id, stage, details=None):
        with self.lock, self.db:
            self.db.execute('UPDATE operations SET stage=?,details=? WHERE id=?', (stage, details, operation_id))

    def operation(self, operation_id):
        with self.lock:
            row = self.db.execute('SELECT * FROM operations WHERE id=?', (operation_id,)).fetchone()
            if not row:
                raise ValueError('找不到操作记录')
            result = dict(row)
            result['snapshot'] = json.loads(result['snapshot'])
            return result

    def operations(self):
        with self.lock:
            return [dict(r) for r in self.db.execute('SELECT id,asset_id,stage,details,created_at FROM operations ORDER BY created_at DESC LIMIT 100')]

    def recover_interrupted(self):
        with self.lock, self.db:
            for row in self.db.execute("SELECT id,asset_id FROM operations WHERE stage='prepared'").fetchall():
                self.db.execute("UPDATE operations SET stage='uncertain',details='服务重启，需验证锁定状态后恢复' WHERE id=?", (row['id'],))
                self.db.execute("UPDATE assets SET status='uncertain' WHERE id=?", (row['asset_id'],))
