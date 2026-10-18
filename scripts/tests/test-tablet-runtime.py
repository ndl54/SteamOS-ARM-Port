#!/usr/bin/env python3
"""Tablet057 regressions: extracted functions and temporary files only, no services/devices."""
import ast
import asyncio
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[2]
ARM = ROOT / 'steamos-overlay/usr/lib/steamos-arm'

def functions(path, names, ns):
    tree = ast.parse(path.read_text())
    tree.body = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    exec(compile(tree, str(path), 'exec'), ns)
    return ns

class TabletRuntime(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='tablet057-', dir='/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = dict(os.environ, HOME=str(self.root), XDG_STATE_HOME=str(self.root/'state'))
        (self.root/'sys/firmware/devicetree/base').mkdir(parents=True)
        self.compat('lenovo,tb321fu')

    def compat(self, value):
        (self.root/'sys/firmware/devicetree/base/compatible').write_bytes((value+'\0qcom,sm8650\0').encode())

    def run_shell(self, text, suffix='', prelude=''):
        for p in ('/sys/', '/etc/', '/run/', '/var/', '/usr/share/'):
            text = text.replace(p, str(self.root)+p)
        result = subprocess.run(['bash','-c',prelude+'\n'+text+'\n'+suffix],env=self.env,capture_output=True,text=True,timeout=15)
        return result

    def audio(self):
        s=(ROOT/'scripts/install-tb321fu.sh').read_text()
        s=s[s.index('#!/bin/bash\n# Lenovo Legion Y700 Gen 3 sound'):]
        return s.split('\nSH\n')[0].split('\nstart || exit 1')[0]

    def audio_mock(self, fail='', card='Lenovo-Y700-TB321FU', hp=False, mic=False):
        cards=json.dumps([{'name':'alsa_card.platform-sound','properties':{'alsa.card_name':card,'alsa.card':'2'}}])
        return f'''
pa() {{
  echo "$*" >>"$HOME/calls"
  [[ "$1" != {shlex.quote(fail or 'never')} ]] || return 1
  case "$*" in
    '-f json list cards') echo {shlex.quote(cards)} ;;
    'list short sinks') echo '1 alsa_output.platform-sound.pro-output-0 PipeWire' ;;
    'list short sources') echo '2 alsa_input.platform-sound.pro-input-2 PipeWire' ;;
  esac
}}
timeout() {{ shift; "$@"; }}
amixer() {{
  case "$*" in *Headphone*) echo ': values={'on' if hp else 'off'}';; *) echo ': values={'on' if mic else 'off'}';; esac
}}
alsaucm() {{ echo "ucm $*" >>"$HOME/calls"; [[ "{fail}" != route ]]; }}
sleep() {{ :; }}
'''

    def test_audio_speaker_first_alias_and_order(self):
        for card in ('Lenovo-Y700-TB321FU','Lenovo-QRD-2.0'):
            calls=self.root/'calls';calls.unlink(missing_ok=True)
            result=self.run_shell(self.audio(), self.audio_mock(card=card)+'\nstart')
            self.assertEqual(result.returncode,0,result.stderr)
            lines=calls.read_text().splitlines()
            ucm=next(i for i,x in enumerate(lines) if x.startswith('ucm '))
            self.assertIn('-c hw:2 set _verb HiFi set _enadev Speaker set _enadev Mic1',lines[ucm])
            self.assertLess(lines.index('set-card-profile alsa_card.platform-sound off'),ucm)
            self.assertLess(ucm,lines.index('set-card-profile alsa_card.platform-sound pro-audio'))
            self.assertTrue((self.root/'state/steamos-arm/tb321fu-audio').exists())

    def test_audio_headphones_without_mic_keep_internal_mic(self):
        for mic,capture in ((False,'Mic1'),(True,'Headset')):
            result=self.run_shell(self.audio(),self.audio_mock(hp=True,mic=mic)+'\nstart')
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('set _enadev Headphones set _enadev '+capture,(self.root/'calls').read_text())

    def test_audio_failure_does_not_mark_initialized(self):
        for fail in ('route','set-default-source','set-sink-volume','set-sink-mute'):
            result=self.run_shell(self.audio(),self.audio_mock(fail=fail)+'\nstart')
            self.assertNotEqual(result.returncode,0,fail)
            self.assertFalse((self.root/'state/steamos-arm/tb321fu-audio').exists())

    def test_audio_repeated_start_preserves_volume(self):
        result=self.run_shell(self.audio(),self.audio_mock()+'\nstart && start')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual((self.root/'calls').read_text().count('set-sink-volume'),1)

    def test_audio_wrong_card_and_board_are_excluded(self):
        result=self.run_shell(self.audio(),self.audio_mock(card='USB Audio')+'\nstart')
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('set-card-profile',(self.root/'calls').read_text())
        self.compat('ayaneo,pocketevo')
        result=self.run_shell(self.audio(),'exit 99')
        self.assertEqual(result.returncode,0)

    def test_flip_snapshot_is_stable_until_next_boot_setup(self):
        script=(ARM/'tablet-display-setup').read_text()
        config=self.root/'etc/steamos-arm/flip-screen';config.parent.mkdir(parents=True);config.touch()
        result=self.run_shell(script,prelude='udevadm() { :; }')
        self.assertEqual(result.returncode,0,result.stderr)
        active=self.root/'run/steamos-arm/flip-screen';self.assertTrue(active.exists())
        config.unlink();self.assertTrue(active.exists())
        self.assertEqual(self.run_shell(script,prelude='udevadm() { :; }').returncode,0)
        self.assertFalse(active.exists())
        self.compat('lenovo,tb321fu-extra');config.touch()
        self.assertEqual(self.run_shell(script,prelude='udevadm() { exit 99; }').returncode,0)
        self.assertFalse(active.exists())

    def test_gamescope_exact_flip_gate(self):
        text=(ROOT/'steamos-overlay/usr/lib/steamos/gamescope-session').read_text()
        block=text[text.index('PANEL_ORIENT='):text.index('# Bottom screen (bottom-screen.service)')]
        active=self.root/'run/steamos-arm/flip-screen';active.parent.mkdir(parents=True);active.touch()
        for board,want in [('lenovo,tb321fu','left'),('lenovo,elden','left'),('lenovo,elden-extra','right'),('ayaneo,pocketevo','right')]:
            self.compat(board)
            result=self.run_shell(block,'echo "$PANEL_ORIENT"',prelude='GAMESCOPE_ORIENTATION=right')
            self.assertEqual(result.stdout.strip(),want,result.stderr)

    def test_flip_rpc_board_and_boolean_guard(self):
        p=ROOT/'external-and-mods/Decky/sm8650/konkr-control/main.py'
        tree=ast.parse(p.read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Plugin')
        cls.body=[n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='set_flip']
        ns={'os':os,'Any':object,'FLIP':str(self.root/'flip'),'tablet':lambda:False}
        exec(compile(ast.Module(body=[cls],type_ignores=[]),str(p),'exec'),ns)
        self.assertFalse(asyncio.run(ns['Plugin']().set_flip(True)))
        self.assertFalse((self.root/'flip').exists())
        ns['tablet']=lambda:True
        with self.assertRaises(ValueError):asyncio.run(ns['Plugin']().set_flip('false'))
        self.assertTrue(asyncio.run(ns['Plugin']().set_flip(True)))
        self.assertFalse(asyncio.run(ns['Plugin']().set_flip(False)))

    def firmware(self, mode='changed', reboot=0):
        self.compat('lenovo,elden')
        manifest=self.root/'usr/share/steamos-arm/tablets/elden-firmware.json'
        manifest.parent.mkdir(parents=True,exist_ok=True);manifest.write_text('{}')
        text=(ARM/'tablet-firmware-boot').read_text().replace('/usr/lib/steamos-arm/tablet-firmware ', 'extractor ')
        # Test first-boot policy before the existing device recovery section.
        text=text.split('# Remote processors that failed')[0]+'\nexit 0\n'
        prelude=f'''
sync() {{ :; }}
systemctl() {{ echo "$*" >>"$HOME/reboots"; return {reboot}; }}
extractor() {{
  [[ {shlex.quote(mode)} != fail ]] || return 1
  if [[ {shlex.quote(mode)} == changed ]]; then
    mkdir -p "$2/qcom/sm8750"
    echo mock >"$2/qcom/sm8750/adsp.mdt"; echo mock >"$2/qcom/sm8750/adsp_dtb.mdt"
    echo changed >"${{@: -1}}"
  fi
}}
'''
        return self.run_shell(text,prelude=prelude)

    def test_firmware_one_reboot_and_failure_retry(self):
        self.assertNotEqual(self.firmware(reboot=1).returncode,0)
        dest=self.root/'var/lib/steamos-arm/firmware/elden'
        self.assertTrue((dest/'.first-boot-restart-pending').exists())
        self.assertFalse((dest/'.first-boot-restarted').exists())
        self.assertEqual(self.firmware(mode='unchanged').returncode,0)
        self.assertTrue((dest/'.first-boot-restarted').exists())
        self.assertEqual(self.firmware(mode='unchanged').returncode,0)
        self.assertEqual((self.root/'reboots').read_text().count('reboot'),2)

    def test_firmware_partial_and_extraction_failure_do_not_reboot(self):
        self.assertNotEqual(self.firmware(mode='fail').returncode,0)
        self.assertFalse((self.root/'reboots').exists())
        self.assertEqual(self.firmware(mode='unchanged').returncode,0)
        self.assertFalse((self.root/'reboots').exists())
        self.assertEqual(self.firmware().returncode,0)
        self.assertEqual((self.root/'reboots').read_text().count('reboot'),1)

    def test_existing_firmware_update_does_not_reboot(self):
        dest=self.root/'var/lib/steamos-arm/firmware/elden';dest.mkdir(parents=True);(dest/'old').touch()
        self.assertEqual(self.firmware().returncode,0)
        self.assertFalse((self.root/'reboots').exists())

    def test_battery_excludes_accessories_and_absent(self):
        values={'/pad/type':'Battery','/pad/scope':'Device','/absent/type':'Battery','/absent/present':'0','/system/type':'Battery'}
        ns={'glob':types.SimpleNamespace(glob=lambda _:['/pad','/absent','/system']),'rd':lambda p,d='':values.get(p,d)}
        functions(ARM/'vpower',{'battery'},ns)
        self.assertEqual(ns['battery'](),'/system')
        values['/system/scope']='Device';self.assertIsNone(ns['battery']())

    def test_charge_thresholds_order_and_board_gate(self):
        bat=self.root/'sys/class/power_supply/battery';bat.mkdir(parents=True)
        for n,v in [('type','Battery'),('scope','System'),('present','1'),('charge_control_end_threshold','80'),('charge_control_start_threshold','70')]: (bat/n).write_text(v)
        script=(ARM/'tablet-charge-full').read_text()
        result=self.run_shell(script,prelude='sleep() { :; }')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual((bat/'charge_control_end_threshold').read_text().strip(),'100')
        self.assertEqual((bat/'charge_control_start_threshold').read_text().strip(),'95')
        self.compat('ayaneo,pocketevo');(bat/'charge_control_end_threshold').write_text('80')
        self.assertEqual(self.run_shell(script).returncode,0)
        self.assertEqual((bat/'charge_control_end_threshold').read_text(),'80')

    def test_fanless_turbo_keeps_schedutil(self):
        writes=[]
        ns={'rd':lambda p: ('lenovo,tb321fu\0qcom,sm8650\0' if p.endswith('compatible') else 'schedutil performance' if p.endswith('governors') else '6 7' if p.endswith('related_cpus') else '3000000'),
            'glob':types.SimpleNamespace(glob=lambda _:['/policy6']), 'wr':lambda p,v:writes.append((p,v)), 'big_cpus':lambda:{6,7}}
        functions(ROOT/'sm8650-overlay/usr/lib/konkr/konkrd',{'fanless','apply_cpu'},ns)
        ns['apply_cpu']('turbo');self.assertIn(('/policy6/scaling_governor','schedutil'),writes)
        old=ns['rd'];ns['rd']=lambda p:'ayaneo,pocketevo\0' if p.endswith('compatible') else old(p)
        writes.clear();ns['apply_cpu']('turbo');self.assertIn(('/policy6/scaling_governor','performance'),writes)

    def test_odin3_fanless_turbo(self):
        writes=[]
        ns={'rd':lambda p: 'schedutil performance' if p.endswith('governors') else '6 7',
            'glob':types.SimpleNamespace(glob=lambda _:['/policy6']), 'wr':lambda p,v:writes.append((p,v)),
            'Config':object, 'FANLESS':True}
        functions(ROOT/'sm8750-overlay/usr/lib/odin3/odin3d',{'PowerManager'},ns)
        manager=ns['PowerManager'](None)
        manager.apply_cpu('turbo');self.assertIn(('/policy6/scaling_governor','schedutil'),writes)
        writes.clear();ns['FANLESS']=False;manager.apply_cpu('turbo')
        self.assertIn(('/policy6/scaling_governor','performance'),writes)

    def test_fresh_limiter_dependency_before_tablet_install(self):
        # Execute only the dependency branch, substituting a non-building stub.
        for path in ('scripts/apply-overlays.sh','scripts/apply-overlays-sm8750.sh'):
            text=(ROOT/path).read_text()
            start=text.index('if [[ ! -s "$R/usr/lib/lv2/dpl.lv2/dpl.so"')
            end=text.index('fi',start)+2
            block=text[start:end].replace('"${SCRIPT_DIR}/build-dpl-lv2-in-rootfs.sh" "$R"','stage_limiter')
            self.assertLess(start,text.index('/install-tb321fu.sh' if path.endswith('apply-overlays.sh') else '/install-elden.sh'))
            root=self.root/Path(path).stem;root.mkdir()
            setup='R='+shlex.quote(str(root))+'''

stage_limiter() {
  echo called >>"$R/count"
  mkdir -p "$R/usr/lib/lv2/dpl.lv2"
  echo fixture >"$R/usr/lib/lv2/dpl.lv2/dpl.so"
  echo fixture >"$R/usr/lib/lv2/dpl.lv2/manifest.ttl"
}
'''
            result=subprocess.run(['bash','-c',setup+block+'\n'+block],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual((root/'count').read_text(),'called\n')

if __name__=='__main__': unittest.main()
