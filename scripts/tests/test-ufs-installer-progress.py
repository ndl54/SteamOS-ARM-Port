#!/usr/bin/env python3
"""GUI/process mocks and extracted cleanup only; never run the UFS installer."""
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

REPO = Path(__file__).resolve().parents[2]
GUI = REPO / 'external-and-mods/ufs-install/easy-ufs-installer.py'
SHELL = (GUI.parent / 'install-masios-to-internal.sh').read_text()


class Widget:
    def __init__(self, **kwargs):
        self.properties = kwargs
        self.handlers = {}

    def __getattr__(self, name):
        value = MagicMock()
        setattr(self, name, value)
        return value

    def connect(self, event, callback):
        self.handlers[event] = callback


def load_gui():
    gtk = MagicMock()
    gtk.Window = Widget
    gtk.Dialog.side_effect = Widget
    gtk.MessageDialog.side_effect = Widget
    glib = MagicMock()
    gi = types.ModuleType('gi')
    gi.require_version = MagicMock()
    repository = types.ModuleType('gi.repository')
    repository.Gtk, repository.GLib, repository.Pango = gtk, glib, MagicMock()
    with patch.dict(sys.modules, {'gi': gi, 'gi.repository': repository}):
        ns = runpy.run_path(str(GUI))
    # Use the function globals: runpy's returned dict need not be that object.
    return ns['MainWindow'].__init__.__globals__, gtk, glib


class Progress(unittest.TestCase):
    def setUp(self):
        self.ns, self.gtk, self.glib = load_gui()
        with patch.object(self.ns['MainWindow'], 'refresh_async'):
            self.win = self.ns['MainWindow']()
        self.win.ack.get_active.return_value = True
        self.win.size_spin.get_value.return_value = 64
        self.win.home_combo.get_active_id.return_value = 'essentials'
        self.win._info = {'TABLE_FINGERPRINT': 'fp with spaces;$(never)'}
        self.gtk.MessageDialog.side_effect = None
        self.confirm = Widget()
        self.confirm.run.return_value = self.gtk.ResponseType.OK
        self.gtk.MessageDialog.return_value = self.confirm

    def start(self, code=0):
        runner = MagicMock(return_value=(code, 'mock transcript'))
        thread = MagicMock()
        with patch.dict(self.ns, {'run_install': runner}), patch.object(
                self.ns['threading'], 'Thread', thread):
            self.win._on_install()
            self.assertTrue(self.win._busy)
            self.assertTrue(self.win.handlers['delete-event']())
            self.assertEqual(self.win._info, {})
            dialog = self.gtk.Dialog.call_args
            self.assertTrue(dialog.kwargs['modal'])
            self.assertIs(dialog.kwargs['transient_for'], self.win)
            # The actual progress widget is captured via the pulse closure.
            thread.call_args.kwargs['target']()
            self.assertTrue(self.win._busy)  # main loop hasn't delivered done
            call = self.glib.idle_add.call_args
            call.args[0](*call.args[1:])
        self.assertFalse(self.win._busy)
        self.assertFalse(self.win.handlers['delete-event']())
        self.glib.source_remove.assert_called_once()
        self.win.install_btn.set_sensitive.assert_called_with(False)
        argv = runner.call_args.args[0]
        self.assertEqual(argv[-4:], ['--expect', 'fp with spaces;$(never)', '--home', 'essentials'])
        return self.win.status.set_text.call_args.args[0]

    def test_completion_and_failure_statuses(self):
        for code in (0, 1, 126, 127, -15, None):
            with self.subTest(code=code):
                self.setUp()
                message = self.start(code)
                self.assertEqual('Install finished.' in message, code == 0)

    def test_tablet_completion(self):
        self.ns['TABLET'] = True
        self.assertIn('unplug the USB drive', self.start())

    def test_progress_close_denied_and_destroyed_only_after_done(self):
        progress = self.win._progress_dialog()
        self.assertTrue(progress.handlers['delete-event']())
        progress.set_deletable.assert_called_once_with(False)
        progress.destroy.assert_not_called()
        with patch.object(self.win, '_progress_dialog', return_value=progress):
            self.start()
        progress.destroy.assert_called_once()

    def test_cancel_and_busy_do_not_launch(self):
        with patch.dict(self.ns, {'run_install': MagicMock()}) as ns, patch.object(
                self.ns['threading'], 'Thread') as thread:
            self.confirm.run.return_value = self.gtk.ResponseType.CANCEL
            self.win._on_install()
            self.win._busy = True
            self.win._on_install()
            thread.assert_not_called()
            ns['run_install'].assert_not_called()
            self.gtk.Dialog.assert_not_called()

    def test_probe_thread_start_error_releases_window(self):
        with patch.object(self.ns['threading'], 'Thread') as thread:
            thread.return_value.start.side_effect = RuntimeError('no worker')
            self.win.refresh_async()
        self.assertFalse(self.win._busy)
        self.assertFalse(self.win.handlers['delete-event']())
        self.win.refresh_btn.set_sensitive.assert_called_with(True)
        self.assertIn('Probe could not start', self.win.status.set_text.call_args.args[0])

    def test_thread_start_error_releases_window(self):
        with patch.object(self.ns['threading'], 'Thread') as thread:
            thread.return_value.start.side_effect = RuntimeError('no worker')
            self.win._on_install()
        self.assertFalse(self.win._busy)
        self.glib.source_remove.assert_called_once()
        self.assertIn('could not complete', self.win.status.set_text.call_args.args[0])


