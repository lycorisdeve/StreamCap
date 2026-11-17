import asyncio
import json
import logging
import os
import traceback
from collections.abc import Callable
from pathlib import Path

import flet as ft
from screeninfo import get_monitors

from app.app_manager import App, execute_dir
from app.auth.auth_manager import AuthManager
from app.core.runtime.backend_services import BackendServices
from app.core.runtime.bundled_env import patch_macos_flet_launcher, setup_bundled_flet_view
from app.core.runtime.paths import assets_dir, prepend_user_bin_dirs
from app.lifecycle.app_close_handler import handle_app_close
from app.lifecycle.tray_manager import TrayManager
from app.ui.components.common.save_progress_overlay import SaveProgressOverlay
from app.ui.layout.responsive_layout import is_mobile_device, setup_responsive_layout
from app.ui.views.login_view import LoginPage
from app.utils.logger import logger

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 6006
MACOS_WINDOW_SCALE = 0.56
WINDOWS_WINDOW_SCALE = 0.68
MIN_WIDTH = 950
MIN_HEIGHT = 620


class ClientDisconnectLogFilter(logging.Filter):
    """Hide noisy ASGI tracebacks produced by normal browser disconnects."""

    DISCONNECT_EXCEPTIONS = {"ClientDisconnected", "InvalidState", "WebSocketDisconnect"}

    def filter(self, record: logging.LogRecord) -> bool:
        if not record.exc_info:
            return True

        exc = record.exc_info[1]
        while exc is not None:
            if type(exc).__name__ in self.DISCONNECT_EXCEPTIONS:
                return False
            exc = exc.__context__ or exc.__cause__
        return True


def suppress_client_disconnect_logs() -> None:
    uvicorn_error_logger = logging.getLogger("uvicorn.error")
    if not any(isinstance(item, ClientDisconnectLogFilter) for item in uvicorn_error_logger.filters):
        uvicorn_error_logger.addFilter(ClientDisconnectLogFilter())


def get_desktop_window_scale(page: ft.Page) -> float:
    is_macos = page.platform is not None and page.platform.value == "macos"
    return MACOS_WINDOW_SCALE if is_macos else WINDOWS_WINDOW_SCALE


async def setup_desktop_window(page: ft.Page, app: App) -> None:
    if page.web:
        return

    page.window.icon = str(assets_dir / "icon.ico")
    page.window.skip_task_bar = False
    page.window.always_on_top = False
    page.focused = True

    try:
        window_scale = get_desktop_window_scale(page)
        page.window.min_width = MIN_WIDTH
        page.window.min_height = max(MIN_HEIGHT, MIN_WIDTH * window_scale)

        if app.settings.user_config.get("remember_window_size"):
            window_width = app.settings.user_config.get("window_width")
            window_height = app.settings.user_config.get("window_height")
            if window_width and window_height:
                page.window.width = int(window_width)
                page.window.height = int(window_height)
            else:
                screen = get_monitors()[0]
                page.window.width = int(screen.width * window_scale)
                page.window.height = int(screen.height * window_scale)
        else:
            screen = get_monitors()[0]
            page.window.width = int(screen.width * window_scale)
            page.window.height = int(screen.height * window_scale)

    except Exception as exc:
        logger.warning(f"Cannot restore screen dimensions; using defaults: {exc}")
        page.window.width = MIN_WIDTH
        page.window.height = MIN_HEIGHT
    finally:
        page.window.visible = True
        page.update()
    try:
        await page.window.center()
        await page.window.to_front()
    except Exception as exc:
        logger.warning(f"Cannot position window: {exc}")


def get_route_handler() -> dict[str, str]:
    return {
        "/": "home",
        "/home": "home",
        "/recordings": "recordings",
        "/settings": "settings",
        "/storage": "storage",
        "/logs": "logs",
        "/about": "about",
    }


def handle_route_change(page: ft.Page, app: App) -> Callable:
    route_map = get_route_handler()

    def route_change(e: ft.RouteChangeEvent) -> None:
        tr = ft.TemplateRoute(e.route)
        page_name = route_map.get(tr.route)
        if page_name:
            page.run_task(app.switch_page, page_name)

    return route_change


def handle_window_event(page: ft.Page, app: App, save_progress_overlay: "SaveProgressOverlay") -> Callable:
    async def on_window_event(e) -> None:
        if e.type == ft.WindowEventType.CLOSE:
            if app.settings.user_config.get("remember_window_size"):
                app.settings.user_config["window_width"] = page.window.width
                app.settings.user_config["window_height"] = page.window.height
                await app.config_manager.save_user_config(app.settings.user_config)
            await handle_app_close(page, app, save_progress_overlay)

    return on_window_event


def handle_disconnect(page: ft.Page, app: App) -> Callable:
    """Handle disconnection for web mode."""

    async def disconnect(_: ft.ControlEvent) -> None:
        page.pubsub.unsubscribe_all()
        app.settings.user_config["last_route"] = page.route
        await app.config_manager.save_user_config(app.settings.user_config)
        logger.info(f"Saved last route: {page.route}")

        if app.services is not None:
            app.services.unregister_ui_bridge(app)

    return disconnect


def handle_page_resize(page: ft.Page, app: App) -> Callable:
    """handle page resize"""

    def on_resize(_: ft.ControlEvent) -> None:
        if app.is_mobile == is_mobile_device(page):
            return
        setup_responsive_layout(page, app)
        page.controls[:] = [app.complete_page]
        page.update()

    return on_resize


