import asyncio
import json
import random
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

from app.core.runtime.backend_services import BackendServices
from app.ui.components.common.appearance_settings import AppearanceSettings
from app.ui.themes import ThemeManager
from app.ui.themes.theme_tokens import (
    DEFAULT_COLOR,
    PRESET_COLORS,
    build_tokens,
    contrast_ratio,
    normalize_color,
    normalize_hex,
)


class TokenTests(unittest.TestCase):
    def test_palette_contrast_and_brand_identity(self):
        rng = random.Random(12)
        colors = [color for _, color in PRESET_COLORS] + ["#000000", "#FFFFFF", "#808080"]
        colors += [f"#{rng.randrange(0x1000000):06X}" for _ in range(100)]
        for color in colors:
            for dark in (False, True):
                with self.subTest(color=color, dark=dark):
                    t = build_tokens(color, dark)
                    assert t.primary == color
                    for background in (t.primary, t.primary_hover, t.primary_active):
                        assert contrast_ratio(t.primary_foreground, background) >= 4.5
                    for background in (
                        t.background,
                        t.surface,
                        t.primary_light,
                        t.selected_background,
                        t.navigation_active,
                    ):
                        assert contrast_ratio(t.interactive_accent, background) >= 4.5
                        assert contrast_ratio(t.focus_ring, background) >= 3
                        assert contrast_ratio(t.on_surface, background) >= 4.5
                    assert t.primary != t.primary_hover
                    assert t.primary_hover != t.primary_active

    def test_hex_and_legacy(self):
        assert normalize_hex(" abc ") == "#AABBCC"
        assert normalize_hex("#2389f5") == "#2389F5"
        assert normalize_color("blue") == "#2196F3"
        assert normalize_color("") == DEFAULT_COLOR
        for invalid in (None, "#", "#1234", "#AABBCCDD", "purple", "#GGGGGG"):
            try:
                normalize_hex(invalid)
            except ValueError:
                pass
            else:
                self.fail(f"Accepted invalid HEX: {invalid}")


class ThemeSessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        (root / "config").mkdir()
        shutil.copytree("locales", root / "locales")
        for name in ("default_settings.json", "language.json", "version.json"):
            shutil.copy(Path("config") / name, root / "config" / name)
        self.services = BackendServices(str(root))
        self.apps = []
        self.loop = asyncio.get_running_loop()

    def tearDown(self):
        for app in self.apps:
            app.theme_manager.dispose()
        self.directory.cleanup()

    def make_app(self):
        page = Mock(spec=ft.Page)
        page.platform_brightness = ft.Brightness.LIGHT
        app = SimpleNamespace(
            page=page,
            services=self.services,
            settings=SimpleNamespace(user_config=self.services.config_manager.load_user_config()),
            language_manager=SimpleNamespace(
                language=json.loads(Path("locales/zh_CN.json").read_text(encoding="utf-8"))
            ),
            snack_bar=SimpleNamespace(show_snack_bar=AsyncMock()),
        )
        app.theme_manager = ThemeManager(app)
        self.apps.append(app)
        return app

    async def test_two_sessions_preview_commit_cancel_and_old_messages(self):
        first, second = self.make_app(), self.make_app()
        one, two = first.theme_manager, second.theme_manager
        bridges = []

        class Bridge:
            def __init__(self, manager, loop):
                self.manager, self.loop = manager, loop

            def schedule_theme_update(self, config, revision):
                self.loop.call_soon_threadsafe(self.manager.receive_committed, config, revision)

        for manager in (one, two):
            bridge = Bridge(manager, self.loop)
            bridges.append(bridge)
            self.services.register_ui_bridge(bridge)
        original = Path(self.services.config_manager.user_config_path).read_bytes()
        one.preview(color="#EC599A")
        assert Path(self.services.config_manager.user_config_path).read_bytes() == original
        assert two.tokens.primary == DEFAULT_COLOR
        two.preview(color="#0EAFA0")
        await one.commit_preview()
        await asyncio.sleep(0)
        assert two.tokens.primary == "#0EAFA0"
        two.cancel_preview()
        assert two.tokens.primary == "#EC599A"
        two.receive_committed({"theme_color": "#303443", "theme_mode": "dark"}, 0)
        assert two.tokens.primary == "#EC599A"
        assert one.draft is None
        assert self.make_app().theme_manager.tokens.primary == "#EC599A"

    async def test_stale_saves_and_failed_commit(self):
        app = self.make_app()
        cm = self.services.config_manager
        old = cm.load_user_config()
        await self.services.commit_appearance({"theme_color": "#303443", "theme_mode": "dark"})
        old["loop_time_seconds"] = 321
        await cm.save_user_config(old)
        stored = cm.load_user_config()
        assert stored["theme_color"] == "#303443"
        assert stored["theme_mode"] == "dark"
        assert stored["loop_time_seconds"] == 321
        app.theme_manager.preview(color="#2389F5")
        before = self.services.snapshot_appearance()
        with patch.object(cm, "_write_json", side_effect=OSError("read only")):
            try:
                await app.theme_manager.commit_preview()
            except OSError:
                pass
            else:
                self.fail("Failed appearance write was reported as successful")
        assert self.services.snapshot_appearance() == before
        assert app.theme_manager.draft["theme_color"] == "#2389F5"
        assert cm.load_user_config() == stored

    async def test_concurrent_commits_keep_disk_and_revision_consistent(self):
        results = await asyncio.gather(
            *[self.services.commit_appearance({"theme_color": color}) for _, color in PRESET_COLORS]
        )
        saved, revision = max(results, key=lambda result: result[1])
        assert revision == 6
        assert self.services.snapshot_appearance() == (saved, revision)
        assert self.services.config_manager.load_user_config()["theme_color"] == saved["theme_color"]

    async def test_motion_preference_is_read_again_and_unavailable_service_disables_motion(self):
        manager = self.make_app().theme_manager
        read_features = AsyncMock(return_value=SimpleNamespace(disable_animations=False, reduce_motion=False))
        with patch.object(manager._semantics, "get_accessibility_features", read_features):
            assert await manager.motion_duration() == 200
            read_features.return_value.reduce_motion = True
            assert await manager.motion_duration() == 0
            read_features.return_value = SimpleNamespace(disable_animations=True, reduce_motion=False)
            assert await manager.motion_duration() == 0
            read_features.side_effect = RuntimeError("session disconnected")
            assert await manager.motion_duration() == 0

    async def test_system_mode_preview_ui_validation_and_defaults(self):
        app = self.make_app()
        manager = app.theme_manager
        panel = AppearanceSettings(app)
        manager.preview(mode="system")
        app.page.platform_brightness = ft.Brightness.DARK
        app.page.on_platform_brightness_change(None)
        assert manager.tokens.is_dark
        assert app.page.theme_mode == ft.ThemeMode.SYSTEM
        assert panel.mode.value == "system"
        panel.select_color("#2389F5")
        panel.hex_changed(SimpleNamespace(control=SimpleNamespace(value="#12")))
        assert panel.apply_button.disabled
        assert manager.tokens.primary == "#2389F5"
        panel.hex_changed(SimpleNamespace(control=SimpleNamespace(value="abc")))
        assert not panel.apply_button.disabled
        assert manager.tokens.primary == "#AABBCC"
        panel.hex_blurred(None)
        assert panel.hex_input.value == "#AABBCC"
        panel.restore_defaults(None)
        assert manager.draft == {"theme_color": DEFAULT_COLOR, "theme_mode": "light"}
        panel.cancel_changes(None)
        assert manager.draft is None
        panel.pick_color(SimpleNamespace(local_position=ft.Offset(132, 74)))
        panel.finish_pick(SimpleNamespace(local_position=ft.Offset(264, 0)))
        assert panel.saturation == 1
        assert panel.value == 1
        panel.dispose()
        assert manager._observers == []
