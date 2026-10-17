#!/usr/bin/env python3
"""Validate/stage a trusted test payload; never build or mount anything."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import sys


def stage(source, destination, check=False):
    source = Path(source).resolve(strict=True)
    destination = Path(destination)
    staging = destination.parent.parent.resolve()  # WORK/initramfs, cleared by build.sh
    destination = destination.resolve()
    if (source == staging or source in staging.parents or staging in source.parents):
        raise ValueError("hotfix input overlaps initramfs staging")
    if not source.is_dir():
        raise ValueError("hotfix input must be a directory")
    files = []
    def walk_error(error):
        raise error

    for directory, dirs, names in os.walk(source, followlinks=False, onerror=walk_error):
        for name in sorted(dirs + names):
            path = Path(directory) / name
            relative = path.relative_to(source)
            info = path.lstat()
            if not re.fullmatch(r"[A-Za-z0-9._+@ /-]+", str(relative)):
                raise ValueError(f"unsupported hotfix filename: {relative!s}")
            if relative.parts[0] not in ("etc", "usr"):
                raise ValueError(f"use canonical etc/ or usr/ paths: {relative}")
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise ValueError(f"symlink or special file in hotfix: {relative}")
            if stat.S_ISREG(info.st_mode):
                if len(relative.parts) < 2 or info.st_mode & 0o6022:
                    raise ValueError(f"unsafe hotfix file mode/path: {relative}")
                if str(relative) in (
                    "etc/sddm.conf.d/zzz-steamos-arm-session.conf",
                    "usr/lib/steamos-arm/bootdebug",
                    "usr/lib/systemd/system/steamos-arm-bootdebug.service",
                    "usr/lib/systemd/system/multi-user.target.wants/steamos-arm-bootdebug.service",
                ):
                    raise ValueError(f"init-managed path is reserved: {relative}")
                files.append((path, relative, stat.S_IMODE(info.st_mode)))
    if not files:
        raise ValueError("hotfix input contains no regular files")
    if check:
        return
    destination.mkdir(mode=0o700)  # Must be a new, private staging tree.
    manifest = []
    modes = []
    for path, relative, mode in sorted(files):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        # Contents and executable bits only: no host owners, ACLs, capabilities,
        # symlinks or hard-link topology. cpio records root ownership.
        with path.open("rb") as src, target.open("xb") as dst:
            shutil.copyfileobj(src, dst)
        target.chmod(mode)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        manifest.append(f"{digest}  {relative}\n")
        modes.append(f"{mode:04o} {relative}\n")
    (destination.parent / "hotfix.sha256").write_text("".join(manifest))
    (destination.parent / "hotfix.modes").write_text("".join(modes))


if __name__ == "__main__":
    try:
        if len(sys.argv) not in (3, 4) or (len(sys.argv) == 4 and sys.argv[3] != "--check"):
            raise ValueError("usage: hotfix-tree.py SOURCE DESTINATION [--check]")
        stage(sys.argv[1], sys.argv[2], len(sys.argv) == 4)
    except (OSError, ValueError) as error:
        sys.exit(f"hotfix: {error}")
