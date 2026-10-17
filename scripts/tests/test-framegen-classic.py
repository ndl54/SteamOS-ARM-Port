#!/usr/bin/env python3
"""Source054 regressions: temporary files and mocked Decky/process APIs only.
No library is loaded, game/service started, or build/install command executed.
"""
import ast
import asyncio
import hashlib
import importlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
PLUGINS = ROOT / 'external-and-mods/Decky/Plug-ins/homebrew/plugins'
CLASSIC = PLUGINS / 'decky-lsfg-vk-classic'
RUN = subprocess.run
DECKY = types.ModuleType('decky')
DECKY.logger = logging.getLogger('classic-test')
DECKY.DECKY_USER_HOME = '/nonexistent-test-home'
sys.modules['decky'] = DECKY


def package(name, path):
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module


package('classic_test', CLASSIC / 'py_modules/lsfg_vk')
package('v2_test', PLUGINS / 'decky-lsfg-vk/py_modules/lsfg_vk')
I = importlib.import_module('classic_test.installation')
C = importlib.import_module('classic_test.configuration')
S = importlib.import_module('classic_test.config_schema')
P = importlib.import_module('classic_test.plugin')
F = importlib.import_module('classic_test.flatpak_service')
W = importlib.import_module('v2_test.wrapper_service')
spec = importlib.util.spec_from_loader('bundle_test', loader=None)
B = importlib.util.module_from_spec(spec)
# Parse/execute module definitions only. __name__ prevents its service entrypoint.
exec((ROOT / 'steamos-overlay/usr/lib/steamos-arm/decky-plugin-fixes').read_text(), B.__dict__)


class ClassicTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        for target, value in [('HOME', str(self.home)), ('XDG_DATA_HOME', str(self.home / 'data'))]:
            context = patch.dict(os.environ, {target: value})
            context.start(); self.addCleanup(context.stop)
        for context in (patch.object(DECKY, 'DECKY_USER_HOME', str(self.home)),
                        patch.object(I.platform, 'machine', return_value='x86_64'),
                        patch.object(subprocess, 'run', side_effect=AssertionError('Unexpected external process')),
                        patch.object(subprocess, 'Popen', side_effect=AssertionError('Unexpected external process'))):
            context.start(); self.addCleanup(context.stop)
        self.install = I.InstallationService()
        self.config = C.ConfigurationService()
        self.install._ensure_directories()

    def profile(self, name='game-one'):
        defaults = S.ConfigurationManager.get_defaults()
        defaults.update(multiplier=3, dxvk_frame_rate=37, performance_mode=False, enable_wow64=True)
        return {'current_profile': name, 'profiles': {name: defaults},
                'global_config': {'dll': '/games/A "quoted" path/Lossless.dll', 'no_fp16': True}}

    def save(self, data):
        text = S.ConfigurationManager.generate_toml_content_multi_profile(data)
        self.install.config_file_path.write_text(text)
        return text

    def test_install_manifest_and_uninstall_preserve_v2_and_config(self):
        other = self.home / '.local/lib/liblsfg-vk-layer.so'
        other.write_text('v2 sentinel')
        result = self.install.install()
        self.assertTrue(result['success'], result)
        manifest = json.loads(self.install.json_file.read_text())
        self.install._validate_manifest(manifest)
        self.assertTrue(self.install.check_installation()['installed'])
        before = self.install.config_file_path.read_bytes()
        self.assertTrue(self.install.uninstall()['success'])
        self.assertEqual(before, self.install.config_file_path.read_bytes())
        self.assertEqual('v2 sentinel', other.read_text())
        self.assertFalse(self.install.check_installation()['installed'])

    def test_reinstall_preserves_exact_config_and_selected_profile(self):
        data = self.profile()
        original = '# user comment\n' + self.save(data) + '\n# trailing comment\n'
        self.install.config_file_path.write_text(original)
        self.assertTrue(self.install.install()['success'])
        self.assertEqual(original, self.install.config_file_path.read_text())
        script = self.install.lsfg_launch_script_path.read_text()
        self.assertIn('LSFG_PROCESS=game-one', script)
        self.assertIn('DXVK_FRAME_RATE=37', script)
        self.assertIn('PROTON_USE_WOW64=1', script)
        parsed = S.ConfigurationManager.parse_toml_content_multi_profile(original)
        self.assertTrue(parsed['global_config']['no_fp16'])
        self.assertEqual(data['global_config']['dll'], parsed['global_config']['dll'])
        self.assertFalse(parsed['profiles']['game-one']['performance_mode'])

    def test_bad_config_never_defaults_or_installs(self):
        for text in ('invalid = [', 'version=2', 'version=1\n[custom]\nx=2',
                     'version=1\n[global]\ncurrent_profile="missing"\n[[game]]\nexe="one"'):
            with self.subTest(text=text):
                self.install.config_file_path.write_text(text)
                self.assertFalse(self.install.install()['success'])
                self.assertEqual(text, self.install.config_file_path.read_text())
                self.assertFalse(self.install.lib_file.exists())
                self.assertFalse(self.config.get_config()['success'])
                self.assertFalse(self.config.update_config_from_dict(S.ConfigurationManager.get_defaults())['success'])
                self.assertEqual(text, self.install.config_file_path.read_text())

    def test_missing_arm_artifacts_fail_before_mutation(self):
        with patch.object(I.platform, 'machine', return_value='aarch64'), \
             patch.object(I.InstallationService, 'ARM_LIB', self.home / 'missing.so'), \
             patch.object(I.InstallationService, 'ARM_JSON', self.home / 'missing.json'):
            self.assertFalse(self.install.install()['success'])
            self.assertFalse(self.install.check_installation()['installed'])
            self.assertFalse(self.install.lib_file.exists())

    def test_missing_script_or_config_is_not_installed(self):
        self.assertTrue(self.install.install()['success'])
        self.install.lsfg_launch_script_path.unlink()
        self.assertFalse(self.install.check_installation()['installed'])
        self.assertTrue(self.install.install()['success'])
        self.install.config_file_path.unlink()
        self.assertFalse(self.install.check_installation()['installed'])

    def test_corrupt_archive_and_missing_members_fail_without_publication(self):
        archive = self.home / 'bad.zip'
        archive.write_bytes(b'broken')
        with self.assertRaises(ValueError):
            self.install._extract_and_install_files(archive)
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('lib/liblsfg-vk.so', b'not ELF')
        with patch.object(self.install, 'ARCHIVE_SHA256', hashlib.sha256(archive.read_bytes()).hexdigest()):
            with self.assertRaises(KeyError):
                self.install._extract_and_install_files(archive)
        self.assertFalse(self.install.lib_file.exists())
        self.assertFalse(self.install.json_file.exists())

    def test_manifest_failure_never_falls_back_to_ungated(self):
        archive = self.home / 'ungated.zip'
        with zipfile.ZipFile(CLASSIC / 'bin/lsfg-vk_noui.zip') as original, zipfile.ZipFile(archive, 'w') as z:
            for name in original.namelist():
                z.writestr(name, b'{"layer": {"library_path": "other.so"}}' if name.endswith('.json') else original.read(name))
        with patch.object(self.install, 'ARCHIVE_SHA256', hashlib.sha256(archive.read_bytes()).hexdigest()):
            with self.assertRaises(ValueError):
                self.install._extract_and_install_files(archive)
        self.assertFalse(self.install.json_file.exists())

    def test_write_failure_preserves_original(self):
        old = self.save(self.profile())
        with patch.object(C.ConfigurationService, '_write_file', side_effect=OSError('disk full')):
            result = self.config.set_current_profile('game-one')
        self.assertFalse(result['success'])
        self.assertEqual(old, self.install.config_file_path.read_text())
        with patch.object(I.os, 'replace', side_effect=OSError('rename failed')):
            with self.assertRaises(OSError):
                self.install._write_file(self.install.config_file_path, 'new')
        self.assertEqual(old, self.install.config_file_path.read_text())
        self.assertEqual([self.install.config_file_path], list(self.install.config_dir.iterdir()))

    def test_wrapper_failure_is_reported(self):
        self.save(self.profile())
        with patch.object(self.config, 'update_lsfg_script_from_profile_data', return_value={'success': False, 'error': 'denied'}):
            self.assertFalse(self.config.set_current_profile('game-one')['success'])
            self.assertFalse(self.config.update_profile_config('game-one', self.profile()['profiles']['game-one'])['success'])

    def test_invalid_types_and_shell_values_are_rejected(self):
        for key, val in [('dxvk_frame_rate', '1; bad'), ('flow_scale', float('nan')),
                         ('multiplier', True), ('performance_mode', 'false'), ('multiplier', 9)]:
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    S.ConfigurationManager.validate_config({key: val})

    def test_profile_roundtrip_and_isolation(self):
        data = self.profile('name with "quotes"; $HOME')
        original = self.save(data)
        self.assertEqual(data['current_profile'], S.ConfigurationManager.parse_toml_content_multi_profile(original)['current_profile'])
        self.assertTrue(self.config.create_profile('game-two')['success'])
        new = S.ConfigurationManager.parse_toml_content_multi_profile(self.install.config_file_path.read_text())
        self.assertEqual(3, new['profiles']['game-two']['multiplier'])
        new_config = dict(new['profiles']['game-two'], multiplier=2)
        self.assertTrue(self.config.update_profile_config('game-two', new_config)['success'])
        new = S.ConfigurationManager.parse_toml_content_multi_profile(self.install.config_file_path.read_text())
        self.assertEqual(3, new['profiles'][data['current_profile']]['multiplier'])
        self.assertEqual(2, new['profiles']['game-two']['multiplier'])
        self.assertTrue(new['global_config']['no_fp16'])

    def test_classic_flatpak_and_migration_never_touch_v2(self):
        service = F.FlatpakService()
        for method, args in [('get_extension_status', ()), ('get_flatpak_apps', ()),
                             ('install_extension', ('25.08',)), ('uninstall_extension', ('25.08',)),
                             ('set_app_override', ('game.id',)), ('remove_app_override', ('game.id',))]:
            self.assertFalse(getattr(service, method)(*args)['success'])
        plugin = P.Plugin()
        asyncio.run(plugin._migration())  # decky migration functions deliberately absent
        asyncio.run(plugin._uninstall())  # all its owned paths are under the temporary HOME

    def test_unmanaged_launcher_is_preserved(self):
        self.install.lsfg_launch_script_path.write_text("#!/bin/sh\n# user launcher\n")
        before = self.install.lsfg_launch_script_path.read_bytes()
        self.assertFalse(self.install.install()["success"])
        self.assertFalse(self.install.uninstall()["success"])
        self.assertEqual(before, self.install.lsfg_launch_script_path.read_bytes())
        self.assertFalse(self.install.lib_file.exists())

    def test_frontend_rpc_and_schema_contract(self):
        import re
        js = (CLASSIC / "dist/index.js").read_text()
        methods = set(re.findall(r'callable\("([^"]+)"\)', js))
        self.assertFalse(methods - set(dir(P.Plugin)))
        manifest = json.loads(re.search(r'const manifest = (.*);', js)[1])
        self.assertEqual(json.loads((CLASSIC / "plugin.json").read_text()), manifest)
        defaults = re.search(r'function getDefaults\(\) \{\s*return \{(.*?)\};', js, re.S)[1]
        for key, value in S.ConfigurationManager.get_defaults().items():
            raw = re.search(r'\b' + key + r': (.*),', defaults)[1]
            self.assertEqual(value, json.loads(raw))
        self.assertNotIn('~/.config/lsfg-vk/conf.toml', js)
        self.assertIn('Classic does not support Flatpak', js)

    def test_wrapper_environments_and_argument_fidelity(self):
        data = self.profile('a; echo nope')
        classic = self.home / 'classic'
        classic.write_text(self.config._generate_script_content_for_profile(data)); classic.chmod(0o755)
        v2 = W.WrapperService()
        document = {'version': 3, 'apps': {'123': {'state': v2.default_state(), 'command_token_added': True, 'non_steam': False}}}
        wrapper = self.home / 'v2'
        wrapper.write_text(v2._render_wrapper(document)); wrapper.chmod(0o755)
        sink = self.home / 'sink.py'
        sink.write_text('import os,sys,json; print(json.dumps({"env":dict(os.environ),"argv":sys.argv[1:]}))')
        # Restore Popen only for a generated shell ending in this inert Python sink.
        with patch.object(subprocess, 'Popen', ORIGINAL_POPEN):
            for wrappers, expected in [([classic], 'classic'), ([wrapper], 'v2'),
                                       ([wrapper, classic], 'classic'), ([classic, wrapper], 'v2')]:
                env = dict(os.environ, SteamAppId='123', DISABLE_LSFG='1', ENABLE_GAMESCOPE_WSI='1')
                command = [str(x) for x in wrappers] + [sys.executable, '-B', str(sink), 'space arg', '$literal', '']
                result = RUN(command, env=env, capture_output=True, text=True, check=True)
                got = json.loads(result.stdout)
                self.assertEqual(['space arg', '$literal', ''], got['argv'])
                e = got['env']
                self.assertFalse(e.get('LSFG_CLASSIC') == '1' and e.get('DISABLE_LSFGVK') != '1')
                if expected == 'classic':
                    self.assertEqual('1', e['LSFG_CLASSIC']); self.assertEqual('1', e['DISABLE_LSFGVK'])
                    self.assertNotIn('DISABLE_LSFG', e)
                    self.assertEqual(data['current_profile'], e['LSFG_PROCESS'])
                else:
                    self.assertNotIn('LSFG_CLASSIC', e); self.assertNotIn('DISABLE_LSFGVK', e)


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.src = self.root / 'bundles/classic'
        self.dst = self.root / 'plugins/classic'
        self.dst.parent.mkdir()
        self.src.mkdir(parents=True)
        for part, text in [('package.json', '{"version":"1"}'), ('main.py', '# plugin'),
                           ('plugin.json', '{"name":"Classic"}'), ('dist/index.js', '// UI')]:
            path = self.src / part; path.parent.mkdir(exist_ok=True); path.write_text(text)
        for context in (patch.object(B, 'BUNDLED', str(self.src.parent)), patch.object(B, 'PLUGINS', str(self.dst.parent)),
                        patch.object(B, 'STATE', str(self.root / 'state/history.json')),
                        patch.object(subprocess, 'run', side_effect=self.chown),
                        patch.object(subprocess, 'Popen', side_effect=AssertionError('unexpected process'))):
            context.start(); self.addCleanup(context.stop)

    def chown(self, args, **kwargs):
        self.assertEqual(['chown', '-R', '1000:1000'], args[:3])
        self.assertTrue(Path(args[3]).is_relative_to(self.root))
        return subprocess.CompletedProcess(args, 0)

    def version(self, value):
        (self.src / 'package.json').write_text(json.dumps({'version': value}))

    def test_fresh_repeat_removal_and_new_version(self):
        self.assertEqual(['classic 1'], B.install_bundled())
        self.assertEqual([], B.install_bundled())
        shutil.rmtree(self.dst)
        self.assertEqual([], B.install_bundled())
        self.assertFalse(self.dst.exists())
        self.version('2')
        self.assertEqual(['classic 2'], B.install_bundled())

    def test_update_owned_copy(self):
        B.install_bundled(); self.version('2')
        cache = self.dst / '__pycache__'; cache.mkdir()
        (cache / 'main.fake.pyc').write_bytes(b'fixture only, not compiled')
        self.assertEqual(['classic 2'], B.install_bundled())
        self.assertEqual('2', B.version(self.dst))

    def test_preserve_custom_newer_and_modified(self):
        shutil.copytree(self.src, self.dst)
        (self.dst / 'package.json').write_text('{"version":"9"}')
        self.assertEqual([], B.install_bundled())
        self.assertEqual('9', B.version(self.dst))
        shutil.rmtree(self.dst); B.install_bundled(); self.version('2')
        (self.dst / 'user-settings').write_text('keep')
        self.assertEqual([], B.install_bundled())
        self.assertEqual('keep', (self.dst / 'user-settings').read_text())

    def test_invalid_state_and_bundle_fail_closed(self):
        state = Path(B.STATE); state.parent.mkdir(); state.write_text('[]')
        with self.assertRaises(ValueError): B.install_bundled()
        state.unlink(); (self.src / 'package.json').write_text('null')
        with self.assertRaises(ValueError): B.install_bundled()
        self.assertFalse(self.dst.exists())
        self.version('1'); (self.src / 'main.py').unlink()
        with self.assertRaises(ValueError): B.install_bundled()

    def test_copy_chown_and_publication_errors_keep_old_tree(self):
        B.install_bundled(); old_hash = B.tree_digest(self.dst); self.version('2')
        before = Path(B.STATE).read_bytes()
        for target in ('copy', 'chown', 'publish', 'state'):
            with self.subTest(target=target):
                replace = os.replace
                def fail_publish(src, dst):
                    if Path(src).name == 'payload': raise OSError('publish failed')
                    return replace(src, dst)
                context = {'copy': patch.object(B.shutil, 'copytree', side_effect=OSError('copy failed')),
                           'chown': patch.object(subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'mock chown')),
                           'publish': patch.object(B.os, 'replace', side_effect=fail_publish),
                           'state': patch.object(B, 'save_state', side_effect=OSError('state failed'))}[target]
                with context, self.assertRaises((OSError, subprocess.SubprocessError)): B.install_bundled()
                self.assertEqual(old_hash, B.tree_digest(self.dst))
                self.assertEqual(before, Path(B.STATE).read_bytes())
                self.assertEqual([self.dst], list(self.dst.parent.iterdir()))

    def test_stale_new_and_state_tmp_are_not_deleted(self):
        stale = self.dst.with_name('classic.new'); stale.mkdir(); (stale/'keep').write_text('sentinel')
        state_tmp = Path(B.STATE + '.tmp'); state_tmp.parent.mkdir(); state_tmp.write_text('sentinel')
        B.install_bundled()
        self.assertEqual('sentinel', (stale/'keep').read_text())
        self.assertEqual('sentinel', state_tmp.read_text())

    def test_symlink_copy_is_preserved(self):
        target = self.root / 'custom'; target.mkdir(); (target/'package.json').write_text('{"version":"1"}')
        self.dst.symlink_to(target, target_is_directory=True)
        self.assertEqual([], B.install_bundled())
        self.assertTrue(self.dst.is_symlink())
        self.assertEqual('{"version":"1"}', (target/'package.json').read_text())


ORIGINAL_POPEN = subprocess.Popen
if __name__ == '__main__':
    logging.disable(logging.CRITICAL)
    unittest.main()
