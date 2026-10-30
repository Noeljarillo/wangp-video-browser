"""
Show a clip's folder in the OS file manager.

The server only listens on 127.0.0.1, so "open the folder" always means "ask
this machine's desktop to show it" - nothing is read, copied or moved (C4).
Every failure comes back as a `RevealError` with a readable reason, so the UI
can fall back to putting the path on the clipboard instead of pretending the
window opened.

Standard library only (C1).
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# How long to watch the opener for an immediate failure (unknown URI scheme,
# no desktop session...). A file manager that is still starting after this is
# treated as success - it will show the folder a moment later.
WAIT_SECONDS = 1.5


class RevealError(RuntimeError):
    """The folder could not be shown; the message says why."""


def _folder_of(path):
    path = Path(path)
    return path if path.is_dir() else path.parent


def reveal_command(path, platform=None, which=shutil.which):
    """The argv that shows `path` (or the folder holding it) in a file manager.

    Windows and macOS can highlight the file itself; the freedesktop openers
    only take a folder, which is what "open the folder containing the video"
    asks for anyway.
    """
    path = Path(path)
    platform = sys.platform if platform is None else platform
    if not path.exists():
        raise RevealError(f"no such file or folder: {path}")
    folder = _folder_of(path)

    if platform.startswith("win"):
        return ["explorer", f"/select,{path}"] if path.is_file() else ["explorer", str(folder)]
    if platform == "darwin":
        return ["open", "-R", str(path)] if path.is_file() else ["open", str(folder)]
    if platform.startswith("linux"):
        if which("xdg-open"):
            return [which("xdg-open"), str(folder)]
        if which("gio"):
            return [which("gio"), "open", str(folder)]
        raise RevealError("no file manager opener found (install xdg-utils or gio)")
    raise RevealError(f"opening a folder is not supported on {platform}")


def check_session(env=None, platform=None):
    """Linux needs a desktop session; a server started over SSH or from a TTY
    has none, and xdg-open would fail with a confusing message."""
    platform = sys.platform if platform is None else platform
    env = os.environ if env is None else env
    if platform.startswith("linux") and not env.get("DISPLAY") and not env.get("WAYLAND_DISPLAY"):
        raise RevealError("no desktop session on this machine (DISPLAY/WAYLAND_DISPLAY unset)")


def open_folder(path, platform=None, env=None, which=shutil.which, popen=None):
    """Show `path` in the OS file manager; returns the folder that was opened."""
    check_session(env, platform)
    path = Path(path)
    argv = reveal_command(path, platform, which)
    folder = _folder_of(path)
    popen = subprocess.Popen if popen is None else popen
    try:
        proc = popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
    except OSError as error:
        raise RevealError(str(error)) from error
    try:
        _, err = proc.communicate(timeout=WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        return folder
    if proc.returncode:
        lines = (err or b"").decode("utf-8", "replace").strip().splitlines()
        raise RevealError(lines[-1] if lines else f"the file manager exited with {proc.returncode}")
    return folder
