"""P3.2 detection storage in the analysis DB (app/.cache/analysis.db). Standard library only.

Written by the worker (faces.py), read by the core (detections_api.py) and by the
clusterer (characters.py). Rows are keyed by the clip's cache key (path + size +
mtime, C6), so a changed file simply gets new rows under a new key.
Boxes are normalised to 0..1 of the sampled frame; embeddings are L2-normalised
float16 vectors (little endian) tagged with the model that produced them.
"""

import json
import sqlite3
import struct
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS detections (
  key TEXT NOT NULL,
  n INTEGER NOT NULL,
  frame INTEGER NOT NULL,
  t REAL,
  kind TEXT NOT NULL,
  x REAL, y REAL, w REAL, h REAL,
  score REAL,
  model TEXT,
  emb BLOB,
  PRIMARY KEY (key, n)
);
CREATE TABLE IF NOT EXISTS detection_runs (
  key TEXT PRIMARY KEY,
  frames INTEGER, faces INTEGER, persons INTEGER, ms INTEGER,
  device TEXT, models TEXT, updated REAL
);
"""

FIELDS = ("n", "frame", "t", "kind", "x", "y", "w", "h", "score", "model")


def connect(db_path):
    conn = sqlite3.connect(str(db_path), timeout=10, isolation_level=None, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def pack(vector):
    values = [float(v) for v in vector]
    return struct.pack(f"<{len(values)}e", *values)


def unpack(blob):
    if not blob:
        return []
    return list(struct.unpack(f"<{len(blob) // 2}e", blob))


def save(conn, key, rows, run):
    """Replace every detection of `key` atomically. rows: dicts with FIELDS + 'emb' (list)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM detections WHERE key = ?", (key,))
        conn.executemany(
            "INSERT INTO detections(key, n, frame, t, kind, x, y, w, h, score, model, emb) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(key, *[r.get(f) for f in FIELDS], pack(r["emb"]) if r.get("emb") is not None else None)
             for r in rows])
        conn.execute(
            "INSERT OR REPLACE INTO detection_runs(key, frames, faces, persons, ms, device, models, updated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (key, run.get("frames"), run.get("faces"), run.get("persons"), run.get("ms"),
             run.get("device"), json.dumps(run.get("models") or {}), time.time()))
        conn.execute("COMMIT")
    except sqlite3.Error:
        conn.execute("ROLLBACK")
        raise


def run_info(conn, key):
    row = conn.execute("SELECT frames, faces, persons, ms, device, models, updated FROM detection_runs "
                       "WHERE key = ?", (key,)).fetchone()
    if not row:
        return None
    return {"frames": row[0], "faces": row[1], "persons": row[2], "ms": row[3], "device": row[4],
            "models": json.loads(row[5] or "{}"), "updated": row[6]}


def load(conn, key, embeddings=False):
    cols = ", ".join(FIELDS) + (", emb" if embeddings else "")
    out = []
    for row in conn.execute(f"SELECT {cols} FROM detections WHERE key = ? ORDER BY n", (key,)):
        item = dict(zip(FIELDS, row))
        if embeddings:
            item["emb"] = unpack(row[-1])
        out.append(item)
    return out


def all_embeddings(conn, kind=None):
    """(key, n, frame, kind, score, w, h, model, emb) for the whole library."""
    sql = "SELECT key, n, frame, kind, score, w, h, model, emb FROM detections WHERE emb IS NOT NULL"
    args = []
    if kind:
        sql += " AND kind = ?"
        args.append(kind)
    for row in conn.execute(sql + " ORDER BY key, n", args):
        yield row[:8] + (unpack(row[8]),)
