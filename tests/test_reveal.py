import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import reveal  # noqa: E402


class FakeProc:
    def __init__(self, code=0, err=b"", hang=False):
        self.returncode = code
        self._err = err
        self._hang = hang

    def communicate(self, timeout=None):
        if self._hang:
            raise subprocess.TimeoutExpired(cmd="opener", timeout=timeout)
        return (b"", self._err)


class RevealCandidatesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.clip = self.dir / "clips" / "a & b.mp4"
        self.clip.parent.mkdir()
        self.clip.write_bytes(b"x")

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_path_is_reported(self):
        with self.assertRaises(reveal.RevealError):
            reveal.reveal_candidates(self.dir / "nope.mp4", "linux", which=lambda name: "/usr/bin/" + name)

    def test_linux_prefers_dbussend_and_selects_the_file(self):
        candidates = reveal.reveal_candidates(self.clip, "linux", which=lambda name: "/usr/bin/" + name)
        argv, selects = candidates[0]
        self.assertTrue(selects)
        self.assertEqual(argv[:7], ["/usr/bin/dbus-send", "--session", "--print-reply",
                                    "--dest=org.freedesktop.FileManager1", "--type=method_call",
                                    "/org/freedesktop/FileManager1",
                                    "org.freedesktop.FileManager1.ShowItems"])
        # the URI is percent-encoded and NOT quoted: a leading quote makes the
        # file manager reject it ("Oops! Something went wrong")
        self.assertEqual(argv[7], "array:string:file://" + str(self.clip).replace(" ", "%20").replace("&", "%26"))
        self.assertNotIn('"', argv[7])
        self.assertEqual(argv[8], 'string:""')
        # and xdg-open is still there as the folder-only fallback
        self.assertEqual(candidates[1], (["/usr/bin/xdg-open", str(self.clip.parent)], False))

    def test_linux_without_dbussend_opens_the_folder(self):
        which = lambda name: "/usr/bin/xdg-open" if name == "xdg-open" else None
        self.assertEqual(reveal.reveal_candidates(self.clip, "linux", which=which),
                         [(["/usr/bin/xdg-open", str(self.clip.parent)], False)])

    def test_linux_falls_back_to_gio(self):
        which = lambda name: "/usr/bin/gio" if name == "gio" else None
        self.assertEqual(reveal.reveal_candidates(self.clip.parent, "linux", which=which),
                         [(["/usr/bin/gio", "open", str(self.clip.parent)], False)])

    def test_linux_without_an_opener_raises(self):
        with self.assertRaises(reveal.RevealError):
            reveal.reveal_candidates(self.clip, "linux", which=lambda name: None)

    def test_macos_selects_the_file(self):
        self.assertEqual(reveal.reveal_candidates(self.clip, "darwin"), [(["open", "-R", str(self.clip)], True)])
        self.assertEqual(reveal.reveal_candidates(self.clip.parent, "darwin"),
                         [(["open", str(self.clip.parent)], False)])

    def test_windows_selects_the_file(self):
        self.assertEqual(reveal.reveal_candidates(self.clip, "win32"),
                         [(["explorer", f"/select,{self.clip}"], True)])

    def test_unknown_platform_raises(self):
        with self.assertRaises(reveal.RevealError):
            reveal.reveal_candidates(self.clip, "sunos5")

    def test_headless_linux_is_rejected(self):
        with self.assertRaises(reveal.RevealError):
            reveal.check_session({}, "linux")
        reveal.check_session({"DISPLAY": ":0"}, "linux")      # no raise
        reveal.check_session({"WAYLAND_DISPLAY": "wayland-0"}, "linux")
        reveal.check_session({}, "darwin")                    # not a Linux concern


class OpenFolderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.clip = self.dir / "a.mp4"
        self.clip.write_bytes(b"x")
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def _open(self, procs, env=None, which=lambda name: "/usr/bin/" + name):
        """`procs` is one FakeProc (reused) or a list, one per candidate."""
        queue = list(procs) if isinstance(procs, list) else [procs]

        def popen(argv, **kwargs):
            self.calls.append((argv, kwargs))
            return queue[min(len(self.calls) - 1, len(queue) - 1)]

        return reveal.open_folder(self.clip, "linux", env if env is not None else {"DISPLAY": ":0"},
                                  which=which, popen=popen)

    def test_returns_selected_when_the_file_manager_can_highlight_it(self):
        folder, selected = self._open(FakeProc(code=0))
        self.assertEqual(folder, self.clip.parent)
        self.assertTrue(selected)
        argv, kwargs = self.calls[0]
        self.assertEqual(argv[0], "/usr/bin/dbus-send")
        self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(kwargs["stderr"], reveal.subprocess.PIPE)
        # a launcher may start the server without the session bus address
        self.assertIn("env", kwargs)

    def test_session_bus_is_discovered_when_missing(self):
        # A launcher-started server has no DBUS_SESSION_BUS_ADDRESS; the socket
        # at /run/user/<uid>/bus is where the session bus always is.
        env = reveal.child_env({})
        if Path(f"/run/user/{os.getuid()}/bus").exists():
            self.assertEqual(env["DBUS_SESSION_BUS_ADDRESS"], f"unix:path=/run/user/{os.getuid()}/bus")
        else:
            self.assertNotIn("DBUS_SESSION_BUS_ADDRESS", env)
        # an explicit address is never overwritten
        given = {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus,guid=abc"}
        self.assertEqual(reveal.child_env(given)["DBUS_SESSION_BUS_ADDRESS"], given["DBUS_SESSION_BUS_ADDRESS"])
        self.assertEqual(given, {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus,guid=abc"})

    def test_falls_back_to_folder_only_when_the_bus_call_fails(self):
        folder, selected = self._open([FakeProc(code=1, err=b"Failed to connect to socket\n"),
                                       FakeProc(code=0)])
        self.assertEqual(folder, self.clip.parent)
        self.assertFalse(selected)
        self.assertEqual([call[0][0] for call in self.calls], ["/usr/bin/dbus-send", "/usr/bin/xdg-open"])

    def test_opener_still_running_counts_as_opened(self):
        self.assertEqual(self._open(FakeProc(hang=True)), (self.clip.parent, True))

    def test_all_candidates_failing_reports_the_last_reason(self):
        with self.assertRaises(reveal.RevealError) as ctx:
            self._open(FakeProc(code=3, err=b"warning\nxdg-open: no method available\n"))
        self.assertIn("no method available", str(ctx.exception))

    def test_failure_without_stderr_still_explains(self):
        with self.assertRaises(reveal.RevealError) as ctx:
            self._open(FakeProc(code=1))
        self.assertIn("exited with 1", str(ctx.exception))

    def test_spawn_error_falls_through_to_the_next_candidate(self):
        first = {"done": False}

        def popen(argv, **kwargs):
            self.calls.append((argv, kwargs))
            if not first["done"]:
                first["done"] = True
                raise OSError("exec format error")
            return FakeProc(code=0)

        folder, selected = reveal.open_folder(self.clip, "linux", {"DISPLAY": ":0"},
                                              which=lambda name: "/usr/bin/" + name, popen=popen)
        self.assertEqual((folder, selected), (self.clip.parent, False))


if __name__ == "__main__":
    unittest.main()
