from __future__ import annotations

import os
import fcntl
import stat
import tempfile
import struct
from pathlib import Path
from typing import Any


def _read_cstring(data: bytes, offset: int) -> tuple[str, int]:
    end = data.index(b"\x00", offset)
    return data[offset:end].decode("utf-8", errors="strict"), end + 1


def pack_vdf_int32(value: int) -> bytes:
    """Pack int32 for Steam binary VDF (appids are unsigned but stored as signed)."""
    value &= 0xFFFFFFFF
    if value >= 0x80000000:
        value -= 0x100000000
    return struct.pack("<i", value)


def vdf_int_as_unsigned(value: int) -> int:
    return value & 0xFFFFFFFF


class UInt64(int):
    """Retain binary VDF type 7 even when its value fits in 32 bits."""


class Snapshot(dict):
    pass


def parse_binary_vdf(data: bytes, offset: int = 0, _depth: int = 0) -> tuple[dict[str, Any], int]:
    if _depth > 64:
        raise ValueError("VDF nesting limit exceeded")
    result: dict[str, Any] = {}
    while offset < len(data):
        kind = data[offset]
        offset += 1
        if kind == 0x08:
            return result, offset
        name, _ = _read_cstring(data, offset)
        if name in result:
            raise ValueError(f"Duplicate VDF key: {name!r}")
        if kind == 0x00:
            name, offset = _read_cstring(data, offset)
            child, offset = parse_binary_vdf(data, offset, _depth + 1)
            result[name] = child
        elif kind == 0x01:
            name, offset = _read_cstring(data, offset)
            value, offset = _read_cstring(data, offset)
            result[name] = value
        elif kind == 0x02:
            name, offset = _read_cstring(data, offset)
            (value,) = struct.unpack_from("<i", data, offset)
            offset += 4
            result[name] = value
        elif kind == 0x07:
            name, offset = _read_cstring(data, offset)
            (value,) = struct.unpack_from("<Q", data, offset)
            offset += 8
            result[name] = UInt64(value)
        else:
            raise ValueError(f"Unsupported VDF type 0x{kind:02x} at offset {offset - 1}")
    raise ValueError("Truncated VDF object")


def emit_binary_vdf(node: dict[str, Any]) -> bytes:
    out = bytearray()
    for key, value in node.items():
        if not isinstance(key, str) or "\0" in key:
            raise ValueError("Invalid VDF key")
        if isinstance(value, str) and "\0" in value:
            raise ValueError("NUL in VDF string")
        if isinstance(value, UInt64):
            out.append(0x07)
            out.extend(key.encode("utf-8") + b"\x00")
            out.extend(struct.pack("<Q", value))
        elif isinstance(value, dict):
            out.append(0x00)
            out.extend(key.encode("utf-8") + b"\x00")
            out.extend(emit_binary_vdf(value))
        elif isinstance(value, int):
            out.append(0x02)
            out.extend(key.encode("utf-8") + b"\x00")
            out.extend(pack_vdf_int32(value))
        elif isinstance(value, str):
            out.append(0x01)
            out.extend(key.encode("utf-8") + b"\x00")
            out.extend(value.encode("utf-8") + b"\x00")
        else:
            raise TypeError(f"Unsupported VDF value type for key {key!r}: {type(value)}")
    out.append(0x08)
    return bytes(out)


def compute_app_id(exe: str, app_name: str) -> int:
    """Steam non-Steam appid hash (same algorithm as Lutris/Heroic/SteamGridDB tools)."""
    combined = exe + app_name
    crc = 0
    for ch in combined:
        crc ^= ord(ch) << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x107) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return int(crc | 0x80000000)


def format_steam_path(path: str) -> str:
    """Quote path for Linux shortcuts.vdf (Lutris/Heroic/PortProton style)."""
    return f'"{path}"'


def normalize_steam_path_field(value: str) -> str:
    """Fix Exe/StartDir values (e.g. old Windows-style \"\\\"path\\\"\" writes)."""
    if not value:
        return value
    if value.startswith('"\\"') and value.endswith('\\""'):
        return f'"{value[3:-3]}"'
    if value.startswith('"') and value.endswith('"'):
        return value
    return f'"{value}"'


def repair_shortcut_paths(tree: dict[str, Any]) -> int:
    """Normalize Exe/StartDir in all shortcuts; returns number of entries fixed."""
    shortcuts = tree.get("shortcuts", tree)
    fixed = 0
    for key, entry in shortcuts.items():
        if key == "tags" or not isinstance(entry, dict):
            continue
        for field in ("Exe", "StartDir"):
            if field not in entry:
                continue
            old = entry[field]
            if not isinstance(old, str):
                raise ValueError(f"Invalid shortcut {field}")
            new = normalize_steam_path_field(old)
            if new != old:
                entry[field] = new
                fixed += 1
    return fixed


def default_shortcut_fields(app_id: int, app_name: str, exe: str, start_dir: str) -> dict[str, Any]:
    return {
        "appid": app_id,
        "AppName": app_name,
        "Exe": format_steam_path(exe),
        "StartDir": format_steam_path(start_dir),
        "icon": "",
        "ShortcutPath": "",
        "LaunchOptions": "",
        "IsHidden": 0,
        "AllowDesktopConfig": 1,
        "AllowOverlay": 1,
        "OpenVR": 0,
        "Devkit": 0,
        "DevkitGameID": "",
        "DevkitOverrideID": "",
        "LastPlayTime": 0,
        "FlatpakAppID": "",
    }


