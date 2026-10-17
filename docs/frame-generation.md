# Frame generation

Lossless Scaling frame gen comes in two Decky plugins. Some games look better with one and some with the other, so both are installed. Use one per game, not both.

| Plugin | lsfg-vk | Launch option |
|---|---|---|
| **Decky LSFG-VK** | 2.0 | `~/.lsfg %command%` |
| **Frame Gen Classic** | 1.x | `~/lsfg-classic %command%` |

The upstream author reports artifacts with 2.0 in some Adreno games. Classic is an alternative to try; this integration has not been tested on a GPU or Pocket EVO.

## Decky LSFG-VK (2.0)

1. In Steam, go to Lossless Scaling > Properties > Game Versions & Betas and pick the `lsfg-vk` branch.
2. Open the Decky LSFG-VK plugin and hit Install.
3. Pick a game in the plugin and set it up, then add `~/.lsfg %command%` to that game's launch options.

## Frame Gen Classic (1.x)

1. Install Lossless Scaling in Steam.
2. Open Frame Gen Classic and hit Install.
3. Set it up, then add `~/lsfg-classic %command%` to the game's launch options.

The Classic wrapper enables its gated 1.x layer and disables 2.0 for that process. Use only one wrapper in each game's launch options. Frame Gen Classic keeps its own settings in `~/.config/lsfg-vk-classic`.

Both default to performance mode with flow scale 0.5. Classic starts with multiplier 1 (OFF); choose 2–4 to request generation. These defaults do not establish a performance gain.

Classic uses a manually selected profile for all games launched through its wrapper; it does not automatically map profiles to Steam AppIDs. Select the profile before launching and restart after changing launch workarounds. The separate 2.0 plugin retains its per-game profiles; the bottom-screen dashboard controls those 2.0 settings only.

Classic Flatpak setup is unavailable in this image because its inherited extension IDs collide with 2.0. Its UI and backend reject those operations, including cleanup on plugin removal. Use 2.0 for Flatpak games.

Reinstall preserves existing Classic config bytes and uses the saved profile for the wrapper. Unsupported or malformed configuration is left intact with an error, rather than reset. Missing runtime artifacts are reported; there is no automatic switch to the other version. Classic needs `Lossless.dll`, while 2.0 needs the `lsfg-vk.dll` from the Steam branch above; detection of one does not prove the other is available.

## Layers

The plugins only come with x86 layers (those still cover x86 games under FEX), so the image adds ARM64 builds for ARM64 games:

- [lsfg-vk](https://lsfg-vk.dev) 2.0 by PancakeTAS, unmodified (CC BY-NC-ND 4.0, see [LICENSE](../LICENSE)).
- lsfg-vk 1.x from [lsfg-vk-arm64](https://github.com/hashtagbasit/lsfg-vk-arm64), with two fixes so Proton ARM64 games start (MIT).
