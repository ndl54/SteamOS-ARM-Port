#!/usr/bin/env python3
"""Bind rebuilt components to reviewed source bytes; verify again before repack."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO=Path(__file__).resolve().parents[1]
SCOPES=['external-and-mods/kernel-common','external-and-mods/kernel-sm8550',
        'external-and-mods/kernel-pocketevo','external-and-mods/gamescope',
        'external-and-mods/InputPlumber','external-and-mods/MangoHud-qualcomm',
        'scripts/build-inputplumber-konkr.sh','scripts/build-gamescope-in-rootfs.sh',
        'scripts/build-mangohud-in-rootfs.sh']
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for data in iter(lambda:f.read(1024*1024),b''): h.update(data)
    return h.hexdigest()
def inputs():
    names=subprocess.check_output(['git','-C',str(REPO),'ls-files','-z','--',*SCOPES]).decode().split('\0')
    return {n:sha(REPO/n) for n in names if n and not (n.startswith('external-and-mods/InputPlumber/inputplumber-')) and (REPO/n).is_file()}
def outputs(paths):
    result={}
    for path in paths:
        for p in sorted(path.rglob('*')) if path.is_dir() else [path]:
            if p.is_file() and not p.is_symlink(): result[str(p.resolve())]=sha(p)
    return result

def main():
    action,path=sys.argv[1],Path(sys.argv[2])
    if action=='create':
        kernel,gs,ip,mh,ks,stagedgs=map(lambda p:Path(p).resolve(),sys.argv[3:])
        # Compare every vendored Gamescope source file with the compiled source
        # copy, excluding subprojects supplied by its separately pinned checkout.
        for n,digest in inputs().items():
            prefix='external-and-mods/gamescope/'
            if n.startswith(prefix) and not n.startswith(prefix+'subprojects/'):
                actual=stagedgs/n[len(prefix):]
                assert actual.is_file() and sha(actual)==digest, n
        data={'source_commit':subprocess.check_output(['git','-C',str(REPO),'rev-parse','HEAD'],text=True).strip(),
              'repo_inputs_sha256':inputs(),
              'outputs_sha256':outputs([kernel,gs/'src/gamescope',gs/'src/gamescopectl',gs/'src/gamescopereaper',gs/'src/gamescopestream',gs/'layer/libVkLayer_FROG_gamescope_wsi_aarch64.so',ip/'inputplumber-0.81.0-konkr',mh/'mangoapp']),
              'kernel_config_sha256':sha(ks/'.config'),
              'kernel_patch_stamp':(ks/'.pocketevo-patched').read_text().strip(),
              'kernel_source_tar_sha256':sha(ks.parent/'cache/linux-7.2.8.tar.xz'),
              'compiler':subprocess.check_output(['gcc','--version'],text=True).splitlines()[0],
              'rocknix_commit':subprocess.check_output(['git','-C','/work/rocknix','rev-parse','HEAD'],text=True).strip(),
              'inputplumber_ref':'ea60d873cca17edd1cb655ede26f557108135252',
              'mangohud_ref':'992103e4fb744897826de04ea00a2f71e7018214',
              'hardware_tested':False}
        path.write_text(json.dumps(data,indent=2)+'\n')
    elif action=='verify':
        data=json.loads(path.read_text()); assert data['repo_inputs_sha256']==inputs(), 'Component source changed: rebuild affected component'
        for n,digest in data['outputs_sha256'].items(): assert sha(Path(n))==digest,n
        print('Component source/output hashes verified')
    else: raise ValueError(action)
if __name__=='__main__': main()
