#!/usr/bin/env python3
"""Read-only, fail-closed checks for destructive UFS reinstall (not an updater)."""
import json
import os
from pathlib import Path
import re
import runpy
import stat
import sys

SYS = Path('/sys/class/block')
PART = runpy.run_path(str(Path(__file__).with_name('ufs-partition.py')))
BOARDS = {
    'qcom,sm8550': {'ayn,odin2', 'ayn,odin2mini', 'ayn,odin2portal', 'ayaneo,pocketevo'},
    'qcom,sm8650': {'konkr,pocket-fit', 'ayaneo,pocket-s2'},
    'qcom,sm8750': {'ayn,odin3', 'konkr,pocket-fit-elite'},
}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def device(name):
    require(re.fullmatch(r'[a-zA-Z0-9_-]+', name), 'invalid device name')
    p = SYS / name
    s = os.stat('/dev/' + name)
    require(stat.S_ISBLK(s.st_mode), 'not a block device')
    require(p.joinpath('dev').read_text().strip() == dev_id(s.st_rdev), 'device identity mismatch')
    require(p.joinpath('ro').read_text().strip() == '0', 'read-only device')
    return p


def dev_id(number):
    return f'{os.major(number)}:{os.minor(number)}'


def parent(p):
    require(p.joinpath('partition').exists(), 'expected a partition')
    return device(p.resolve(strict=True).parent.name)


def board():
    compat = set(Path('/sys/firmware/devicetree/base/compatible').read_bytes().decode().split('\0'))
    matches = [(soc, b) for soc, boards in BOARDS.items() for b in boards if b in compat]
    require(not any(x.startswith('lenovo,') for x in compat) and len(matches) == 1
            and matches[0][0] in compat, 'retry requires an explicitly supported handheld; tablets are excluded')


def source_disk():
    disks = []
    for mount in ('/', '/boot'):
        data = json.loads(PART['sh']('findmnt', '--json', '--mountpoint', mount,
                                     '--output', 'MAJ:MIN,FSTYPE,FSROOT'))['filesystems']
        require(len(data) == 1 and data[0]['fsroot'] == '/', 'ambiguous or indirect source mount')
        require(data[0]['fstype'] == ('ext4' if mount == '/' else 'vfat'), 'unexpected source filesystem')
        identity = data[0]['maj:min']
        require(re.fullmatch(r'\d+:\d+', identity), 'invalid source identity')
        p = device(Path('/sys/dev/block', identity).resolve(strict=True).name)
        require(p.joinpath('dev').read_text().strip() == identity, 'source identity changed')
        disk = parent(p)
        require(disk.joinpath('device/type').read_text().strip() == 'SD', 'source is not physical SD')
        disks.append(disk.resolve(strict=True))
    require(disks[0] == disks[1], '/boot must be on the running SD card')
    return disks[0]


def idle(disk):
    nodes = [disk] + [p for p in SYS.iterdir() if p.joinpath('partition').exists()
                     and p.resolve(strict=True).parent == disk.resolve(strict=True)]
    ids = {p.joinpath('dev').read_text().strip() for p in nodes}
    for p in nodes:
        require(not list(p.joinpath('holders').iterdir()), 'target has block holders')
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        require(line.split()[2] not in ids, 'target is mounted')
    for line in Path('/proc/swaps').read_text().splitlines()[1:]:
        s = os.stat(line.split()[0])
        require(dev_id(s.st_rdev if stat.S_ISBLK(s.st_mode) else s.st_dev) not in ids,
                'target contains active swap')
    for p in SYS.glob('loop*/loop/backing_file'):
        name = p.read_text().strip()
        require(name.startswith('/'), 'unresolved loop backing file')
        s = os.stat(name)
        require(dev_id(s.st_rdev if stat.S_ISBLK(s.st_mode) else s.st_dev) not in ids,
                'target backs a loop mapping')


def layout(t, disk):
    require(t.get('device') == disk and t.get('label') == 'gpt' and t.get('unit') == 'sectors'
            and t.get('sectorsize') in (512, 4096), 'invalid GPT identity/units')
    require(t.get('id'), 'missing GPT identity')
    parts = t['partitions']
    nodes, uuids = set(), set()
    end = int(t['firstlba'])
    for p in parts:
        require(isinstance(p['start'], int) and isinstance(p['size'], int) and p['size'] > 0
                and p['start'] >= end, 'invalid or overlapping GPT entries')
        end = p['start'] + p['size']
        require(end <= int(t['lastlba']) + 1, 'partition exceeds disk')
        require(re.fullmatch(re.escape(disk) + r'[1-9][0-9]*', p['node']), 'foreign partition node')
        uuid = p.get('uuid', '').lower()
        require(uuid and uuid not in uuids and p['node'] not in nodes, 'duplicate partition identity')
        uuids.add(uuid)
        nodes.add(p['node'])
    require(PART['classify'](t)[0] == 'installed', 'requires complete three-partition layout')
    require([p['name'] for p in parts[-4:]] == ['userdata', 'ROCKNIX', 'STORAGE', 'HOME'],
            'unexpected trailing layout')
    require(all(sum(p['name'] == name for p in parts) == 1 for name in PART['OURS']),
            'duplicate install labels')
    ud, boot, root, home = parts[-4:]
    require(ud['start'] + ud['size'] <= boot['start']
            and boot['start'] + boot['size'] == root['start']
            and root['start'] + root['size'] == home['start'], 'unexpected install geometry')
    require([p['type'].upper() for p in (boot, root, home)] ==
            [PART['TYPE_ESP'], PART['TYPE_LINUX'], PART['TYPE_LINUX']], 'unexpected install types')
    require(boot['size'] * t['sectorsize'] == 2 * PART['GIB']
            and root['size'] * t['sectorsize'] >= 20 * PART['GIB']
            and home['size'] * t['sectorsize'] >= 16 * PART['GIB'], 'unsupported install sizes')
    # Old installations may retain <16 GiB userdata; retry must never resize it.
    return parts


def check(disk, expect):
    board()
    require(re.fullmatch(r'/dev/sd[a-z]+', disk), 'requires canonical whole UFS disk')
    d = device(Path(disk).name)
    require(not d.joinpath('partition').exists(), 'target is a partition')
    require(d.resolve(strict=True) != source_disk(), 'target is running source')
    require(any((p / 'driver').resolve().name == 'ufshcd-qcom' for p in d.resolve(strict=True).parents),
            'target is not physical Qualcomm UFS')
    t = PART['read_table'](disk)
    require(re.fullmatch(r'[0-9a-f]{16}', expect) and PART['fingerprint'](t) == expect,
            'table changed since probe')
    for entry in layout(t, disk):
        p = device(Path(entry['node']).name)
        require(parent(p).resolve(strict=True) == d.resolve(strict=True), 'partition parent mismatch')
        require(p.joinpath('partition').read_text().strip() == entry['node'][len(disk):], 'partition number mismatch')
        require(int(p.joinpath('start').read_text()) * 512 == entry['start'] * t['sectorsize']
                and int(p.joinpath('size').read_text()) * 512 == entry['size'] * t['sectorsize'],
                'kernel partition geometry is stale; reboot to SD before retry')
    PART['sh']('sfdisk', '--verify', disk)
    idle(d)
    return t


if __name__ == '__main__':
    try:
        require(len(sys.argv) == 3, 'usage: ufs-resume-check.py DISK FINGERPRINT')
        check(*sys.argv[1:])
    except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
        sys.exit(f'Reinstall refused: {exc}')
