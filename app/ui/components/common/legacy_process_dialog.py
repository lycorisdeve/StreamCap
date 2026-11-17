import asyncio

import flet as ft

from ....core.runtime.legacy_processes import terminate_legacy_process


def show_legacy_process_dialog(app):
    services = app.services
    english = app.language_code == "en"
    message = ft.Text(
        "Possible recordings left by an older version. Recording is paused until reviewed. "
        "Stopping a task may leave an incomplete file. Files will be kept."
        if english
        else "发现可能由旧版遗留的录制任务，确认前已暂停录制。结束任务可能导致文件不完整，已有文件会保留。"
    )
    rows = []
    for candidate in services.legacy_processes:
        checkbox = ft.Checkbox(label=f"PID {candidate.pid} · {candidate.started_at}\n{candidate.output}", value=False)
        rows.append((candidate, checkbox))
    error = ft.Text(color=ft.Colors.ERROR)

    def finish():
        if not services.legacy_processes:
            services.startup_blocked = False
            dialog.open = False
        app.page.update()

    async def stop_selected(_):
        stop_button.disabled = True
        error.value = ""
        app.page.update()
        try:
            for candidate, checkbox in rows:
                if checkbox.value and candidate in services.legacy_processes:
                    await asyncio.to_thread(terminate_legacy_process, candidate)
                    if candidate in services.legacy_processes:
                        services.legacy_processes.remove(candidate)
                    checkbox.disabled = True
        except Exception as exc:
            error.value = str(exc)
        finally:
            stop_button.disabled = False
            finish()

    def unrelated(_):
        services.legacy_processes.clear()
        finish()

    stop_button = ft.TextButton("Stop selected tasks" if english else "确认结束选中任务", on_click=stop_selected)
    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Review existing FFmpeg tasks" if english else "确认旧版残留任务"),
        content=ft.Column(
            [message, *(checkbox for _, checkbox in rows), error], tight=True, scroll=ft.ScrollMode.AUTO, width=560
        ),
        actions=[
            stop_button,
            ft.TextButton("None belong to this app" if english else "确认全部与本应用无关", on_click=unrelated),
        ],
    )
    app.dialog_area.content = dialog
    dialog.open = True
    app.page.update()
