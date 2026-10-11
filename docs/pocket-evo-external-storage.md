# Pocket EVO workspace on removable storage

All project data lives under `/Volumes/Mac Folder/SteamOS-PocketEvo/`:

- `Steam-OS-ARM-PocketEvo/`: SteamOS Git checkout.
- `Steam-OS-ARM-PocketEvo-build/`: downloads, scripts, logs and output images.
- `colima/`: Colima configuration, Linux VM disks, Docker images/containers and
  the `pocket-evo-work` volume containing the kernel sources, caches and `/work`.

There are no workspace symlinks under `~/Documents/ChatGPT/`. Open this checkout
by its external path in your editor. The local shell sets `COLIMA_HOME` to the
external `colima/` directory. The helper below also sets it explicitly, so it
works from an existing terminal or an editor that has an older environment.

From this checkout:

```bash
bash scripts/pocket-evo-vm.sh start
# Existing commands inside the builder:
docker --context colima-pocket-evo exec pocket-evo-build bash /src/scripts/build-pocket-evo-kernel.sh
docker --context colima-pocket-evo exec pocket-evo-build bash /src/scripts/repack-pocket-evo-test-image.sh
# When finished, before ejecting the external disk:
bash scripts/pocket-evo-vm.sh stop
```

`status` prints the profile and container states. The helper refuses to start if
its adjacent Colima profile or project directories are absent. The container
mounts the source checkout at `/src` read-only,
`/artifacts` is writable, and `/work` is a Docker volume inside the external VM
disk. The existing toolchain is preserved when recreating the container.

Keep the volume name `Mac Folder` unchanged: Colima mounts and Docker context
configuration contain absolute paths. Finish build/copy/Git operations, stop
Colima, and eject in Finder before disconnecting. Reattach the same volume and
run `start` to resume. Do not unplug the drive while the VM is running.

Host-installed Colima, Docker CLI and small shell/SSH/Docker-context settings
remain on the Mac; the disk is not a self-contained installation for another
computer. [Colima supports relocating its home through COLIMA_HOME](https://colima.run/docs/commands/#environment-variables).
