"""SQLite 운영 이력. 측정 데이터는 저장하지 않는다."""

import json
import sqlite3
from pathlib import Path
from CODE_Common.io import now


class Store:
    def __init__(self, workspace):
        self.root = Path(workspace)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "history.sqlite3", timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY, source TEXT NOT NULL, source_hash TEXT NOT NULL,
          status TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL,
          config_json TEXT NOT NULL, error TEXT NOT NULL DEFAULT '', cleaned INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS steps (
          run_id TEXT, stage TEXT, status TEXT, updated TEXT, result_json TEXT,
          PRIMARY KEY(run_id, stage));
        CREATE TABLE IF NOT EXISTS receipts (
          identity TEXT PRIMARY KEY, local_path TEXT, sha256 TEXT, size INTEGER, completed TEXT);
        CREATE TABLE IF NOT EXISTS publications (
          identity TEXT PRIMARY KEY, completed TEXT);
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, stage TEXT,
          message TEXT, created TEXT);
        CREATE INDEX IF NOT EXISTS idx_runs_source_hash ON runs(source,source_hash,created DESC);
        CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created DESC);
        CREATE INDEX IF NOT EXISTS idx_runs_cleanup ON runs(status,cleaned,updated);
        """)

    def close(self):
        self.db.close()

    def create(self, run_id, source, source_hash, config):
        self.db.execute(
            "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                str(source),
                source_hash,
                "대기",
                now(),
                now(),
                json.dumps(config, ensure_ascii=False),
                "",
                0,
            ),
        )
        self.db.commit()

    def run(self, run_id):
        r = self.db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not r:
            raise ValueError("실행 기록을 찾을 수 없습니다.")
        return dict(r)

    def runs(self):
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT * FROM runs ORDER BY created DESC LIMIT 100"
            )
        ]

    def state(self, run_id, state, error=""):
        self.db.execute(
            "UPDATE runs SET status=?,updated=?,error=? WHERE id=?",
            (state, now(), error, run_id),
        )
        self.db.commit()

    def steps(self, run_id):
        return {
            r["stage"]: dict(r)
            for r in self.db.execute("SELECT * FROM steps WHERE run_id=?", (run_id,))
        }

    def step(self, run_id, stage, status, result=None):
        self.db.execute(
            "INSERT OR REPLACE INTO steps VALUES (?,?,?,?,?)",
            (
                run_id,
                stage,
                status,
                now(),
                json.dumps(result or {}, ensure_ascii=False),
            ),
        )
        self.db.commit()

    def event(self, run_id, stage, message):
        self.db.execute(
            "INSERT INTO events(run_id,stage,message,created) VALUES (?,?,?,?)",
            (run_id, stage, message, now()),
        )
        self.db.commit()
