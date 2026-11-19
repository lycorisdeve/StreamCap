from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

APP_NAME = "StreamCap"
ROOT = Path(__file__).resolve().parents[1]
FLET_ARCHIVE_DIR = ROOT / "build" / "flet_desktop_app"
VENDOR_DIR = ROOT / "vendor"


def detect_target_platform() -> str:
    system = platform.system()
    if system == "Darwin":
        return "macos"
    if system == "Windows":
        return "windows"
    raise SystemExit(f"Unsupported build platform: {system}")


def get_flet_version() -> str:
    try:
        import flet_desktop.version
    except ImportError as exc:
        raise SystemExit("flet_desktop is not installed in the current Python environment.") from exc
    return flet_desktop.version.version


def artifact_name(target_platform: str) -> str:
    if target_platform == "macos":
        return "flet-macos.tar.gz"
    if target_platform == "windows":
        return "flet-windows.zip"
    raise ValueError(target_platform)


def prepare_flet_archive(target_platform: str, refresh: bool) -> Path:
    version = get_flet_version()
    name = artifact_name(target_platform)
    target_dir = FLET_ARCHIVE_DIR / version / target_platform
    archive_path = target_dir / name

    target_dir.mkdir(parents=True, exist_ok=True)
    if archive_path.exists() and not refresh:
        print(f"Using cached Flet desktop archive: {archive_path}")
        return target_dir

    url = f"https://github.com/flet-dev/flet/releases/download/v{version}/{name}"
    print(f"Downloading {url}")
    urllib.request.urlretrieve(url, archive_path)
    print(f"Saved Flet desktop archive: {archive_path}")
    return target_dir


def add_data_arg(source: str, dest: str, target_platform: str) -> str:
    separator = ";" if target_platform == "windows" else ":"
    return f"{source}{separator}{dest}"


def bundled_ffmpeg_source(target_platform: str) -> Path:
    if target_platform == "macos":
        return VENDOR_DIR / "ffmpeg" / "macos" / "ffmpeg"
    if target_platform == "windows":
        return VENDOR_DIR / "ffmpeg" / "windows" / "ffmpeg.exe"
    raise ValueError(target_platform)


def bundled_node_source(target_platform: str) -> Path:
    if target_platform == "macos":
        return VENDOR_DIR / "node" / "macos" / "node"
    if target_platform == "windows":
        return VENDOR_DIR / "node" / "windows" / "node.exe"
    raise ValueError(target_platform)


def pyinstaller_command(args: argparse.Namespace, target_platform: str) -> list[str]:
    contents_directory = "_internal" if target_platform == "windows" else "."
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onedir",
        "-w",
        "--contents-directory",
        contents_directory,
        "--add-data",
        add_data_arg(str(ROOT / "locales"), "locales", target_platform),
        "--add-data",
        add_data_arg(str(ROOT / "assets"), "assets", target_platform),
        "--hidden-import",
        "pyexpat",
        "--hidden-import",
        "_multiprocessing",
        "--hidden-import",
        "tzdata",
        "--collect-data",
        "streamget",
        "--name",
        APP_NAME,
        "--icon",
        str(ROOT / ("assets/icons/Appicon.icns" if target_platform == "macos" else "assets/icon.ico")),
        "--noconfirm",
    ]

    for filename in ("default_settings.json", "language.json", "version.json"):
        command.extend(["--add-data", add_data_arg(str(ROOT / "config" / filename), "config", target_platform)])

    ffmpeg_source = bundled_ffmpeg_source(target_platform)
    if args.bundle_ffmpeg and ffmpeg_source.is_file():
        command.extend(["--add-data", add_data_arg(str(ffmpeg_source), "ffmpeg", target_platform)])
    elif args.bundle_ffmpeg:
        raise SystemExit(f"Bundled FFmpeg missing; run scripts/download_ffmpeg.py: {ffmpeg_source}")

    node_source = bundled_node_source(target_platform)
    if args.bundle_node and node_source.is_file():
        command.extend(["--add-data", add_data_arg(str(node_source), "node", target_platform)])
    elif args.bundle_node:
        raise SystemExit(f"Bundled Node.js missing; run scripts/download_nodejs.py: {node_source}")

    if args.clean:
        command.append("--clean")

    if target_platform == "macos":
        command.extend(
            [
                "--hidden-import",
                "plyer.platforms.macosx.notification",
                "--osx-bundle-identifier",
                "io.github.ihmily.streamcap",
            ]
        )
        if args.target_arch:
            command.extend(["--target-arch", args.target_arch])
    else:
        command.extend(["--hidden-import", "plyer.platforms.win.notification"])
        version_file = ROOT / "version_info.txt"
        if version_file.is_file():
            command.extend(["--version-file", str(version_file)])

    command.append(str(ROOT / "main.py"))
    return command


