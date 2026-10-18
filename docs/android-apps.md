# Android apps (experimental)

Android apps run through Valve's Lepton (the Android layer the Steam Frame uses), with the Google Play Store built in. There's a Google Play Store title in your library after first login.

Everything you install, from the Play Store or as an `.apk`/`.apkm`/`.xapk`/`.apks` (open it in Dolphin or drop it in `~/Android/Inbox`), shows up as its own Steam title with its icon. The first launch downloads Lepton through Steam.

Apps run fullscreen with the touchscreen, the controller (as an Xbox pad) and a touch keyboard. Back/Home sit at the bottom left of Android's nav bar, Recents at the bottom right. Leave with Steam > Exit Game.

```
konkr-apk install Xbox.apkm   # same as opening it in Dolphin
konkr-apk list
konkr-apk remove com.gamepass
```

Games with anti-cheat that blocks emulators won't run, and a few apps may still crash. How it works is in [external-and-mods/konkr-android](../external-and-mods/konkr-android/README.md).

## Subordinate IDs and existing installations

At boot, `konkr-android-subids.service` prepares the stock `steamos` account
for Android's isolated-process IDs (90000–99999). It expands an existing
single `/etc/subuid` and `/etc/subgid` allocation to at least 131072 IDs,
keeping its start unchanged. It accepts the account name or its numeric UID,
keeps sufficient custom allocations, and checks both files before writing.
Missing, malformed, overlapping, overflowing or multiple allocations are
reported in the system journal and left for administrator review. Missing
files/accounts and non-file subid providers are not initialized automatically.

The Android user service actually runs as the logged-in nonroot user. This
boot helper only provisions `steamos`; renamed/custom login accounts need
separately reviewed allocations. These records grant *host* subordinate IDs;
they are not Android UID numbers. The actual Lepton/Podman namespace mapping
must be inspected on the target before diagnosing a remaining setuid/setgid
failure. Do not move a range to resolve a collision: retained Android and
container storage can already be owned by IDs from that range.

Boot ordering includes lingering user managers. A failed helper does not
block login, so check its journal if Android still fails. On an already-running
system, restarting Android alone may retain Podman's old pause namespace.
[Podman's migration documentation](https://docs.podman.io/en/latest/markdown/podman-system-migrate.1.html)
explains the required container/pause-process shutdown. Schedule that work
explicitly (or a clean reboot) after preserving data; this helper neither stops
containers nor migrates/deletes/chowns their storage. Do not manually run it
while rootless containers are active. It serializes with cooperating shadow
account tools, but external editors and non-enumerable directory accounts need
administrator coordination. Publication is atomic per file; a write failure
between the two replacements can leave only one file expanded, and a retry
can complete it without changing either starting ID.

This allocation does not change process-count, file-descriptor, stack or
memory limits. The existing Lepton stack option and cgroups-disabled policy
are separate; extending subids is not evidence that Android/apps boot or that
all host limits are adequate.
