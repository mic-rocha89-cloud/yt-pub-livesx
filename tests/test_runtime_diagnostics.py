import ast
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

import runtime_status

ROOT = Path(__file__).resolve().parents[1]


def load_server(directory):
    spec = importlib.util.spec_from_file_location(directory.replace('-', '_'),
                                                ROOT / directory / 'server.py')
    module = importlib.util.module_from_spec(spec)
    real_open = open

    def isolated_open(file, *args, **kwargs):
        if Path(file).name == 'instances.json':
            return io.StringIO('[]')
        return real_open(file, *args, **kwargs)

    with tempfile.TemporaryDirectory() as config:
        with patch.dict(os.environ, {'GWS_CONFIG_DIR': config}):
            with patch('builtins.open', side_effect=isolated_open):
                spec.loader.exec_module(module)
    return module


class SchedulerStatusTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / 'dashboard').mkdir()
        self.status = self.root / 'dashboard' / 'scheduler_status.json'
        self.heartbeat = self.root / 'dashboard' / 'scheduler_heartbeat.json'

    def write_heartbeat(self, **overrides):
        data = {'running': True, 'pid': 123, 'started_at': time.time() - 3600,
                'heartbeat_at': time.time()}
        data.update(overrides)
        self.heartbeat.write_text(json.dumps(data), encoding='utf-8')

    def test_missing_heartbeat_is_offline_even_with_old_idle_status(self):
        self.status.write_text('{"state":"idle","detail":"Scheduler iniciado"}')
        status = runtime_status.read_scheduler_status(self.root)
        self.assertFalse(status['running'])
        self.assertEqual(status['state'], 'offline')
        self.assertFalse(self.heartbeat.exists())

    def test_stale_stopped_future_and_malformed_heartbeat_fail_closed(self):
        for data in [dict(heartbeat_at=time.time() - 46), dict(running=False),
                     dict(heartbeat_at=time.time() + 60), dict(heartbeat_at='invalid'),
                     dict(heartbeat_at=float('nan')), dict(pid='123'),
                     dict(running='true'), dict(started_at=time.time() + 60)]:
            with self.subTest(data=data):
                self.write_heartbeat(**data)
                self.assertFalse(runtime_status.read_scheduler_status(self.root)['running'])
        for text in ['{', '[]', 'null']:
            self.heartbeat.write_text(text)
            self.assertFalse(runtime_status.read_scheduler_status(self.root)['running'])

    def test_long_task_remains_running_with_fresh_heartbeat(self):
        self.status.write_text('{"state":"cortando","detail":"download longo"}')
        os.utime(self.status, (time.time() - 1800, time.time() - 1800))
        self.write_heartbeat()
        status = runtime_status.read_scheduler_status(self.root)
        self.assertTrue(status['running'])
        self.assertEqual(status['state'], 'cortando')

    def test_previous_process_status_is_not_reused(self):
        self.status.write_text('{"state":"publicando"}')
        os.utime(self.status, (1, 1))
        self.write_heartbeat()
        self.assertEqual(runtime_status.read_scheduler_status(self.root)['state'], 'starting')

    def test_active_process_with_missing_or_invalid_status(self):
        self.write_heartbeat()
        self.assertTrue(runtime_status.read_scheduler_status(self.root)['running'])
        for text in ['{', '[]', '{"state":123}']:
            self.status.write_text(text)
            self.assertEqual(runtime_status.read_scheduler_status(self.root)['state'], 'starting')

    def test_heartbeat_refreshes_without_running_jobs_and_stops(self):
        with runtime_status.scheduler_heartbeat(self.root, interval=0.01):
            first = json.loads(self.heartbeat.read_text())['heartbeat_at']
            deadline = time.monotonic() + 2
            while json.loads(self.heartbeat.read_text())['heartbeat_at'] == first:
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.01)
            self.assertTrue(runtime_status.read_scheduler_status(self.root)['running'])
        self.assertFalse(runtime_status.read_scheduler_status(self.root)['running'])

    def test_shutdown_after_exception_marks_offline(self):
        with self.assertRaises(RuntimeError):
            with runtime_status.scheduler_heartbeat(self.root):
                raise RuntimeError('simulated task failure')
        self.assertFalse(runtime_status.read_scheduler_status(self.root)['running'])

    def test_write_failure_does_not_start_jobs_or_claim_health(self):
        with patch.object(Path, 'open', side_effect=PermissionError), patch('sys.stderr', io.StringIO()):
            with runtime_status.scheduler_heartbeat(self.root):
                self.assertFalse(runtime_status.read_scheduler_status(self.root)['running'])

    def test_duplicate_scheduler_exits_without_reading_or_signalling_owner(self):
        tree = ast.parse((ROOT / 'scheduler.py').read_text(encoding='utf-8'))
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == 'acquire_lock')
        # Execute only the real lock function, never scheduler imports or main().
        code = ast.unparse(function)
        namespace = {'os': os, 'sys': sys, '__file__': str(self.root / 'scheduler.py')}
        exec(compile(code, 'scheduler-lock-test', 'exec'), namespace)
        owner = namespace['acquire_lock']()
        try:
            child = 'import os, sys\n__file__ = sys.argv[1]\n' + code + '\nlock = acquire_lock()\n'
            result = subprocess.run([sys.executable, '-c', child, namespace['__file__']],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertIn('Nao foi possivel adquirir o lock', result.stderr)
            self.assertNotIn('Traceback', result.stderr)
            owner.seek(0)
            self.assertEqual(owner.read(), str(os.getpid()))
        finally:
            owner.close()


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dashboard = load_server('dashboard')
        cls.master = load_server('master-dashboard')

    def test_dashboard_status_uses_shared_runtime_evidence(self):
        handler = object.__new__(self.dashboard.DashboardHandler)
        handler.send_json = MagicMock()
        status = {'running': False, 'state': 'offline'}
        with patch.object(self.dashboard, 'read_scheduler_status', return_value=status):
            handler.handle_scheduler_status()
        handler.send_json.assert_called_once_with(200, status)

    def test_health_no_longer_treats_stale_status_as_healthy(self):
        handler = object.__new__(self.dashboard.DashboardHandler)
        handler.send_json = MagicMock()
        cfg = {'ai_mode': 'openrouter-api', 'thumb_image_provider': 'minimax'}
        status = {'state': 'offline', 'running': False, 'detail': 'Sem heartbeat'}
        with tempfile.TemporaryDirectory() as config, \
                patch.object(self.dashboard, 'CONFIG_DIR', config), \
                patch.object(self.dashboard.db, 'load_config', return_value=cfg), \
                patch.object(self.dashboard.subprocess, 'run', return_value=MagicMock(returncode=0, stdout='test')), \
                patch.object(self.dashboard, 'youtube_api', return_value={'items': [{'snippet': {'title': 'test'}}]}), \
                patch.object(self.dashboard, 'read_scheduler_status', return_value=status):
            handler.handle_api_health()
        self.assertFalse(handler.send_json.call_args.args[1]['scheduler']['ok'])

    def test_local_dashboard_checks_expected_login_page(self):
        response = MagicMock(status=200)
        response.__enter__.return_value = response
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(self.master.urllib.request, 'build_opener', return_value=opener):
            for body, expected in [(b'<title>Login - YT Pub Lives</title>', 'running'),
                                   (b'another application', 'stopped')]:
                response.read.return_value = body
                self.assertEqual(self.master.get_local_dashboard_info(8091)['SubState'], expected)
            opener.open.side_effect = OSError
            self.assertEqual(self.master.get_local_dashboard_info(8091)['SubState'], 'stopped')
        opener.open.assert_called_with('http://127.0.0.1:8091/login', timeout=2)

    def test_windows_skips_systemctl(self):
        with patch.object(self.master.sys, 'platform', 'win32'), \
                patch.object(self.master.subprocess, 'run') as run:
            self.assertEqual(self.master.get_service_info('test.service'), {})
            run.assert_not_called()

    def test_master_windows_reports_runtime_and_linux_retains_systemd(self):
        with tempfile.TemporaryDirectory() as directory:
            inst = {'id': 'test', 'name': 'test', 'path': directory, 'port': 8091,
                    'scheduler_svc': 'scheduler', 'dashboard_svc': 'dashboard'}
            status = {'running': False, 'state': 'offline', 'pid': ''}
            for platform, expected in [('win32', False), ('linux', True)]:
                with self.subTest(platform=platform), \
                        patch.object(self.master.sys, 'platform', platform), \
                        patch.object(self.master, 'get_service_info', return_value={'SubState': 'running'}), \
                        patch.object(self.master, 'get_scheduler_status', return_value=status), \
                        patch.object(self.master, 'get_local_dashboard_info', return_value={'SubState': 'running'}) as local, \
                        patch.object(self.master, 'get_db_stats', return_value={'lives': 3}), \
                        patch.object(self.master, 'check_oauth_quick', return_value={'ok': True}):
                    result = self.master.check_instance(inst)
                    self.assertEqual(result['scheduler']['running'], expected)
                    self.assertTrue(result['dashboard']['running'])
                    self.assertEqual(result['db'], {'lives': 3})
                    self.assertEqual(local.call_count, int(platform == 'win32'))


if __name__ == '__main__':
    unittest.main()
