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

## Steam client beta and PyroWave (SM8550)

Both are opt-in, by creating a file in `~/.local/share/Steam` and restarting Steam:

- `touch ~/.local/share/Steam/.allow-client-updates` allows client updates and the beta channel selected in Steam. With the shipped settings, updates are blocked without this file. `STEAM_ALLOW_CLIENT_UPDATES=1` in the **Steam launcher's environment** also opts in; `0` does not override an existing marker. An unrelated terminal's environment is not automatically passed to the Steam service. Removing the file and unsetting that variable blocks future updates; it does not downgrade the client.
- `touch ~/.local/share/Steam/.pyrowave-box64` requests the x86-64 streaming client from `steamrt64` under box64 for Remote Play. It requires that client, box64, and a valid native ARM64 client to back up. No beta client or libraries are downloaded by this switch. Select a compatible client beta separately if needed. Remove the file and restart Steam to restore native routing.

RUNSTEAM preserves unrelated `steam.cfg` settings in the Steam root and selected ARM runtime directory, removing only the five exact shipped suppression defaults on update opt-in. Custom bootstrap values remain authoritative and may still prevent updates; review them if the opt-in has no effect. The original launcher/installer did not record ownership of those five lines, so identical manually entered values cannot be distinguished from shipped defaults.

The PyroWave route keeps `streaming_client.arm64` as a recovery copy and refuses to overwrite an unknown custom launcher. Setup errors appear in the Steam service's output; the box64 stream log is `~/.local/share/Steam/logs/streaming_client_box64.log`. A running box64 client's failure is reported as its exit status, without automatically starting a second stream. The host and beta client's codec support determine whether PyroWave is negotiated; the UI toggle alone does not confirm it. Check for `Pyrowave Vulkan decoding` in the stream log. Codec decoding, performance and compatibility still require device validation.
