"""
Live watch folder (P1.5): a stdlib polling thread plus a tiny SSE hub.

Polling is kept cheap: every tick only the *directories* are stat'ed. A
directory is re-listed with ``os.scandir`` only when its mtime changed (a file
was created, renamed or deleted in it). New files are reported once their
size and mtime held still for one tick, so half-written renders are not
indexed. Nothing here touches the video files except ``stat`` (C4).
"""

import json
import os
import queue
import threading


class EventHub:
    """Fan-out of JSON events to any number of SSE subscribers."""

    def __init__(self, backlog=64):
        self._lock = threading.Lock()
        self._subs = set()
        self._backlog = backlog

    def subscribe(self):
        q = queue.Queue(maxsize=self._backlog)
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            self._subs.discard(q)

    def publish(self, event):
        data = json.dumps(event)
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(data)
            except queue.Full:   # a stalled client loses events, never blocks us
                pass

    def count(self):
        with self._lock:
            return len(self._subs)


def serve_sse(handler, hub, keepalive=15.0, stop=None):
    """Stream events to one HTTP client until it disconnects.

    Runs inside the request's own ThreadingHTTPServer thread, so it never
    blocks other requests.
    """
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "close")
    handler.send_header("X-Accel-Buffering", "no")
    handler.end_headers()
    handler.close_connection = True
    q = hub.subscribe()
    try:
        handler.wfile.write(b"retry: 3000\n: connected\n\n")
        handler.wfile.flush()
        while not (stop and stop.is_set()):
            try:
                data = q.get(timeout=keepalive)
                chunk = f"data: {data}\n\n"
            except queue.Empty:
                chunk = ": ping\n\n"
            handler.wfile.write(chunk.encode("utf-8"))
            handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
        pass
    finally:
        hub.unsubscribe(q)


class FolderWatcher:
    """Poll a set of roots and report added / removed video files.

    ``roots_fn()`` returns the current roots; ``on_change(added, removed)``
    receives lists of ``(path, root)`` tuples and path strings.
    """

    def __init__(self, roots_fn, on_change, extensions, skip_dirs=(), interval=2.0):
        self.roots_fn = roots_fn
        self.on_change = on_change
        self.extensions = tuple(e.lower() for e in extensions)
        self.skip_dirs = set(skip_dirs)
        self.interval = interval
        self._dirs = {}      # dir path -> (mtime_ns, root, {file names}, [subdirs])
        self._pending = {}   # file path -> (size, mtime_ns, root)
        self._roots = ()
        self._rootset = set()
        self._stop = threading.Event()
        self._thread = None

    # -- scanning -----------------------------------------------------------
    def _wanted_dir(self, name):
        return name not in self.skip_dirs and not name.startswith(".")

    def _wanted_file(self, name):
        return not name.startswith(".") and name.lower().endswith(self.extensions)

    def _list(self, path):
        files, subdirs = set(), []
        try:
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if self._wanted_dir(entry.name):
                                subdirs.append(entry.path)
                        elif self._wanted_file(entry.name):
                            files.add(entry.name)
                    except OSError:
                        continue
        except OSError:
            return None
        return files, subdirs

    def _walk(self, path, root, added, removed, baseline):
        try:
            mtime = os.stat(path).st_mtime_ns
        except OSError:
            self._drop(path, removed)
            return
        known = self._dirs.get(path)
        if known and known[0] == mtime:
            subdirs = known[3]
        else:
            listed = self._list(path)
            if listed is None:
                self._drop(path, removed)
                return
            files, subdirs = listed
            old_files = known[2] if known else set()
            if not baseline:
                for name in files - old_files:
                    full = os.path.join(path, name)
                    if full not in self._pending:
                        try:
                            st = os.stat(full)
                            self._pending[full] = (st.st_size, st.st_mtime_ns, root)
                        except OSError:
                            pass
                for name in old_files - files:
                    full = os.path.join(path, name)
                    if self._pending.pop(full, None) is None:
                        removed.append(full)
                for gone in set(known[3] if known else []) - set(subdirs):
                    self._drop(gone, removed)
            self._dirs[path] = (mtime, root, files, subdirs)
        for sub in subdirs:
            if sub not in self._rootset:   # a nested root owns its own subtree
                self._walk(sub, root, added, removed, baseline)

    def _drop(self, path, removed):
        """Forget a vanished directory and everything below it."""
        prefix = path + os.sep
        for dpath in [d for d in self._dirs if d == path or d.startswith(prefix)]:
            _, _, files, _ = self._dirs.pop(dpath)
            for name in files:
                full = os.path.join(dpath, name)
                if self._pending.pop(full, None) is None:
                    removed.append(full)

    def _settle(self, added):
        """Promote pending files whose size/mtime held still since last tick."""
        for path, (size, mtime, root) in list(self._pending.items()):
            try:
                st = os.stat(path)
            except OSError:
                self._pending.pop(path, None)
                continue
            if st.st_size > 0 and (st.st_size, st.st_mtime_ns) == (size, mtime):
                self._pending.pop(path, None)
                added.append((path, root))
            else:
                self._pending[path] = (st.st_size, st.st_mtime_ns, root)

    def tick(self):
        """One poll. Returns (added, removed); also calls on_change if any."""
        roots = tuple(sorted({str(r) for r in self.roots_fn()}, key=len, reverse=True))
        added, removed = [], []
        if roots != self._roots:
            # Roots changed (added/removed in the UI): the server rescans then,
            # so just re-baseline silently.
            self._dirs.clear()
            self._pending.clear()
            self._roots = roots
            self._rootset = set(roots)
            for root in roots:
                self._walk(root, root, added, removed, True)
            return [], []
        self._settle(added)
        for root in roots:
            self._walk(root, root, added, removed, root not in self._dirs)
        seen = set()
        added = [(p, r) for p, r in added if not (p in seen or seen.add(p))]
        if added or removed:
            try:
                self.on_change(added, removed)
            except Exception as error:  # never let a bad file kill the watcher
                print(f"[wangp-video-browser] watcher: {error}")
        return added, removed

    # -- thread -------------------------------------------------------------
    def start(self):
        if self._thread:
            return self
        self._thread = threading.Thread(target=self._run, name="folder-watcher", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as error:
                print(f"[wangp-video-browser] watcher: {error}")
            self._stop.wait(self.interval)
