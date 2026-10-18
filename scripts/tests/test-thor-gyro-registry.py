#!/usr/bin/env python3
"""Exercise registry startup in temp dirs, without DSP, mounts, builds or devices.

Only the registry prefix of the real startup script runs. Linux mv -T is
represented by os.rename on macOS; generator output/failures are fixtures.
QCOM_SENSORS_SCRIPT can select an extracted upstream version for regression.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
ST = ROOT / 'external-and-mods/kernel/vendor/qcom-gyro/steamos'
SCRIPT = Path(os.environ.get('QCOM_SENSORS_SCRIPT', ST / 'qcom-sensors-start.sh'))


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.state = self.base / 'state'
        self.reg = self.state / 'registry'
        self.reg.mkdir(parents=True)
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        self.compat = self.base / 'compatible'
        self.compat.write_bytes(b'ayn,thor\0qcom,qcs8550\0qcom,sm8550\0')
        self.soc = self.base / 'soc_id'
        self.soc.write_text('603\n')
        self.env = dict(os.environ, QCOM_GYRO_DIR=str(self.base),
                        QCOM_GYRO_STATE=str(self.state), TEST_MODE='ok',
                        PATH=str(self.bin) + os.pathsep + os.environ['PATH'])
        self.write_tool('sscregistrygen', '''
import os, sys
from pathlib import Path
assert sys.argv[1:5] == ['-p', 'HDK', '-s', '603']
p = Path(sys.argv[-1]); state = Path(os.environ['QCOM_GYRO_STATE'])
(state / 'generator-called').touch()
(p / 'sh5001_0_platform.config').write_text('generated config')
mode = os.environ['TEST_MODE']
if mode == 'fail': sys.exit(23)
if mode != 'no-orient': (p / 'sh5001_0_platform.orient').write_text('generated orient')
(p / 'learned').write_text('default calibration')
if mode == 'race': (state / 'registry' / 'learned').write_text('concurrent calibration')
''')
        self.write_tool('mv', '''
import os, sys
assert sys.argv[1:3] == ['-T', '--']
if os.environ['TEST_MODE'] == 'rename-fail': sys.exit(24)
os.rename(sys.argv[3], sys.argv[4])
''')
        # Fail closed if a test accidentally reaches the Odin mount branch.
        self.write_tool('mount', 'raise SystemExit(99)\n')
        prefix = SCRIPT.read_text().split('\nln -snf ', 1)[0]
        prefix = prefix.replace('/proc/device-tree/compatible', str(self.compat))
        prefix = prefix.replace('/sys/devices/soc0/soc_id', str(self.soc))
        self.script = self.base / 'registry.sh'
        self.script.write_text(prefix + '\n')

    def write_tool(self, name, body):
        p = self.bin / name
        p.write_text('#!' + sys.executable + '\n' + body)
        p.chmod(0o755)

    def run_registry(self, mode='ok'):
        return subprocess.run(['bash', str(self.script)],
                              env=dict(self.env, TEST_MODE=mode),
                              capture_output=True, text=True, timeout=10)

    def snapshot(self):
        return {p.name: p.read_bytes() for p in self.reg.iterdir()}

    def no_staging(self):
        self.assertEqual(list(self.state.glob('registry.new.*')), [])

    def test_publish_and_preserve_learned_calibration_on_restart(self):
        r = self.run_registry()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.reg / 'sh5001_0_platform.orient').is_file())
        (self.reg / 'learned').write_text('unit calibration')
        before = self.snapshot()
        r = self.run_registry('fail')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.snapshot(), before)
        self.no_staging()

    def test_generator_failure_leaves_no_registry_or_staging_data(self):
        self.assertNotEqual(self.run_registry('fail').returncode, 0)
        self.assertEqual(self.snapshot(), {})
        self.no_staging()
        self.assertEqual(self.run_registry().returncode, 0)

    def test_missing_orientation_rejects_generated_tree(self):
        self.assertNotEqual(self.run_registry('no-orient').returncode, 0)
        self.assertEqual(self.snapshot(), {})
        self.no_staging()

    def test_existing_config_without_orientation_is_not_accepted(self):
        (self.reg / 'sh5001_0_platform.config').write_text('partial')
        before = self.snapshot()
        self.assertNotEqual(self.run_registry().returncode, 0)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.state / 'generator-called').exists())

    def test_existing_calibration_without_config_is_not_overwritten(self):
        (self.reg / 'learned').write_text('irreplaceable calibration')
        before = self.snapshot()
        self.assertNotEqual(self.run_registry().returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_failed_publish_is_retryable_without_partial_registry(self):
        self.assertNotEqual(self.run_registry('rename-fail').returncode, 0)
        self.assertFalse(self.reg.exists())
        self.no_staging()
        self.assertEqual(self.run_registry().returncode, 0)

    def test_new_data_during_generation_is_preserved(self):
        self.assertNotEqual(self.run_registry('race').returncode, 0)
        self.assertEqual(self.snapshot(), {'learned': b'concurrent calibration'})
        self.no_staging()

    def test_service_board_gate_matches_complete_compatible_tokens(self):
        text = (ST / 'supported').read_text().replace('/proc/device-tree/compatible', str(self.compat))
        for board, expected in [('ayn,thor', 0), ('ayn,odin2', 0),
                                ('ayn,odin2mini', 0), ('ayn,odin2portal', 0),
                                ('ayaneo,pocketevo', 1), ('ayn,thorlite', 1),
                                ('ayn,thor-extra', 1), ('xayn,thor', 1)]:
            with self.subTest(board=board):
                self.compat.write_bytes(board.encode() + b'\0qcom,sm8550\0')
                r = subprocess.run(['sh', '-c', text], capture_output=True)
                self.assertEqual(r.returncode, expected)


if __name__ == '__main__':
    unittest.main()