async def _load_main(page: ft.Page) -> None:
    page.title = "StreamCap"

    _services = BackendServices.get()
    app = App(page, services=_services)
    page.data = app
    app.is_web_mode = page.web
    app.is_mobile = False
    await setup_desktop_window(page, app)

    if not page.web:
        try:
            app.tray_manager = TrayManager(app)
            logger.info("Tray manager initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize tray manager: {e}")

    theme_mode = app.settings.user_config.get("theme_mode", "light")
    if theme_mode == "dark":
        page.theme_mode = ft.ThemeMode.DARK
    else:
        page.theme_mode = ft.ThemeMode.LIGHT

    save_progress_overlay = SaveProgressOverlay(app)
    page.overlay.append(save_progress_overlay.overlay)

    async def load_app():
        if page.web:
            setup_responsive_layout(page, app)
            page.on_resize = handle_page_resize(page, app)
            page.on_disconnect = handle_disconnect(page, app)

        page.add(app.complete_page)

        page.window.prevent_close = True
        page.window.on_event = handle_window_event(page, app, save_progress_overlay)
        if page.web:
            rm = _services.recording_manager
            if rm is not None and not rm.is_periodic_task_running():
                logger.info("Starting periodic tasks for the first time in web mode (via session)")
                page.run_task(app.start_periodic_tasks)
            else:
                logger.info("Periodic tasks already running (BackendServices), skipping")
        else:
            logger.info("Starting periodic tasks in desktop mode")
            page.run_task(app.start_periodic_tasks)

            if page.platform and page.platform.value == "windows":
                if app.tray_manager is not None:
                    try:
                        app.tray_manager.start(page)
                    except Exception as err:
                        logger.error(f"Failed to start tray manager: {err}")

        page.update()

        if page.route in ["/", ""]:
            last_route = app.settings.user_config.get("last_route", "/home")
            logger.info(f"Restored last route: {last_route}")
            await page.push_route(last_route)

        await app.switch_page(page.route.lstrip("/") or "home")
        page.on_route_change = handle_route_change(page, app)
        if _services.startup_blocked:
            from app.ui.components.common.legacy_process_dialog import show_legacy_process_dialog

            show_legacy_process_dialog(app)

    if page.web:
        auth_manager = AuthManager(app)
        app.auth_manager = auth_manager
        await auth_manager.initialize()

        login_required = app.settings.get_config_value("login_required", False)

        if login_required:
            session_token = await ft.SharedPreferences().get("session_token")
            if not session_token or not auth_manager.validate_session(session_token):

                async def on_login_success(token):
                    _session_info = auth_manager.active_sessions.get(token, {})
                    app.current_username = _session_info.get("username")

                    page.controls.clear()
                    await load_app()

                page.controls.clear()

                login_page = LoginPage(page, auth_manager, on_login_success)
                page.add(login_page.get_view())
                return
            else:
                session_info = auth_manager.active_sessions.get(session_token, {})
                app.current_username = session_info.get("username")
        else:
            app.current_username = "admin"

    await load_app()
    if not page.web and _services.instance is not None:

        async def restore_window():
            page.window.minimized = False
            page.window.visible = True
            page.update()
            await page.window.to_front()

        _services.instance.watch(lambda: page.run_task(restore_window))
    if _services.smoke_test:

        async def smoke_finished():
            children = []
            for name in ("recording", "conversion"):
                process = await _services.process_manager.create_process(
                    "ffmpeg",
                    "-v",
                    "error",
                    "-re",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440",
                    "-c:a",
                    "pcm_s16le",
                    "-y",
                    str(Path(execute_dir, name + ".mkv")),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    startupinfo=_services.subprocess_start_up_info,
                )
                children.append(process.pid)
            Path(execute_dir, "desktop-ready.json").write_text(
                json.dumps({"ready": bool(app.content_area.controls), "route": page.route, "children": children}),
                encoding="utf-8",
            )
            for _ in range(600):
                if Path(execute_dir, "desktop-stop").exists():
                    break
                await asyncio.sleep(0.1)
            await _services.shutdown()
            await page.window.destroy()

        page.run_task(smoke_finished)


async def main(page: ft.Page) -> None:
    try:
        await _load_main(page)
    except Exception:
        logger.exception("Application initialization failed")
        services = BackendServices.get_or_none()
        if services is not None:
            await services.shutdown()
        if not page.web:
            if not (services and services.smoke_test):
                if os.name == "nt":
                    from windows_runtime import notify, runtime_directory

                    log = runtime_directory() / "startup-error.log"
                    log.parent.mkdir(parents=True, exist_ok=True)
                    log.write_text(traceback.format_exc(), encoding="utf-8")
                    notify(f"StreamCap 初始化失败，请查看日志。\n{log}", error=True)
            await page.window.destroy()
        raise


def run_flet_app(**kwargs) -> None:
    async def run():
        try:
            await ft.run_async(**kwargs)
        finally:
            services = BackendServices.get_or_none()
            if services is not None:
                await services.shutdown()

    asyncio.run(run())


def run_application(args, instance=None):
    prepend_user_bin_dirs()
    services = BackendServices.bootstrap(execute_dir)
    services.instance = instance
    services.smoke_test = args.smoke_test
    if not args.smoke_test:
        from app.core.runtime.legacy_processes import find_legacy_processes

        services.legacy_processes = find_legacy_processes(services)
        services.startup_blocked = bool(services.legacy_processes)
    if args.web:
        suppress_client_disconnect_logs()
        services.start_background_loop()
        run_flet_app(
            main=main,
            view=ft.AppView.WEB_BROWSER,
            host=args.host,
            port=args.port,
            assets_dir=str(assets_dir),
            web_renderer=ft.WebRenderer.CANVAS_KIT,
        )
    else:
        setup_bundled_flet_view()
        patch_macos_flet_launcher()
        run_flet_app(main=main, view=ft.AppView.FLET_APP_HIDDEN, assets_dir=str(assets_dir))
