import asyncio
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft
import httpx

import application as main
from app.core.recording.record_manager import GlobalRecordingState
from app.core.runtime.backend_services import BackendServices


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_backend_bootstrap_and_web_loop_with_empty_temp_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            for name in ("default_settings.json", "version.json", "language.json"):
                shutil.copy2(Path("config") / name, root / "config" / name)
            shutil.copytree("locales", root / "locales")
            with patch.object(BackendServices, "_instance", None), patch.object(GlobalRecordingState, "recordings", []):
                services = BackendServices.bootstrap(directory)
                assert services.recording_manager.recordings == []
                assert "recording_manager" in services.language_manager.language
                services.start_background_loop()
                try:
                    ready = asyncio.run_coroutine_threadsafe(asyncio.sleep(0), services.backend_loop)
                    await asyncio.wrap_future(ready)
                    assert services.backend_loop.is_running()
                finally:
                    await services.shutdown()
                    await services.shutdown()
                assert not services._backend_thread.is_alive()

    async def test_desktop_and_web_window_setup(self):
        web = SimpleNamespace(web=True)
        await main.setup_desktop_window(web, SimpleNamespace())
        for platform in ("windows", "macos"):
            page = SimpleNamespace(
                web=False,
                platform=SimpleNamespace(value=platform),
                window=SimpleNamespace(center=AsyncMock(), to_front=AsyncMock()),
                update=Mock(),
            )
            app = SimpleNamespace(settings=SimpleNamespace(user_config={}))
            with patch.object(main, "get_monitors", return_value=[SimpleNamespace(width=1920, height=1080)]):
                await main.setup_desktop_window(page, app)
            assert page.window.min_width == main.MIN_WIDTH
            assert page.window.width >= page.window.min_width

    async def test_web_app_serves_index_and_assets(self):
        web_app = ft.run(main=main.main, export_asgi_app=True, assets_dir=str(Path("assets").resolve()))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web_app), base_url="http://test") as client:
            response = await client.get("/")
            assert response.status_code == 200
            assert "flutter" in response.text.lower()
            logo = await client.get("/images/logo-mark.svg")
            assert logo.status_code == 200
            assert "<svg" in logo.text

    async def test_monitor_failure_still_reveals_desktop_window(self):
        page = SimpleNamespace(
            web=False,
            platform=SimpleNamespace(value="windows"),
            window=SimpleNamespace(center=AsyncMock(), to_front=AsyncMock()),
            update=Mock(),
        )
        with patch.object(main, "get_monitors", side_effect=RuntimeError("No display metadata")):
            await main.setup_desktop_window(page, SimpleNamespace(settings=SimpleNamespace(user_config={})))
        assert page.window.visible
        assert page.window.width == main.MIN_WIDTH
        page.update.assert_called()

    async def test_flet_launch_entrypoints_without_native_window(self):
        with patch.object(main.ft, "run_async", new_callable=AsyncMock) as runner:
            await asyncio.to_thread(
                main.run_flet_app, main=main.main, view=ft.AppView.FLET_APP_HIDDEN, assets_dir="assets"
            )
            assert runner.call_args.kwargs["view"] == ft.AppView.FLET_APP_HIDDEN
            await asyncio.to_thread(
                main.run_flet_app, main=main.main, view=ft.AppView.WEB_BROWSER, host="127.0.0.1", port=6006
            )
            assert runner.call_args.kwargs["port"] == 6006


class WebProcessTests(unittest.TestCase):
    def test_cli_web_server_starts_and_serves_http(self):
        """Exercise the same Flet/FastAPI/Uvicorn startup path as CI."""
        source_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "assets").mkdir()
            for name in ("default_settings.json", "version.json", "language.json"):
                shutil.copy2(source_root / "config" / name, root / "config" / name)
            shutil.copytree(source_root / "locales", root / "locales")
            launcher = root / "main.py"
            launcher.write_text(
                "import sys\n"
                f"sys.path.insert(0, {str(source_root)!r})\n"
                "from pathlib import Path\n"
                f"exec(compile(Path({str(source_root / 'main.py')!r}).read_text(encoding='utf-8'), "
                f"{str(source_root / 'main.py')!r}, 'exec'))\n",
                encoding="utf-8",
            )
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            env = {**os.environ, "FLET_FORCE_WEB_SERVER": "true", "PLATFORM": "web"}
            for name in ("FLET_SERVER_PORT", "FLET_SERVER_IP", "FLET_SERVER_UDS_PATH"):
                env.pop(name, None)
            with (root / "server.log").open("w+", encoding="utf-8") as output:
                process = subprocess.Popen(
                    [sys.executable, str(launcher), "--web", "--host", "127.0.0.1", "--port", str(port)],
                    cwd=root,
                    env=env,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                )
                try:
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline and process.poll() is None:
                        try:
                            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as response:
                                assert response.status == 200
                                assert b"flutter" in response.read().lower()
                                return
                        except (urllib.error.URLError, TimeoutError):
                            time.sleep(0.2)
                    output.seek(0)
                    raise AssertionError(f"Web server failed to start:\n{output.read()}")
                finally:
                    if process.poll() is None:
                        if sys.platform == "win32":
                            subprocess.run(
                                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                check=True,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE,
                            )
                        else:
                            process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
