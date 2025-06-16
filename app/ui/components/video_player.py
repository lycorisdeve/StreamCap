import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import flet as ft

from ...utils import utils
from ...utils.logger import logger


class VideoPlayer:
    def __init__(self, app):
        self.app = app
        self._ = {}
        self.load_language()

    def load_language(self):
        language = self.app.language_manager.language
        for key in ("video_player", "storage_page", "base"):
            self._.update(language.get(key, {}))

    async def create_video_dialog(
            self, title: str,
            video_source: str,
            is_file_path: bool = True,
            room_url: str | None = None
    ):
        """
        Create video playback dialog
        :param title: Dialog title
        :param video_source: Video source (file path or URL)
        :param is_file_path: Whether in file path mode
        :param room_url: Live room URL
        """

        def close_dialog(_):
            dialog.open = False
            self.app.dialog_area.update()

        video = ft.Video(
            width=800,
            height=450,
            playlist=[ft.VideoMedia(video_source)],
            autoplay=True
        )

        async def copy_source(_):
            self.app.page.set_clipboard(video_source)
            await self.app.snack_bar.show_snack_bar(self._["copy_success"])

        async def open_in_browser(_):
            self.app.page.launch_url(room_url)

        actions = [
            ft.TextButton(self._["close"], on_click=close_dialog)
        ]

        if room_url:
            actions.insert(0, ft.TextButton(self._["open_live_room_page"], on_click=open_in_browser))
        if not is_file_path:
            if self._["stream_source"] in title:
                actions.insert(0, ft.TextButton(self._["copy_stream_url"], on_click=copy_source))
            else:
                actions.insert(0, ft.TextButton(self._["copy_video_url"], on_click=copy_source))

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title),
            content=video,
            actions=actions,
            actions_alignment=ft.MainAxisAlignment.END
        )
        dialog.open = True
        self.app.dialog_area.content = dialog
        self.app.dialog_area.update()

    async def preview_video(self, source: str, is_file_path: bool = True, room_url: str | None = None):
        """
        Preview video
        :param source: Video source (file path or URL)
        :param is_file_path: Whether in file path mode
        :param room_url: Live room URL
        """
        if is_file_path:
            if not utils.is_valid_video_file(source):
                logger.warning(f"unsupported file type: {Path(source).suffix.lower()}")
                await self.app.snack_bar.show_snack_bar(
                    self._["unsupported_file_type"] + ":" + os.path.basename(source))
                return
            title = os.path.basename(source)
        else:
            parsed = urlparse(source)
            params = parse_qs(parsed.query)
            filename = params.get('filename', [''])[0]
            sub_folder = params.get('subfolder', [''])[0]
            if filename:
                title = self._["previewing"] + ": " + (f"{sub_folder}/{filename}" if sub_folder else filename)
                if Path(filename).suffix.lower() != ".mp4":
                    await self.app.snack_bar.show_snack_bar(self._["unsupported_play_on_web"])
                    return
            else:
                title = self._["view_stream_source_now"]
        await self.create_video_dialog(title, source, is_file_path, room_url)
