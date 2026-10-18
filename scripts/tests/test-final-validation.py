#!/usr/bin/env python3
"""Failure probes for final source repairs; no Steam, input or block devices."""
import ast
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('vdf', ROOT/'external-and-mods/NO_Steam/no_steam_games/shortcuts_vdf.py')
vdf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vdf)

class VDFTests(unittest.TestCase):
    def test_exact_roundtrip(self):
        tree = {'shortcuts': {'0': {'appid': -1, 'n': vdf.UInt64(2**63+7), 'small': vdf.UInt64(4), 'AppName': 'Việt'}}}
        data = vdf.emit_binary_vdf(tree)
        parsed, end = vdf.parse_binary_vdf(data)
        self.assertEqual(end, len(data))
        self.assertEqual(vdf.emit_binary_vdf(parsed), data)

    def test_malformed_preserved(self):
        valid = vdf.emit_binary_vdf({'shortcuts': {}})
        cases = [b'', valid[:-1], valid+b'x', b'\x01shortcuts\0bad\0\x08',
                 b'\x00shortcuts\0\x01x\0\xff\0\x08\x08',
                 b'\x00shortcuts\0\x02x\0\x01',
                 b'\x00shortcuts\0\x01x\0a\0\x01x\0b\0\x08\x08']
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'shortcuts.vdf'
            for data in cases:
                p.write_bytes(data)
                with self.assertRaises((ValueError, struct_error())):
                    vdf.load_shortcuts(p)
                self.assertEqual(p.read_bytes(), data)
        for obj in ({'bad\0key': ''}, {'x': 'bad\0value'}):
            with self.assertRaises(ValueError): vdf.emit_binary_vdf(obj)

    def test_atomic_backup_and_intervening_edit(self):
        with tempfile.TemporaryDirectory() as d, patch.object(vdf, 'require_steam_closed'):
            p = Path(d)/'shortcuts.vdf'
            original = vdf.emit_binary_vdf({'shortcuts': {}})
            p.write_bytes(original)
            first, stale = vdf.load_shortcuts(p), vdf.load_shortcuts(p)
            first['shortcuts']['0'] = {'AppName': 'new'}
            vdf.save_shortcuts(p, first)
            self.assertEqual(next(Path(d).glob('*.backup-*')).read_bytes(), original)
            published = p.read_bytes()
            with self.assertRaises(RuntimeError): vdf.save_shortcuts(p, stale)
            self.assertEqual(p.read_bytes(), published)
            with patch.object(vdf.os, 'replace', side_effect=OSError('injected rename failure')):
                with self.assertRaises(OSError): vdf.save_shortcuts(p, first)
            self.assertEqual(p.read_bytes(), published)
            self.assertFalse(list(Path(d).glob('*.new-*')))

    def test_symlink_and_online_refuse(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'vdf'; target = Path(d)/'other'
            target.write_bytes(vdf.emit_binary_vdf({'shortcuts': {}})); p.symlink_to(target)
            with self.assertRaises(OSError): vdf.load_shortcuts(p)
            p.unlink(); p.write_bytes(target.read_bytes()); tree = vdf.load_shortcuts(p)
            with patch.object(vdf, 'require_steam_closed', side_effect=RuntimeError('Steam running')):
                with self.assertRaises(RuntimeError): vdf.save_shortcuts(p, tree)
            self.assertEqual(p.read_bytes(), target.read_bytes())

def struct_error():
    import struct
    return struct.error

class RemoteTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((ROOT/'dualscreen-overlay/usr/lib/steamos-arm/bottom-screen/dashboard').read_text())
        remote = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'RemoteInput')
        class Device:
            all_devices = []
            def __init__(self, *args): self.events=[]; self.closed=False; self.all_devices.append(self)
            def emit(self, events): self.events += events
            def close(self): self.closed=True
        self.device = Device
        ns = dict(threading=threading, time=time, UInputDevice=Device, BUTTONS={'left':272,'right':273},
                  MOD_KEYS={'ctrl':29}, US_KEYS={'a':(30,False)}, NAMED_KEYS={}, EV_KEY=1,
                  EV_REL=2, REL_X=0, REL_Y=1, REL_WHEEL=8, REL_HWHEEL=6, log=lambda *a:None)
        exec(compile(ast.Module(body=[remote], type_ignores=[]), '<actual RemoteInput>', 'exec'), ns)
        self.r = ns['RemoteInput'](); self.ns=ns; self.session=self.r.begin()
    def send(self, seq, action, **kw):
        return self.r.dispatch(action, dict(session=self.session, sequence=seq, **kw))
    def test_late_down_after_release(self):
        self.assertFalse(self.send(2,'letgo'))
        self.assertFalse(self.send(1,'click',state='down'))
        self.assertFalse(self.r.mouse)
    def test_keepalive_cannot_skip_a_release(self):
        self.send(1,'click',state='down')
        self.assertFalse(self.send(3,'keepalive'))
        self.assertIn((1,272,0), self.r.mouse.events)
        self.assertFalse(self.send(2,'click',state='up'))
    def test_watchdog_invalidates_delayed_requests(self):
        self.assertTrue(self.send(1,'click',state='down'))
        self.r.deadline=0; self.r.expire()
        self.assertIn((1,272,0),self.r.mouse.events)
        self.assertFalse(self.send(2,'click',state='down'))
    def test_independent_owners(self):
        self.send(1,'click',state='down',owner='manual'); self.send(2,'click',state='down',owner='drag')
        self.send(3,'click',state='up',owner='drag')
        self.assertEqual(self.r.mouse.events,[(1,272,1)])
        self.send(4,'click',state='up',owner='manual')
        self.assertEqual(self.r.mouse.events[-1],(1,272,0))
    def test_partial_creation_closes_first_device(self):
        def factory(*args):
            if self.device.all_devices: raise OSError('keys failed')
            return self.device(*args)
        self.ns['UInputDevice']=factory
        self.assertFalse(self.send(1,'click',state='down'))
        self.assertTrue(self.device.all_devices[0].closed)

class HashTests(unittest.TestCase):
    def test_fail_closed(self):
        script = ROOT/'external-and-mods/baldur/switch-to-steamos/storage.sh'
        for shell in ('bash','dash'):
            for status, output, success in ((0,'a'*64+'  file',True),(1,'a'*64+'  file',False),(0,'',False),(0,'abcd',False),(0,'G'*64,False)):
                code = '. "$1"; probe_output=$2; probe_status=$3; sha256sum() { printf "%s\\n" "$probe_output"; return "$probe_status"; }; hash anything'
                result = subprocess.run([shell,'-c',code,'probe',str(script),output,str(status)],capture_output=True,text=True)
                self.assertEqual(result.returncode == 0, success)
                if not success: self.assertEqual(result.stdout,'')

if __name__ == '__main__': unittest.main()
