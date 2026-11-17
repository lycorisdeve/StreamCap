import flet as ft

from .tray_manager import TrayManager


async def handle_app_close(page: ft.Page, app, save_progress_overlay) -> None:
    _ = {}
    language = app.language_manager.language
    for key in ("app_close_handler", "base"):
        _.update(language.get(key, {}))

    if not getattr(app, "is_web_mode", False) and not hasattr(app, "tray_manager"):
        app.tray_manager = TrayManager(app)

    async def minimize_to_tray(e):
        page.window.visible = False
        page.update()
        await close_dialog(e)

    async def close_dialog_dismissed(e):
        if app.services.closing:
            return
        app.services.closing = True
        app.settings.user_config["last_route"] = page.route
        await app.config_manager.save_user_config(app.settings.user_config)
        await close_dialog(e)
        active = sum(p.returncode is None for p in app.process_manager.ffmpeg_processes)
        if active:
            save_progress_overlay.show(_["saving_recordings"].format(active_recordings_count=active), cancellable=False)
            page.update()
        try:
            await app.cleanup()
            await app.services.shutdown()
        finally:
            await page.window.destroy()

    async def close_dialog(_):
        close_confirm_dialog.open = False
        page.update()

    close_confirm_controls = [
        ft.Text(
            _["confirm_exit_content"],
            size=14,
            text_align=ft.TextAlign.CENTER,
        ),
        ft.Container(height=10),
    ]

    if page.platform.value != "macos":
        close_confirm_controls.append(
            ft.Container(
                content=ft.Text(
                    _["minimize_to_tray_tip"],
                    size=12,
                    color=ft.Colors.GREY_500,
                    text_align=ft.TextAlign.CENTER,
                ),
                padding=ft.Padding.all(8),
                border_radius=5,
                bgcolor=ft.Colors.with_opacity(0.1, ft.Colors.BLUE_GREY),
            )
        )

    close_confirm_actions = [
        ft.TextButton(
            content=ft.Text(_["cancel"], size=14),
            on_click=close_dialog,
            style=ft.ButtonStyle(
                color=ft.Colors.PRIMARY,
            ),
        ),
        ft.OutlinedButton(
            content=ft.Text(_["exit_program"], size=14),
            on_click=close_dialog_dismissed,
            style=ft.ButtonStyle(
                color=ft.Colors.ERROR,
            ),
        ),
    ]
    if page.platform.value != "macos":
        close_confirm_actions.insert(
            1,
            ft.TextButton(
                content=ft.Text(_["minimize_to_tray"], size=14),
                on_click=minimize_to_tray,
                style=ft.ButtonStyle(
                    color=ft.Colors.PRIMARY,
                ),
            ),
        )

    close_confirm_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(
            _["confirm_exit"],
            size=18,
            weight=ft.FontWeight.BOLD,
            text_align=ft.TextAlign.CENTER,
        ),
        content=ft.Container(
            content=ft.Column(
                controls=close_confirm_controls,
                spacing=5,
                tight=True,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=20, vertical=10),
            width=400 if page.platform.value != "macos" else None,
        ),
        actions=close_confirm_actions,
        actions_alignment=ft.MainAxisAlignment.END,
        shape=ft.RoundedRectangleBorder(radius=10),
    )

    close_confirm_dialog.open = True
    app.dialog_area.content = close_confirm_dialog
    app.close_confirm_dialog = close_confirm_dialog
    page.update()
