"""Runtime evidence shared by the scheduler and the two dashboards."""

from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import sys
import threading
import time

HEARTBEAT_INTERVAL = 15
HEARTBEAT_MAX_AGE = 45


def _read_json(path):
    try:
        with path.open(encoding='utf-8') as stream:
            data = json.load(stream)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


@contextmanager
def scheduler_heartbeat(project_root, interval=HEARTBEAT_INTERVAL):
    """Call only after acquiring the scheduler lock; never run any jobs here."""
    path = Path(project_root) / 'dashboard' / 'scheduler_heartbeat.json'
    temporary = path.with_suffix('.json.tmp')
    started_at = time.time()
    stop = threading.Event()

    def write(running):
        try:
            with temporary.open('w', encoding='utf-8') as stream:
                json.dump({'running': running, 'pid': os.getpid(),
                           'started_at': started_at, 'heartbeat_at': time.time()}, stream)
            os.replace(temporary, path)
        except OSError as exc:
            print(f'[WARN] Scheduler heartbeat: {type(exc).__name__}', file=sys.stderr)

    def pulse():
        while not stop.wait(interval):
            write(True)

    write(True)
    worker = threading.Thread(target=pulse, name='scheduler-heartbeat', daemon=True)
    worker.start()
    try:
        yield
    finally:
        stop.set()
        worker.join()
        write(False)


def read_scheduler_status(project_root):
    """An old task status is not evidence of a live scheduler.

    Abrupt termination is detected within HEARTBEAT_MAX_AGE seconds. Older
    schedulers without this heartbeat need a controlled restart to be verified.
    """
    directory = Path(project_root) / 'dashboard'
    heartbeat = _read_json(directory / 'scheduler_heartbeat.json')
    status_path = directory / 'scheduler_status.json'
    status = _read_json(status_path)
    stamp = heartbeat.get('heartbeat_at')
    started_at = heartbeat.get('started_at')
    pid = heartbeat.get('pid')
    valid_times = all(type(value) in (int, float) and math.isfinite(value)
                      for value in (stamp, started_at))
    running = (heartbeat.get('running') is True and valid_times
               and type(pid) is int and pid > 0
               and started_at <= stamp
               and 0 <= time.time() - stamp <= HEARTBEAT_MAX_AGE)
    if not running:
        return {'state': 'offline', 'running': False, 'pid': '',
                'detail': 'Sem heartbeat atual: scheduler parado ou precisa reiniciar',
                'updated_at': '', 'video_id': '', 'clip_id': '',
                'clip_title': '', 'step': ''}
    try:
        status_current = status_path.stat().st_mtime >= started_at
    except OSError:
        status_current = False
    if not status_current or not isinstance(status.get('state'), str):
        status = {'state': 'starting', 'detail': 'Scheduler ativo; aguardando status',
                  'updated_at': '', 'video_id': '', 'clip_id': '',
                  'clip_title': '', 'step': ''}
    return {**status, 'running': True, 'pid': pid}
