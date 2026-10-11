#!/usr/bin/env python3
"""Validate prepared EVO mode arithmetic, then optional compiled DTB/config/output.

Usage: verify-pocket-evo-kernel.py KERNEL_SOURCE [PACKAGED_OUTPUT]
Reads files only. Does not build, load modules, or contact a device.
"""
import ast
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]


def number(expression):
    tree = ast.parse(expression.strip(), mode='eval')
    def visit(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return node.value
        if isinstance(node, ast.BinOp):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left // right  # C integer timing initializers
        raise ValueError(expression)
    return visit(tree.body)


def fdt(data):
    magic, size, offset, strings = struct.unpack_from('>4I', data)
    assert magic == 0xd00dfeed and size == len(data)
    nodes, stack = {}, []
    while True:
        token, = struct.unpack_from('>I', data, offset)
        offset += 4
        if token == 1:
            end = data.index(b'\0', offset)
            stack.append(data[offset:end].decode())
            offset = (end + 4) & ~3
            nodes['/'.join(stack) or '/'] = {}
        elif token == 2:
            stack.pop()
        elif token == 3:
            length, name = struct.unpack_from('>2I', data, offset)
            offset += 8
            start = strings + name
            name = data[start:data.index(b'\0', start)].decode()
            nodes['/'.join(stack) or '/'][name] = data[offset:offset + length]
            offset = (offset + length + 3) & ~3
        elif token == 9:
            return nodes
        else:
            assert token == 4


def cells(data):
    return struct.unpack('>' + 'I' * (len(data) // 4), data)


def main():
    source = Path(sys.argv[1])
    panel = (source / 'drivers/gpu/drm/panel/panel-chipone-icna35xx.c').read_text()
    array = panel.split('pocketevo_modes[] = {', 1)[1].split('\n};', 1)[0]
    fields = ('clock', 'hdisplay', 'hsync_start', 'hsync_end', 'htotal',
              'vdisplay', 'vsync_start', 'vsync_end', 'vtotal')
    modes = []
    for body in re.findall(r'\{([^{}]+)\}', array):
        modes.append({k: number(re.search(r'\.' + k + r'\s*=\s*([^,]+)', body)[1]) for k in fields})
    expected = json.loads((ROOT / 'docs/audit/pocket-evo-panel-timings.json').read_text())['modes']
    assert len(modes) == len(expected) == 5
    assert round(modes[0]['clock'] * 1000 / modes[0]['htotal'] / modes[0]['vtotal']) == 120
    for ref in expected:
        matches = [m for m in modes if abs(m['clock'] * 1000 / m['htotal'] / m['vtotal'] - ref['hz']) < .001]
        assert len(matches) == 1, ref
        m = matches[0]
        assert m['clock'] == ref['clock_khz']
        for prefix, active in [('h', 1080), ('v', 1920)]:
            assert m[prefix + 'display'] == active
            assert m[prefix + 'sync_start'] - active == ref[prefix + 'fp']
            assert m[prefix + 'sync_end'] - m[prefix + 'sync_start'] == ref[prefix + 'sync']
            assert m[prefix + 'total'] - m[prefix + 'sync_end'] == ref[prefix + 'bp']
        pclk = m['clock'] * 1000 * (m['htotal'] - 1080 + 360) // m['htotal']
        bitrate = (pclk * 24 // 32) * 8
        assert bitrate == ref['lane_bit_rate']
        assert 600_000_000 <= bitrate <= 5_000_000_000
        assert ref['active_dsc_bits_per_second'] < 4 * bitrate
        print(f"{ref['hz']} Hz: {m['clock']*1000/m['htotal']/m['vtotal']:.6f}, lane {bitrate} bit/s")
    for path, digest in json.loads((ROOT / 'docs/audit/pocket-evo-preserved-files.json').read_text()).items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path
    print('10 LED/RGB baseline files unchanged')
    if len(sys.argv) < 3:
        return
    output = Path(sys.argv[2]).resolve()
    dtbs = list((output / 'dtbs').glob('*.dtb'))
    assert len(dtbs) == 1 and dtbs[0].name == 'qcs8550-ayaneo-pocketevo.dtb'
    nodes = fdt(dtbs[0].read_bytes())
    assert b'ayaneo,pocketevo\0' in nodes['/']['compatible']
    keys = [props for path, props in nodes.items() if path.startswith('/aya-keys/') and 'linux,code' in props]
    assert sorted(cells(p['linux,code'])[0] for p in keys) == [183, 184, 185, 186]
    assert sorted(cells(p['gpios'])[1] for p in keys) == [85, 91, 169, 170]
    assert all(cells(p['gpios'])[-1] == 1 and cells(p['debounce-interval']) == (15,) and 'wakeup-source' not in p for p in keys)
    pin_phandles = cells(nodes['/aya-keys']['pinctrl-0'])
    pin_states = [p for p in nodes.values() if 'phandle' in p and cells(p['phandle'])[0] in pin_phandles]
    assert len(pin_states) == 1 and 'bias-pull-up' in pin_states[0]
    assert set(pin_states[0]['pins'].rstrip(b'\0').split(b'\0')) == {b'gpio85', b'gpio91', b'gpio169', b'gpio170'}
    volume = [p for p in nodes.values() if p.get('linux,code') == struct.pack('>I', 115)]
    assert volume and all('wakeup-source' not in p for p in volume)
    power = [p for p in nodes.values() if p.get('linux,code') == struct.pack('>I', 116)]
    # PMK8350 power-key match data enables wake by default, without a DT flag.
    assert any(b'qcom,pmk8350-pwrkey\0' in p.get('compatible', b'') or 'wakeup-source' in p for p in power)
    panels = [p for p in nodes.values() if b'ayaneo,pocketevo-panel\0' in p.get('compatible', b'')]
    assert len(panels) == 1 and cells(panels[0]['rotation']) == (270,)
    pcie = [p for p in nodes.values() if 'wake-gpios' in p and cells(p['wake-gpios'])[1] in (96,99)]
    assert len(pcie) == 2 and all(cells(p['wake-gpios'])[-1] == 1 for p in pcie)
    assert not any('sdhci-caps-mask' in p for p in nodes.values())
    assert nodes['/sound']['model'] == b'SM8550-APS\0'
    config = next(output.glob('config-*')).read_text()
    for key in ['DRM_MSM', 'DRM_PANEL_CHIPONE_ICNA35XX', 'SENSORS_PWM_FAN', 'BATTERY_QCOM_BATTMGR', 'QCOM_IPCC', 'ATH12K', 'SND_SOC_SC8280XP', 'JOYSTICK_XPAD', 'INPUT_PM8941_PWRKEY']:
        assert re.search(r'^CONFIG_' + key + r'=[ym]$', config, re.M), key
    assert (output / 'boot/KERNEL').stat().st_size > 1_000_000
    assert list((output / 'modules').rglob('*.ko*'))
    for path in ['qcom/sm8550/SM8550-APS-tplg.bin', 'qcom/sm8550/ayaneo/adsp.mdt', 'renesas_usb_fw.mem']:
        assert (output / 'firmware' / path).stat().st_size > 0, path
    print('Packaged EVO DTB, GPIO/wake/rotation, config, modules and firmware verified')


if __name__ == '__main__':
    main()
