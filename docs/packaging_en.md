# StreamCap Packaging Guide

This document explains how to package the StreamCap desktop app with PyInstaller and how to prepare optional bundled FFmpeg / Node.js executables.

## Requirements

- Build on the target platform:
  - Build macOS packages on macOS.
  - Build Windows packages on Windows.
- PyInstaller does not support cross-compiling between macOS and Windows.
- Install project dependencies first and make sure StreamCap can run in the current Python environment.

## One-Command Build

Run from the project root:

```bash
python scripts/build.py
```

The script automatically:

- Prepares the Flet desktop runtime archive.
- Bundles `config`, `locales`, and `assets`.
- Bundles `streamget` data files.
- Bundles optional FFmpeg / Node.js executables when present.
- On macOS, hides the outer PyInstaller Dock icon so only one StreamCap panda icon is shown.

macOS output:

```text
dist/StreamCap.app
```

Run it with:

```bash
open dist/StreamCap.app
```

Windows output:

```text
dist/StreamCap/
├─ StreamCap.exe
└─ _internal/
   ├─ assets/
   ├─ config/
   ├─ locales/
   └─ ...
```

Windows uses the PyInstaller one-dir layout: `StreamCap.exe` stays at the top level as the user entry point, while runtime dependencies, resources, and DLLs live under `_internal`.

GitHub Actions automatically zips downloaded artifacts, so the workflow uploads the app directory under `dist` instead of creating an inner zip first. After downloading `StreamCap-windows.zip`, extracting it once gives a `StreamCap` folder.

## macOS Architecture

By default, the package uses the current Python environment and host architecture. Apple Silicon machines usually produce an arm64 package.

You can specify it explicitly:

```bash
python scripts/build.py --target-arch arm64
```

Avoid `universal2` unless all Python and native dependencies are universal2. Otherwise PyInstaller may fail with `is not a fat binary`.

## Bundled FFmpeg

To bundle FFmpeg, prepare it first:

```bash
python scripts/download_ffmpeg.py
```

Download both supported platforms:

```bash
python scripts/download_ffmpeg.py --platform all
```

Files are saved to:

```text
vendor/ffmpeg/macos/ffmpeg
vendor/ffmpeg/windows/ffmpeg.exe
```

The script extracts only `ffmpeg` / `ffmpeg.exe`; it does not keep `ffplay` or `ffprobe`.

`scripts/build.py` automatically bundles the matching file when it exists. To skip bundled FFmpeg:

```bash
python scripts/build.py --no-bundle-ffmpeg
```

Runtime behavior:

- If `ffmpeg` is already available on `PATH`, the bundled version is not copied.
- If `ffmpeg` is not available and a bundled executable exists, it is copied to the user data directory.

Destination:

```text
macOS:   ~/Library/Application Support/StreamCap/ffmpeg/ffmpeg
Windows: %APPDATA%\StreamCap\ffmpeg\ffmpeg.exe
```

## Bundled Node.js

To bundle Node.js, prepare it first:

```bash
python scripts/download_nodejs.py
```

Download both supported platforms:

```bash
python scripts/download_nodejs.py --platform all
```

Specify a version:

```bash
python scripts/download_nodejs.py --version 22.12.0
```

Files are saved to:

```text
vendor/node/macos/node
vendor/node/windows/node.exe
```

The script extracts only `node` / `node.exe`; it does not keep `npm`, `npx`, headers, docs, or other files.

`scripts/build.py` automatically bundles the matching file when it exists. To skip bundled Node.js:

```bash
python scripts/build.py --no-bundle-node
```

Runtime behavior:

- If `node` is already available on `PATH`, the bundled version is not copied.
- If `node` is not available and a bundled executable exists, it is copied to the user data directory.

Destination:

```text
macOS:   ~/Library/Application Support/StreamCap/node/node
Windows: %APPDATA%\StreamCap\node\node.exe
```

## macOS Flet Notes

StreamCap uses Flet desktop mode. On macOS, Flet uses `Flet.app` as the actual window process.

The packaged app applies the following handling:

- The outer `StreamCap.app` runs as a background agent and does not show a Dock icon.
- The global Flet cache is not modified directly.
- On first launch, StreamCap creates its own Flet app copy:

```text
~/Library/Application Support/StreamCap/flet_client/<version>/StreamCap Flet.app
```

- The dedicated Flet copy uses the StreamCap panda icon.

In normal use, the Dock should show only one panda icon.

If macOS keeps showing an old icon after upgrading Flet or changing icons, delete the dedicated Flet cache and restart Dock:

```bash
rm -rf "$HOME/Library/Application Support/StreamCap/flet_client"
killall Dock
open dist/StreamCap.app
```

## User Data Directory

In packaged builds, mutable files such as config, logs, FFmpeg, and Node.js are not written into the app bundle or installation directory.

Locations:

```text
macOS:   ~/Library/Application Support/StreamCap
Windows: %APPDATA%\StreamCap
```

On Windows, the default recording directory is `downloads` next to `StreamCap.exe`, so large videos are not written to the C drive user data directory by default. If the user chooses a save directory in Settings, that value takes precedence.

When running from source, StreamCap still uses the project directory for easier development and debugging.

## Common Commands

Prepare optional bundled dependencies:

```bash
python scripts/download_ffmpeg.py --platform all
python scripts/download_nodejs.py --platform all
```

Build:

```bash
python scripts/build.py
```

Force re-download of the Flet desktop runtime archive:

```bash
python scripts/build.py --refresh-flet
```

Build without bundled FFmpeg / Node.js:

```bash
python scripts/build.py --no-bundle-ffmpeg --no-bundle-node
```
