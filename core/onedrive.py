import os
import sys


def list_onedrive_mount_points() -> list[str]:
    """Local folder paths OneDrive is actively syncing on this machine.

    Covers both the personal/business OneDrive library (via the
    %OneDrive%/%OneDriveCommercial%/%OneDriveConsumer% env vars) and any
    additional SharePoint team-site libraries added via "Sync" -- those
    only show up in the registry, not the env vars, and are a completely
    ordinary way to end up with a shared team folder (this app's own
    default clients location is one).
    """
    mount_points = []
    for var in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        value = os.environ.get(var)
        if value:
            mount_points.append(value)

    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\SyncEngines\Providers\OneDrive") as key:
                index = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(key, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        with winreg.OpenKey(key, subkey_name) as subkey:
                            mount_point, _ = winreg.QueryValueEx(subkey, "MountPoint")
                            if mount_point:
                                mount_points.append(mount_point)
                    except OSError:
                        continue
        except OSError:
            pass

    return mount_points


def is_onedrive_synced_path(path: str, mount_points: list[str] | None = None) -> bool:
    """True if `path` is inside a folder OneDrive is actively syncing.

    `mount_points` is only ever passed explicitly by tests -- production
    callers rely on the default, which reads this machine's real sync
    state via list_onedrive_mount_points().
    """
    if not path:
        return False
    if mount_points is None:
        mount_points = list_onedrive_mount_points()

    target = os.path.normcase(os.path.abspath(path))
    for mount in mount_points:
        mount_abs = os.path.normcase(os.path.abspath(mount))
        try:
            if os.path.commonpath([target, mount_abs]) == mount_abs:
                return True
        except ValueError:
            continue  # different drives on Windows -- definitely not inside it
    return False
