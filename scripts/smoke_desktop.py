"""Run the shipped Windows app with isolated profiles and real FFmpeg children."""

import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes as wt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from windows_runtime import WindowsAPI


def visible_window(hide=False):
    user = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wt.LPARAM]
    user.IsWindowVisible.argtypes = [wt.HWND]
    user.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
    found = []

    def visit(window, _):
        title = ctypes.create_unicode_buffer(256)
        user.GetWindowTextW(window, title, len(title))
        if title.value == "StreamCap" and user.IsWindowVisible(window):
            pid = wt.DWORD()
            user.GetWindowThreadProcessId(window, ctypes.byref(pid))
            found.append(pid.value)
            if hide:
                user.ShowWindow(window, 0)
        return True

    user.EnumWindows(callback_type(visit), 0)
    return found


def run(package):
    if os.name != "nt":
        raise SystemExit("This smoke check requires Windows")
    package = Path(package).resolve()
    for relative in (
        "config/default_settings.json",
        "resources/icon.ico",
        "resources/locales/zh_CN.json",
        "runtime/ffmpeg/ffmpeg.exe",
        "runtime/node/node.exe",
        "runtime/flet/flet.exe",
        "version.txt",
    ):
        assert (package / relative).is_file(), f"Missing bundled resource: {relative}"
    api = WindowsAPI()
    with tempfile.TemporaryDirectory(prefix="StreamCap 桌面 ") as directory:
        root = Path(directory)
        copied = root / "应用 程序"
        shutil.copytree(package, copied)
        executable = copied / "StreamCap.exe"
        second_copy = root / "another copy"
        shutil.copytree(package, second_copy)
        independent = subprocess.Popen(
            [
                str(copied / "runtime/ffmpeg/ffmpeg.exe"),
                "-v",
                "error",
                "-re",
                "-f",
                "lavfi",
                "-i",
                "sine",
                "-f",
                "null",
                "-",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            for scenario in ("normal", "frontend-crash", "backend-crash"):
                profile = root / scenario
                profile.mkdir()
                env = dict(os.environ)
                for key in list(env):
                    if key.startswith("FLET_"):
                        env.pop(key)
                env.update(
                    USERPROFILE=str(profile),
                    APPDATA=str(profile / "Roaming"),
                    LOCALAPPDATA=str(profile / "Local"),
                    PLATFORM="desktop",
                    PATH=os.environ["SYSTEMROOT"] + r"\System32",
                    HTTP_PROXY="http://127.0.0.1:1",
                    HTTPS_PROXY="http://127.0.0.1:1",
                    NO_PROXY="127.0.0.1,localhost",
                )
                data = copied
                marker = data / "desktop-ready.json"
                marker.unlink(missing_ok=True)
                (data / "desktop-stop").unlink(missing_ok=True)
                process = subprocess.Popen([str(executable), "--smoke-test"], cwd=root, env=env)
                handles = []
                try:
                    deadline = time.monotonic() + 90
                    while not marker.exists() and time.monotonic() < deadline and process.poll() is None:
                        time.sleep(0.1)
                    if not marker.exists():
                        logs = []
                        for log in root.rglob("*.log"):
                            logs.append(log.read_text(encoding="utf-8", errors="replace")[-6000:])
                        raise AssertionError(f"{scenario}: startup failed ({process.poll()}): {logs}")
                    state = json.loads(marker.read_text(encoding="utf-8"))
                    assert state["ready"], state
                    assert not (profile / ".flet/client").exists(), "Unexpected external Flet client cache"
                    assert (data / "data/database/recordings.db").is_file()
                    assert (data / "logs/app.log").is_file()
                    assert not (data / "assets").exists()
                    assert not (data / "ffmpeg").exists()
                    frontend = visible_window()
                    assert len(frontend) == 1, f"Expected one visible StreamCap window: {frontend}"
                    for pid in [*state["children"], *frontend]:
                        handles.append(api.checked(api.kernel.OpenProcess(0x100001, False, pid)))
                    visible_window(hide=True)
                    assert not visible_window(), "Could not hide the test window"
                    second = subprocess.Popen(
                        [str(second_copy / "StreamCap.exe"), "--smoke-test"], cwd=profile, env=env
                    )
                    assert second.wait(timeout=10) == 0, "Second launch did not exit"
                    restored_by = time.monotonic() + 5
                    while visible_window() != frontend and time.monotonic() < restored_by:
                        time.sleep(0.1)
                    assert visible_window() == frontend, "Second launch did not restore the original window"
                    time.sleep(1)
                    if scenario == "normal":
                        (data / "desktop-stop").touch()
                    elif scenario == "frontend-crash":
                        api.checked(api.kernel.TerminateProcess(handles[-1], 1))
                    else:
                        process.kill()
                    exit_code = process.wait(timeout=25)
                    if scenario == "normal":
                        assert exit_code == 0, exit_code
                        for name in ("recording", "conversion"):
                            media = data / (name + ".mkv")
                            assert media.stat().st_size > 1000
                            subprocess.run(
                                [
                                    str(copied / "runtime/ffmpeg/ffmpeg.exe"),
                                    "-v",
                                    "error",
                                    "-i",
                                    str(media),
                                    "-f",
                                    "null",
                                    "-",
                                ],
                                check=True,
                                capture_output=True,
                                timeout=10,
                            )
                    for handle in handles:
                        assert api.kernel.WaitForSingleObject(handle, 5000) == 0, "Owned child survived exit"
                    assert independent.poll() is None, "Unrelated FFmpeg was stopped"
                    print(f"PASS: {scenario}; UI loaded, duplicate rejected, owned children exited", flush=True)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)
                    for handle in handles:
                        api.kernel.CloseHandle(handle)
        finally:
            independent.kill()
            independent.wait(timeout=5)


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "dist/StreamCap")
