# Profiles, commands and SSH

## Profiles

- **Silent**: GPU capped, quiet fan
- **Balanced**: the default
- **Turbo**: big cores pinned high, fan kicks in early

Switch with the Performance button (Pocket FIT), the KONKR Control plugin, the bottom screen dashboard (Thor, Pocket DS), or `konkrctl profile turbo` etc.

## Handy commands

```
konkrctl status               # profile, fan, clocks, temps
konkrctl rgb ff3c00           # stick colour (Pocket FIT)
konkrctl speaker flat         # speakers without the loudness boost (Pocket FIT / S2)
konkr-game fast %command%     # FEX preset for launch options, also fastest / compat
```

## Calibrate 60 / 120 Hz (RP6, Odin 3)

These panels can run a little off their rate, which makes a frame limiter stutter now and then. In Desktop Mode, set the screen to 60 Hz, open Konsole and run:

```
sudo steamos-arm-panel-calibrate
```

Keep the built-in screen awake and do not change display settings while it runs. Then switch to 120 Hz and run it again. It aims just above the selected rate (within 0.05 Hz at 60 Hz or 0.2 Hz at 120 Hz), and saves only a result that passes a longer final measurement. Allow about 30 seconds per rate; a panel may not converge within that tolerance. On failure or interruption it attempts to restore the previous value and reports any restore error. `steamos-arm-panel-calibrate show` prints what's set.

Saved values are tied to the board and panel and restored at boot. A file from a different board or an older unbound format must be moved aside before recalibrating. This tool supports the RP6 (including TOP-DPAD) and Odin 3 only; it does not calibrate the Pocket EVO's ICNA3512 panel.

## SSH

SSH is off by default. To turn it on, set a password (`passwd` in Konsole), then run `sudo systemctl enable --now sshd`. From your PC: `ssh steamos@<device-ip>`. Root login is off, use sudo. `sudo systemctl disable --now sshd` turns it off again.
