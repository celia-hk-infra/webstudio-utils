import importlib.util
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest


SPEC = importlib.util.spec_from_file_location(
    'egress_supervisor', Path(__file__).resolve().parents[1] / 'scripts/egress_supervisor.py')
supervisor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(supervisor)


class RecoveryTests(unittest.TestCase):
    def exercise(self, failure):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / 'client.py'
            fake.write_text('''
import pathlib, signal, sys, time
root = pathlib.Path(__file__).parent
count = root / 'starts'
if sys.argv[-1] == 'check':
    sys.exit(0 if int(count.read_text()) >= 2 else 1)
n = int(count.read_text()) + 1 if count.exists() else 1
count.write_text(str(n))
def stop(*_):
    (root / ('stopped-' + str(n))).touch()
    sys.exit(0)
signal.signal(signal.SIGTERM, stop)
if n == 1 and sys.argv[1] == 'exit':
    sys.exit(1)
while True:
    time.sleep(.01)
''')
            stopped = threading.Event()
            worker = threading.Thread(target=supervisor.supervise,
                args=([sys.executable, str(fake), failure], stopped),
                kwargs=dict(interval=.05, grace=.1, retry=.02))
            worker.start()
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if (root / 'starts').exists() and (root / 'starts').read_text() == '2':
                        break
                    time.sleep(.02)
                self.assertEqual((root / 'starts').read_text(), '2')
                time.sleep(.4)
                self.assertEqual((root / 'starts').read_text(), '2', 'healthy client restarted')
                if failure == 'stall':
                    self.assertTrue((root / 'stopped-1').exists())
            finally:
                stopped.set()
                worker.join(timeout=10)
            self.assertFalse(worker.is_alive())
            self.assertTrue((root / 'stopped-2').exists())

    def test_restarts_exited_client(self):
        self.exercise('exit')

    def test_restarts_stalled_client_and_stops_cleanly(self):
        self.exercise('stall')
