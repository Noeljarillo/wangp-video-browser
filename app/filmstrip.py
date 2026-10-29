"""
Filmstrips (P2.2): one 8-frame sprite JPEG per clip, made lazily by ffmpeg.

Requests never wait for ffmpeg: ``status()`` returns the cached sprite if it
exists, otherwise queues the clip for a single background worker and reports
"queued". Sprites are keyed by path + size + mtime (C6), so an unchanged clip
is never rendered twice and a re-rendered one gets a fresh strip. Without
ffmpeg every clip reports "unavailable" and the UI keeps the poster. The
source video is only read (C4).
"""

import os
import queue
import subprocess
import threading
from hashlib import sha1
from pathlib import Path

FRAMES = 8
FRAME_WIDTH = 160


def frame_times(duration, frames=FRAMES):
    """Centre of each of ``frames`` equal slices - where the sprite samples."""
    if not duration or duration <= 0:
        return []
    return [round((i + 0.5) * duration / frames, 3) for i in range(frames)]


def build_command(ffmpeg, source, target, duration, frames=FRAMES, width=FRAME_WIDTH):
    # fps=N/duration picks N evenly spaced frames in one decode pass; tile
    # packs them into a single row. Unknown duration: take the first N frames
    # one second apart.
    rate = f"{frames}/{duration:.3f}" if duration and duration > 0 else "1"
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", str(source), "-an", "-sn",
        "-vf", f"fps={rate},scale={width}:-2,tile={frames}x1",
        "-frames:v", "1", "-q:v", "5", str(target),
    ]


class Filmstrips:
    def __init__(self, cache_dir, ffmpeg, timeout=120):
        self.dir = Path(cache_dir)
        self.ffmpeg = ffmpeg
        self.timeout = timeout
        self._queue = queue.Queue()
        self._queued = set()
        self._failed = set()
        self._lock = threading.Lock()
        self._worker = None

    def key(self, entry):
        raw = f"{entry['path']}|{entry.get('size')}|{entry.get('mtime')}"
        return sha1(raw.encode("utf-8")).hexdigest()[:20]

    def target(self, entry):
        return self.dir / f"{self.key(entry)}.jpg"

    def status(self, entry):
        """Return ("ready", path) | ("queued", None) | ("unavailable", None)."""
        target = self.target(entry)
        try:
            if target.stat().st_size > 0:
                return "ready", target
        except OSError:
            pass
        if not self.ffmpeg:
            return "unavailable", None
        key = self.key(entry)
        with self._lock:
            if key in self._failed:
                return "unavailable", None
            if key not in self._queued:
                self._queued.add(key)
                self._queue.put(dict(entry))
            self._ensure_worker()
        return "queued", None

    def pending(self):
        with self._lock:
            return len(self._queued)

    def _ensure_worker(self):
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._run, name="filmstrips", daemon=True)
            self._worker.start()

    def _run(self):
        while True:
            entry = self._queue.get()
            key = self.key(entry)
            ok = False
            try:
                ok = self.render(entry)
            except Exception as error:  # never let one clip stop the queue
                print(f"[wangp-video-browser] filmstrip failed: {error}")
            with self._lock:
                self._queued.discard(key)
                if not ok:
                    self._failed.add(key)

    def render(self, entry):
        self.dir.mkdir(parents=True, exist_ok=True)
        target = self.target(entry)
        partial = target.with_suffix(".part.jpg")
        duration = (entry.get("probe") or {}).get("duration") or 0
        try:
            subprocess.run(build_command(self.ffmpeg, entry["path"], partial, duration),
                           capture_output=True, timeout=self.timeout, check=False)
        except (OSError, subprocess.SubprocessError):
            return False
        try:
            if partial.stat().st_size > 0:
                os.replace(partial, target)
                return True
        except OSError:
            pass
        return False
