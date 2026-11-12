import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft
import httpx

import main
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

                    async def cancel_background_tasks():
                        tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
                        for task in tasks:
                            task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)

                    cancelled = asyncio.run_coroutine_threadsafe(cancel_background_tasks(), services.backend_loop)
                    await asyncio.wrap_future(cancelled)
                    services.stop_background_loop()
                    await asyncio.to_thread(services._backend_thread.join, 5)
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

    async def test_flet_launch_entrypoints_without_native_window(self):
        with patch.object(main.ft, "run") as runner:
            main.run_flet_app(main=main.main, view=ft.AppView.FLET_APP_HIDDEN, assets_dir="assets")
            assert runner.call_args.kwargs["view"] == ft.AppView.FLET_APP_HIDDEN
            main.run_flet_app(main=main.main, view=ft.AppView.WEB_BROWSER, host="127.0.0.1", port=6006)
            assert runner.call_args.kwargs["port"] == 6006
