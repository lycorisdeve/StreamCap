import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.core.recording.stream_manager import LiveStreamRecorder
from app.core.runtime.backend_services import BackendServices
from app.core.runtime.legacy_processes import LegacyProcess, matching_output, terminate_legacy_process
from app.core.runtime.process_manager import AsyncProcessManager

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = shutil.which("ffmpeg")


class ProcessCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_interrupted_conversion_keeps_original_even_if_ffmpeg_returns_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "recording.ts"
            source.write_bytes(b"original recording")
            recorder = LiveStreamRecorder.__new__(LiveStreamRecorder)
            recorder.subprocess_start_info = None
            recorder.services = SimpleNamespace(
                closing=True,
                process_manager=SimpleNamespace(
                    create_process=AsyncMock(
                        return_value=SimpleNamespace(
                            returncode=0,
                            communicate=AsyncMock(return_value=(b"", b"")),
                        )
                    ),
                ),
            )
            await recorder._do_converts_mp4(str(source), is_original_delete=True)
            assert source.read_bytes() == b"original recording"

    async def test_shutdown_waits_for_inflight_spawn_and_rejects_new_work(self):
        manager = AsyncProcessManager()
        spawned = asyncio.Event()
        release = asyncio.Event()
        process = SimpleNamespace(returncode=None, stdin=None, terminate=Mock(), wait=AsyncMock(), kill=Mock())

        async def spawn(*args, **kwargs):
            spawned.set()
            await release.wait()
            return process

        with patch("asyncio.create_subprocess_exec", side_effect=spawn):
            starting = asyncio.create_task(manager.create_process("fake"))
            await spawned.wait()
            closing = asyncio.create_task(manager.cleanup())
            await asyncio.sleep(0)
            with self.assertRaises(RuntimeError):  # noqa: PT027 - standard-library unittest suite
                await manager.create_process("late")
            starting.cancel()
            release.set()
            await asyncio.gather(starting, return_exceptions=True)
            await closing
        process.terminate.assert_called_once()
        assert manager.ffmpeg_processes == []
        await manager.cleanup()
        process.terminate.assert_called_once()

    async def test_unresponsive_process_is_killed(self):
        manager = AsyncProcessManager()
        waits = 0

        async def wait():
            nonlocal waits
            waits += 1
            if waits == 1:
                await asyncio.sleep(60)

        process = SimpleNamespace(returncode=None, stdin=None, terminate=Mock(), wait=wait, kill=Mock())
        manager.add_process(process)
        await manager.cleanup(timeout=0.02)
        process.kill.assert_called_once()

    @unittest.skipUnless(FFMPEG, "FFmpeg is required for media integration test")
    async def test_graceful_quit_finalizes_recording(self):
        manager = AsyncProcessManager()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "recording.mkv"
            process = await manager.create_process(
                FFMPEG,
                "-hide_banner",
                "-loglevel",
                "error",
                "-re",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440",
                "-c:a",
                "pcm_s16le",
                str(output),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.sleep(1)
            await asyncio.wait_for(manager.cleanup(), 5)
            assert process.returncode == 0
            assert output.stat().st_size > 1000
            result = await asyncio.to_thread(
                subprocess.run,
                [FFMPEG, "-v", "error", "-i", str(output), "-f", "null", "-"],
                capture_output=True,
                timeout=10,
            )
            assert result.returncode == 0, result.stderr


class StartupGateTests(unittest.TestCase):
    def test_disk_space_cannot_reenable_shutdown_or_pending_review(self):
        services = BackendServices.__new__(BackendServices)
        services.closing = False
        services.startup_blocked = False
        services.smoke_test = False
        services.recording_enabled = True
        assert services.recording_enabled
        for flag in ("closing", "startup_blocked", "smoke_test"):
            setattr(services, flag, True)
            services.recording_enabled = True
            assert not services.recording_enabled
            setattr(services, flag, False)

    def test_only_outputs_inside_recording_directories_are_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "recordings/room/test_%03d.ts"
            assert matching_output(["ffmpeg", "-i", "https://secret", str(target)], [root / "recordings"])
            assert matching_output(["ffmpeg", str(root / "recordings-other/other.mp4")], [root / "recordings"]) is None
            assert matching_output(["ffmpeg", "https://secret/test.ts"], [root]) is None
            assert matching_output(["ffmpeg", "-"], [root]) is None

    def test_legacy_pid_reuse_never_terminates_replacement(self):
        api = Mock()
        api.kernel.OpenProcess.return_value = 123
        api.process_identity.return_value = (200, "ffmpeg.exe")
        with patch("app.core.runtime.legacy_processes.WindowsAPI", return_value=api):
            with self.assertRaisesRegex(RuntimeError, "identity changed"):  # noqa: PT027 - unittest suite
                terminate_legacy_process(LegacyProcess(10, 100, "ffmpeg.exe", "file.ts"))
        api.kernel.TerminateProcess.assert_not_called()
        api.kernel.CloseHandle.assert_called_once_with(123)


@unittest.skipUnless(os.name == "nt", "Windows kernel ownership")
class WindowsOwnershipTests(unittest.TestCase):
    def wait_for_file(self, path, process):
        deadline = time.monotonic() + 15
        while not path.exists() and time.monotonic() < deadline and process.poll() is None:
            time.sleep(0.05)
        assert path.exists(), f"Helper failed: {process.poll()}"

    def test_second_instance_signals_owner_and_crash_releases_mutex(self):
        from windows_runtime import SingleInstance

        with tempfile.TemporaryDirectory() as directory:
            namespace = "StreamCapTest." + uuid.uuid4().hex
            ready, activated = Path(directory) / "ready", Path(directory) / "activated"
            code = (
                "from windows_runtime import SingleInstance; from pathlib import Path; import time; "
                f"owner=SingleInstance({namespace!r},{directory!r}); assert owner.acquired; "
                f"owner.watch(lambda: Path({str(activated)!r}).touch()); Path({str(ready)!r}).touch(); time.sleep(60)"
            )
            process = subprocess.Popen([sys.executable, "-c", code], cwd=ROOT)
            try:
                self.wait_for_file(ready, process)
                second = SingleInstance(namespace, directory)
                try:
                    assert not second.acquired
                    second.activate_existing()
                    self.wait_for_file(activated, process)
                finally:
                    second.close()
            finally:
                process.kill()
                process.wait(timeout=5)
            replacement = SingleInstance(namespace, directory)
            try:
                assert replacement.acquired
            finally:
                replacement.close()

    @unittest.skipUnless(FFMPEG, "FFmpeg integration test")
    def test_backend_crash_kills_owned_ffmpeg_but_not_independent_process(self):
        from windows_runtime import WindowsAPI

        command = [FFMPEG, "-v", "error", "-re", "-f", "lavfi", "-i", "sine", "-f", "null", "-"]
        independent = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        try:
            with tempfile.TemporaryDirectory() as directory:
                ready = Path(directory) / "children.json"
                code = (
                    "from windows_runtime import ProcessJob; import subprocess,time,json; from pathlib import Path; "
                    "job=ProcessJob(); "
                    f"children=[subprocess.Popen({command!r},stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,"
                    "stderr=subprocess.DEVNULL) for _ in range(2)]; "
                    f"Path({str(ready)!r}).write_text(json.dumps([p.pid for p in children])); time.sleep(60)"
                )
                parent = subprocess.Popen([sys.executable, "-c", code], cwd=ROOT)
                handles = []
                api = WindowsAPI()
                try:
                    self.wait_for_file(ready, parent)
                    for pid in json.loads(ready.read_text()):
                        handles.append(api.checked(api.kernel.OpenProcess(0x100000, False, pid)))
                    parent.kill()
                    parent.wait(timeout=5)
                    for handle in handles:
                        assert api.kernel.WaitForSingleObject(handle, 5000) == 0
                    assert independent.poll() is None
                finally:
                    if parent.poll() is None:
                        parent.kill()
                    parent.wait(timeout=5)
                    for handle in handles:
                        api.kernel.CloseHandle(handle)
        finally:
            independent.kill()
            independent.wait(timeout=5)
