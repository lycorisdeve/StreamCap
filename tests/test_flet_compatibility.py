import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

import main
from app.ui.layout.responsive_layout import setup_responsive_layout
from app.ui.navigation.sidebar import ControlGroup, NavigationColumn
from app.ui.views.home_view import HomePage
from app.ui.views.login_view import LoginPage


class FletCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_sidebar_navigation_awaits_current_page_api(self):
        page = Mock(spec=ft.Page)
        page.push_route = AsyncMock()
        sidebar = SimpleNamespace(
            control_groups=[
                ControlGroup(ft.Icons.HOME, "Home", 0, "home", ft.Icons.HOME),
                ControlGroup(ft.Icons.SETTINGS, "Settings", 1, "settings", ft.Icons.SETTINGS),
            ]
        )
        column = NavigationColumn(sidebar, page, SimpleNamespace())
        await column.item_clicked(SimpleNamespace(control=column.navigation_items[1]))
        page.push_route.assert_awaited_once_with("/settings")
        assert column.selected_index == 1

    async def test_home_renders_in_light_and_dark_web_layouts(self):
        language = json.loads(Path("locales/zh_CN.json").read_text(encoding="utf-8"))
        page = Mock(spec=ft.Page)
        app = SimpleNamespace(
            page=page,
            content_area=SimpleNamespace(controls=[], update=Mock()),
            language_manager=SimpleNamespace(language=language, add_observer=Mock()),
            record_manager=SimpleNamespace(recordings=[]),
            about=SimpleNamespace(about_config=json.loads(Path("config/version.json").read_text(encoding="utf-8"))),
            language_code="zh_CN",
            is_mobile=False,
        )
        home = HomePage(app)
        for theme in (ft.ThemeMode.LIGHT, ft.ThemeMode.DARK):
            for mobile in (False, True):
                with self.subTest(theme=theme, mobile=mobile):
                    page.theme_mode = theme
                    app.is_mobile = mobile
                    page.width = 390 if mobile else 1280
                    await home.load()
                    assert len(app.content_area.controls) == 1

    async def test_start_recording_navigates_before_opening_dialog(self):
        calls = []
        page = Mock(spec=ft.Page)

        async def navigate(route):
            calls.append(route)

        async def open_dialog(event):
            calls.append("dialog")

        page.push_route = AsyncMock(side_effect=navigate)
        home = HomePage.__new__(HomePage)
        home.app = SimpleNamespace(
            page=page, recordings=SimpleNamespace(add_recording_on_click=AsyncMock(side_effect=open_dialog))
        )
        await home.on_start_recording_click(None)
        assert calls == ["/recordings", "dialog"]

    async def test_login_saves_session_with_shared_preferences_service(self):
        login = LoginPage.__new__(LoginPage)
        login.page = Mock(spec=ft.Page)
        login.username_field = SimpleNamespace(value="test-user")
        login.password_field = SimpleNamespace(value="test-password")
        login.login_button = SimpleNamespace(content="Login", disabled=False)
        login._ = {"login_in_progress": "Signing in"}
        login.auth_manager = SimpleNamespace(authenticate=AsyncMock(return_value=(True, "test-token")))
        login.on_login_success = AsyncMock()
        preferences = SimpleNamespace(set=AsyncMock())
        with patch("app.ui.views.login_view.ft.SharedPreferences", return_value=preferences):
            await login.handle_login(None)
        preferences.set.assert_awaited_once_with("session_token", "test-token")
        login.on_login_success.assert_awaited_once_with("test-token")
        assert not login.login_button.disabled

    async def test_web_resize_replaces_root_and_restores_sidebar(self):
        page = Mock(spec=ft.Page)
        page.width = 1280
        page.route = "/settings"
        language = json.loads(Path("locales/zh_CN.json").read_text(encoding="utf-8"))
        content = ft.Column([ft.Text("existing content")])
        app = SimpleNamespace(
            language_manager=SimpleNamespace(language=language),
            left_navigation_menu=ft.Column(width=192),
            content_area=content,
            dialog_area=ft.Container(),
            snack_bar_area=ft.Container(),
        )
        setup_responsive_layout(page, app)
        page.controls = [app.complete_page]
        resize = main.handle_page_resize(page, app)
        page.width = 390
        resize(None)
        assert page.controls[0] is app.complete_page
        assert isinstance(page.controls[0], ft.Column)
        assert app.complete_page.controls[0] is content
        assert not app.left_navigation_menu.visible
        assert app.bottom_navigation.selected_index == 2
        app.bottom_navigation.on_change(SimpleNamespace(control=SimpleNamespace(selected_index=3)))
        page.run_task.assert_called_once_with(page.push_route, "/storage")
        page.width = 1280
        resize(None)
        assert isinstance(page.controls[0], ft.Row)
        assert app.left_navigation_menu.visible
        assert app.left_navigation_menu.width == 192
        assert app.complete_page.controls[2] is content
