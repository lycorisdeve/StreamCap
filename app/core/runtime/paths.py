import os
import shutil
import sys
from pathlib import Path

APP_NAME = "StreamCap"
EXECUTABLE_SUFFIX = ".exe" if sys.platform == "win32" else ""


def _executable_dir() -> Path:
    executable = sys.executable if getattr(sys, "frozen", False) else sys.argv[0]
    return Path(executable).resolve().parent


def _macos_bundle_contents_dir(executable_dir: Path) -> Path | None:
    contents_dir = executable_dir.parent
    app_dir = contents_dir.parent
    if (
        getattr(sys, "frozen", False)
        and sys.platform == "darwin"
        and executable_dir.name == "MacOS"
        and contents_dir.name == "Contents"
        and app_dir.suffix == ".app"
    ):
        return contents_dir
    return None


_EXECUTABLE_DIR = _executable_dir()
_CONTENTS_DIR = _macos_bundle_contents_dir(_EXECUTABLE_DIR)
windows_package_layout = (
    getattr(sys, "frozen", False) and sys.platform == "win32" and (_EXECUTABLE_DIR / "resources").is_dir()
)

if _CONTENTS_DIR is not None:
    resource_dir = _CONTENTS_DIR / "Resources"
    user_data_dir = Path.home() / "Library" / "Application Support" / APP_NAME
elif getattr(sys, "frozen", False) and sys.platform == "win32":
    internal_dir = _EXECUTABLE_DIR / "_internal"
    resource_dir = internal_dir if (internal_dir / "config/default_settings.json").is_file() else _EXECUTABLE_DIR
    user_data_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    if windows_package_layout:
        resource_dir = _EXECUTABLE_DIR
        if not any(
            (user_data_dir / name).is_file()
            for name in (
                "config/user_settings.json",
                "config/recordings.db",
                "data/database/recordings.db",
            )
        ):
            user_data_dir = _EXECUTABLE_DIR
else:
    resource_dir = _EXECUTABLE_DIR
    user_data_dir = _EXECUTABLE_DIR

# Existing portable installations keep their configuration and SQLite history.
if getattr(sys, "frozen", False) and any(
    (_EXECUTABLE_DIR / relative).is_file()
    for relative in ("config/user_settings.json", "config/recordings.db", "data/database/recordings.db")
):
    user_data_dir = _EXECUTABLE_DIR

if getattr(sys, "frozen", False) and sys.platform == "win32":
    default_recordings_dir = _EXECUTABLE_DIR / "downloads"
    if windows_package_layout and user_data_dir == _EXECUTABLE_DIR and not default_recordings_dir.exists():
        default_recordings_dir = user_data_dir / "data/recordings"
else:
    default_recordings_dir = user_data_dir / "downloads"

assets_dir = resource_dir / "resources" if windows_package_layout else resource_dir / "assets"
locales_dir = assets_dir / "locales" if windows_package_layout else user_data_dir / "locales"
runtime_dir = _EXECUTABLE_DIR / "runtime" if windows_package_layout else user_data_dir
log_dir = user_data_dir / ("logs" if windows_package_layout else "log")


def prepare_user_data_dir() -> None:
    """Copy bundled defaults to the writable user data directory when needed."""
    if getattr(sys, "frozen", False):
        for relative in (
            "config/default_settings.json",
            "config/language.json",
            "config/version.json",
        ):
            if not (resource_dir / relative).exists():
                raise FileNotFoundError(f"Incomplete StreamCap package: {resource_dir / relative}")
        for path in (assets_dir, assets_dir / "locales" if windows_package_layout else resource_dir / "locales"):
            if not path.is_dir():
                raise FileNotFoundError(f"Incomplete StreamCap package: {path}")
    user_data_dir.mkdir(parents=True, exist_ok=True)
    if user_data_dir == resource_dir:
        return

    for directory in ("config", "locales"):
        if windows_package_layout and directory == "locales":
            continue
        source = resource_dir / directory
        target = user_data_dir / directory
        if source.is_dir():
            for source_file in source.rglob("*"):
                if not source_file.is_file():
                    continue
                target_file = target / source_file.relative_to(source)
                if directory == "config" and target_file.exists():
                    continue
                target_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_file, target_file)

    if not windows_package_layout:
        prepare_bundled_ffmpeg()
        prepare_bundled_node()


def prepare_bundled_ffmpeg() -> None:
    source_executable = resource_dir / "ffmpeg" / f"ffmpeg{EXECUTABLE_SUFFIX}"
    target_dir = user_data_dir / "ffmpeg"
    target_executable = target_dir / f"ffmpeg{EXECUTABLE_SUFFIX}"
    if not source_executable.is_file() or target_executable.exists():
        return
    if shutil.which("ffmpeg"):
        return

    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_executable, target_executable)
    if sys.platform != "win32":
        target_executable.chmod(target_executable.stat().st_mode | 0o755)


def prepare_bundled_node() -> None:
    source_executable = resource_dir / "node" / f"node{EXECUTABLE_SUFFIX}"
    target_dir = user_data_dir / "node"
    target_executable = target_dir / f"node{EXECUTABLE_SUFFIX}"
    if not source_executable.is_file() or target_executable.exists():
        return
    if shutil.which("node"):
        return

    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_executable, target_executable)
    if sys.platform != "win32":
        target_executable.chmod(target_executable.stat().st_mode | 0o755)


def prepend_user_bin_dirs() -> None:
    for directory in (runtime_dir / "ffmpeg", runtime_dir / "node"):
        if directory.is_dir():
            os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
