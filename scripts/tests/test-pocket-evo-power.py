#!/usr/bin/env python3
"""Exercise boot policy and wake selection against a temporary sysfs tree."""
import importlib.machinery
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
HELPERS = ROOT / 'sm8550-overlay/usr/lib/pocketevo'
loader = importlib.machinery.SourceFileLoader('power', str(HELPERS / 'pocket-evo-power'))
spec = importlib.util.spec_from_loader(loader.name, loader)
power = importlib.util.module_from_spec(spec)
loader.exec_module(power)


class PowerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.compat = self.put('firmware/devicetree/base/compatible', 'ayaneo,pocketevo\0qcom,sm8550\0')
        self.timeout = self.put('module/ufshcd_core/parameters/uic_cmd_timeout', '500\n')
        self.put('class/hwmon/hwmon0/name', 'pwmfan\n')
        self.fan = self.put('class/hwmon/hwmon0/pwm1_sleep_charging', '90\n')
        self.put('class/hwmon/hwmon1/name', 'unrelated\n')
        self.other = self.put('class/hwmon/hwmon1/pwm1_sleep_charging', '77\n')

    def put(self, path, value):
        path = self.root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
        return path

    def test_default_disables_opt_in_only_for_pwmfan(self):
        power.apply(self.root)
        self.assertEqual(self.timeout.read_text(), '3000\n')
        self.assertEqual(self.fan.read_text(), '0\n')
        self.assertEqual(self.other.read_text(), '77\n')

    def test_explicit_fan_speed_and_absent_optional_attributes(self):
        power.apply(self.root, '80')
        self.assertEqual(self.fan.read_text(), '80\n')
        self.timeout.unlink()
        self.fan.unlink()
        power.apply(self.root, '255')
        self.assertFalse(self.fan.exists())

    def test_invalid_config_never_partially_applies(self):
        for value in ['-1', '256', '1.5', '$(touch bad)']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                power.apply(self.root, value)
            self.assertEqual(self.timeout.read_text(), '500\n')
            self.assertEqual(self.fan.read_text(), '90\n')

    def test_other_board_is_untouched(self):
        self.compat.write_text('ayaneo,pocketds\0qcom,sm8550\0')
        power.apply(self.root, '80')
        self.assertEqual(self.timeout.read_text(), '500\n')
        self.assertEqual(self.fan.read_text(), '90\n')

    def test_wake_policy_keeps_power_button_without_enabling_volume(self):
        powerkey = self.put('devices/platform/soc@0/1.spmi/spmi-0/0/pon/pwrkey/power/wakeup', 'disabled\n')
        volume = self.put('devices/platform/gpio-keys/power/wakeup', 'disabled\n')
        wifi = self.put('bus/pci/devices/0000:01:00.0/power/wakeup', 'enabled\n')
        source = (HELPERS / 'pocket-evo-sleep').read_text()
        function = source.split('wake_sources() {', 1)[1].split('\n}\n', 1)[0]
        function = 'wake_sources() {' + function.replace('/sys/', str(self.root) + '/') + '\n}\nwake_sources\n'
        subprocess.run(['bash', '-c', function], check=True)
        self.assertEqual(powerkey.read_text(), 'enabled\n')
        self.assertEqual(volume.read_text(), 'disabled\n')
        self.assertEqual(wifi.read_text(), 'disabled\n')


if __name__ == '__main__':
    unittest.main()
