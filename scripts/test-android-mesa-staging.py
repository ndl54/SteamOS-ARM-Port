#!/usr/bin/env python3
"""Exercise the isolated Mesa staging block with temporary text fixtures only."""
import os
from pathlib import Path
import subprocess
import tempfile

repo = Path(__file__).resolve().parents[1]
current = (repo / 'scripts/apply-overlays.sh').read_text()
old = subprocess.check_output(['git', 'show', 'c2308e448f17114db9bc399f56797ed543d37f80:scripts/apply-overlays.sh'], cwd=repo, text=True)
vendor = 'usr/share/guestos/android/vendor/lib64'
files = ['hw/vulkan.freedreno.so', 'libgallium_dri.so', 'libgbm_mesa.so', 'dri_gbm.so', 'egl/libEGL_mesa.so', 'egl/libGLESv2_mesa.so', 'egl/libGLESv1_CM_mesa.so']

def run(source, restored=False, bundle=False, repeat=False):
    with tempfile.TemporaryDirectory(prefix='mesa041-') as td:
        base = Path(td); root = base/'root'; stack = base/'mesa'; stock = root/'opt/stock-steamos'
        def put(p, value):
            p.parent.mkdir(parents=True, exist_ok=True); p.write_text(value)
        for f in files:
            put(root/vendor/f, 'custom-old' if restored else 'valve')
            if restored: put(stock/vendor/f, 'valve')
            if bundle: put(stack/'android'/vendor/f, 'custom-new')
        put(root/vendor/'unrelated-vendor.so', 'keep')
        for arch, lib in [('aarch64','lib'),('x86_64','lib'),('i386','lib32')]:
            put(stack/arch/f'usr/{lib}/libgallium-test.so', 'Mesa 26.2.3')
            put(stack/arch/f'usr/{lib}/dri/zink_dri.so', 'linux-new')
            put(stack/arch/'usr/share/vulkan/icd.d/freedreno_icd.test.json', '{}')
        guest = root/'usr/share/guestos/fex-mesa'
        for p in [root/'usr/lib', root/'usr/share', guest/'usr/lib', guest/'usr/lib32', guest/'usr/share/vulkan']:
            p.mkdir(parents=True, exist_ok=True)
        for pkg, file in [('deckard-mesa-linux-aarch64','usr/lib/old.so'),('deckard-mesa-linux-x86_64','usr/share/guestos/fex-mesa/usr/lib/old.so'),('deckard-mesa-android-aarch64',vendor+'/'+files[0])]:
            put(root/f'usr/lib/holo/pacmandb/local/{pkg}-1/files', '%FILES%\n'+file+'\n')
            if 'android' not in pkg: put(root/file, 'linux-old')
        # Execute only the Mesa-stack branch against disposable text fixtures.
        # Ownership is mocked; no installer/build entrypoint or runtime is run.
        block = source.split('if [[ -n "${MESA_STACK:-}" ]]; then\n',1)[1].split('elif [[ -n "$MESA_SO" ]]; then',1)[0]
        script = 'set -euo pipefail\nlog() { :; }\ndie() { echo "$*" >&2; exit 1; }\nchown() { :; }\n'+block
        env = dict(os.environ, R=str(root), STOCK=str(stock), MESA_STACK=str(stack))
        for _ in range(2 if repeat else 1):
            result = subprocess.run(['bash','-c',script],env=env,capture_output=True,text=True)
            if result.returncode: return result.returncode, result.stderr
        assert all((root/vendor/f).read_text() == 'valve' for f in files)
        assert (root/vendor/'unrelated-vendor.so').read_text() == 'keep'
        assert (root/'usr/lib/dri/zink_dri.so').read_text() == 'linux-new'
        assert (guest/'usr/lib/dri/zink_dri.so').read_text() == 'linux-new'
        assert (guest/'usr/lib32/dri/zink_dri.so').read_text() == 'linux-new'
        assert not (root/'usr/lib/old.so').exists()
        assert (stock/'usr/lib/old.so').read_text() == 'linux-old'
        assert 'MESA_LOADER_DRIVER_OVERRIDE=zink' in (root/'usr/lib/environment.d/60-sm8550-zink.conf').read_text()
        return 0, ''

status, error = run(old)
assert status != 0 and 'no android build' in error
print('PASS: pre-merge regression reproduced (Linux-only bundle rejected)')
for name, kwargs in [('fresh Linux-only bundle',{}),('fresh with ignored Android bundle',{'bundle':True}),('reused stock restore',{'restored':True,'bundle':True}),('repeated stock restore',{'restored':True,'repeat':True})]:
    status, error = run(current, **kwargs)
    assert status == 0, (name,error)
    print('PASS:',name)
