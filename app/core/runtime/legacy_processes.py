"""Inspect old, untracked Windows recordings without claiming ownership of them."""

import ctypes
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from windows_runtime import WindowsAPI


@dataclass(frozen=True)
class LegacyProcess:
    pid: int
    created: int
    executable: str
    output: str

    @property
    def started_at(self):
        return datetime.fromtimestamp(self.created / 10_000_000 - 11644473600).isoformat(sep=" ", timespec="seconds")


def split_windows_command_line(command):
    from ctypes import wintypes as wt

    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [wt.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(wt.LPWSTR)
    count = ctypes.c_int()
    result = shell.CommandLineToArgvW(command, ctypes.byref(count))
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return [result[index] for index in range(count.value)]
    finally:
        WindowsAPI().kernel.LocalFree(ctypes.cast(result, wt.HLOCAL))


def matching_output(arguments, roots):
    # StreamCap's FFmpeg builders put the output last (also for segmented recordings).
    if not arguments:
        return None
    output = Path(arguments[-1])
    if not output.is_absolute() or output.suffix.lower() not in {".ts", ".flv", ".mp4", ".mkv", ".mov", ".mp3", ".m4a"}:
        return None
    output = output.resolve()
    if any(output.is_relative_to(Path(root).resolve()) for root in roots):
        return str(output)
    return None


def find_legacy_processes(services):
    if os.name != "nt":
        return []
    api = WindowsAPI()
    sid = api.user_sid()
    roots = [services.settings_config.get_video_save_path()]
    for recording in services.recording_manager.recordings:
        if recording.recording_dir:
            roots.append(recording.recording_dir)
    command = (
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); "
        "@(Get-CimInstance Win32_Process -Filter \"Name = 'ffmpeg.exe'\" | "
        "Select-Object ProcessId,CommandLine,@{Name='OwnerSid';Expression={"
        "(Invoke-CimMethod -InputObject $_ -MethodName GetOwnerSid).Sid}}) | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        encoding="utf-8",
        check=True,
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    entries = json.loads(result.stdout or "[]")
    if isinstance(entries, dict):
        entries = [entries]
    found = []
    for entry in entries:
        if entry.get("OwnerSid") != sid or not entry.get("CommandLine"):
            continue
        output = matching_output(split_windows_command_line(entry["CommandLine"]), roots)
        if output is None:
            continue
        handle = api.kernel.OpenProcess(0x1000, False, entry["ProcessId"])
        if not handle:
            continue
        try:
            created, executable = api.process_identity(handle)
            if Path(executable).name.lower() == "ffmpeg.exe":
                found.append(LegacyProcess(entry["ProcessId"], created, executable, output))
        finally:
            api.kernel.CloseHandle(handle)
    return found


def terminate_legacy_process(candidate):
    api = WindowsAPI()
    handle = api.kernel.OpenProcess(0x1000 | 1 | 0x100000, False, candidate.pid)
    if not handle:
        if ctypes.get_last_error() == 87:  # Already exited.
            return
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        identity = api.process_identity(handle)
        if identity != (candidate.created, candidate.executable):
            raise RuntimeError("进程身份已变化，未结束任何任务 / Process identity changed")
        api.checked(api.kernel.TerminateProcess(handle, 1))
        if api.kernel.WaitForSingleObject(handle, 5000) != 0:
            raise RuntimeError("进程尚未退出 / Process has not exited")
    finally:
        api.kernel.CloseHandle(handle)
