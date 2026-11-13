#!/usr/bin/env python3
"""Keep the pinned egress client connected across host restarts."""
import os
from pathlib import Path
import signal
import subprocess
import threading
import time


def stop_client(client):
    # remote.sh owns its lock and child. Give its EXIT trap time to clean up.
    try:
        os.killpg(client.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        client.wait(timeout=8)
    except subprocess.TimeoutExpired:
        os.killpg(client.pid, signal.SIGKILL)
        client.wait()


def supervise(command, stopped, interval=10, grace=30, retry=5):
    while not stopped.is_set():
        client = subprocess.Popen(command, start_new_session=True)
        started = time.monotonic()
        failures = 0
        try:
            while not stopped.wait(interval):
                if client.poll() is not None:
                    print('Egress client exited; reconnecting.', flush=True)
                    break
                if time.monotonic() - started < grace:
                    continue
                try:
                    check = subprocess.run(
                        command + ['check'], stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=8,
                    )
                    healthy = check.returncode == 0
                except subprocess.TimeoutExpired:
                    healthy = False
                failures = 0 if healthy else failures + 1
                if failures >= 3:
                    print('Egress failed three health checks; reconnecting.', flush=True)
                    break
        finally:
            stop_client(client)
        stopped.wait(retry)


def main():
    repo = Path(__file__).resolve().parent.parent
    state = os.environ.get('WEBSTUDIO_AGENT_STATE_DIR',
                           str(repo.parent / '.webstudio-agent-home'))
    os.environ.setdefault('EGRESS_STATE_DIR', str(Path(state) / 'egress'))
    stopped = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: stopped.set())
    supervise(['bash', str(repo / 'vendor/codex-local-egress/remote.sh')], stopped)


if __name__ == '__main__':
    main()