def _read_regular(path: Path) -> bytes | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as f:
        info = os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 16 * 1024 * 1024:
            raise ValueError("VDF must be a regular file smaller than 16 MiB")
        return f.read()


def require_steam_closed() -> None:
    proc = Path("/proc")
    if not proc.is_dir():
        raise RuntimeError("Offline Steam check requires Linux /proc")
    for p in proc.glob("[0-9]*/comm"):
        try:
            if p.read_text().strip() in {"steam", "steamwebhelper"}:
                raise RuntimeError("Close Steam before editing its VDF files")
        except FileNotFoundError:
            pass


def load_shortcuts(path: Path) -> dict[str, Any]:
    data = _read_regular(path)
    if data is None:
        parsed = {"shortcuts": {}}
    else:
        try:
            parsed, end = parse_binary_vdf(data)
        except (struct.error, UnicodeError, IndexError) as exc:
            raise ValueError("Malformed VDF; original preserved") from exc
        if end != len(data) or not isinstance(parsed.get("shortcuts"), dict):
            raise ValueError("Invalid shortcuts root or trailing VDF data")
    tree = Snapshot(parsed)
    tree.source_path = path.absolute()
    tree.source_bytes = data
    return tree


def save_shortcuts(path: Path, tree: dict[str, Any]) -> None:
    # Cooperating writers serialize; snapshots also catch intervening edits.
    # Steam does not honor this lock, hence the explicit offline-only checks.
    if not isinstance(tree, Snapshot) or tree.source_path != path.absolute():
        raise ValueError("Load the original VDF before saving")
    payload = emit_binary_vdf(tree)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a+b") as lock:
        if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
            raise ValueError("Invalid VDF lock")
        fcntl.flock(lock, fcntl.LOCK_EX)
        require_steam_closed()
        if _read_regular(path) != tree.source_bytes:
            raise RuntimeError("VDF changed since it was loaded; reload first")
        if tree.source_bytes is not None:
            backup_fd, _ = tempfile.mkstemp(prefix=path.name + ".backup-", dir=path.parent)
            with os.fdopen(backup_fd, "wb") as backup:
                backup.write(tree.source_bytes)
                backup.flush()
                os.fsync(backup.fileno())
        tmp_fd, tmp = tempfile.mkstemp(prefix=path.name + ".new-", dir=path.parent)
        try:
            with os.fdopen(tmp_fd, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            require_steam_closed()
            if _read_regular(path) != tree.source_bytes:
                raise RuntimeError("VDF changed during save")
            os.replace(tmp, path)
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            tree.source_bytes = payload
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


def next_shortcut_index(shortcuts_root: dict[str, Any]) -> str:
    shortcuts = shortcuts_root.get("shortcuts", shortcuts_root)
    indices: list[int] = []
    for key in shortcuts:
        if key == "tags":
            continue
        if key.isdigit():
            indices.append(int(key))
    return str(max(indices, default=-1) + 1)


def find_existing_app_id(shortcuts_root: dict[str, Any], app_id: int) -> str | None:
    shortcuts = shortcuts_root.get("shortcuts", shortcuts_root)
    for key, entry in shortcuts.items():
        if key == "tags" or not isinstance(entry, dict):
            continue
        if vdf_int_as_unsigned(entry.get("appid", 0)) == vdf_int_as_unsigned(app_id):
            return key
    return None


def add_shortcut(
    shortcuts_path: Path,
    app_name: str,
    exe: str,
    start_dir: str | None = None,
    launch_options: str = "",
) -> int:
    exe = str(Path(exe).resolve())
    if start_dir:
        start = str(Path(start_dir).resolve())
    else:
        start = str(Path(exe).parent)

    app_id = compute_app_id(exe, app_name)
    tree = load_shortcuts(shortcuts_path)
    repair_shortcut_paths(tree)
    shortcuts = tree.setdefault("shortcuts", tree)

    existing = find_existing_app_id(tree, app_id)
    key = existing if existing is not None else next_shortcut_index(tree)

    entry = default_shortcut_fields(app_id, app_name, exe, start)
    if launch_options:
        entry["LaunchOptions"] = launch_options
    shortcuts[key] = entry

    if "tags" not in shortcuts:
        shortcuts["tags"] = {}

    save_shortcuts(shortcuts_path, tree)
    os.chmod(shortcuts_path, 0o644)
    return app_id


def install_grid_art(userdata_dir: Path, app_id: int, image_path: Path) -> None:
    """Copy cover into Steam grid folder (library + portrait)."""
    grid_dir = userdata_dir / "config" / "grid"
    grid_dir.mkdir(parents=True, exist_ok=True)
    suffix = image_path.suffix.lower() or ".png"
    if suffix not in {".png", ".jpg", ".jpeg"}:
        suffix = ".png"
    library = grid_dir / f"{app_id}_.{suffix.lstrip('.')}"
    portrait = grid_dir / f"{app_id}p.{suffix.lstrip('.')}"
    data = image_path.read_bytes()
    library.write_bytes(data)
    portrait.write_bytes(data)
    os.chmod(library, 0o644)
    os.chmod(portrait, 0o644)
