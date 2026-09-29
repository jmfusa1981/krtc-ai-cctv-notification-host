import ctypes
import hashlib
import json
import secrets
from pathlib import Path

DRIVE_REMOVABLE = 2
KEY_TYPE = "KRTC_SUPERUSER_KEY"
KEY_PROJECT = "KRTC_AI_CCTV"
KEY_RELATIVE_PATH = Path(r"KRTC_SUPERUSER_KEY\\krtc_superuser.key")


def iter_removable_drives():
    if not hasattr(ctypes, "windll"):
        return []
    get_drive_type = ctypes.windll.kernel32.GetDriveTypeW
    result = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        root = Path(f"{letter}:\\")
        try:
            if root.exists() and get_drive_type(str(root)) == DRIVE_REMOVABLE:
                result.append(root)
        except OSError:
            continue
    return result


def volume_label(root):
    if not hasattr(ctypes, "windll"):
        return ""
    try:
        volume_name = ctypes.create_unicode_buffer(261)
        fs_name = ctypes.create_unicode_buffer(261)
        serial = ctypes.c_ulong()
        max_component = ctypes.c_ulong()
        flags = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            str(root), volume_name, len(volume_name),
            ctypes.byref(serial), ctypes.byref(max_component),
            ctypes.byref(flags), fs_name, len(fs_name),
        )
        return volume_name.value if ok else ""
    except Exception:
        return ""


def read_key_file(key_path):
    try:
        payload = json.loads(Path(key_path).read_text(encoding="utf-8"))
    except Exception:
        return None
    if payload.get("type") != KEY_TYPE:
        return None
    if payload.get("project") not in ("", None, KEY_PROJECT):
        return None
    token = str(payload.get("token", "")).strip()
    if not token:
        return None
    return payload


def token_sha256(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest().lower()


def list_removable_drives():
    items = []
    for root in iter_removable_drives():
        key_path = root / KEY_RELATIVE_PATH
        item = read_key_file(key_path) if key_path.exists() else None
        items.append({
            "drive": str(root).rstrip("\\"),
            "label": volume_label(root),
            "has_krtc_key": bool(item),
            "key_id": item.get("key_id", "") if item else "",
        })
    return items


def resolve_drive(drive_value=""):
    value = (drive_value or "").strip().rstrip("\\/")
    if not value:
        drives = iter_removable_drives()
        if len(drives) == 1:
            return drives[0]
        if not drives:
            raise ValueError("未偵測到可移除式 USB。")
        raise ValueError("偵測到多支 USB，請指定要使用的裝置。")
    if len(value) == 1:
        value += ":"
    root = Path(value + "\\")
    if not root.exists():
        raise ValueError(f"找不到 USB 裝置：{root}")
    return root


def create_or_register_master_key(drive_value=""):
    root = resolve_drive(drive_value)
    key_path = root / KEY_RELATIVE_PATH
    key_path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_key_file(key_path) if key_path.exists() else None
    if existing:
        payload = existing
        created = False
    else:
        payload = {
            "type": KEY_TYPE,
            "project": KEY_PROJECT,
            "key_id": "SKYNET-MASTER-01",
            "scope": "ALL_TRUSTED_HOSTS",
            "token": secrets.token_urlsafe(48),
        }
        key_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        created = True
    return {
        "created": created,
        "key_path": str(key_path),
        "key_id": payload.get("key_id", "SKYNET-MASTER-01"),
        "token_sha256": token_sha256(str(payload["token"])),
    }


def verify_trusted_key(expected_sha256):
    expected = (expected_sha256 or "").strip().lower()
    if not expected:
        return False, None
    for root in iter_removable_drives():
        key_path = root / KEY_RELATIVE_PATH
        if not key_path.exists():
            continue
        payload = read_key_file(key_path)
        if not payload:
            continue
        if token_sha256(str(payload["token"])) == expected:
            return True, {
                "drive": str(root).rstrip("\\"),
                "key_id": payload.get("key_id", ""),
                "key_path": str(key_path),
            }
    return False, None