def run_build(args: argparse.Namespace) -> None:
    target_platform = args.platform or detect_target_platform()
    host_platform = detect_target_platform()
    if target_platform != host_platform:
        raise SystemExit(
            f"PyInstaller does not support cross-compiling from {host_platform} to {target_platform}. "
            f"Run this script on {target_platform} instead."
        )

    flet_view_path = prepare_flet_archive(target_platform, args.refresh_flet)

    env = os.environ.copy()
    env["FLET_VIEW_PATH"] = str(flet_view_path)

    command = pyinstaller_command(args, target_platform)
    print("Running:")
    print(" ".join(command))
    subprocess.run(command, cwd=ROOT, env=env, check=True)

    if target_platform == "macos":
        app_path = ROOT / "dist" / f"{APP_NAME}.app"
        hide_launcher_dock_icon(app_path)
        print(f"Built app: {app_path}")
        print(f"Run with: open {app_path}")
    else:
        arrange_windows_package(ROOT / "dist" / APP_NAME)
        print(f"Built app: {ROOT / 'dist' / APP_NAME / f'{APP_NAME}.exe'}")


def arrange_windows_package(package: Path) -> None:
    """Separate application files from PyInstaller's private dependencies."""
    package = package.resolve()
    for source, destination in (
        ("config", "config"),
        ("assets", "resources"),
        ("locales", "resources/locales"),
        ("ffmpeg", "runtime/ffmpeg"),
        ("node", "runtime/node"),
    ):
        origin = (package / "_internal" / source).resolve()
        target = (package / destination).resolve()
        if not origin.is_relative_to(package) or not target.is_relative_to(package):
            raise ValueError("Package path escaped its root")
        if origin.is_dir():
            if target.exists():
                raise FileExistsError(f"Refusing to merge package directories: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(origin), str(target))

    archive = package / "_internal/flet_desktop/app/flet-windows.zip"
    with zipfile.ZipFile(archive) as client:
        runtime = package / "runtime"
        for entry in client.infolist():
            if not (runtime / entry.filename).resolve().is_relative_to(runtime):
                raise ValueError("Invalid desktop runtime archive path")
        client.extractall(runtime)
    archive.unlink()
    # The archive was the only application data collected for flet_desktop.
    for directory in (archive.parent, archive.parent.parent):
        if not any(directory.iterdir()):
            directory.rmdir()
    version = json.loads((package / "config/version.json").read_text(encoding="utf-8"))["version_updates"][0]["version"]
    (package / "version.txt").write_text(version + "\n", encoding="utf-8")


def hide_launcher_dock_icon(app_path: Path) -> None:
    info_plist = app_path / "Contents" / "Info.plist"
    if not info_plist.is_file():
        return

    with info_plist.open("rb") as file:
        info = plistlib.load(file)
    info["LSUIElement"] = True
    with info_plist.open("wb") as file:
        plistlib.dump(info, file)

    codesign = shutil.which("codesign")
    if codesign:
        subprocess.run([codesign, "--force", "--deep", "--sign", "-", str(app_path)], check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build StreamCap desktop packages with PyInstaller.")
    parser.add_argument("--platform", choices=("macos", "windows"), help="Target platform. Defaults to the host OS.")
    parser.add_argument("--target-arch", choices=("arm64", "x86_64", "universal2"), help="macOS target architecture.")
    parser.add_argument("--refresh-flet", action="store_true", help="Re-download the Flet desktop archive.")
    parser.add_argument(
        "--no-bundle-ffmpeg",
        dest="bundle_ffmpeg",
        action="store_false",
        help="Do not bundle vendor FFmpeg even if present.",
    )
    parser.add_argument(
        "--no-bundle-node",
        dest="bundle_node",
        action="store_false",
        help="Do not bundle vendor Node.js even if present.",
    )
    parser.add_argument("--no-clean", dest="clean", action="store_false", help="Do not pass --clean to PyInstaller.")
    parser.set_defaults(bundle_ffmpeg=True, bundle_node=True, clean=True)
    return parser.parse_args()


if __name__ == "__main__":
    run_build(parse_args())
