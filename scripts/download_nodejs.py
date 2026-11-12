#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR_NODE_DIR = ROOT / "vendor" / "node"
NODE_DIST_INDEX = "https://nodejs.org/dist/index.json"
NODE_DIST_BASE = "https://nodejs.org/dist"


def detect_platform() -> str:
    system = platform.system()
    if system == "Darwin":
        return "macos"
    if system == "Windows":
        return "windows"
    raise SystemExit(f"Unsupported platform: {system}")


def default_arch(target_platform: str) -> str:
    machine = platform.machine().lower()
    if target_platform == "macos":
        return "arm64" if machine in ("arm64", "aarch64") else "x64"
    if target_platform == "windows":
        return "x64"
    raise ValueError(target_platform)


def normalize_version(version: str) -> str:
    return version if version.startswith("v") else f"v{version}"


def latest_lts_version() -> str:
    with urllib.request.urlopen(NODE_DIST_INDEX, timeout=30) as response:
        releases = json.load(response)
    for release in releases:
        if release.get("lts"):
            return release["version"]
    raise SystemExit("Could not find a Node.js LTS release.")


def target_path(target_platform: str) -> Path:
    if target_platform == "macos":
        return VENDOR_NODE_DIR / "macos" / "node"
    if target_platform == "windows":
        return VENDOR_NODE_DIR / "windows" / "node.exe"
    raise ValueError(target_platform)


def archive_name(version: str, target_platform: str, arch: str) -> str:
    if target_platform == "macos":
        return f"node-{version}-darwin-{arch}.tar.gz"
    if target_platform == "windows":
        return f"node-{version}-win-{arch}.zip"
    raise ValueError(target_platform)


def executable_member_name(target_platform: str) -> str:
    return "node.exe" if target_platform == "windows" else "node"


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


def extract_from_zip(archive_path: Path, output_path: Path, wanted_name: str) -> None:
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


def extract_from_tar(archive_path: Path, output_path: Path, wanted_name: str) -> None:
    with tarfile.open(archive_path, "r:gz") as archive:
        members = [
            member
            for member in archive.getmembers()
            if member.isfile() and Path(member.name).name.lower() == wanted_name.lower()
        ]
        if not members:
            raise SystemExit(f"{wanted_name} not found in archive: {archive_path}")
        member = min(members, key=lambda item: len(Path(item.name).parts))
        source = archive.extractfile(member)
        if source is None:
            raise SystemExit(f"Could not extract {member.name}")
        with source, output_path.open("wb") as target:
            shutil.copyfileobj(source, target)


def extract_node(archive_path: Path, output_path: Path, target_platform: str) -> None:
    wanted_name = executable_member_name(target_platform)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if archive_path.suffix == ".zip":
        extract_from_zip(archive_path, output_path, wanted_name)
    else:
        extract_from_tar(archive_path, output_path, wanted_name)

    if target_platform != "windows":
        output_path.chmod(output_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def can_verify(target_platform: str, arch: str) -> bool:
    if target_platform != detect_platform():
        return False
    return arch == default_arch(target_platform)


def verify_node(node_path: Path) -> None:
    try:
        result = subprocess.run([str(node_path), "-v"], capture_output=True, text=True, timeout=15)
    except Exception as exc:
        raise SystemExit(f"Failed to verify {node_path}: {exc}") from exc

    if result.returncode != 0:
        raise SystemExit(f"Failed to verify {node_path}: {result.stderr.strip()}")
    print(f"Verified: node {result.stdout.strip()}")


def install_platform(target_platform: str, version: str, arch: str, refresh: bool, verify: bool) -> None:
    output_path = target_path(target_platform)
    if output_path.exists() and not refresh:
        print(f"Already exists: {output_path}")
        if verify and can_verify(target_platform, arch):
            verify_node(output_path)
        elif verify:
            print(f"Skipping verification for {target_platform}/{arch} on this host.")
        return

    name = archive_name(version, target_platform, arch)
    url = f"{NODE_DIST_BASE}/{version}/{name}"

    with tempfile.TemporaryDirectory(prefix="streamcap-node-") as temp_dir:
        archive_path = Path(temp_dir) / name
        download(url, archive_path)
        extract_node(archive_path, output_path, target_platform)

    print(f"Saved: {output_path}")
    if verify and can_verify(target_platform, arch):
        verify_node(output_path)
    elif verify:
        print(f"Skipping verification for {target_platform}/{arch} on this host.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download Node.js executables for StreamCap packaging.")
    parser.add_argument(
        "--platform",
        choices=("macos", "windows", "all"),
        default=detect_platform(),
        help="Target platform to download. Defaults to the host OS.",
    )
    parser.add_argument("--version", help="Node.js version, for example 22.12.0 or v22.12.0. Defaults to latest LTS.")
    parser.add_argument("--macos-arch", choices=("arm64", "x64"), help="macOS Node.js architecture.")
    parser.add_argument(
        "--windows-arch",
        choices=("x64", "x86", "arm64"),
        default="x64",
        help="Windows Node.js architecture.",
    )
    parser.add_argument("--refresh", action="store_true", help="Overwrite an existing vendor Node.js executable.")
    parser.add_argument("--no-verify", dest="verify", action="store_false", help="Skip running node -v.")
    parser.set_defaults(verify=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    version = normalize_version(args.version) if args.version else latest_lts_version()
    platforms = ("macos", "windows") if args.platform == "all" else (args.platform,)

    for target_platform in platforms:
        arch = args.macos_arch or default_arch("macos") if target_platform == "macos" else args.windows_arch
        install_platform(target_platform, version, arch, args.refresh, args.verify)


if __name__ == "__main__":
    main()
