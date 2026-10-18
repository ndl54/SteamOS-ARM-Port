#!/usr/bin/env python3
"""Offline targeted kernel-patch regression for 090; never compiles or runs C.

SLEEP_SOURCE_ROOT must contain linux/<version>/<path> and
rocknix/<release>/<path> files pinned by fixtures/sleep-kernel-090.json.
Only changed driver file hunks are replayed, in the common builder's order.
"""
from pathlib import Path
import subprocess,os,json,hashlib,re,shutil,tempfile
repo=Path(os.environ.get('SLEEP_REPO_ROOT', Path(__file__).resolve().parents[2]))
root=Path(os.environ["SLEEP_SOURCE_ROOT"])
manifest=json.loads((Path(__file__).parent/'fixtures/sleep-kernel-090.json').read_text())
targets=sorted({t for _,t,_ in manifest['linux']})
variants=[('sm8550',{'SM8550_RECIPE':'7.1'}),('sm8550',{'SM8550_RECIPE':'7.2'}),('sm8650',{}),('sm8650',{'SM8650_RECIPE':'7.1'}),('sm8750',{}),('pocketevo',{}),('tb321fu',{})]
rows=[];jobs={};pins={}
for soc,extra in variants:
 env={k:v for k,v in os.environ.items() if k not in ('SM8550_RECIPE','SM8650_RECIPE','DTBS_OVERRIDE')};env.update(extra)
 vals=subprocess.check_output(['bash','-c','source "$1"; printf "%s\n" "$KVER" "$ROCKNIX_REF" "$PATCH_DIRS" "${PATCH_SKIP:-}" "${PORT_DIRS:-kernel-'+soc+'}" "${PATCH_OVERRIDE_DIR:-}"','bash',str(repo/f'external-and-mods/kernel-{soc}/soc.env')],env=env,text=True).splitlines()
 ver,ref,dirs,skip,ports,override=vals;cache=root/'rocknix'/ref;pin=manifest['rocknix'][ref];entries=pin['patches'];paths=[];pins[ref]=pin['revision']
 for d in dirs.split():
  for name in sorted(p for p in entries if p.startswith(d+'/') and p.endswith('.patch') and '/' not in p[len(d)+1:]):
   jobs[(ref,name)]=(cache/name,entries[name],pin['revision']);paths.append(name)
 rows.append((soc,ver,ref,paths,skip.split(),ports.split(),override))
resolved={}
for (ref,name),(p,sha,pin) in jobs.items():
 b=p.read_bytes()
 assert hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()==sha,(ref,name)
 resolved[(ref,name)]=p
print('Verified',len(resolved),'ROCKNIX blobs',pins)
for ver,t,sha in manifest['linux']:
 p=root/'linux'/ver/t
 if sha:assert hashlib.sha256(p.read_bytes()).hexdigest()==sha,(ver,t)
 else:assert not p.exists(),(ver,t)
def section(s):
 parts=re.split(r'(?m)(?=^--- (?:a/|/dev/null))',s)[1:];chunks=[]
 for part in parts:
  lines=part.splitlines(True)
  if not any(re.match(r'^\+\+\+ b/'+re.escape(t)+r'(?:\s|$)',lines[1]) for t in targets):continue
  keep=lines[:2];i=2
  while i<len(lines):
   m=re.match(r'@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@',lines[i])
   if not m:break
   keep.append(lines[i]);a=int(m[1] or 1);b=int(m[2] or 1);i+=1
   while a or b:
    line=lines[i];keep.append(line);i+=1
    if line[0] in ' -':a-=1
    if line[0] in ' +':b-=1
   if i<len(lines) and lines[i].startswith('\\'):keep.append(lines[i]);i+=1
  chunks.append(''.join(keep))
 return ''.join(chunks)
temp=tempfile.TemporaryDirectory(prefix="sleep-090-")
results=[]
for soc,ver,ref,paths,skip,ports,override in rows:
 name=soc+'-'+ver;dest=Path(temp.name)/name
 if dest.exists():shutil.rmtree(dest)
 for target in targets:
  if (root/'linux'/ver/target).exists():
   (dest/target).parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(root/'linux'/ver/target,dest/target)
 selected=[resolved[(ref,n)] for n in paths]
 for port in ports:
  for p in sorted((repo/'external-and-mods'/port/'patches').glob('*.patch')):
   over=Path(override)/p.name;selected.append(over if override and over.exists() else p)
 applied=[];fail=[]
 for p in selected:
  if p.name in skip or p.name=='9900-i915-10bit-hack.patch':continue
  over=Path(override)/p.name
  if override and over.exists():p=over
  diff=section(p.read_bytes().decode('latin1'))
  if not diff:continue
  r=subprocess.run(['patch','-p1','-N','--batch','--fuzz='+('0' if soc=='pocketevo' else '2')],cwd=dest,input=diff,text=True,capture_output=True)
  if r.returncode:fail.append({'patch':str(p),'output':r.stdout+r.stderr})
  applied.append(str(p))
 results.append({'variant':name,'applied':applied,'fail':fail,'sha256':{t:hashlib.sha256((dest/t).read_bytes()).hexdigest() for t in targets if (dest/t).exists()}})
 print(name,'FAIL' if fail else 'PASS',len(applied),'patches',json.dumps(fail),flush=True)
