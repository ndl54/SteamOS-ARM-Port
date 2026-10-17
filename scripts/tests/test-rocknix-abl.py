#!/usr/bin/env python3
"""ABL source regression probes; never execute real staging or device tools.

Every Android path is rewritten to a temporary directory, the block-file
predicate becomes a regular-file predicate, and the entire command PATH is
mocked. The mocks reject any path outside that directory. No dd, sync,
blockdev, mount, adb, fastboot, reboot or build command is invoked.
"""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'external-and-mods/rocknix-abl'
IMAGE = b'synthetic-ABL-image\x00' * 8
SOCPARAMS = {
    'SM8550': ('SM8550 QCS8550', 'kalama'),
    'SM8650': ('SM8650', 'pineapple'),
    'SM8750': ('SM8750 CQ8725S', 'sun'),
}
MOCK = r'''
import hashlib,json,os,pathlib,shutil,sys,tempfile
root = pathlib.Path(os.environ['MOCK_ROOT']).resolve()
cmd = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
log = root/'calls.jsonl'
with log.open('a') as f: f.write(json.dumps([cmd,args])+'\n')
def path(s):
    p=pathlib.Path(s).resolve()
    assert p.is_relative_to(root), ('OUTSIDE SYNTHETIC ROOT',str(p))
    return p
if os.environ.get('FAIL_TOOL') == cmd: sys.exit(1)
if cmd == 'getprop':
    print(os.environ.get('MODEL','SM8550') if args[0]=='ro.soc.model' else os.environ.get('PLATFORM','kalama'))
elif cmd == 'blockdev':
    assert args[0]=='--getsize64'
    print(path(args[1]).stat().st_size)
elif cmd == 'readlink': print(path(args[1]))
elif cmd == 'sha256sum': print(hashlib.sha256(path(args[0]).read_bytes()).hexdigest()+'  '+args[0])
elif cmd == 'wc': print(len(sys.stdin.buffer.read()))
elif cmd == 'tr': sys.stdout.write(''.join(sys.stdin.read().split()))
elif cmd == 'mktemp':
    assert args[0]=='-d'
    p=path(args[1]); print(tempfile.mkdtemp(prefix=p.name[:-6],dir=p.parent))
elif cmd == 'cp': shutil.copyfile(path(args[0]),path(args[1]))
elif cmd == 'mv': path(args[0]).rename(path(args[1]))
elif cmd == 'rm':
    assert args[0]=='-rf'
    p=path(args[1]); assert p.name.startswith('.abl-work.')
    if p.exists(): shutil.rmtree(p)
elif cmd == 'sync': pass
elif cmd == 'head':
    assert args[0]=='-c'
    sys.stdout.buffer.write(path(args[2]).read_bytes()[:int(args[1])])
elif cmd == 'dd':
    opts=dict(a.split('=',1) for a in args)
    src,dst=path(opts['if']),path(opts['of'])
    write=dst.parent.name=='devices'
    slot=(dst if write else src).name[-1]
    data=src.read_bytes()
    if not write and os.environ.get('SHORT_BACKUP')==slot: data=data[:8]
    if not write and os.environ.get('CORRUPT_BACKUP')==slot: data=b'!'+data[1:]
    if not write and os.environ.get('FAIL_BACKUP')==slot: sys.exit(1)
    if write:
        old=dst.read_bytes()
        assert len(data)<=len(old), 'oversized partition write'
        if os.environ.get('FAIL_WRITE')==slot:
            dst.write_bytes(data[:4]+old[4:]); sys.exit(1)
        if os.environ.get('CORRUPT_WRITE')==slot: data=b'!'+data[1:]
        dst.write_bytes(data+old[len(data):])
    else: dst.write_bytes(data)
else: raise AssertionError(('UNMOCKED COMMAND',cmd,args))
'''


class AblTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='abl safety ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.folder = self.root/'sdcard'/'rocknix_abl'
        self.folder.mkdir(parents=True)
        self.devices = self.root/'devices'
        self.devices.mkdir()
        self.original = {'a': b'A'*1024, 'b': b'B'*1536}
        for slot, data in self.original.items(): (self.devices/f'abl_{slot}').write_bytes(data)
        self.bin = self.root/'bin'
        self.bin.mkdir()
        for tool in ('getprop','blockdev','readlink','sha256sum','dd','head','wc','tr','mktemp','cp','mv','rm','sync'):
            p=self.bin/tool
            p.write_text('#!'+sys.executable+'\n'+MOCK)
            p.chmod(0o755)
        self.env = {'MOCK_ROOT':str(self.root),'PATH':'', 'LC_ALL':'C'}

    def render(self, action, soc='SM8550', image=IMAGE):
        # Mirror only template concatenation/substitution, not the stager.
        models, platform = SOCPARAMS[soc]
        text=(SRC/'abl-safety.sh').read_text()+(SRC/f'{action}_abl.sh').read_text()
        for key,value in {'SOC':soc,'MODELS':models,'PLATFORM':platform,'VERSION':'1.2',
                          'SHA256':hashlib.sha256(image).hexdigest()}.items():
            text=text.replace('@'+key+'@',value)
        self.assertNotIn('@',text)
        self.assertEqual(text.count('PATH=/system/bin:/system/xbin'),1)
        self.assertEqual(text.count('[ -b "$part" ]'),1)
        text=text.replace('PATH=/system/bin:/system/xbin','PATH='+shlex.quote(str(self.bin)))
        for key,value in [('D=/sdcard/rocknix_abl',self.folder),
                          ('A=/dev/block/by-name/abl_a',self.devices/'abl_a'),
                          ('B=/dev/block/by-name/abl_b',self.devices/'abl_b')]:
            self.assertEqual(text.count(key),1)
            text=text.replace(key,key[:2]+shlex.quote(str(value)))
        text=text.replace('[ -b "$part" ]','[ -f "$part" ]')
        text=text.replace('/dev/null',shlex.quote(str(self.root/'null-output')))
        self.assertNotIn('/dev/',text)
        self.assertNotIn('D=/sdcard/',text)
        (self.folder/f'abl_signed-{soc}.elf').write_bytes(image)
        return text

    def run_action(self, action='flash', soc='SM8550', shell='/bin/dash', image=IMAGE, **env):
        result=subprocess.run([shell,'-c',self.render(action,soc,image),'root-tool-stdin'],
            cwd=self.root,env={**self.env,**env},text=True,capture_output=True,timeout=25)
        self.assertNotIn('OUTSIDE SYNTHETIC ROOT',result.stderr)
        self.assertNotIn('UNMOCKED COMMAND',result.stderr)
        return result

    def calls(self):
        p=self.root/'calls.jsonl'
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def writes(self):
        return [args for cmd,args in self.calls() if cmd=='dd' and any(x.startswith('of='+str(self.devices)) for x in args)]

    def assert_stopped(self, result, writes=0):
        self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertNotIn('Done.',result.stdout)
        self.assertEqual(len(self.writes()),writes)

    def seed_backup(self):
        for slot,data in self.original.items():
            p=self.folder/f'abl_{slot}.img'
            p.write_bytes(data)
            Path(str(p)+'.sha256').write_text(hashlib.sha256(data).hexdigest()+'\n')

    def test_success_keeps_backup_and_restores_per_slot(self):
        result=self.run_action()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(len(self.writes()),2)
        for slot,data in self.original.items():
            self.assertEqual((self.folder/f'abl_{slot}.img').read_bytes(),data)
            self.assertEqual((self.devices/f'abl_{slot}').read_bytes(),IMAGE+data[len(IMAGE):])
        self.assertEqual(self.run_action('backup').returncode,0)
        self.assertEqual(len(self.writes()),2)
        self.assertEqual(self.run_action('restore').returncode,0)
        for slot,data in self.original.items(): self.assertEqual((self.devices/f'abl_{slot}').read_bytes(),data)
        self.assertFalse(list(self.folder.glob('.abl-work.*')))

    def test_backup_failures_precede_any_write(self):
        for flag in ('FAIL_BACKUP','SHORT_BACKUP','CORRUPT_BACKUP'):
            for slot in ('a','b'):
                with self.subTest(flag=flag,slot=slot):
                    result=self.run_action(**{flag:slot})
                    self.assert_stopped(result)
                    self.assertFalse(list(self.folder.glob('abl_?.img')))
                    self.assertFalse(list(self.folder.glob('.abl-work.*')))

    def test_partial_and_legacy_backups_never_overwritten(self):
        p=self.folder/'abl_a.img'; p.write_bytes(b'original partial')
        self.assert_stopped(self.run_action())
        self.assertEqual(p.read_bytes(),b'original partial')
        p.write_bytes(self.original['a'])
        (self.folder/'abl_b.img').write_bytes(self.original['b'])
        self.assert_stopped(self.run_action('restore'))
        self.assertEqual(p.read_bytes(),self.original['a'])

    def test_invalid_backups_stop_before_restore(self):
        self.seed_backup()
        p=self.folder/'abl_b.img'
        p.write_bytes(b'wrong size')
        self.assert_stopped(self.run_action('restore'))
        p.write_bytes(b'Z'*len(self.original['b']))
        self.assert_stopped(self.run_action('restore'))

    def test_old_layout_backup_is_not_bypassed(self):
        old=self.folder/'SM8550'/'abl_a.img'
        old.parent.mkdir()
        old.write_bytes(b'original backup from older layout')
        self.assert_stopped(self.run_action())
        self.assert_stopped(self.run_action('restore'))
        self.assertEqual(old.read_bytes(),b'original backup from older layout')

    def test_backup_preserved_on_reflash(self):
        self.seed_backup()
        self.assertEqual(self.run_action().returncode,0)
        self.assertEqual(self.run_action().returncode,0)
        for slot,data in self.original.items(): self.assertEqual((self.folder/f'abl_{slot}.img').read_bytes(),data)

    def test_unknown_chip_properties_or_missing_tools_stop(self):
        for env in ({'MODEL':'unknown','PLATFORM':'wrong'}, {'MODEL':'','PLATFORM':''},
                    {'FAIL_TOOL':'getprop'}, {'FAIL_TOOL':'blockdev'}, {'FAIL_TOOL':'readlink'},
                    {'FAIL_TOOL':'sha256sum'}, {'FAIL_TOOL':'sync'}):
            with self.subTest(env=env): self.assert_stopped(self.run_action(**env))
        (self.bin/'getprop').unlink()
        self.assert_stopped(self.run_action())

    def test_partition_alias_and_missing_slot_stop(self):
        b=self.devices/'abl_b'; b.unlink(); b.symlink_to(self.devices/'abl_a')
        self.assert_stopped(self.run_action())
        b.unlink()
        self.assert_stopped(self.run_action())

    def test_oversize_image_stops(self):
        self.assert_stopped(self.run_action(image=b'oversize'*300))

    def test_wrong_pinned_digest_stops(self):
        text=self.render('flash')
        (self.folder/'abl_signed-SM8550.elf').write_bytes(b'wrong image')
        r=subprocess.run(['/bin/dash','-c',text],cwd=self.root,env=self.env,text=True,capture_output=True,timeout=25)
        self.assert_stopped(r)

    def test_slot_write_and_readback_failures_stop_in_order(self):
        self.seed_backup()
        for flag in ('FAIL_WRITE','CORRUPT_WRITE'):
            for slot in ('a','b'):
                with self.subTest(flag=flag,slot=slot):
                    (self.root/'calls.jsonl').write_text('')
                    result=self.run_action(**{flag:slot})
                    self.assert_stopped(result,1 if slot=='a' else 2)
                    self.assertIn('Do NOT restart',result.stderr)
                    for s,data in self.original.items(): self.assertEqual((self.folder/f'abl_{s}.img').read_bytes(),data)

    def test_restore_failure_never_claims_success(self):
        self.seed_backup()
        self.assert_stopped(self.run_action('restore',FAIL_WRITE='a'),1)

    def test_read_sync_cleanup_errors_do_not_claim_success(self):
        self.seed_backup()
        for tool in ('head','sync','rm'):
            with self.subTest(tool=tool):
                (self.root/'calls.jsonl').write_text('')
                result=self.run_action(FAIL_TOOL=tool)
                self.assert_stopped(result,2 if tool=='rm' else 1)

    def test_three_chip_templates_work_with_bare_shells(self):
        self.seed_backup()
        for soc,(models,platform) in SOCPARAMS.items():
            for shell in ('/bin/dash','/bin/bash'):
                with self.subTest(soc=soc,shell=shell):
                    r=self.run_action(soc=soc,shell=shell,MODEL=models.split()[0],PLATFORM=platform)
                    self.assertEqual(r.returncode,0,r.stdout+r.stderr)

    def test_stager_only_templates_flat_folder_and_retains_backups(self):
        text=(ROOT/'scripts/stage-rocknix-abl.sh').read_text()
        self.assertIn('out=$BOOT/rocknix_abl\n',text)
        self.assertNotIn('rm -rf "$out"',text)
        self.assertIn('cat "$SRC/abl-safety.sh" "$SRC/$s.sh" | fill',text)
        self.assertIn('s|@SHA256@|$want|g',text)
        # Execute just the actual pure text fill function, never staging.
        fill=text.split('fill() {',1)[1].split('\nfor s in ',1)[0]
        for soc,(models,platform) in SOCPARAMS.items():
            release=dict(line.split('=',1) for line in (SRC/'release.env').read_text().splitlines() if line.startswith('ABL_'))
            variables={'soc':soc,'models':models,'platform':platform,'ABL_VERSION':release['ABL_VERSION'],
                       'devices':'fixture labels','want':release['ABL_SHA256_'+soc]}
            script='\n'.join(k+'='+shlex.quote(v) for k,v in variables.items())+'\nfill() {'+fill+'\nfill\n'
            for action in ('flash','backup','restore'):
                source=(SRC/'abl-safety.sh').read_text()+(SRC/f'{action}_abl.sh').read_text()
                r=subprocess.run(['/bin/bash','-c',script],input=source,text=True,capture_output=True,check=True)
                self.assertNotIn('@',r.stdout)
                self.assertTrue(r.stdout.startswith('#!/system/bin/sh\n'))
                for shell in ('/bin/dash','/bin/bash'):
                    subprocess.run([shell,'-n'],input=r.stdout,text=True,check=True)


if __name__ == '__main__': unittest.main()
