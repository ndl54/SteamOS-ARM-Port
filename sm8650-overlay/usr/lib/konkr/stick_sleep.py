#!/usr/bin/env python3
"""Serialize common sysfs stick LEDs across s2idle; EVO owns its UART LEDs."""
import contextlib
import fcntl
import functools
import json
import os
from pathlib import Path
import re
import sys

LEDS = Path('/sys/class/leds')
RUNTIME = Path('/run/konkr/stick-sleep')
COMPATIBLE = Path('/proc/device-tree/compatible')
STANDBY = Path('/run/konkr-standby')


def selected(name):
    return ('joysticks' in name or name in ('left-joystick', 'right-joystick')
            or re.fullmatch(r'rgb:[lr][0-9]+', name) is not None)


def log(message):
    print(f'stick-sleep: {message}', file=sys.stderr, flush=True)


@contextlib.contextmanager
def locked(blocking=True):
    RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (RUNTIME / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        yield


def awake_only(method):
    """Check under the same lock as blanking, including reload/live colours."""
    @functools.wraps(method)
    def guarded(self, *args, **kwargs):
        if not self.sticks:
            return
        self.sticks_pending = True
        try:
            with locked(blocking=False):
                if not (RUNTIME / 'state.json').exists() and not STANDBY.exists():
                    result = method(self, *args, **kwargs)
                    self.sticks_pending = False
                    return result
        except BlockingIOError:
            return  # never stall the fan/control loop behind sleep I/O
        except OSError as exc:
            log(f'LED update skipped: {exc}')
    return guarded


def read_state(path):
    state = json.loads(path.read_text())
    if not isinstance(state, dict):
        raise ValueError('invalid state')
    for name, attrs in state.items():
        if '/' in name or not selected(name) or not isinstance(attrs, dict):
            raise ValueError('invalid LED name/state')
        if 'brightness' not in attrs or set(attrs) - {'brightness', 'effect', 'trigger'}:
            raise ValueError('invalid attributes')
        if any(not isinstance(v, str) or not v or len(v) > 128 for v in attrs.values()):
            raise ValueError('invalid attribute value')
    return state


def write(path, value):
    # Do not create missing sysfs attributes after a device disappears.
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_TRUNC), 'w') as stream:
        stream.write(value + '\n')


def change(action):
    try:
        if b'ayaneo,pocketevo' in COMPATIBLE.read_bytes().split(b'\0'):
            return
    except OSError:
        pass
    with locked():
        journal = RUNTIME / 'state.json'
        if action == 'pre':
            if journal.exists():
                state = read_state(journal)  # repeated pre must not save zero
            else:
                state = {}
                for led in sorted(LEDS.iterdir()):
                    if not selected(led.name) or not (led / 'brightness').exists():
                        continue
                    try:
                        attrs = {'brightness': (led / 'brightness').read_text().strip()}
                        if (led / 'effect').exists():
                            attrs['effect'] = (led / 'effect').read_text().strip()
                        if (led / 'trigger').exists():
                            active = re.findall(r'\[([^]\s]+)\]', (led / 'trigger').read_text())
                            if len(active) != 1:
                                log(f'{led.name}: unknown trigger, left unchanged')
                                continue
                            attrs['trigger'] = active[0]
                        state[led.name] = attrs
                    except OSError as exc:
                        log(f'{led.name}: cannot save, left unchanged: {exc}')
                temp = RUNTIME / 'state.tmp'
                temp.write_text(json.dumps(state))
                temp.replace(journal)  # publish before touching hardware
            for name, attrs in state.items():
                try:
                    # brightness selects static in the KONKR backend. Set it
                    # to zero before switching effect to avoid a bright flash.
                    if 'trigger' in attrs:
                        write(LEDS / name / 'trigger', 'none')
                    write(LEDS / name / 'brightness', '0')
                    if 'effect' in attrs:
                        write(LEDS / name / 'effect', 'static')
                except OSError as exc:
                    log(f'{name}: blank failed: {exc}')
        else:
            if not journal.exists():
                return
            try:
                state = read_state(journal)
                for name, attrs in state.items():
                    # Brightness before effect (KONKR selects static on write);
                    # restore a previously active kernel trigger last.
                    for attr in ('brightness', 'effect', 'trigger'):
                        if attr in attrs:
                            try:
                                write(LEDS / name / attr, attrs[attr])
                            except OSError as exc:
                                log(f'{name}/{attr}: restore failed: {exc}')
            finally:
                journal.unlink(missing_ok=True)  # let daemon retry its config


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in ('pre', 'post'):
        sys.exit('usage: stick_sleep.py pre|post')
    try:
        change(sys.argv[1])
    except (OSError, ValueError) as exc:
        log(str(exc))  # LED failure must not block other device recovery
