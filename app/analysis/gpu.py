"""GPU gating for the analysis worker (C5): don't fight Wan2GP for the GPU.

`snapshot()` reads nvidia-smi once. A WanGP generation is "running" when a GPU
compute process belongs to a WanGP install (its exe / cwd / cmdline lives under
a launcher folder that has app/wgp.py) and holds a generation-sized amount of
VRAM (idle WanGP keeps only a small CUDA context; models are offloaded). When
the driver doesn't report per-process memory, GPU utilisation is used instead.
No nvidia-smi means no gating: the worker simply runs (CPU fallback).
Standard library only.
"""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

WANGP_BUSY_MB = int(os.environ.get("ANALYSIS_WANGP_BUSY_MB", "1500"))
UTIL_BUSY = int(os.environ.get("ANALYSIS_UTIL_BUSY", "30"))
DEFAULT_VRAM_CAP_MB = int(os.environ.get("ANALYSIS_VRAM_MB", "4096"))


def _pinokio_home():
    try:
        home = json.loads((Path.home() / ".pinokio" / "config.json").read_text(encoding="utf-8")).get("home")
        if home:
            return Path(home)
    except (OSError, ValueError, AttributeError):
        pass
    env = os.environ.get("PINOKIO_HOME")
    return Path(env) if env else None


def wangp_dirs():
    """Launcher folders of WanGP installs (anything under <home>/api/* with app/wgp.py)."""
    dirs = [Path(p) for p in os.environ.get("WANGP_DIR", "").split(os.pathsep) if p.strip()]
    here = Path(__file__).resolve().parents[3]  # .../api
    home = _pinokio_home()
    for api in {here} | ({home / "api"} if home else set()):
        if api.is_dir():
            dirs.extend(p.parent.parent for p in api.glob("*/app/wgp.py"))
    out = []
    for d in dirs:
        try:
            r = str(d.resolve())
        except OSError:
            continue
        if r not in out:
            out.append(r)
    return out


def _proc_paths(pid, name):
    paths = [name or ""]
    for link in ("cwd", "exe"):
        try:
            paths.append(os.readlink(f"/proc/{pid}/{link}"))
        except OSError:
            pass
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            paths.extend(handle.read().decode("utf-8", "ignore").split("\0"))
    except OSError:
        pass
    return [p for p in paths if p]


def _num(text):
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _smi(args, runner):
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        res = runner([exe] + args, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    return [[c.strip() for c in line.split(",")] for line in res.stdout.splitlines() if line.strip()]


def snapshot(runner=subprocess.run, dirs=None):
    """One nvidia-smi read -> {available, util, used_mb, total_mb, free_mb, wangp: [{pid, mb}]}."""
    gpus = _smi(["--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"], runner)
    if not gpus:
        return {"available": False}
    util = max((_num(g[0]) or 0) for g in gpus)
    used = sum((_num(g[1]) or 0) for g in gpus)
    total = sum((_num(g[2]) or 0) for g in gpus)
    apps = _smi(["--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader,nounits"], runner) or []
    dirs = wangp_dirs() if dirs is None else dirs
    wangp = []
    for row in apps:
        if len(row) < 2:
            continue
        pid, name = row[0], row[1]
        if dirs and any(p.startswith(d) for p in _proc_paths(pid, name) for d in dirs):
            wangp.append({"pid": _num(pid), "mb": _num(row[2]) if len(row) > 2 else None})
    return {"available": True, "util": util, "used_mb": used, "total_mb": total,
            "free_mb": max(0, total - used), "wangp": wangp}


def wangp_busy(snap):
    """WanGP holds a generation-sized VRAM block *and* the GPU is working.

    Memory alone is not enough: WanGP profiles that keep models resident hold
    VRAM while idle, but then utilisation drops to ~0.
    """
    busy_gpu = (snap.get("util") or 0) >= UTIL_BUSY
    return busy_gpu and any(p.get("mb") is None or p["mb"] >= WANGP_BUSY_MB for p in snap.get("wangp") or [])


class Gate:
    """check(needs_gpu) -> (paused, reason, snapshot). `detector` is swappable for tests."""

    def __init__(self, detector=snapshot, vram_cap_mb=DEFAULT_VRAM_CAP_MB, hold=10.0):
        self.detector = detector
        self.vram_cap_mb = vram_cap_mb
        self.hold = hold  # stay paused this long after WanGP last looked busy (step gaps, VAE decode)
        self._busy_at = None

    def check(self, needs_gpu=False):
        snap = self.detector()
        if not snap.get("available"):
            return False, None, snap
        now = time.monotonic()
        if wangp_busy(snap):
            self._busy_at = now
        if self._busy_at is not None and now - self._busy_at < max(self.hold, 1e-9) and (
                wangp_busy(snap) or snap.get("wangp")):
            return True, "wangp", snap
        if needs_gpu and snap.get("free_mb", 0) < self.vram_cap_mb:
            return True, "vram", snap
        return False, None, snap
