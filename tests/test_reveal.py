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
            raise subprocess.TimeoutExpired(cmd="xdg-open", timeout=timeout)
        return (b"", self._err)


class RevealCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.clip = self.dir / "clips" / "a.mp4"
        self.clip.parent.mkdir()
        self.clip.write_bytes(b"x")

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_path_is_reported(self):
        with self.assertRaises(reveal.RevealError):
            reveal.reveal_command(self.dir / "nope.mp4", "linux", which=lambda name: "/usr/bin/" + name)

    def test_linux_opens_the_containing_folder(self):
        argv = reveal.reveal_command(self.clip, "linux", which=lambda name: "/usr/bin/" + name)
        self.assertEqual(argv, ["/usr/bin/xdg-open", str(self.clip.parent)])

    def test_linux_falls_back_to_gio(self):
        which = lambda name: "/usr/bin/gio" if name == "gio" else None
        argv = reveal.reveal_command(self.clip.parent, "linux", which=which)
        self.assertEqual(argv, ["/usr/bin/gio", "open", str(self.clip.parent)])

    def test_linux_without_an_opener_raises(self):
        with self.assertRaises(reveal.RevealError):
            reveal.reveal_command(self.clip, "linux3", which=lambda name: None)

    def test_macos_selects_the_file(self):
        self.assertEqual(reveal.reveal_command(self.clip, "darwin"), ["open", "-R", str(self.clip)])

    def test_windows_selects_the_file(self):
        self.assertEqual(reveal.reveal_command(self.clip, "win32"),
                         ["explorer", f"/select,{self.clip}"])

    def test_unknown_platform_raises(self):
        with self.assertRaises(reveal.RevealError):
            reveal.reveal_command(self.clip, "sunos5")

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

    def _open(self, proc, env=None, which=lambda name: "/usr/bin/" + name):
        def popen(argv, **kwargs):
            self.calls.append((argv, kwargs))
            return proc
        return reveal.open_folder(self.clip, "linux", env if env is not None else {"DISPLAY": ":0"},
                                  which=which, popen=popen)

    def test_returns_the_folder_and_detaches(self):
        folder = self._open(FakeProc(code=0))
        self.assertEqual(folder, self.clip.parent)
        argv, kwargs = self.calls[0]
        self.assertEqual(argv, ["/usr/bin/xdg-open", str(self.clip.parent)])
        self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(kwargs["stderr"], reveal.subprocess.PIPE)

    def test_opener_still_running_counts_as_opened(self):
        self.assertEqual(self._open(FakeProc(hang=True)), self.clip.parent)

    def test_failure_message_surfaces_stderr(self):
        with self.assertRaises(reveal.RevealError) as ctx:
            self._open(FakeProc(code=3, err=b"warning\nxdg-open: no method available\n"))
        self.assertIn("no method available", str(ctx.exception))

    def test_failure_without_stderr_still_explains(self):
        with self.assertRaises(reveal.RevealError) as ctx:
            self._open(FakeProc(code=1))
        self.assertIn("exited with 1", str(ctx.exception))

    def test_spawn_error_becomes_reveal_error(self):
        def boom(argv, **kwargs):
            raise OSError("exec format error")
        with self.assertRaises(reveal.RevealError):
            reveal.open_folder(self.clip, "linux", {"DISPLAY": ":0"},
                               which=lambda name: "/usr/bin/" + name, popen=boom)


if __name__ == "__main__":
    unittest.main()
