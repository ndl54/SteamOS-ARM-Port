#!/usr/bin/env python3
"""Set the image's battery policy; no daemon or build commands are run."""
import configparser
import math
from pathlib import Path
import re
import sys

POLICY = {'UsePercentageForPolicy': 'true', 'PercentageLow': '10',
          'PercentageCritical': '6', 'PercentageAction': '4',
          'CriticalPowerAction': 'PowerOff'}


def configure(path):
    text = path.read_text() if path.exists() else ''
    # Reject malformed/duplicate active configuration rather than silently
    # accepting a different effective value. Preserve unrelated text/comments.
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read_string(text)
    policy = dict(POLICY)
    try:
        low = parser.getfloat('UPower', 'PercentageLow')
        if math.isfinite(low) and 6 < low <= 100:
            policy['PercentageLow'] = parser['UPower']['PercentageLow']
    except (configparser.Error, ValueError):
        pass
    lines, section, inserted = [], None, False
    for line in text.splitlines():
        match = re.fullmatch(r'\s*\[([^]]+)\]\s*', line)
        if match:
            section = match[1]
            lines.append(line)
            if section == 'UPower':
                lines.extend(f'{key}={value}' for key, value in policy.items())
                inserted = True
            continue
        if section == 'UPower' and re.match(
                r'\s*(?:' + '|'.join(POLICY) + r')\s*=', line):
            continue
        lines.append(line)
    if not inserted:
        lines.extend(['', '[UPower]'] + [f'{k}={v}' for k, v in policy.items()])
    result = '\n'.join(lines) + '\n'
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read_string(result)
    assert all(parser['UPower'][k] == v for k, v in policy.items())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result)


if __name__ == '__main__':
    configure(Path(sys.argv[1]))
