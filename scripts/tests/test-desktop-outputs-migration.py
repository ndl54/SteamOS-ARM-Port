#!/usr/bin/env python3
"""Old Desktop layout migration with temp files and mocked hardware discovery.

Run with python3; no display command, libdrm, service, build or device access.
"""
import copy
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[2]


def load(name, relative):
    loader = importlib.machinery.SourceFileLoader(name, str(REPO / relative))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class Migration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='desktop-seed-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.mod = load('desktop_outputs', 'steamos-overlay/usr/lib/steamos/desktop-outputs')
        self.fit = load('desktop_fit', 'steamos-overlay/usr/lib/steamos-arm/desktop-fit')
        self.panel = dict(name='DSI-1', width=1080, height=1920,
                          orientation='left-up', rates=[60, 90, 120, 144, 165])
        self.mod.CONFIG = self.root / 'config'
        self.mod.CONFIG.mkdir()
        self.mod.KWIN_OUTPUTS = self.mod.CONFIG / 'kwinoutputconfig.json'
        self.mod.KCMINPUT = self.mod.CONFIG / 'kcminputrc'
        self.mod.KCMINPUT.write_text('[Libinput][0][0][NVTCapacitivePen]\nCalibrationMatrix=sentinel\n')
        self.touch_before = self.mod.KCMINPUT.read_bytes()
        self.mod.STAMP = self.mod.CONFIG / 'steamos-arm/desktop-outputs.sha256'
        self.mod.FIT_STATE = self.root / 'state/steamos-arm/desktop-fit-1'
        self.mod.LEGACY = self.root / 'legacy.json'
        self.mod.LEGACY.write_bytes((REPO / 'steamos-overlay/etc/xdg/kwinoutputconfig.json').read_bytes())
        self.mod.log = mock.Mock()
        self.mod.panels = mock.Mock(side_effect=lambda: [self.panel])
        self.mod.model = mock.Mock(return_value='AYANEO Pocket EVO')
        self.mod.touchscreens = mock.Mock(return_value=[])
        self.fit.STATE = str(self.mod.FIT_STATE)
        self.fit.CONF = str(self.mod.KWIN_OUTPUTS)
        self.fit.SHIPPED = str(self.mod.LEGACY)
        self.fit.panels = mock.Mock(side_effect=lambda: [
            (self.panel['name'], self.panel['width'], self.panel['height'])])
        self.fit.kwrite = mock.Mock()
        self.seed()
        self.marker_before = self.mod.FIT_STATE.read_bytes()

    def seed(self):
        self.mod.KWIN_OUTPUTS.unlink(missing_ok=True)
        self.mod.FIT_STATE.unlink(missing_ok=True)
        self.assertEqual(self.fit.main(), 0)

    def read(self):
        return json.loads(self.mod.KWIN_OUTPUTS.read_text())

    def write(self, data):
        self.mod.KWIN_OUTPUTS.write_text(json.dumps(data, indent=2))

    def unchanged(self):
        before = self.mod.KWIN_OUTPUTS.read_bytes()
        self.assertEqual(self.mod.main(), 0)
        self.assertEqual(self.mod.KWIN_OUTPUTS.read_bytes(), before)
        self.assertEqual(self.mod.KCMINPUT.read_bytes(), self.touch_before)

    def test_real_fit_seed_repaired_once_preserving_fit_policy(self):
        self.assertTrue(self.mod.seeded_upside_down([self.panel]))
        self.assertEqual(self.mod.main(), 0)
        output = self.read()[0]['data'][0]
        self.assertEqual((output['transform'], output['scale'], output['autoRotation']),
                         ('Rotated90', 1.5, 'Never'))
        self.assertEqual(output['mode'], dict(width=1080, height=1920, refreshRate=60000))
        self.assertFalse(self.mod.STAMP.exists())
        self.assertEqual(self.mod.FIT_STATE.read_bytes(), self.marker_before)
        self.assertEqual(self.mod.KCMINPUT.read_bytes(), self.touch_before)
        self.mod.touchscreens.assert_not_called()
        before = self.mod.KWIN_OUTPUTS.read_bytes()
        for _ in range(2):
            self.assertEqual(self.mod.main(), 0)
            self.assertEqual(self.fit.main(), 0)
            self.assertEqual(self.mod.KWIN_OUTPUTS.read_bytes(), before)

    def test_known_models_and_panel_sizes(self):
        for model, size in [('AYANEO Pocket EVO', (1080, 1920)),
                            ('Retroid Pocket 6', (1080, 1920)),
                            ('AYN Odin 2 Portal', (1080, 1920)),
                            ('AYANEO Pocket DMG', (1240, 1080)),
                            ('AYANEO Pocket DS', (1080, 1920))]:
            with self.subTest(model=model):
                self.mod.model.return_value = model
                self.panel.update(width=size[0], height=size[1])
                self.seed()
                self.assertEqual(self.mod.main(), 0)
                output = self.read()[0]['data'][0]
                self.assertEqual(output['transform'], 'Rotated90')
                self.assertEqual(output['scale'], self.fit.scale_for(*size))
                self.assertEqual((output['mode']['width'], output['mode']['height']), size)
                self.unchanged()

    def test_all_user_output_fields_preserved_even_rotated270(self):
        seed = self.read()
        changes = {'scale': 1.75, 'brightness': 0.4, 'highDynamicRange': True,
                   'autoRotation': 'Always', 'transform': 'Rotated180',
                   'connectorName': 'eDP-1', 'edidIdentifier': 'monitor',
                   'mode': {'width': 1080, 'height': 1920, 'refreshRate': 120000},
                   'iccProfilePath': '/custom.icc', 'unknownSetting': 123}
        for key, value in changes.items():
            with self.subTest(key=key):
                data = copy.deepcopy(seed)
                data[0]['data'][0][key] = value
                self.write(data)
                self.unchanged()

    def test_user_setups_and_saved_external_output_preserved(self):
        seed = self.read()
        variants = []
        positioned = copy.deepcopy(seed)
        positioned[1]['data'][0]['outputs'][0]['position']['x'] = 100
        variants.append(positioned)
        disabled = copy.deepcopy(seed)
        disabled[1]['data'][0]['outputs'][0]['enabled'] = False
        variants.append(disabled)
        docked = copy.deepcopy(seed)
        external = copy.deepcopy(docked[0]['data'][0])
        external['connectorName'] = 'DP-1'
        docked[0]['data'].append(external)
        variants.append(docked)
        extra_setup = copy.deepcopy(seed)
        extra_setup[1]['data'].append(copy.deepcopy(seed[1]['data'][0]))
        variants.append(extra_setup)
        for data in variants:
            self.write(data)
            self.unchanged()

    def test_stamp_and_missing_wrong_marker_preserve(self):
        self.mod.STAMP.parent.mkdir(parents=True)
        for stamp in ['', 'old-hash\n']:
            self.mod.STAMP.write_text(stamp)
            self.unchanged()
        self.mod.STAMP.unlink()
        for marker in ['', 'DSI-2 1080x1920 scale 1.5\n', 'DSI-1 1920x1080 scale 1.5\n',
                       'DSI-1 1080x1920 scale 1.25\n']:
            self.mod.FIT_STATE.write_text(marker)
            self.unchanged()
        self.mod.FIT_STATE.unlink()
        self.unchanged()

    def test_other_boards_orientations_and_connectors_preserve(self):
        for model in ['REDMAGIC 6', 'AYN Thor', 'AYANEO Pocket EVO Other',
                      'Lenovo Legion Y700 Gen 3', 'Lenovo Legion Y700 Gen 4', '']:
            self.mod.model.return_value = model
            self.unchanged()
        self.mod.model.return_value = 'AYANEO Pocket EVO'
        for orientation in ['none', 'normal', 'upside-down', 'right-up']:
            self.panel['orientation'] = orientation
            self.unchanged()
        self.panel['orientation'] = 'left-up'
        self.panel['name'] = 'eDP-1'
        self.unchanged()

    def test_multiple_or_no_panels_preserve_unowned_seed(self):
        for panels in [[], [self.panel, dict(self.panel, name='DSI-2')]]:
            self.mod.panels.side_effect = None
            self.mod.panels.return_value = panels
            self.unchanged()

    def test_malformed_json_and_shapes_preserve(self):
        for value in ['{', 'null', '{}', '[null]', '[{"name":"outputs","data":[null]}]',
                      '[{"name":"outputs","data":[]}]', '42']:
            self.mod.KWIN_OUTPUTS.write_text(value)
            self.unchanged()
        self.seed()
        self.mod.LEGACY.write_text('{}')
        self.unchanged()
        self.mod.LEGACY.unlink()
        self.unchanged()

    def test_customization_after_repair_preserved(self):
        self.mod.main()
        data = self.read()
        data[0]['data'][0]['brightness'] = 0.6
        data[0]['data'][0]['transform'] = 'Rotated270'
        self.write(data)
        self.unchanged()

    def test_replace_failure_preserves_original_and_retry_succeeds(self):
        before = self.mod.KWIN_OUTPUTS.read_bytes()
        with mock.patch.object(self.mod.os, 'replace', side_effect=OSError('synthetic replace failure')):
            with self.assertRaises(OSError):
                self.mod.main()
        self.assertEqual(self.mod.KWIN_OUTPUTS.read_bytes(), before)
        self.assertEqual(list(self.mod.CONFIG.glob('.kwinoutputconfig.json.*')), [])
        self.assertFalse(self.mod.STAMP.exists())
        self.assertEqual(self.mod.FIT_STATE.read_bytes(), self.marker_before)
        self.assertEqual(self.mod.main(), 0)
        self.assertEqual(self.read()[0]['data'][0]['transform'], 'Rotated90')

    def test_partial_write_failure_preserves_original_and_cleans_temp(self):
        before = self.mod.KWIN_OUTPUTS.read_bytes()
        real_temp = self.mod.tempfile.NamedTemporaryFile
        def broken_temp(**kwargs):
            fh = real_temp(**kwargs)
            class Partial:
                def __enter__(self):
                    return self
                @property
                def name(self):
                    return fh.name
                def write(self, data):
                    fh.write(data[:12])
                    raise OSError('synthetic disk full')
                def __exit__(self, *args):
                    fh.close()
            return Partial()
        with mock.patch.object(self.mod.tempfile, 'NamedTemporaryFile', side_effect=broken_temp):
            with self.assertRaises(OSError):
                self.mod.main()
        self.assertEqual(self.mod.KWIN_OUTPUTS.read_bytes(), before)
        self.assertEqual(list(self.mod.CONFIG.glob('.kwinoutputconfig.json.*')), [])
        self.assertFalse(self.mod.STAMP.exists())

    def test_missing_and_exact_legacy_still_generate_and_stamp(self):
        for original in [None, self.mod.LEGACY.read_bytes()]:
            self.mod.STAMP.unlink(missing_ok=True)
            if original is None:
                self.mod.KWIN_OUTPUTS.unlink(missing_ok=True)
            else:
                self.mod.KWIN_OUTPUTS.write_bytes(original)
            self.assertEqual(self.mod.main(), 0)
            self.assertEqual(self.mod.STAMP.read_text().strip(), self.mod.digest(self.mod.KWIN_OUTPUTS))
            self.assertEqual(self.read()[0]['data'][0]['transform'], 'Rotated90')
            before = self.mod.KWIN_OUTPUTS.read_bytes()
            self.assertEqual(self.mod.main(), 0)
            self.assertEqual(self.mod.KWIN_OUTPUTS.read_bytes(), before)

    def test_stamp_replace_failure_leaves_complete_config_and_old_stamp(self):
        self.mod.KWIN_OUTPUTS.unlink()
        self.mod.STAMP.parent.mkdir(parents=True)
        self.mod.STAMP.write_text('previous-stamp\n')
        real_replace = self.mod.os.replace
        def fail_stamp(src, dst):
            if dst == self.mod.STAMP:
                raise OSError('synthetic stamp failure')
            real_replace(src, dst)
        with mock.patch.object(self.mod.os, 'replace', side_effect=fail_stamp):
            with self.assertRaises(OSError):
                self.mod.main()
        self.assertEqual(self.read()[0]['data'][0]['transform'], 'Rotated90')
        self.assertEqual(self.mod.STAMP.read_text(), 'previous-stamp\n')
        self.assertEqual(list(self.mod.STAMP.parent.glob('.desktop-outputs.sha256.*')), [])
        self.unchanged()  # Failure loses management, never guesses ownership.

    def test_managed_dual_panel_generation_keeps_existing_touch_routing(self):
        self.mod.KWIN_OUTPUTS.unlink()
        self.mod.panels.side_effect = None
        self.mod.panels.return_value = [self.panel, dict(self.panel, name='DSI-2', width=720, height=1280)]
        self.mod.model.return_value = 'AYN Thor'
        self.mod.touchscreens.return_value = [('main_touchscreen', 1, 1), ('bottom_touchscreen', 1, 2)]
        self.assertEqual(self.mod.main(), 0)
        data = self.read()
        self.assertEqual(len(data[0]['data']), 2)
        self.assertEqual(data[1]['data'][0]['outputs'][1]['position'], {'x': 128, 'y': 864})
        touch = self.mod.KCMINPUT.read_text()
        self.assertIn('[Libinput][1][1][main_touchscreen]\nOutputName=DSI-1', touch)
        self.assertIn('[Libinput][1][2][bottom_touchscreen]\nOutputName=DSI-2', touch)
        self.assertIn(self.touch_before.decode().strip(), touch)


if __name__ == '__main__':
    unittest.main()
