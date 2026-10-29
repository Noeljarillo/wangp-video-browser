"""P3.0: analysis add-on scaffold - queue, worker, GPU gating, core detection."""

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import analysis_host  # noqa: E402
from analysis import gpu, jobqueue, worker  # noqa: E402


def items(n, mtime=1):
    return [{"path": f"/v/clip{i}.mp4", "size": 100 + i, "mtime_ns": mtime} for i in range(n)]


class FakeDetector:
    def __init__(self):
        self.busy = False

    def __call__(self):
        wangp = [{"pid": 42, "mb": 9000}] if self.busy else [{"pid": 42, "mb": 300}]
        return {"available": True, "util": 90, "used_mb": 20000, "total_mb": 24000, "free_mb": 4000, "wangp": wangp}


class AnalysisTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "analysis.db")
        self.conn = jobqueue.connect(self.db)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_enqueue_is_keyed_by_path_size_mtime(self):
        self.assertEqual(jobqueue.enqueue(self.conn, "noop", items(5)), 5)
        self.assertEqual(jobqueue.enqueue(self.conn, "noop", items(5)), 0)  # unchanged: no new work (C6)
        self.assertEqual(jobqueue.enqueue(self.conn, "noop", items(5, mtime=2)), 5)  # touched files: redo

    def test_noop_job_processes_all_clips(self):
        jobqueue.enqueue(self.conn, "noop", items(20))
        w = worker.Worker(self.db, gate=gpu.Gate(detector=lambda: {"available": False}), poll=0.01)
        while w.step() == "worked":
            pass
        self.assertEqual(jobqueue.counts(self.conn), {"noop": {"done": 20}})
        self.assertEqual(jobqueue.worker_row(self.conn)["state"], "idle")

    def test_pauses_within_5s_of_wangp_generation(self):
        jobqueue.enqueue(self.conn, "noop", items(2000))
        detector = FakeDetector()
        slow = {"noop": lambda job, ctx: time.sleep(0.01) or {"ok": True}}
        w = worker.Worker(self.db, gate=gpu.Gate(detector=detector, hold=0), poll=1.0, handlers=slow)
        thread = threading.Thread(target=w.run, daemon=True)
        thread.start()
        time.sleep(0.5)
        self.assertGreater(w.processed, 0)
        detector.busy = True  # WanGP generation starts
        started = time.monotonic()
        paused_at = None
        while time.monotonic() - started < 6:
            row = jobqueue.worker_row(self.conn)
            if row and row["state"] == "paused":
                paused_at = time.monotonic() - started
                break
            time.sleep(0.05)
        self.assertIsNotNone(paused_at, "worker never paused")
        self.assertLess(paused_at, 5.0)
        before = w.processed
        time.sleep(1.5)
        self.assertEqual(w.processed, before, "worker kept working while WanGP generates")
        self.assertEqual(jobqueue.worker_row(self.conn)["reason"], "wangp")
        detector.busy = False  # resumes
        time.sleep(2.5)
        self.assertGreater(w.processed, before)
        w.stopped = True
        thread.join(5)
        print(f"\n  paused {paused_at:.2f}s after WanGP started", file=sys.stderr)

    def test_snapshot_matches_wangp_process_and_vram_cap(self):
        def runner(cmd, **_):
            out = ("35, 20000, 24576\n" if "--query-gpu=utilization.gpu,memory.used,memory.total" in cmd else
                   "111, /x/lmstudio/llm, 12000\n222, /p/api/wan.git/app/env/bin/python, 8000\n")
            return subprocess.CompletedProcess(cmd, 0, out, "")
        with mock.patch("shutil.which", return_value="/usr/bin/nvidia-smi"):
            snap = gpu.snapshot(runner=runner, dirs=["/p/api/wan.git"])
        self.assertEqual(snap["wangp"], [{"pid": 222, "mb": 8000}])
        self.assertEqual(snap["free_mb"], 4576)
        self.assertTrue(gpu.wangp_busy(snap))
        self.assertFalse(gpu.wangp_busy(dict(snap, wangp=[{"pid": 222, "mb": 400}])))  # idle WanGP
        self.assertFalse(gpu.wangp_busy(dict(snap, util=0)))  # models resident, not generating
        flicker = iter([snap, dict(snap, util=0)])
        gate = gpu.Gate(lambda: next(flicker), hold=10)
        self.assertTrue(gate.check()[0])
        self.assertTrue(gate.check()[0])  # held through a utilisation dip
        idle = dict(snap, wangp=[])
        self.assertEqual(gpu.Gate(lambda: idle, vram_cap_mb=8000).check(needs_gpu=True)[:2], (True, "vram"))
        self.assertEqual(gpu.Gate(lambda: idle, vram_cap_mb=4000).check(needs_gpu=True)[:2], (False, None))
        self.assertEqual(gpu.Gate(lambda: idle, vram_cap_mb=8000).check(needs_gpu=False)[:2], (False, None))

    @unittest.skipUnless(shutil.which("nvidia-smi"), "no nvidia-smi")
    def test_real_nvidia_smi_read(self):
        snap = gpu.snapshot()
        self.assertTrue(snap["available"])
        print(f"\n  real nvidia-smi: util={snap['util']}% free={snap['free_mb']}MB wangp={snap['wangp']} "
              f"busy={gpu.wangp_busy(snap)} dirs={gpu.wangp_dirs()}", file=sys.stderr)

    def test_core_reports_absent_without_venv(self):
        with mock.patch.object(analysis_host, "VENV_DIR", Path(self.tmp.name) / "no-env"), \
                mock.patch.dict(os.environ, {"ANALYSIS_DEV": ""}):
            self.assertFalse(analysis_host.installed())
            self.assertEqual(analysis_host.status(), {"installed": False, "state": "absent"})
            self.assertEqual(analysis_host.enqueue_entries([{"path": "/x.mp4", "size": 1}]), 0)
            self.assertFalse(analysis_host.start())


if __name__ == "__main__":
    unittest.main()
