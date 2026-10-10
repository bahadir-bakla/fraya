import pathlib, subprocess, sys, tempfile, unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from builder import slot_lock


class SlotLockTests(unittest.TestCase):
    def test_competing_process_cannot_take_owned_slot_then_can_after_release(self):
        with tempfile.TemporaryDirectory() as directory:
            path=pathlib.Path(directory)/'slot.lock'
            script="import sys; sys.path.insert(0,sys.argv[1]); from builder import slot_lock\ntry:\n with slot_lock(sys.argv[2]): pass\nexcept BlockingIOError: sys.exit(3)"
            command=[sys.executable,'-B','-c',script,str(ROOT),str(path)]
            with slot_lock(path):
                self.assertEqual(subprocess.run(command,capture_output=True,timeout=5).returncode,3)
            self.assertEqual(subprocess.run(command,capture_output=True,timeout=5).returncode,0)

    def test_exception_releases_the_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path=pathlib.Path(directory)/'slot.lock'
            with self.assertRaises(ValueError):
                with slot_lock(path):raise ValueError('stopped')
            with slot_lock(path):pass


if __name__=='__main__':unittest.main()
