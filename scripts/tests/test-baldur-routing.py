#!/usr/bin/env python3
"""Baldur shell helpers under fake sysfs/ALSA/PipeWire; no hardware/services/builds."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
HELPERS = REPO / 'external-and-mods/baldur/rootfs/usr/libexec/tb323fu'
MOCK = r'''
import json, os, sys, subprocess
from pathlib import Path
root=Path(os.environ['FIXTURE']); name=Path(sys.argv[0]).name; args=sys.argv[1:]
cfg=json.loads((root/'cfg').read_text())
with (root/'calls').open('a') as f: f.write(json.dumps([name,*args])+'\n')
if name=='gpiodetect': print('gpiochip7 [f100000.pinctrl] (200 lines)')
elif name=='gpioget':
 print((root/'gpio').read_text().strip()); sys.exit(cfg.get('get_fail',0))
elif name=='gpioset':
 if cfg.get('set_fail'): sys.exit(1)
 (root/'gpio').write_text(args[-1].split('=')[1])
elif name=='sleep':
 if cfg.get('late_card'):
  (root/'proc/asound/cards').write_text('0 [LENOVOTB323FU ]: simple - LENOVO-TB323FU\n')
 if cfg.get('enumerate') == (root/'gpio').read_text() and (root/'sys/class/usb_role/a600000.usb-role-switch/role').read_text().strip()=='device':
  (root/'sys/class/udc/a600000.usb/state').write_text('configured')
elif name=='timeout':
 sys.exit(subprocess.run(args[1:]).returncode)
elif name=='pactl':
 if args[0]==cfg.get('pactl_fail'): sys.exit(1)
 if args[0]=='get-default-sink': print(cfg.get('default','alsa_output.platform-sound.HiFi__Speaker__sink'))
 if args[0]=='list': print(cfg.get('sinks','1\teffect_input.speakers\tPipeWire\tSUSPENDED'))
elif name=='amixer':
 if cfg.get('amp_fail') in args: sys.exit(1)
 if 'cget' in args: print(': values=159')
'''


class Helpers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = {}
        self.put('sys/firmware/devicetree/base/compatible', 'lenovo,baldur\0qcom,kaanapali\0')
        self.put('sys/class/usb_role/a600000.usb-role-switch/role', 'device')
        self.put('sys/class/udc/a600000.usb/state', 'not attached')
        self.put('sys/class/udc/a600000.usb/function', 'gadget')
        self.put('proc/asound/cards', '0 [LENOVOTB323FU ]: simple - LENOVO-TB323FU\n')
        self.put('gpio', '0')
        self.put('calls', '')
        (self.root/'run/lock').mkdir(parents=True)
        (self.root/'bin').mkdir()
        for name in ('gpiodetect', 'gpioget', 'gpioset', 'flock', 'logger', 'sleep', 'timeout', 'pactl', 'amixer'):
            f = self.root/'bin'/name
            f.write_text('#!'+sys.executable+'\n'+MOCK)
            f.chmod(0o755)

    def put(self, path, text):
        p = self.root/path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def read(self, path):
        return (self.root/path).read_text().strip()

    def port(self, n, power='[sink]', data='[device]'):
        self.put(f'sys/class/typec/port{n}-partner', '')
        self.put(f'sys/class/typec/port{n}/power_role', power)
        self.put(f'sys/class/typec/port{n}/data_role', data)

    def run_helper(self, which, arg=''):
        source = (HELPERS/('tb323fu-'+which)).read_text()
        for prefix in ('/sys/', '/proc/', '/run/', '/etc/', '/usr/sbin/'):
            source = source.replace(prefix, str(self.root)+prefix)
        p = self.root/'helper'
        p.write_text(source)
        (self.root/'cfg').write_text(json.dumps(self.config))
        env = dict(os.environ, PATH=str(self.root/'bin')+os.pathsep+os.environ['PATH'], FIXTURE=str(self.root))
        result = subprocess.run(['/bin/sh', str(p), arg], env=env, capture_output=True, text=True, timeout=20)
        self.calls = [json.loads(x) for x in (self.root/'calls').read_text().splitlines()]
        return result

    def role(self):
        return self.read('sys/class/usb_role/a600000.usb-role-switch/role')

    def assert_conservative(self):
        writes = [c for c in self.calls if c[0]=='amixer' and 'cset' in c]
        self.assertTrue(writes)
        self.assertTrue(all(c[-1]=='159' for c in writes), writes)
        self.assertTrue(any('name=aw_dev_0_volume' in c for c in writes))
        self.assertTrue(any('name=aw_dev_1_volume' in c for c in writes))

    def test_other_boards_no_writes(self):
        for board in ('ayaneo,pocketevo', 'lenovo,elden', 'lenovo,baldur-other'):
            self.put('sys/firmware/devicetree/base/compatible', board+'\0')
            for which in ('speaker-gain', 'usb-port'):
                self.assertEqual(self.run_helper(which,'on').returncode,0)
                self.assertEqual(self.calls,[])
                self.assertFalse((self.root/'run/lock/tb323fu-usb-port.lock').exists())

    def test_side_host_beats_bottom_charger_and_is_idempotent(self):
        self.port(0); self.port(1,'[source]','[host]')
        self.assertEqual(self.run_helper('usb-port','host-reconcile').returncode,0)
        self.assertEqual((self.read('gpio'),self.role()),('1','host'))
        self.put('calls','')
        self.assertEqual(self.run_helper('usb-port','host-reconcile').returncode,0)
        self.assertFalse(any(c[0]=='gpioset' for c in self.calls))

    def test_keep_current_host_when_both_eligible(self):
        self.port(0,'[source]','[host]'); self.port(1,'[source]','[host]')
        self.put('gpio','1'); self.put('sys/class/usb_role/a600000.usb-role-switch/role','host')
        self.assertEqual(self.run_helper('usb-port').returncode,0)
        self.assertEqual(self.read('gpio'),'1')
        self.assertFalse(any(c[0]=='gpioset' for c in self.calls))

    def test_reconcile_without_host_does_not_probe_device(self):
        self.port(0); self.port(1)
        self.assertEqual(self.run_helper('usb-port','host-reconcile').returncode,0)
        self.assertFalse(any(c[0]=='gpioset' for c in self.calls))

    def test_unknown_side_power_does_not_select_host(self):
        self.port(1,power='unknown')
        self.assertNotEqual(self.run_helper('usb-port').returncode,0)
        self.assertEqual((self.read('gpio'),self.role()),('0','device'))

    def test_gpio_read_error_or_invalid_value_stops(self):
        self.port(1,'[source]','[host]')
        for value, error in [('0',1),('invalid',0)]:
            self.put('gpio',value); self.config['get_fail']=error
            self.assertNotEqual(self.run_helper('usb-port').returncode,0)
            self.assertEqual(self.role(),'device')
            self.assertFalse(any(c[0]=='gpioset' for c in self.calls))

    def test_unreadable_current_host_does_not_fall_into_device_path(self):
        self.port(1,'[source]','[host]')
        self.put('sys/class/usb_role/a600000.usb-role-switch/role','host')
        self.config['get_fail']=1
        self.assertNotEqual(self.run_helper('usb-port').returncode,0)
        self.assertEqual(self.role(),'host')
        self.assertFalse(any(c[0]=='gpioset' for c in self.calls))

    def test_source_device_role_is_not_forced_to_host(self):
        self.port(1,'[source]','[device]')
        self.assertNotEqual(self.run_helper('usb-port').returncode,0)
        self.assertEqual((self.read('gpio'),self.role()),('0','device'))

    def test_gpio_write_failure_does_not_change_role(self):
        self.port(1,'[source]','[host]'); self.config['set_fail']=True
        self.assertNotEqual(self.run_helper('usb-port').returncode,0)
        self.assertEqual(self.role(),'device')

    def test_usb_storage_prevents_mux_and_role_change(self):
        self.port(1,'[source]','[host]')
        target=self.root/'sys/bus/usb/drivers/uas'; target.mkdir(parents=True)
        link=self.root/'sys/bus/usb/devices/1-1:1.0/driver'; link.parent.mkdir(parents=True); link.symlink_to(target)
        self.assertNotEqual(self.run_helper('usb-port').returncode,0)
        self.assertEqual((self.read('gpio'),self.role()),('0','device'))

    def test_configured_gadget_is_preserved(self):
        self.port(1); self.put('sys/class/udc/a600000.usb/state','configured')
        self.assertEqual(self.run_helper('usb-port').returncode,0)
        self.assertFalse(any(c[0]=='gpioset' for c in self.calls))

    def test_dual_device_probe_enumerates_side(self):
        self.port(0); self.port(1); self.config['enumerate']='1'
        self.assertEqual(self.run_helper('usb-port').returncode,0)
        self.assertEqual(self.read('gpio'),'1')
        self.assertEqual(self.read('sys/class/udc/a600000.usb/state'),'configured')

    def test_dual_probe_timeout_restores_bottom(self):
        self.port(0); self.port(1)
        self.assertEqual(self.run_helper('usb-port').returncode,0)
        self.assertEqual((self.read('gpio'),self.role()),('0','device'))
        self.assertEqual(len([c for c in self.calls if c[0]=='sleep']),12)

    def test_speaker_retains_boot_attenuation_and_selects_filter(self):
        self.put('etc/tb323fu/audio.conf','SPEAKER_ATTEN=0\nSPEAKER_ATTEN_PROTECTED=0\n')
        self.assertEqual(self.run_helper('speaker-gain','on').returncode,0)
        self.assert_conservative()
        self.assertTrue(any(c[0]=='pactl' and c[1]=='set-default-sink' for c in self.calls))

    def test_speaker_keeps_bluetooth_default(self):
        self.config['default']='bluez_output.test'
        self.assertEqual(self.run_helper('speaker-gain','on').returncode,0)
        self.assert_conservative()
        self.assertFalse(any(c[0]=='pactl' and c[1]=='set-default-sink' for c in self.calls))

    def test_failed_audio_queries_and_wrong_sink_are_conservative(self):
        for conf in ({'pactl_fail':'get-default-sink'}, {'pactl_fail':'list'}, {'pactl_fail':'set-default-sink'}, {'sinks':'1 effect_input.speakers_fake PipeWire SUSPENDED'}):
            self.config=conf; self.put('calls','')
            self.assertNotEqual(self.run_helper('speaker-gain','on').returncode,0)
            self.assert_conservative()

    def test_missing_or_wrong_card_never_writes(self):
        self.put('proc/asound/cards','0 [LENOVO ]: audio - Lenovo unrelated\n')
        self.assertNotEqual(self.run_helper('speaker-gain','on').returncode,0)
        self.assertFalse(any(c[0]=='amixer' for c in self.calls))
        self.assertEqual(len([c for c in self.calls if c[0]=='sleep']),20)

    def test_late_card_is_retried(self):
        self.put('proc/asound/cards',''); self.config['late_card']=True
        self.assertEqual(self.run_helper('speaker-gain','on').returncode,0)
        self.assert_conservative()

    def test_amplifier_failure_writes_both_and_reports_failure(self):
        self.config['amp_fail']='name=aw_dev_0_volume'
        self.assertNotEqual(self.run_helper('speaker-gain','on').returncode,0)
        self.assert_conservative()
        self.assertNotEqual(self.run_helper('speaker-gain','status').returncode,0)

    def test_speaker_off_ignores_pipewire(self):
        self.config['pactl_fail']='get-default-sink'
        self.assertEqual(self.run_helper('speaker-gain','off').returncode,0)
        self.assert_conservative()
        self.assertFalse(any(c[0]=='pactl' for c in self.calls))


if __name__ == '__main__':
    unittest.main()
