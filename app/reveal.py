"""
Show a clip in the OS file manager, with the file itself selected where the
platform allows it.

The server only listens on 127.0.0.1, so this always means "ask this machine's
desktop" - nothing is read, copied or moved (C4). Candidates are tried best
first: on Linux the freedesktop FileManager1 D-Bus interface both opens the
folder and highlights the file; `xdg-open` / `gio` can only open the folder, so
they are the fallback. Every failure comes back as a `RevealError` with a
readable reason, so the UI can put the path on the clipboard instead of
pretending a window opened.

Standard library only (C1).
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# How long to watch an opener for an immediate failure (unknown URI scheme, no
# desktop session...). A file manager still starting after this counts as
# success - it shows the folder a moment later.
WAIT_SECONDS = 1.5


class RevealError(RuntimeError):
    """The clip could not be shown; the message says why."""


def _folder_of(path):
    path = Path(path)
    return path if path.is_dir() else path.parent


def _uri(path):
    return Path(path).absolute().as_uri()


def reveal_candidates(path, platform=None, which=shutil.which):
    """`[(argv, selects_file)]`, best first, for this platform.

    `selects_file` is True when the file manager highlights the clip instead of
    only opening the folder around it.
    """
    path = Path(path)
    platform = sys.platform if platform is None else platform
    if not path.exists():
        raise RevealError(f"no such file or folder: {path}")
    folder = _folder_of(path)
    file_is_real = path.is_file()

    if platform.startswith("win"):
        # explorer /select, opens the folder with the file highlighted.
        return [(["explorer", f"/select,{path}"], True)]
    if platform == "darwin":
        return [(["open", "-R", str(path)], True)] if file_is_real else [(["open", str(folder)], False)]
    if not platform.startswith("linux"):
        raise RevealError(f"showing a folder is not supported on {platform}")

    candidates = []
    if file_is_real and which("dbus-send"):
        # Nautilus, Dolphin, Nemo, Caja and Thunar all implement ShowItems; the
        # call fails fast (and we fall through) when none of them owns the name.
        # The URI must NOT be wrapped in extra quotes: dbus-send would hand the
        # file manager a value starting with a quote, which is not a URI, and
        # Nautilus answers with its "Oops! Something went wrong" alert. A
        # percent-encoded URI has no spaces, so it needs no quoting at all.
        candidates.append((
            [which("dbus-send"), "--session", "--print-reply",
             "--dest=org.freedesktop.FileManager1", "--type=method_call",
             "/org/freedesktop/FileManager1",
             "org.freedesktop.FileManager1.ShowItems",
             f"array:string:{_uri(path)}", 'string:""'],
            True,
        ))
    if which("xdg-open"):
        candidates.append(([which("xdg-open"), str(folder)], False))
    elif which("gio"):
        candidates.append(([which("gio"), "open", str(folder)], False))
    if not candidates:
        raise RevealError("no file manager opener found (install xdg-utils or gio)")
    return candidates


def check_session(env=None, platform=None):
    """Linux needs a desktop session; a server started over SSH or from a TTY
    has none, and the openers would fail with a confusing message."""
    platform = sys.platform if platform is None else platform
    env = os.environ if env is None else env
    if platform.startswith("linux") and not env.get("DISPLAY") and not env.get("WAYLAND_DISPLAY"):
        raise RevealError("no desktop session on this machine (DISPLAY/WAYLAND_DISPLAY unset)")


def child_env(env=None):
    """Environment for the opener.

    Launchers (Pinokio, systemd units) often start the server without
    DBUS_SESSION_BUS_ADDRESS even though the user is logged in on a desktop;
    dbus-send cannot reach org.freedesktop.FileManager1 without it. The session
    bus socket is at a fixed path per user, so point at it when it exists.
    """
    env = dict(os.environ if env is None else env)
    if sys.platform.startswith("linux") and not env.get("DBUS_SESSION_BUS_ADDRESS"):
        socket = Path(f"/run/user/{os.getuid()}/bus")
        if socket.exists():
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={socket}"
    return env


def open_folder(path, platform=None, env=None, which=shutil.which, popen=None):
    """Show `path` in the file manager; returns `(folder, selected_file)`."""
    check_session(env, platform)
    path = Path(path)
    folder = _folder_of(path)
    popen = subprocess.Popen if popen is None else popen
    errors = []
    child = child_env(env)

    for argv, selects in reveal_candidates(path, platform, which):
        try:
            proc = popen(argv, env=child, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                         start_new_session=True)
        except OSError as error:
            errors.append(str(error))
            continue
        try:
            _, err = proc.communicate(timeout=WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            return folder, selects          # still running: it is opening
        if proc.returncode == 0:
            return folder, selects
        lines = (err or b"").decode("utf-8", "replace").strip().splitlines()
        errors.append(lines[-1] if lines else f"{Path(argv[0]).name} exited with {proc.returncode}")

    raise RevealError(errors[-1] if errors else "no way to show the folder")
