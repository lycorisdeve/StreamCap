import flet as ft

from ...app_manager import App
from ...utils.logger import logger


def is_mobile_device(page: ft.Page) -> bool:
    return page.width < 768


def setup_responsive_layout(page: ft.Page, app: App) -> None:
    _ = app.language_manager.language.get("sidebar", {})
    content = getattr(app, "content_surface", app.content_area)

    if is_mobile_device(page):
        logger.info("mobile device detected, enable mobile layout")
        app.is_mobile = True
        app.left_navigation_menu.visible = False

        routes = ["home", "recordings", "settings", "storage", "logs", "about"]
        current_route = page.route.lstrip("/")
        app.bottom_navigation = ft.NavigationBar(
            selected_index=routes.index(current_route) if current_route in routes else 0,
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.HOME, label=_["home"]),
                ft.NavigationBarDestination(icon=ft.Icons.DASHBOARD_ROUNDED, label=_["recordings"]),
                ft.NavigationBarDestination(icon=ft.Icons.SETTINGS, label=_["settings"]),
                ft.NavigationBarDestination(icon=ft.Icons.DRIVE_FILE_MOVE, label=_["storage"]),
                ft.NavigationBarDestination(icon=ft.Icons.HISTORY, label=_["logs"]),
                ft.NavigationBarDestination(icon=ft.Icons.INFO, label=_["about"]),
            ],
            on_change=lambda e: page.run_task(
                page.push_route,
                f"/{routes[e.control.selected_index]}",
            ),
        )

        app.content_area.expand = True

        app.complete_page = ft.Column(
            expand=True,
            spacing=0,
            controls=[content, app.bottom_navigation, app.dialog_area, app.snack_bar_area],
        )
    else:
        logger.info("desktop device detected, enable desktop layout")
        app.is_mobile = False
        app.left_navigation_menu.visible = True
        app.complete_page = ft.Row(
            expand=True,
            controls=[
                app.left_navigation_menu,
                ft.VerticalDivider(width=1),
                content,
                app.dialog_area,
                app.snack_bar_area,
            ],
        )
