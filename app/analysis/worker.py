"""Analysis worker: drains the SQLite job queue, pausing for WanGP (C5).

Run from the add-on venv by the core (analysis_host.py):
    env/bin/python worker.py --db ../.cache/analysis.db --cache ../.cache [--ffmpeg PATH] [--parent PID]
"""

import argparse
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis import faces, frames, gpu, jobqueue  # noqa: E402


def run_noop(job, ctx):
    return {"ok": True}


HANDLERS = {"noop": run_noop, "frames": frames.run_job, "faces": faces.run_job}
NEEDS_GPU = {"faces"}


def _parent_alive(pid):
    if not pid:
        return True
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


class Worker:
    def __init__(self, db_path, ctx=None, gate=None, poll=1.0, parent=None, handlers=None):
        self.conn = jobqueue.connect(db_path)
        self.ctx = ctx or {}
        self.gate = gate or gpu.Gate()
        self.poll = poll
        self.parent = parent
        self.handlers = handlers or HANDLERS
        self.stopped = False
        self.processed = 0
        self.gate_interval = min(2.0, poll * 2)
        self._gate_cache, self._gate_at = None, 0.0

    def step(self):
        """One loop iteration. Returns 'paused', 'idle' or 'worked'."""
        # nvidia-smi costs ~50 ms: re-read at most every `gate_interval` s
        # (well inside the 5 s pause budget) instead of once per job.
        now = time.monotonic()
        if self._gate_cache is None or now - self._gate_at >= self.gate_interval:
            self._gate_cache, self._gate_at = self.gate.check(needs_gpu=False), now
        paused, reason, snap = self._gate_cache
        if paused:
            jobqueue.set_worker(self.conn, pid=os.getpid(), state="paused", reason=reason, job=None, gpu=snap)
            return "paused"
        job = jobqueue.claim(self.conn, kinds=list(self.handlers))
        if not job:
            jobqueue.set_worker(self.conn, pid=os.getpid(), state="idle", reason=None, job=None, gpu=snap)
            return "idle"
        if job["kind"] in NEEDS_GPU:
            paused, reason, snap = self.gate.check(needs_gpu=True)
            if paused:
                self.conn.execute("UPDATE jobs SET state = 'queued' WHERE id = ?", (job["id"],))
                jobqueue.set_worker(self.conn, pid=os.getpid(), state="paused", reason=reason, job=None, gpu=snap)
                return "paused"
        jobqueue.set_worker(self.conn, pid=os.getpid(), state="running", reason=None,
                            job=f"{job['kind']}:{Path(job['path']).name}", gpu=snap)
        try:
            result = self.handlers[job["kind"]](job, self.ctx)
            jobqueue.finish(self.conn, job["id"], result=result)
        except Exception as error:  # a bad file must not stop the queue
            jobqueue.finish(self.conn, job["id"], error=f"{type(error).__name__}: {error}")
            traceback.print_exc(file=sys.stderr)
        self.processed += 1
        return "worked"

    def run(self):
        jobqueue.requeue_running(self.conn)
        while not self.stopped and _parent_alive(self.parent):
            if self.step() != "worked":
                time.sleep(self.poll)
        jobqueue.set_worker(self.conn, pid=None, state="stopped", reason=None, job=None)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--ffmpeg", default="")
    parser.add_argument("--parent", type=int, default=0)
    parser.add_argument("--poll", type=float, default=1.0)
    parser.add_argument("--vram-mb", type=int, default=gpu.DEFAULT_VRAM_CAP_MB)
    args = parser.parse_args()
    ctx = {"cache": Path(args.cache), "ffmpeg": args.ffmpeg or None, "db": args.db, "vram_mb": args.vram_mb}
    print(f"[analysis] worker {os.getpid()} on {args.db}", flush=True)
    Worker(args.db, ctx=ctx, gate=gpu.Gate(vram_cap_mb=args.vram_mb), poll=args.poll,
           parent=args.parent or None).run()


if __name__ == "__main__":
    main()
