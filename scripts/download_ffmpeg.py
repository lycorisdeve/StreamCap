from __future__ import annotations

import argparse
import platform
import shutil
import stat
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR_FFMPEG_DIR = ROOT / "vendor" / "ffmpeg"

DEFAULT_URLS = {
    "macos": "https://evermeet.cx/ffmpeg/getrelease/zip",
    "windows": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
}


def detect_platform() -> str:
    system = platform.system()
    if system == "Darwin":
        return "macos"
    if system == "Windows":
        return "windows"
    raise SystemExit(f"Unsupported platform: {system}")


def target_path(target_platform: str) -> Path:
    if target_platform == "macos":
        return VENDOR_FFMPEG_DIR / "macos" / "ffmpeg"
    if target_platform == "windows":
        return VENDOR_FFMPEG_DIR / "windows" / "ffmpeg.exe"
    raise ValueError(target_platform)


def executable_name(target_platform: str) -> str:
    return "ffmpeg.exe" if target_platform == "windows" else "ffmpeg"


def download(url: str, destination: Path) -> None:
    print(f"Downloading {url}")

    def report(block_count: int, block_size: int, total_size: int) -> None:
        if total_size <= 0:
            return
        downloaded = min(block_count * block_size, total_size)
        percent = downloaded * 100 / total_size
        print(f"\r{percent:5.1f}%  {downloaded // 1024}KB/{total_size // 1024}KB", end="")

    urllib.request.urlretrieve(url, destination, reporthook=report)
    print()


def extract_ffmpeg(archive_path: Path, output_path: Path, target_platform: str) -> None:
    wanted_name = executable_name(target_platform)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive_path) as archive:
        members = [
            member
            for member in archive.infolist()
            if not member.is_dir() and Path(member.filename).name.lower() == wanted_name.lower()
        ]
        if not members:
            raise SystemExit(f"{wanted_name} not found in archive: {archive_path}")

        member = min(members, key=lambda item: len(Path(item.filename).parts))
        with archive.open(member) as source, output_path.open("wb") as target:
            shutil.copyfileobj(source, target)

    if target_platform != "windows":
        output_path.chmod(output_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def verify_ffmpeg(ffmpeg_path: Path) -> None:
    command = [str(ffmpeg_path), "-version"]
    try:
        import subprocess

        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    except Exception as exc:
        raise SystemExit(f"Failed to verify {ffmpeg_path}: {exc}") from exc

    if result.returncode != 0:
        raise SystemExit(f"Failed to verify {ffmpeg_path}: {result.stderr.strip()}")

    first_line = result.stdout.splitlines()[0] if result.stdout else "ffmpeg"
    print(f"Verified: {first_line}")


def can_verify(target_platform: str) -> bool:
    return target_platform == detect_platform()


def install_platform(target_platform: str, url: str, refresh: bool, verify: bool) -> None:
    output_path = target_path(target_platform)
    if output_path.exists() and not refresh:
        print(f"Already exists: {output_path}")
        if verify and can_verify(target_platform):
            verify_ffmpeg(output_path)
        elif verify:
            print(f"Skipping verification for {target_platform} on this host.")
        return

    with tempfile.TemporaryDirectory(prefix="streamcap-ffmpeg-") as temp_dir:
        archive_path = Path(temp_dir) / f"ffmpeg-{target_platform}.zip"
        download(url, archive_path)
        extract_ffmpeg(archive_path, output_path, target_platform)

    print(f"Saved: {output_path}")
    if verify and can_verify(target_platform):
        verify_ffmpeg(output_path)
    elif verify:
        print(f"Skipping verification for {target_platform} on this host.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download FFmpeg executables for StreamCap packaging.")
    parser.add_argument(
        "--platform",
        choices=("macos", "windows", "all"),
        default=detect_platform(),
        help="Target platform to download. Defaults to the host OS.",
    )
    parser.add_argument("--macos-url", default=DEFAULT_URLS["macos"], help="macOS FFmpeg zip URL.")
    parser.add_argument("--windows-url", default=DEFAULT_URLS["windows"], help="Windows FFmpeg zip URL.")
    parser.add_argument("--refresh", action="store_true", help="Overwrite an existing vendor FFmpeg executable.")
    parser.add_argument("--no-verify", dest="verify", action="store_false", help="Skip running ffmpeg -version.")
    parser.set_defaults(verify=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    platforms = ("macos", "windows") if args.platform == "all" else (args.platform,)
    urls = {"macos": args.macos_url, "windows": args.windows_url}

    for target_platform in platforms:
        install_platform(target_platform, urls[target_platform], args.refresh, args.verify)


if __name__ == "__main__":
    main()
