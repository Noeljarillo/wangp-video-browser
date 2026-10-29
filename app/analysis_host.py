"""Core-side bridge to the optional analysis add-on (C2). Standard library only.

The add-on counts as installed when app/analysis/ exists *and* its venv
(app/analysis/env) has a python - or ANALYSIS_DEV=1 is set, which runs the
worker with this interpreter (for development without the heavy deps).
The core never imports anything heavy: it enqueues jobs in SQLite, spawns /
attaches the worker subprocess and reads status back.
"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ANALYSIS_DIR = APP_DIR / "analysis"
VENV_DIR = ANALYSIS_DIR / "env"
CACHE_DIR = APP_DIR / ".cache"
DB_PATH = CACHE_DIR / "analysis.db"
STALE_AFTER = 15  # seconds without a worker heartbeat

# Job kinds enqueued for every clip, in order. "frames" (P3.1) feeds every later
# analyser; "noop" (the scaffold's smoke test) can be added via ANALYSIS_KINDS.
KINDS = [k for k in os.environ.get("ANALYSIS_KINDS", "frames,faces").split(",") if k.strip()]

_lock = threading.Lock()
_proc = None
_ffmpeg = None


def _venv_python():
    for rel in ("bin/python", "Scripts/python.exe"):
        candidate = VENV_DIR / rel
        if candidate.is_file():
            return str(candidate)
    return None


def python_for_worker():
    if not (ANALYSIS_DIR / "worker.py").is_file():
        return None
    return _venv_python() or (sys.executable if os.environ.get("ANALYSIS_DEV") == "1" else None)


def installed():
    return python_for_worker() is not None


def _jobqueue():
    from analysis import jobqueue  # stdlib-only module of the add-on
    return jobqueue


def _pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _worker_alive(conn):
    if _proc is not None and _proc.poll() is None:
        return True
    row = _jobqueue().worker_row(conn)
    return bool(row and row["pid"] and _pid_alive(row["pid"]) and time.time() - (row["heartbeat"] or 0) < STALE_AFTER)


def start(ffmpeg=None):
    """Spawn the worker unless one is already alive (attach). No-op when the add-on is absent."""
    global _proc, _ffmpeg
    _ffmpeg = ffmpeg or _ffmpeg
    python = python_for_worker()
    if not python:
        return False
    with _lock:
        conn = _jobqueue().connect(DB_PATH)
        try:
            if _worker_alive(conn):
                return True
        finally:
            conn.close()
        command = [python, str(ANALYSIS_DIR / "worker.py"), "--db", str(DB_PATH), "--cache", str(CACHE_DIR),
                   "--parent", str(os.getpid())]
        if _ffmpeg:
            command += ["--ffmpeg", _ffmpeg]
        try:
            _proc = subprocess.Popen(command, cwd=str(ANALYSIS_DIR))
        except OSError as error:
            print(f"[wangp-video-browser] analysis worker failed to start: {error}", file=sys.stderr)
            return False
    return True


def stop():
    if _proc is not None and _proc.poll() is None:
        _proc.terminate()


def enqueue_entries(entries):
    """Queue every kind for every clip; unchanged files are skipped by key (C6)."""
    if not installed() or not entries:
        return 0
    items = []
    for entry in entries:
        try:
            mtime_ns = os.stat(entry["path"]).st_mtime_ns
        except OSError:
            continue
        probe = entry.get("probe") or {}
        items.append({"path": entry["path"], "size": entry["size"], "mtime_ns": mtime_ns,
                      "payload": {"duration": probe.get("duration"), "fps": probe.get("fps")}})
    jq = _jobqueue()
    conn = jq.connect(DB_PATH)
    try:
        added = sum(jq.enqueue(conn, kind, items) for kind in KINDS)
    finally:
        conn.close()
    if added:
        start()
    return added


def status():
    if not installed():
        return {"installed": False, "state": "absent"}
    jq = _jobqueue()
    conn = jq.connect(DB_PATH)
    try:
        counts = jq.counts(conn)
        row = jq.worker_row(conn) or {}
        alive = _worker_alive(conn)
    finally:
        conn.close()
    total = sum(sum(c.values()) for c in counts.values())
    done = sum(c.get("done", 0) + c.get("error", 0) for c in counts.values())
    state = row.get("state") if alive else "stopped"
    return {"installed": True, "dev": _venv_python() is None, "state": state or "starting",
            "reason": row.get("reason") if alive else None, "job": row.get("job") if alive else None,
            "total": total, "done": done, "errors": sum(c.get("error", 0) for c in counts.values()),
            "queued": sum(c.get("queued", 0) for c in counts.values()), "kinds": counts, "gpu": row.get("gpu")}
