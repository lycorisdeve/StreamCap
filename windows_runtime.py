"""Windows ownership primitives. Safe to import before the application package."""

import ctypes
import json
import os
import threading
from ctypes import wintypes as wt
from pathlib import Path


class WindowsAPI:
    def __init__(self):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        signatures = {
            "CreateMutexW": ([wt.LPVOID, wt.BOOL, wt.LPCWSTR], wt.HANDLE),
            "ReleaseMutex": ([wt.HANDLE], wt.BOOL),
            "CreateEventW": ([wt.LPVOID, wt.BOOL, wt.BOOL, wt.LPCWSTR], wt.HANDLE),
            "SetEvent": ([wt.HANDLE], wt.BOOL),
            "WaitForSingleObject": ([wt.HANDLE, wt.DWORD], wt.DWORD),
            "CloseHandle": ([wt.HANDLE], wt.BOOL),
            "GetCurrentProcess": ([], wt.HANDLE),
            "CreateJobObjectW": ([wt.LPVOID, wt.LPCWSTR], wt.HANDLE),
            "SetInformationJobObject": ([wt.HANDLE, ctypes.c_int, wt.LPVOID, wt.DWORD], wt.BOOL),
            "AssignProcessToJobObject": ([wt.HANDLE, wt.HANDLE], wt.BOOL),
            "OpenProcess": ([wt.DWORD, wt.BOOL, wt.DWORD], wt.HANDLE),
            "GetProcessTimes": ([wt.HANDLE] + [ctypes.POINTER(wt.FILETIME)] * 4, wt.BOOL),
            "QueryFullProcessImageNameW": ([wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)], wt.BOOL),
            "TerminateProcess": ([wt.HANDLE, wt.UINT], wt.BOOL),
            "LocalFree": ([wt.HLOCAL], wt.HLOCAL),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.kernel, name)
            fn.argtypes, fn.restype = args, result
        self.advapi.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
        self.advapi.OpenProcessToken.restype = wt.BOOL
        self.advapi.GetTokenInformation.argtypes = [
            wt.HANDLE,
            ctypes.c_int,
            wt.LPVOID,
            wt.DWORD,
            ctypes.POINTER(wt.DWORD),
        ]
        self.advapi.GetTokenInformation.restype = wt.BOOL
        self.advapi.ConvertSidToStringSidW.argtypes = [wt.LPVOID, ctypes.POINTER(wt.LPWSTR)]
        self.advapi.ConvertSidToStringSidW.restype = wt.BOOL

    @staticmethod
    def checked(result):
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())
        return result

    def user_sid(self):
        token = wt.HANDLE()
        self.checked(self.advapi.OpenProcessToken(self.kernel.GetCurrentProcess(), 8, ctypes.byref(token)))
        try:
            size = wt.DWORD()
            self.advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            data = ctypes.create_string_buffer(size.value)
            self.checked(self.advapi.GetTokenInformation(token, 1, data, size, ctypes.byref(size)))
            sid = ctypes.cast(data, ctypes.POINTER(wt.LPVOID))[0]
            string = wt.LPWSTR()
            self.checked(self.advapi.ConvertSidToStringSidW(sid, ctypes.byref(string)))
            try:
                return string.value
            finally:
                self.kernel.LocalFree(ctypes.cast(string, wt.HLOCAL))
        finally:
            self.kernel.CloseHandle(token)

    def process_identity(self, handle):
        times = [wt.FILETIME() for _ in range(4)]
        self.checked(self.kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)))
        size = wt.DWORD(32768)
        image = ctypes.create_unicode_buffer(size.value)
        self.checked(self.kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)))
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime, image.value


class JobBasicLimits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_int64),
        ("job_time", ctypes.c_int64),
        ("flags", wt.DWORD),
        ("min_working_set", ctypes.c_size_t),
        ("max_working_set", ctypes.c_size_t),
        ("active_processes", wt.DWORD),
        ("affinity", ctypes.c_size_t),
        ("priority", wt.DWORD),
        ("scheduling", wt.DWORD),
    ]


class JobExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", JobBasicLimits),
        ("io_counters", ctypes.c_uint64 * 6),
        ("process_memory", ctypes.c_size_t),
        ("job_memory", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t),
        ("peak_job_memory", ctypes.c_size_t),
    ]


class ProcessJob:
    """Own this process tree until OS exit; deliberately never inherit the handle."""

    def __init__(self):
        self.api = WindowsAPI()
        self.handle = self.api.checked(self.api.kernel.CreateJobObjectW(None, None))
        limits = JobExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try:
            self.api.checked(
                self.api.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits))
            )
            self.api.checked(self.api.kernel.AssignProcessToJobObject(self.handle, self.api.kernel.GetCurrentProcess()))
        except BaseException:
            self.api.kernel.CloseHandle(self.handle)
            raise
        # Closing this handle also kills this process. The OS closes it at exit.


def runtime_directory():
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "StreamCap/runtime"


def notify(message, error=False):
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.MessageBoxW.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.UINT]
    user.MessageBoxW(None, message, "StreamCap", 0x10 if error else 0x40)


class SingleInstance:
    def __init__(self, namespace="StreamCap", directory=None):
        self.api = WindowsAPI()
        name = f"Global\\{namespace}.{self.api.user_sid()}"
        self.mutex = self.api.checked(self.api.kernel.CreateMutexW(None, False, name))
        self.event = self.api.checked(self.api.kernel.CreateEventW(None, False, False, name + ".activate"))
        state = self.api.kernel.WaitForSingleObject(self.mutex, 250)
        if state not in (0, 0x80, 258):
            raise ctypes.WinError(ctypes.get_last_error())
        self.acquired = state in (0, 0x80)
        self.directory = Path(directory) if directory is not None else runtime_directory()
        self.metadata = self.directory / "instance.json"
        self.stop = threading.Event()
        self.thread = None

    def publish(self, mode, address=None):
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.metadata.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps({"pid": os.getpid(), "mode": mode, "address": address}), encoding="utf-8")
        os.replace(temporary, self.metadata)

    def activate_existing(self):
        self.api.checked(self.api.kernel.SetEvent(self.event))
        try:
            info = json.loads(self.metadata.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info = {}
        if info.get("mode") == "web":
            notify(f"StreamCap Web 已在运行 / already running:\n{info.get('address', '')}")

    def watch(self, callback):
        if self.thread is not None:
            return

        def listen():
            while not self.stop.is_set():
                if self.api.kernel.WaitForSingleObject(self.event, 250) == 0 and not self.stop.is_set():
                    callback()

        self.thread = threading.Thread(target=listen, name="InstanceActivation", daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=1)
        if self.acquired:
            try:
                self.metadata.unlink(missing_ok=True)
            except OSError:
                pass
            finally:
                self.api.kernel.ReleaseMutex(self.mutex)
        self.api.kernel.CloseHandle(self.event)
        self.api.kernel.CloseHandle(self.mutex)
