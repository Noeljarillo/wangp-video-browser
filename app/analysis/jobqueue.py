"""SQLite job queue shared by the core (enqueue / status) and the worker (claim / finish).

Jobs are keyed by (kind, cache key) where the cache key derives from
path + size + mtime (C6): re-enqueueing an unchanged file is a no-op, and a
changed file gets a new key and therefore a fresh job.
"""

import json
import os
import sqlite3
import time
from hashlib import sha1

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,
  key TEXT NOT NULL,
  path TEXT NOT NULL,
  payload TEXT,
  state TEXT NOT NULL DEFAULT 'queued',
  result TEXT,
  error TEXT,
  created REAL,
  updated REAL,
  UNIQUE(kind, key)
);
CREATE INDEX IF NOT EXISTS jobs_state ON jobs(state, id);
CREATE TABLE IF NOT EXISTS worker (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  pid INTEGER, state TEXT, reason TEXT, job TEXT, gpu TEXT, heartbeat REAL
);
"""


def cache_key(path, size, mtime_ns):
    return sha1(f"{path}|{int(size)}|{int(mtime_ns)}".encode("utf-8")).hexdigest()[:20]


def connect(db_path):
    os.makedirs(os.path.dirname(str(db_path)) or ".", exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10, isolation_level=None, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def enqueue(conn, kind, items):
    """items: iterable of dicts with path, size, mtime_ns and optional payload. Returns rows added."""
    now = time.time()
    rows = [(kind, cache_key(i["path"], i["size"], i["mtime_ns"]), str(i["path"]),
             json.dumps(i.get("payload") or {}), now, now) for i in items]
    before = conn.total_changes
    conn.execute("BEGIN")
    conn.executemany("INSERT OR IGNORE INTO jobs(kind, key, path, payload, created, updated) "
                     "VALUES (?, ?, ?, ?, ?, ?)", rows)
    conn.execute("COMMIT")
    return conn.total_changes - before


def claim(conn, kinds=None):
    """Atomically move the oldest queued job to 'running' and return it (or None)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        sql = "SELECT id, kind, key, path, payload FROM jobs WHERE state = 'queued'"
        args = []
        if kinds:
            sql += f" AND kind IN ({','.join('?' * len(kinds))})"
            args = list(kinds)
        row = conn.execute(sql + " ORDER BY id LIMIT 1", args).fetchone()
        if row:
            conn.execute("UPDATE jobs SET state = 'running', updated = ? WHERE id = ?", (time.time(), row[0]))
        conn.execute("COMMIT")
    except sqlite3.Error:
        conn.execute("ROLLBACK")
        raise
    if not row:
        return None
    return {"id": row[0], "kind": row[1], "key": row[2], "path": row[3], "payload": json.loads(row[4] or "{}")}


def finish(conn, job_id, result=None, error=None):
    conn.execute("UPDATE jobs SET state = ?, result = ?, error = ?, updated = ? WHERE id = ?",
                 ("error" if error else "done", json.dumps(result) if result is not None else None,
                  error, time.time(), job_id))


def requeue_running(conn):
    """A worker that died mid-job leaves rows in 'running'; put them back on start."""
    conn.execute("UPDATE jobs SET state = 'queued' WHERE state = 'running'")


def set_worker(conn, **fields):
    fields = dict(fields, heartbeat=time.time())
    if "gpu" in fields and not isinstance(fields["gpu"], (str, type(None))):
        fields["gpu"] = json.dumps(fields["gpu"])
    conn.execute("INSERT OR IGNORE INTO worker(id) VALUES (1)")
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE worker SET {cols} WHERE id = 1", list(fields.values()))


def counts(conn):
    out = {}
    for kind, state, n in conn.execute("SELECT kind, state, COUNT(*) FROM jobs GROUP BY kind, state"):
        out.setdefault(kind, {})[state] = n
    return out


def worker_row(conn):
    row = conn.execute("SELECT pid, state, reason, job, gpu, heartbeat FROM worker WHERE id = 1").fetchone()
    if not row:
        return None
    gpu = None
    try:
        gpu = json.loads(row[4]) if row[4] else None
    except ValueError:
        pass
    return {"pid": row[0], "state": row[1], "reason": row[2], "job": row[3], "gpu": gpu, "heartbeat": row[5]}