class Process(unittest.TestCase):
    def setUp(self):
        self.ns, _, _ = load_gui()

    def test_auth_routing_argv_and_no_terminal_input(self):
        argv = ['bash', '/mock path/a;$(never).sh', '--expect', 'a b']
        for uid, pkexec, prefix in ((0, None, []), (1000, '/mock/pkexec', ['pkexec']),
                                    (1000, None, ['sudo', '-n', '--'])):
            with self.subTest(uid=uid, pkexec=pkexec), patch.object(os, 'geteuid', return_value=uid), \
                    patch.object(self.ns['shutil'], 'which', return_value=pkexec), \
                    patch.object(subprocess, 'run') as run:
                self.ns['_pkexec'](argv)
                self.assertEqual(run.call_args.args[0], prefix + argv)
                self.assertEqual(run.call_args.kwargs['stdin'], subprocess.DEVNULL)
                self.assertNotIn('shell', run.call_args.kwargs)
                self.assertEqual(run.call_args.kwargs['errors'], 'replace')

    def test_real_harmless_child_wait_log_tail_and_invalid_utf8(self):
        # Only this Python child runs; no shell, privilege helper or installer.
        with tempfile.TemporaryDirectory(prefix='ufs test ') as tmp, \
                patch.object(self.ns['tempfile'], 'tempdir', tmp), \
                patch.object(os, 'geteuid', return_value=0):
            code, out = self.ns['run_install']([
                sys.executable, '-c',
                "import os; os.write(1,b'x'*20000); os.write(2,b'\\xffEND'); raise SystemExit(7)",
            ])
            self.assertEqual(code, 7)
            self.assertIn('\ufffdEND', out)
            self.assertLess(len(out), 8300)
            logs = list(Path(tmp).glob('*.log'))
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].stat().st_mode & 0o777, 0o600)
            self.assertEqual(logs[0].read_bytes(), b'x' * 20000 + b'\xffEND')
            self.assertIn(str(logs[0]), out)

    def test_launch_error_and_log_creation_failure(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(self.ns['tempfile'], 'tempdir', tmp), \
                patch.dict(self.ns, {'_pkexec': MagicMock(side_effect=FileNotFoundError('missing helper'))}):
            code, out = self.ns['run_install'](['never-run'])
            self.assertIsNone(code)
            self.assertIn('missing helper', out)
            self.assertIn('Full log:', out)
        with patch.object(self.ns['tempfile'], 'NamedTemporaryFile', side_effect=OSError('no log space')), \
                patch.dict(self.ns, {'_pkexec': MagicMock()}) as ns:
            code, out = ns['run_install'](['never-run'])
            self.assertIsNone(code)
            self.assertIn('no log space', out)
            ns['_pkexec'].assert_not_called()


class Cleanup(unittest.TestCase):
    def test_cleanup_order_failure_and_exit_status(self):
        fragment = SHELL[SHELL.index('cleanup() {'):SHELL.index('mnt() {')]
        for status in (0, 7):
            for busy in ('', '/mock/home'):
                with self.subTest(status=status, busy=busy):
                    # Run ONLY extracted functions; umount is a mock shell function.
                    shell = '''set -euo pipefail
mounted=(/mock/boot /mock/root /mock/home /mock/src)
umount() { printf 'unmount %s\\n' "$1"; [[ "$1" != "$BUSY" ]]; }
'''
                    shell += fragment + '\nexit "$INITIAL_STATUS"\n'
                    proc = subprocess.run(['bash', '-c', shell], capture_output=True, text=True,
                                          env={**os.environ, 'BUSY': busy, 'INITIAL_STATUS': str(status)})
                    self.assertEqual(proc.returncode, status or bool(busy), proc.stderr)
                    self.assertEqual(proc.stdout.splitlines(), [f'unmount /mock/{p}'
                                     for p in ('src', 'home', 'root', 'boot')])
                    self.assertEqual('not complete' in proc.stderr, bool(busy))

    def test_successful_cleanup_then_empty_exit_cleanup(self):
        fragment = SHELL[SHELL.index('cleanup() {'):SHELL.index('mnt() {')]
        shell = "set -euo pipefail\nmounted=(/mock/home)\numount() { echo mock-unmount; }\n"
        proc = subprocess.run(['bash', '-c', shell + fragment + '\ncleanup\necho SUCCESS\n'],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, 'mock-unmount\nSUCCESS\n')

    def test_explicit_cleanup_failure_cannot_reach_success(self):
        fragment = SHELL[SHELL.index('cleanup() {'):SHELL.index('mnt() {')]
        shell = '''set -euo pipefail
mounted=(/mock/boot /mock/home)
umount() { printf 'unmount %s\\n' "$1"; [[ "$1" != /mock/home ]]; }
'''
        proc = subprocess.run(['bash', '-c', shell + fragment + '\ncleanup\necho SUCCESS\n'],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn('SUCCESS', proc.stdout)
        self.assertEqual(proc.stdout.count('unmount /mock/home'), 2)  # retained for EXIT retry
        self.assertEqual(proc.stdout.count('unmount /mock/boot'), 1)


if __name__ == '__main__':
    unittest.main()
