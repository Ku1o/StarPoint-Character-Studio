"""Focused, no-UI regressions for the desktop ownership and save-before-close gate."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop_host import CloseGate, WindowsInstance, instance_key


class DesktopTests(unittest.TestCase):
    def test_close_requires_success_and_cancel_allows_retry(self):
        called = threading.Event()
        gate = CloseGate(called.set)
        self.assertFalse(gate.request())
        self.assertTrue(called.wait(2))
        self.assertTrue(gate.pending)
        self.assertFalse(gate.request())
        gate.cancel()
        self.assertFalse(gate.pending)
        self.assertFalse(gate.request())
        gate.allowed = True
        self.assertTrue(gate.request())

    @unittest.skipUnless(os.name == "nt", "Windows kernel mutex")
    def test_one_owner_activation_and_crash_recovery(self):
        with tempfile.TemporaryDirectory(prefix="studio-desktop-lock-") as folder:
            projects = Path(folder) / "projects"
            owner = WindowsInstance(projects)
            duplicate = WindowsInstance(projects)
            independent = WindowsInstance(Path(folder) / "other-projects")
            try:
                self.assertTrue(owner.owner)
                self.assertFalse(duplicate.owner)
                self.assertTrue(independent.owner)
                duplicate.notify_existing(wait_seconds=0)
                self.assertTrue(owner.wait_activation(100))
            finally:
                duplicate.close()
                independent.close()
                owner.close()
            restarted = WindowsInstance(projects)
            self.assertTrue(restarted.owner)
            restarted.close()
            # An abruptly exiting previous owner leaves no persistent lock file.
            code = "import sys,os;sys.path.insert(0,sys.argv[1]);from desktop_host import WindowsInstance;x=WindowsInstance(sys.argv[2]);assert x.owner;os._exit(0)"
            subprocess.run([sys.executable, "-c", code, str(Path(__file__).resolve().parents[1]), str(projects)],
                           check=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            recovered = WindowsInstance(projects)
            self.assertTrue(recovered.owner)
            recovered.close()

    def test_directory_identity_is_canonical(self):
        self.assertEqual(instance_key(Path("example") / ".." / "projects"), instance_key(Path("projects")))


if __name__ == "__main__":
    unittest.main()