assert all(not r['fail'] for r in results), 'Patch chain regression'


# Source-level lifecycle contracts: these complement patch applicability, not C execution.
active=[r for r in results if r['variant']!='sm8650-7.1.2']
for r in active:
 d=Path(temp.name)/r['variant']
 def read(t): return (d/t).read_text()
 def body(s,name):
  start=re.search(r'\b'+re.escape(name)+r'\(', s).start();start=s.index('{',start);depth=1;i=start+1
  while depth:
   depth+=(s[i]=='{')-(s[i]=='}');i+=1
  return s[start:i]
 k=read('drivers/input/misc/pm8941-pwrkey.c')
 irq=body(k,'pm8941_pwrkey_irq')
 assert 'guard(mutex)(&pwrkey->sleep_lock)' in irq
 assert 'static bool pm8941_pwrkey_sleeping' not in k
 assert 'if (pwrkey->ignored_press)' in irq and 'if (!sts && pwrkey->suppress_release)' in irq
 assert 'input_report_key(pwrkey->input, pwrkey->code, 0)' in body(k,'pm8941_pwrkey_suspend')
 dsi=read('drivers/gpu/drm/msm/dsi/phy/dsi_phy.c')
 assert 'pm_clk_add(' not in dsi and 'pm_clk_suspend' not in dsi
 assert 'if (!ret) {\n\t\tphy->iface_prepared = true;' in dsi
 assert 'clk_is_enabled_when_prepared(phy->iface_vote)' in dsi
 assert 'phy->iface_sleep_dropped ? dsi_phy_prepare_iface(dev) : 0' in dsi
 assert body(dsi,'dsi_phy_runtime_resume').index('dsi_phy_prepare_iface') < body(dsi,'dsi_phy_runtime_resume').index('clk_enable')
 assert dsi.index('devm_add_action_or_reset(dev, dsi_phy_iface_cleanup') < dsi.index('devm_pm_runtime_enable(dev)')
 batt=read('drivers/power/supply/qcom_battmgr.c')
 for cb in ['qcom_battmgr_pm_prepare','qcom_battmgr_pm_complete','qcom_battmgr_enable_worker']:
  b=body(batt,cb)
  call = 'qcom_battmgr_request(' if cb == 'qcom_battmgr_enable_worker' else 'qcom_battmgr_set_notify('
  assert b.index('mutex_lock(&battmgr->lock)') < b.index(call) < b.index('mutex_unlock(&battmgr->lock)')
  if cb == 'qcom_battmgr_enable_worker': assert 'battmgr->sleep_notifications_off ? 0 :' in b
 for n in ['rx','tx','wsa','va']:
  m=read('sound/soc/codecs/lpass-'+n+'-macro.c')
  assert 'pm_runtime_disable(&pdev->dev)' in body(m,n+'_macro_remove')
  assert 'if (!pm_runtime_status_suspended(&pdev->dev))' in body(m,n+'_macro_remove')
  resume=body(m,n+'_macro_runtime_resume_clks')
  assert 'ret = regcache_sync(' in resume and 'regcache_cache_only('+n+'->regmap, true)' in resume
 if r['variant']!='sm8750-7.2':
  w=read('sound/soc/codecs/wsa884x.c')
  work=body(w,'wsa884x_pa_check_work');mute=body(w,'wsa884x_mute_stream')
  assert 'guard(mutex)(&wsa884x->pa_lock)' in work and 'guard(mutex)(&wsa884x->pa_lock)' in mute
  assert 'err0 == BIT(6) && !err1' in work and '(intr1 & BIT(1))' in work
  assert 'system_freezable_wq' in work and 'system_freezable_wq' in mute
  assert 'pm_runtime_get_if_active' in work and 'pm_runtime_put_autosuspend' in work
  assert 'cancel_delayed_work_sync' in w and 'pm_runtime_disable(wsa884x->dev)' in body(w,'wsa884x_pa_cleanup')
  probe=body(w,'wsa884x_probe')
  assert probe.index('devm_regmap_init_sdw') < probe.index('pm_runtime_enable') < probe.index('devm_add_action_or_reset(dev, wsa884x_pa_cleanup') < probe.index('devm_snd_soc_register_component')
print('PASS: lifecycle source contracts on',len(active),'active variants')
evo=Path(temp.name)/'pocketevo-7.2.8'
fan=(evo/'drivers/hwmon/pwm-fan.c').read_text()
assert 'pwm_fan_apply_charging' in fan and 'if (!ret && !on)' in fan
assert 'if (ret)\n\t\t\t__set_pwm(ctx, ctx->pwm_awake);' in fan
batt=(evo/'drivers/power/supply/qcom_battmgr.c').read_text()
assert 'case BATTMGR_BAT_PROPERTY_SET:' in batt and 'case BATTMGR_DISABLE_NOTIFICATION:' in batt
led=(evo/'drivers/leds/leds-htr3212.c').read_text()
assert 'guard(mutex)(&priv->sleep_lock)' in body(led,'htr3212_suspend')
assert 'if (priv->suspended)' in body(led,'htr3212_brightness_set')
assert 'ret = __htr3212_brightness_set' in body(led,'htr3212_resume')
assert 'if (ret)\n\t\t\treturn ret;' in body(led,'htr3212_resume')
print('PASS: EVO fan/charge-current and LED lifecycle preservation')
temp.cleanup()
