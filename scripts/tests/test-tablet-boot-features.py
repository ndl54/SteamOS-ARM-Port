#!/usr/bin/env python3
"""Source070 regression fixtures. Ordinary files and intercepted calls only."""
import importlib.machinery
import importlib.util
import os
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
ARM = ROOT / 'steamos-overlay/usr/lib/steamos-arm'


def load(name):
    loader = importlib.machinery.SourceFileLoader(name.replace('-', '_'), str(ARM / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Fixtures(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='tablet070-', dir='/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.fw = load('tablet-firmware')
        self.ch = load('tablet-charger-hold')

    def path(self, path):
        return self.base / str(path).lstrip('/')

    def write(self, path, data):
        p = self.path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode())
        return p

    def elf(self, directory='fw', is64=False, compact=False):
        d = self.base / directory
        d.mkdir(parents=True, exist_ok=True)
        hdr, ent = (64, 56) if is64 else (52, 32)
        end = hdr + 3 * ent
        data = bytearray(end)
        data[:7] = b'\x7fELF' + bytes([2 if is64 else 1, 1, 1])
        struct.pack_into('<Q' if is64 else '<I', data, 32 if is64 else 28, hdr)
        struct.pack_into('<HH', data, 54 if is64 else 42, ent, 3)
        for i, (kind, off, size, flags) in enumerate(((0, 0, end, 0), (1, 512, 4, 2 << 24), (1, 1024, 4, 0))):
            if is64:
                struct.pack_into('<II6Q', data, hdr+i*ent, kind, flags, off, 0, 0, size, size, 0)
            else:
                struct.pack_into('<8I', data, hdr+i*ent, kind, off, 0, 0, size, size, flags, 0)
        p = d/'ZAP.MDT'
        if compact:
            data += b'HASH'
        else:
            (d/'ZAP.B01').write_bytes(b'HASH')
        p.write_bytes(data)
        (d/'ZAP.B02').write_bytes(b'CODE')
        return p

    def test_squash_32_64_and_compact_hash(self):
        for wide in (False, True):
            for compact in (False, True):
                p = self.elf(f'fw{wide}{compact}', wide, compact)
                result = self.fw.squash(p)
                self.assertEqual(result[:7], p.read_bytes()[:7])
                self.assertEqual(result[512:516], b'HASH')
                self.assertEqual(result[1024:], b'CODE')
                self.assertEqual(result[516:1024], bytes(508))

    def test_squash_bad_headers_and_bounds(self):
        p = self.elf()
        original = p.read_bytes()
        for field, value in ((4, 0), (5, 2), (6, 0)):
            bad = bytearray(original); bad[field] = value; p.write_bytes(bad)
            with self.assertRaises(ValueError): self.fw.squash(p)
        p.write_bytes(original[:20])
        with self.assertRaises(ValueError): self.fw.squash(p)
        bad = bytearray(original); struct.pack_into('<I', bad, 52+2*32+4, 0xffffffff); p.write_bytes(bad)
        with self.assertRaises(ValueError): self.fw.squash(p)

    def test_squash_missing_truncated_symlink_and_overlap(self):
        p = self.elf(); seg=p.parent/'ZAP.B02'
        seg.unlink()
        with self.assertRaises(ValueError): self.fw.squash(p)
        seg.write_bytes(b'X')
        with self.assertRaises(ValueError): self.fw.squash(p)
        seg.unlink(); other=self.base/'other';other.write_bytes(b'CODE');seg.symlink_to(other)
        with self.assertRaises(ValueError): self.fw.squash(p)
        seg.unlink();seg.write_bytes(b'CODE')
        bad=bytearray(p.read_bytes());struct.pack_into('<I',bad,52+2*32+4,0);p.write_bytes(bad)
        with self.assertRaises(ValueError): self.fw.squash(p)

    def test_squash_active_split_beats_inactive_monolithic(self):
        p=self.elf('active'); inactive=self.base/'inactive';inactive.mkdir();(inactive/'zap.mbn').write_bytes(b'OLD')
        rows=[{'path':'qcom/zap.mbn'}]
        result=self.fw.by_name([p.parent,inactive],rows,rows)
        self.assertEqual(result,{'qcom/zap.mbn':[(p,'qcom/zap.mbn')]})
        (p.parent/'ZAP.B02').unlink()
        result=self.fw.by_name([p.parent,inactive],rows,rows)
        self.assertEqual(result['qcom/zap.mbn'][0][0],inactive/'zap.mbn')

    def test_existing_mdt_bundle_header_last_and_no_independent_segment(self):
        p=self.elf(); rows=[{'path':'qcom/zap.mdt'},{'path':'qcom/zap.b02'}]
        out=self.fw.by_name([p.parent],rows,rows)
        self.assertEqual(set(out),{'qcom/zap.mdt'})
        self.assertEqual(out['qcom/zap.mdt'][-1],(p,'qcom/zap.mdt'))
        self.assertIn((p.parent/'ZAP.B02','qcom/zap.b02'),out['qcom/zap.mdt'])

    def test_charger_mode_exact_and_bootconfig(self):
        for args in ('androidboot.mode=charger', 'x=1 androidboot.mode = "charger"\ny=2', 'androidboot.mode=offmode_charging'):
            self.assertTrue(self.ch.charger_mode(args),args)
        for args in ('fooandroidboot.mode=charger', 'androidboot.mode=charger_extra', 'androidboot.mode=normal'):
            self.assertFalse(self.ch.charger_mode(args),args)

    def test_charger_board_and_unknown_usb_pd_accessory(self):
        self.ch.Path=self.path
        for board, allowed in (('ayaneo,pocketevo',False),('lenovo,elden-other',False),('lenovo,baldur',False),('lenovo,elden',True)):
            self.write('/sys/firmware/devicetree/base/compatible',board+'\0qcom,x\0')
            self.assertEqual(self.ch.supported_board(),allowed)
        self.assertIsNone(self.ch.charger_online())
        self.write('/sys/class/power_supply/usb/type','USB_PD')
        online=self.write('/sys/class/power_supply/usb/online','1')
        self.assertIs(self.ch.charger_online(),True)
        online.write_text('0'); self.assertIs(self.ch.charger_online(),False)
        self.write('/sys/class/power_supply/usb/scope','Device')
        self.assertIsNone(self.ch.charger_online())

    def charger_main(self, poweroff=1, key=False):
        self.ch.supported_board=lambda:True
        self.ch.bootloader_args=lambda:'androidboot.mode=charger'
        self.ch.battery=lambda:'50'
        bl=self.base/'panel';bl.mkdir();(bl/'brightness').write_text('123')
        self.ch.backlights=Mock(return_value={bl:'123'})
        self.ch.power_keys=lambda:[99]
        self.ch.say=Mock()
        self.ch.charger_online=lambda:False
        self.ch.time=types.SimpleNamespace(monotonic=Mock(side_effect=[0,7,8,9]),sleep=Mock(side_effect=RuntimeError('shutdown wait')))
        self.ch.select=types.SimpleNamespace(select=Mock(return_value=([99] if key else [],[],[])))
        self.ch.os=types.SimpleNamespace(close=Mock(),read=Mock(return_value=self.ch.EVENT.pack(0,0,1,116,1)))
        self.ch.subprocess=types.SimpleNamespace(run=Mock(return_value=types.SimpleNamespace(returncode=poweroff)),TimeoutExpired=subprocess.TimeoutExpired)
        return bl

    def test_charger_poweroff_failure_restores_and_closes(self):
        bl=self.charger_main()
        self.assertEqual(self.ch.main(),1)
        self.ch.subprocess.run.assert_called_once_with(['systemctl','--no-block','poweroff'],timeout=10)
        self.ch.os.close.assert_called_once_with(99)
        self.assertEqual((bl/'brightness').read_text(),'123')

    def test_charger_poweroff_acceptance_does_not_release_boot(self):
        self.charger_main(poweroff=0)
        with self.assertRaisesRegex(RuntimeError,'shutdown wait'):self.ch.main()
        self.ch.time.sleep.assert_called_once_with(60)

    def test_charger_hold_starts_boot(self):
        bl=self.charger_main(key=True)
        self.assertEqual(self.ch.main(),0)
        self.ch.subprocess.run.assert_not_called()
        self.assertEqual((bl/'brightness').read_text(),'123')

    def test_charger_input_loss_restores_instead_of_spinning(self):
        bl=self.charger_main(key=True)
        self.ch.os.read.return_value=b''
        self.assertEqual(self.ch.main(),1)
        self.ch.subprocess.run.assert_not_called()
        self.assertEqual((bl/'brightness').read_text(),'123')
        self.ch.os.close.assert_called_once_with(99)

    def shell(self,name,arg):
        text=(ARM/name).read_text()
        for prefix in ('/sys/','/var/','/proc/'):
            text=text.replace(prefix,str(self.base)+prefix)
        return subprocess.run(['bash','-c',text,'fixture',arg],capture_output=True,text=True,timeout=5)

    def backlight(self):
        self.write('/sys/firmware/devicetree/base/compatible','lenovo,elden\0')
        self.write('/sys/class/backlight/panel/max_brightness','4095')
        return self.write('/sys/class/backlight/panel/brightness','42')

    def test_backlight_low_value_zero_and_clamp(self):
        bl=self.backlight()
        self.assertEqual(self.shell('tablet-backlight','save').returncode,0)
        state=self.path('/var/lib/steamos-arm/backlight/panel')
        self.assertEqual(state.read_text().strip(),'42')
        bl.write_text('0'); self.shell('tablet-backlight','save')
        self.assertEqual(state.read_text().strip(),'42')
        self.shell('tablet-backlight','restore');self.assertEqual(bl.read_text().strip(),'42')
        state.write_text('9999');self.shell('tablet-backlight','restore');self.assertEqual(bl.read_text().strip(),'4095')
        state.write_text('corrupt');self.shell('tablet-backlight','restore');self.assertEqual(bl.read_text().strip(),'2457')

    def test_backlight_wrong_board_and_bad_max(self):
        bl=self.backlight()
        self.write('/sys/firmware/devicetree/base/compatible','ayaneo,pocketevo\0')
        self.shell('tablet-backlight','restore');self.assertEqual(bl.read_text(),'42')
        self.assertFalse(self.path('/var/lib/steamos-arm/backlight').exists())
        self.write('/sys/firmware/devicetree/base/compatible','lenovo,elden\0')
        self.write('/sys/class/backlight/panel/max_brightness','bogus')
        self.shell('tablet-backlight','restore');self.assertEqual(bl.read_text(),'42')

    def test_iwd_first_boot_and_preserve_choice(self):
        text=(ROOT/'scripts/install-elden.sh').read_text()
        line=next(x for x in text.splitlines() if x.startswith("ExecStart=/bin/sh -c 'mkdir -p /etc/NetworkManager"))
        # Emulate documented systemd $$ and C backslash unescaping, then run
        # only this shell command on a temporary etc tree.
        cmd=line.split(" -c '",1)[1][:-1].replace('$$','$').replace('\\\\','\\')
        cmd=cmd.replace('/etc/',str(self.base)+'/etc/')
        for n in range(2):
            result=subprocess.run(['sh','-c',cmd],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            file=self.path('/etc/NetworkManager/conf.d/99-valve-wifi-backend.conf')
            self.assertEqual(file.read_text(),'[device]\nwifi.backend=iwd\n' if n==0 else 'user-choice\n')
            file.write_text('user-choice\n')

    def test_firmware_publication_marker_and_retry(self):
        p=self.elf('modem_a');dest=self.base/'dest';marker=self.base/'changed'
        manifest=self.base/'manifest.json'
        manifest.write_text(json.dumps({'files':[{'path':'qcom/zap.mbn','size':9999,'sha256':'missing'}]}))
        m=self.fw
        m.os=types.SimpleNamespace(geteuid=lambda:0,walk=os.walk,replace=os.replace)
        m.by_partlabel=lambda:{'modem_a':'fixture'}
        m.SUFFIX='_a'
        m.Mounts=lambda:types.SimpleNamespace(mount=lambda *a:p.parent,close=Mock())
        m.console=Mock()
        args=['tablet-firmware',str(manifest),str(dest),'--changed-file',str(marker)]
        with patch.object(m.sys,'argv',args):
            m.main()
            self.assertEqual((dest/'qcom/zap.mbn').read_bytes(),m.squash(p))
            self.assertTrue(marker.exists());marker.unlink()
            m.main();self.assertFalse(marker.exists())
            (p.parent/'ZAP.B02').write_bytes(b'NEXT')
            m.main();self.assertTrue(marker.exists());marker.unlink()
            (p.parent/'ZAP.B02').unlink()
            old=(dest/'qcom/zap.mbn').read_bytes()
            m.main();self.assertFalse(marker.exists())
            self.assertEqual((dest/'qcom/zap.mbn').read_bytes(),old)

    def test_boot_watch_rechecks_session_before_console(self):
        self.write('/sys/firmware/devicetree/base/compatible','lenovo,elden\0')
        self.write('/proc/uptime','151.0 0.0')
        text=(ARM/'tablet-boot-watch').read_text()
        for prefix in ('/sys/','/var/','/proc/'):
            text=text.replace(prefix,str(self.base)+prefix)
        tty=self.write('/dev/tty1','unchanged')
        text=text.replace('/dev/tty1',str(tty))
        prelude="""
sleep() { :; }
pgrep() { [ -e "$FIXTURE/logged" ]; }
journalctl() { touch "$FIXTURE/logged"; echo diagnostic; }
dmesg() { :; }
systemctl() { :; }
chvt() { touch "$FIXTURE/switched"; }
"""
        result=subprocess.run(['bash','-c',prelude+text,'fixture','0'],env={**os.environ,'FIXTURE':str(self.base)},capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(self.path('/var/log/steamos-arm/boot-watch.txt').exists())
        self.assertEqual(tty.read_text(),'unchanged')
        self.assertFalse((self.base/'switched').exists())

    def test_vbmeta_header_ordinary_file(self):
        out=self.base/'vbmeta'
        result=subprocess.run(['python3','-B',str(ROOT/'scripts/mk-vbmeta-disabled.py'),str(out)],capture_output=True)
        self.assertEqual(result.returncode,0)
        data=out.read_bytes();self.assertEqual(len(data),4096);self.assertEqual(data[:4],b'AVB0')
        self.assertEqual(struct.unpack_from('>II',data,4),(1,0))
        self.assertEqual(struct.unpack_from('>QI',data,112),(0,2))
        self.assertEqual(data[12:112],bytes(100))


if __name__ == '__main__':
    unittest.main()
