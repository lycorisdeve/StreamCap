import asyncio
import os.path
import time

import flet as ft

from ....models.recording.recording_model import Recording
from ....models.recording.recording_status_model import RecordingStatus
from ....utils import utils
from ....utils.logger import logger
from ...themes.glass import CARD_BORDER_WIDTH, CARD_RADIUS, glass_gradient, glass_shadows
from ...views.storage_view import StoragePage
from ..dialogs.card_dialog import CardDialog
from ..state.recording_card_state import RecordingCardState
from .recording_dialog import RecordingDialog
from .video_player import VideoPlayer


class RecordingCardManager:
    def __init__(self, app):
        self.app = app
        self.cards_obj = {}
        self.update_duration_tasks = {}
        self.selected_cards = {}
        self.last_card_click_at = {}
        self._hovered_cards = set()
        self.app.language_manager.add_observer(self)
        self._ = {}
        self.load()
        self.pubsub_subscribe()
        theme_manager = getattr(self.app, "theme_manager", None)
        self._unsubscribe_theme = theme_manager.subscribe(self.refresh_theme) if theme_manager else None

    def load(self):
        language = self.app.language_manager.language
        for key in ("recording_card", "recording_manager", "base", "recordings_page", "video_quality", "storage_page"):
            self._.update(language.get(key, {}))

    def pubsub_subscribe(self):
        self.app.page.pubsub.subscribe_topic("update", self.subscribe_update_card)
        self.app.page.pubsub.subscribe_topic("delete", self.subscribe_remove_cards)

    async def create_card(self, recording: Recording, subscribe_add_cards: bool = False):
        """Create a card for a given recording."""
        rec_id = recording.rec_id
        if not self.cards_obj.get(rec_id):
            check_live_on_browser_refresh = self.app.settings.user_config.get("check_live_on_browser_refresh", True)
            if self.app.recording_enabled and not subscribe_add_cards:
                if check_live_on_browser_refresh or recording.streamer_name == self._["live_room"]:
                    self.app.page.run_task(self.app.record_manager.check_if_live, recording)

        card_data = self._create_card_components(recording)
        self.cards_obj[rec_id] = card_data
        self.start_update_task(recording)
        return card_data["card"]

    def _create_card_components(self, recording: Recording):
        """create card components."""
        speed = recording.speed or ""
        duration_text_label = ft.Text(
            self.app.record_manager.get_duration(recording),
            size=12,
            max_lines=1,
            no_wrap=True,
            weight=ft.FontWeight.W_600,
            color=ft.Colors.ON_SURFACE,
        )
        duration_icon = ft.Icon(
            ft.Icons.FIBER_MANUAL_RECORD if recording.is_recording else ft.Icons.SCHEDULE,
            size=14,
            color=ft.Colors.RED if recording.is_recording else ft.Colors.PRIMARY,
            tooltip=self.app.language_manager.language["logs_page"]["duration"],
        )

        record_button = ft.IconButton(
            icon=self.get_icon_for_recording_state(recording),
            icon_color=ft.Colors.PRIMARY,
            tooltip=self.get_tip_for_recording_state(recording),
            on_click=lambda e, rec=recording: self.app.page.run_task(self.recording_button_on_click, e, rec),
        )

        edit_button = ft.IconButton(
            icon=ft.Icons.EDIT,
            icon_color=ft.Colors.PRIMARY,
            tooltip=self._["edit_record_config"],
            on_click=lambda e, rec=recording: self.app.page.run_task(self.edit_recording_button_click, e, rec),
        )

        preview_button = ft.IconButton(
            icon=ft.Icons.VIDEO_LIBRARY,
            icon_color=ft.Colors.PRIMARY,
            tooltip=self._["preview_video"],
            on_click=lambda e, rec=recording: self.app.page.run_task(self.preview_video_button_on_click, e, rec),
        )

        monitor_button = ft.IconButton(
            icon=self.get_icon_for_monitor_state(recording),
            icon_color=ft.Colors.PRIMARY,
            tooltip=self.get_tip_for_monitor_state(recording),
            on_click=lambda e, rec=recording: self.app.page.run_task(self.monitor_button_on_click, e, rec),
        )

        pin_button = ft.IconButton(
            icon=self.get_icon_for_pin_state(recording),
            icon_color=ft.Colors.PRIMARY,
            tooltip=self.get_tip_for_pin_state(recording),
            on_click=lambda e, rec=recording: self.app.page.run_task(self.pin_recording_button_on_click, e, rec),
        )

        delete_button = ft.IconButton(
            icon=ft.Icons.DELETE,
            icon_color=ft.Colors.PRIMARY,
            tooltip=self._["delete_monitor"],
            on_click=lambda e, rec=recording: self.app.page.run_task(self.recording_delete_button_click, e, rec),
        )

        display_title = RecordingCardState.get_display_title(recording, self._)
        display_title_label = ft.Text(
            display_title,
            size=14,
            max_lines=1,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
            weight=RecordingCardState.get_title_weight(recording),
        )

        open_folder_button = ft.IconButton(
            icon=ft.Icons.FOLDER,
            icon_color=ft.Colors.PRIMARY,
            tooltip=self._["open_folder"],
            on_click=lambda e, rec=recording: self.app.page.run_task(self.recording_dir_button_on_click, e, rec),
        )
        speed_text_label = ft.Text(
            speed,
            size=12,
            color=ft.Colors.ON_SURFACE_VARIANT,
            tooltip=self._["recording_speed_hint"],
            max_lines=1,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
            text_align=ft.TextAlign.RIGHT,
            expand=True,
            expand_loose=True,
        )
        speed_icon = ft.Icon(ft.Icons.DOWNLOAD_ROUNDED, size=15, color=ft.Colors.GREEN, visible=bool(speed))
        speed_row = ft.Row(
            [speed_icon, speed_text_label],
            spacing=4,
            expand=True,
            alignment=ft.MainAxisAlignment.END,
            tooltip=self._["recording_speed_hint"],
        )
        action_buttons = [
            record_button,
            pin_button,
            open_folder_button,
            preview_button,
            edit_button,
            delete_button,
            monitor_button,
        ]
        for button in action_buttons:
            button.width = 36
            button.height = 36
            button.padding = 6
            button.icon_size = 20
            button.expand = True
            button.expand_loose = True
            self.apply_button_theme(button)

        status_label = ft.Container(
            content=ft.Text(size=12, weight=ft.FontWeight.BOLD, max_lines=1, no_wrap=True),
            min_width=60,
            height=26,
            padding=ft.Padding.symmetric(horizontal=7),
            border_radius=7,
            alignment=ft.Alignment.CENTER,
        )
        self.update_status_label(status_label, recording)
        info_margin = ft.Margin.symmetric(horizontal=8)
        title_row = ft.Row(
            [ft.SelectionArea(content=display_title_label, expand=True), status_label],
            height=26,
            margin=info_margin,
            spacing=8,
        )

        card_container = ft.Container(
            content=ft.Column(
                [
                    title_row,
                    ft.Row(
                        [ft.Row([duration_icon, duration_text_label], spacing=6, tight=True), speed_row],
                        height=20,
                        margin=info_margin,
                        spacing=8,
                    ),
                    ft.Row(
                        action_buttons,
                        spacing=0,
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                ],
                spacing=7,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                tight=True,
            ),
            tooltip=self._["recording_card_tip"],
            on_click=lambda e, rec=recording: self.app.page.run_task(self.recording_card_on_click, e, rec),
            on_hover=lambda e, rec=recording: self.app.page.run_task(self.on_card_hover, e, rec),
            bgcolor=self.get_card_background_color(recording),
            border_radius=CARD_RADIUS,
            border=ft.Border.all(CARD_BORDER_WIDTH, self.get_card_border_color(recording)),
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        )
        # Keep the blur inside the surface so it doesn't clip the outer shadows.
        card_container.content = ft.Container(
            content=card_container.content,
            padding=ft.Padding.symmetric(horizontal=4, vertical=10),
            blur=8,
            border_radius=CARD_RADIUS - CARD_BORDER_WIDTH,
        )
        self.apply_card_material(card_container, recording)
        card = ft.Card(
            key=str(recording.rec_id),
            content=card_container,
            margin=0,
            elevation=0,
            bgcolor=ft.Colors.TRANSPARENT,
            clip_behavior=ft.ClipBehavior.NONE,
        )

        return {
            "card": card,
            "display_title_label": display_title_label,
            "duration_label": duration_text_label,
            "duration_icon": duration_icon,
            "speed_label": speed_text_label,
            "speed_icon": speed_icon,
            "speed_row": speed_row,
            "record_button": record_button,
            "pin_button": pin_button,
            "open_folder_button": open_folder_button,
            "edit_button": edit_button,
            "monitor_button": monitor_button,
            "status_label": status_label,
            "recording": recording,
            "action_buttons": action_buttons,
        }

    def theme_color(self, name, fallback):
        manager = getattr(self.app, "theme_manager", None)
        return getattr(manager.tokens, name, fallback) if manager else fallback

    def apply_button_theme(self, button):
        button.hover_color = self.theme_color("primary_light", ft.Colors.SECONDARY_CONTAINER)
        focus_ring = self.theme_color("focus_ring", ft.Colors.PRIMARY)
        button.focus_color = ft.Colors.with_opacity(0.12, focus_ring)
        button.style = ft.ButtonStyle(side={ft.ControlState.FOCUSED: ft.BorderSide(1, focus_ring)})

    def refresh_theme(self):
        for card_data in self.cards_obj.values():
            recording = card_data.get("recording")
            if recording is not None:
                self.apply_card_material(card_data["card"].content, recording)
            for button in card_data.get("action_buttons", []):
                self.apply_button_theme(button)
        current_page = getattr(self.app, "current_page", None)
        if current_page is not None and getattr(current_page, "page_name", None) == "recordings":
            try:
                self.app.page.update()
            except (ft.FletPageDisconnectedException, AssertionError):
                pass

    def dispose(self):
        if self._unsubscribe_theme is not None:
            self._unsubscribe_theme()
            self._unsubscribe_theme = None

    def apply_card_material(self, container, recording):
        container.bgcolor = self.get_card_background_color(recording)
        manager = getattr(self.app, "theme_manager", None)
        if manager is not None:
            hovered = recording.rec_id in self._hovered_cards
            container.gradient = glass_gradient(manager.tokens, tinted=recording.selected or hovered)
            container.shadow = glass_shadows(manager.tokens, hovered=hovered)
            container.content.blur = None if manager.tokens.is_classic else 8
            if manager.tokens.is_classic:
                container.animate = None
                container.animate_offset = None
                container.offset = ft.Offset(0, 0)
        container.border = ft.Border.all(
            CARD_BORDER_WIDTH,
            ft.Colors.with_opacity(
                1 if recording.rec_id in self._hovered_cards else 0.76, self.get_card_border_color(recording)
            ),
        )

    async def on_card_hover(self, event, recording):
        if event.data in (True, "true"):
            self._hovered_cards.add(recording.rec_id)
        else:
            self._hovered_cards.discard(recording.rec_id)
        manager = getattr(self.app, "theme_manager", None)
        duration = await manager.motion_duration() if manager is not None else 0
        hovered = recording.rec_id in self._hovered_cards
        event.control.animate = ft.Animation(duration, ft.AnimationCurve.EASE_OUT)
        event.control.animate_offset = ft.Animation(duration, ft.AnimationCurve.EASE_OUT)
        event.control.offset = ft.Offset(0, -2 / 120 if hovered and duration else 0)
        self.apply_card_material(event.control, recording)
        event.control.update()

    def get_card_background_color(self, recording: Recording):
        if recording.selected:
            return self.theme_color("selected_background", ft.Colors.PRIMARY_CONTAINER)
        if recording.rec_id in getattr(self, "_hovered_cards", set()):
            return self.theme_color("primary_light", ft.Colors.SECONDARY_CONTAINER)
        return None

    @staticmethod
    def get_card_border_color(recording: Recording):
        """Get the border color of the card."""
        return RecordingCardState.get_border_color(recording)

    def update_status_label(self, label, recording: Recording):
        config = RecordingCardState.get_status_label_config(recording, self._)
        label.visible = bool(config)
        if config:
            label.content.value = config["text"]
            label.content.color = config["text_color"]
            label.bgcolor = config["bgcolor"]
        label.tooltip = self._["skip_condition"] if recording.skip_current_live else None

    async def update_card(self, recording):
        """Update only the recordings cards in the scrollable content area."""
        self.app.record_manager.sort_recordings()
        self.reorder_recording_cards()
        if recording.rec_id in self.cards_obj:
            try:
                recording_card = self.cards_obj[recording.rec_id]

                display_title = RecordingCardState.get_display_title(recording, self._)
                if recording_card.get("display_title_label"):
                    recording_card["display_title_label"].value = display_title
                    recording_card["display_title_label"].weight = RecordingCardState.get_title_weight(recording)

                self.update_status_label(recording_card["status_label"], recording)

                if recording_card.get("duration_label"):
                    recording_card["duration_label"].value = self.app.record_manager.get_duration(recording)
                    recording_card["duration_icon"].icon = (
                        ft.Icons.FIBER_MANUAL_RECORD if recording.is_recording else ft.Icons.SCHEDULE
                    )
                    recording_card["duration_icon"].color = (
                        ft.Colors.RED if recording.is_recording else ft.Colors.PRIMARY
                    )

                if recording_card.get("speed_label"):
                    recording_card["speed_label"].value = recording.speed or ""
                    recording_card["speed_icon"].visible = bool(recording.speed)

                if recording_card.get("record_button"):
                    recording_card["record_button"].disabled = recording.stopping_in_progress
                    recording_card["record_button"].icon = self.get_icon_for_recording_state(recording)
                    recording_card["record_button"].tooltip = self.get_tip_for_recording_state(recording)

                if recording_card.get("monitor_button"):
                    recording_card["monitor_button"].icon = self.get_icon_for_monitor_state(recording)
                    recording_card["monitor_button"].tooltip = self.get_tip_for_monitor_state(recording)

                if recording_card.get("pin_button"):
                    recording_card["pin_button"].icon = self.get_icon_for_pin_state(recording)
                    recording_card["pin_button"].icon_color = ft.Colors.PRIMARY
                    recording_card["pin_button"].tooltip = self.get_tip_for_pin_state(recording)

                if recording_card["card"] and recording_card["card"].content:
                    self.apply_card_material(recording_card["card"].content, recording)
                    try:
                        current_page = getattr(self.app, "current_page", None)
                        if current_page is not None and getattr(current_page, "page_name", None) == "recordings":
                            await current_page.apply_filter()
                        self.app.page.update()
                    except (ft.FletPageDisconnectedException, AssertionError) as e:
                        logger.debug(f"Update card failed: {e}")
                        return

            except (ft.FletPageDisconnectedException, AssertionError) as e:
                logger.debug(f"Update card failed: {e}")
                return
            except Exception as e:
                logger.debug(f"Update card failed: {e}")

    async def update_monitor_state(self, recording: Recording):
        """Update the monitor button state based on the current monitoring status."""
        if recording.monitor_status:
            recording.update(
                {
                    "recording": False,
                    "monitor_status": not recording.monitor_status,
                    "status_info": RecordingStatus.STOPPED_MONITORING,
                    "display_title": f"[{self._['monitor_stopped']}] {recording.title}",
                }
            )
            self.app.record_manager.stop_recording(recording, manually_stopped=True)
            self.app.page.run_task(self.app.snack_bar.show_snack_bar, self._["stop_monitor_tip"])
        else:
            recording.update(
                {
                    "monitor_status": not recording.monitor_status,
                    "status_info": RecordingStatus.STATUS_CHECKING,
                    "display_title": f"{recording.title}",
                    "showed_checking_status": False,
                }
            )
            self.app.page.run_task(self.app.record_manager.check_if_live, recording)
            self.app.page.run_task(self.app.snack_bar.show_snack_bar, self._["start_monitor_tip"], ft.Colors.GREEN)

        await self.update_card(recording)
        self.app.page.pubsub.send_others_on_topic("update", recording)
        self.app.services.run_coro(self.app.record_manager.persist_recordings())

    async def show_recording_info_dialog(self, recording: Recording):
        """Display a dialog with detailed information about the recording."""
        try:
            dialog = CardDialog(self.app, recording)
            dialog.open = True
            self.app.dialog_area.content = dialog
            try:
                self.app.page.update()
            except (ft.FletPageDisconnectedException, AssertionError) as e:
                logger.debug(f"Update recording info dialog failed: {e}")
        except (ft.FletPageDisconnectedException, AssertionError) as e:
            logger.debug(f"Show recording info dialog failed: {e}")
        except Exception as e:
            logger.debug(f"Show recording info dialog failed: {e}")

    async def edit_recording_callback(self, recording_list: list[dict]):
        recording_dict = recording_list[0]
        rec_id = recording_dict["rec_id"]
        recording = self.app.record_manager.find_recording_by_id(rec_id)

        await self.app.record_manager.update_recording_card(recording, updated_info=recording_dict)
        if not recording_dict["monitor_status"]:
            recording.display_title = f"[{self._['monitor_stopped']}] " + recording.title

        recording.scheduled_time_range = await self.app.record_manager.get_scheduled_time_range(
            recording.scheduled_start_time, recording.monitor_hours
        )

        await self.update_card(recording)
        self.app.page.pubsub.send_others_on_topic("update", recording_dict)

    async def on_toggle_recording(self, recording: Recording):
        """Toggle the recording state for a specific recording."""
        guard_until = getattr(recording, "_ignore_record_button_until", 0)
        if guard_until and time.monotonic() < guard_until:
            logger.debug(f"Ignore recording toggle immediately after pin click: {recording.rec_id}")
            return

        if recording and recording.recording_start_pending:
            return

        if recording and self.app.recording_enabled:
            if recording.stopping_in_progress:
                await self.app.snack_bar.show_snack_bar(self._["stopping_tip"])
                return
            if recording.is_recording:
                saved = await self.app.record_manager.request_recording_stop(recording)
                await self.app.snack_bar.show_snack_bar(self._["stop_record_tip" if saved else "stop_save_failed"])
            else:
                if recording.monitor_status:
                    result = await self.app.record_manager.request_recording_start(recording)
                    if result in ("busy", "scheduled", "save_failed"):
                        key = {
                            "busy": "stopping_tip",
                            "scheduled": "scheduled_tip",
                            "save_failed": "resume_save_failed",
                        }[result]
                        await self.app.snack_bar.show_snack_bar(self._[key])
                    elif recording.is_recording:
                        await self.app.snack_bar.show_snack_bar(self._["pre_record_tip"], bgcolor=ft.Colors.PRIMARY)
                    else:
                        await self.app.snack_bar.show_snack_bar(self._["is_not_live_tip"])
                else:
                    await self.app.snack_bar.show_snack_bar(self._["please_start_monitor_tip"])

            await self.update_card(recording)
            self.app.page.pubsub.send_others_on_topic("update", recording)

    async def on_delete_recording(self, recording: Recording):
        """Delete a recording from the list and update UI."""
        if recording:
            if recording.is_recording:
                await self.app.snack_bar.show_snack_bar(self._["please_stop_monitor_tip"])
                return
            await self.app.record_manager.delete_recording_cards([recording])
            current_page = getattr(self.app, "current_page", None)
            if current_page is not None and getattr(current_page, "page_name", None) == "recordings":
                current_page.content_area.controls[1] = current_page.create_filter_area()
                current_page.content_area.update()
            await self.app.snack_bar.show_snack_bar(
                self._["delete_recording_success_tip"], bgcolor=ft.Colors.PRIMARY, duration=2000
            )

    async def remove_recording_card(self, recordings: list[Recording]):
        try:
            recordings_page = self.app.current_page

            existing_ids = {rec.rec_id for rec in self.app.record_manager.recordings}
            remove_ids = {rec.rec_id for rec in recordings}
            keep_ids = existing_ids - remove_ids

            cards_to_remove = [
                card_data["card"] for rec_id, card_data in self.cards_obj.items() if rec_id not in keep_ids
            ]

            recordings_page.recording_card_area.content.controls = [
                control
                for control in recordings_page.recording_card_area.content.controls
                if control not in cards_to_remove
            ]

            self.cards_obj = {k: v for k, v in self.cards_obj.items() if k in keep_ids}

            try:
                recordings_page.recording_card_area.update()
            except (ft.FletPageDisconnectedException, AssertionError) as e:
                logger.debug(f"Update recording card area failed: {e}")

        except (ft.FletPageDisconnectedException, AssertionError) as e:
            logger.debug(f"Remove recording card failed: {e}")
        except Exception as e:
            logger.debug(f"Remove recording card failed: {e}")

    async def update_record_hover(self, recording: Recording):
        return self.get_card_background_color(recording)

    @staticmethod
    def get_icon_for_recording_state(recording: Recording):
        """Return the appropriate icon based on the recording's state."""
        return RecordingCardState.get_recording_icon(recording)

    def get_tip_for_recording_state(self, recording: Recording):
        if recording.skip_current_live and not recording.is_recording:
            return self._["resume_record"]
        return self._["stop_record"] if recording.is_recording else self._["start_record"]

    @staticmethod
    def get_icon_for_monitor_state(recording: Recording):
        """Return the appropriate icon based on the monitor's state."""
        return RecordingCardState.get_monitor_icon(recording)

    def get_tip_for_monitor_state(self, recording: Recording):
        return self._["stop_monitor"] if recording.monitor_status else self._["start_monitor"]

    @staticmethod
    def get_icon_for_pin_state(recording: Recording):
        if recording.pinned_at:
            return getattr(ft.Icons, "PUSH_PIN", ft.Icons.STAR)
        return getattr(ft.Icons, "PUSH_PIN_OUTLINED", getattr(ft.Icons, "STAR_BORDER", ft.Icons.STAR))

    def get_tip_for_pin_state(self, recording: Recording):
        return self._["unpin_record"] if recording.pinned_at else self._["pin_record"]

    def reorder_recording_cards(self):
        current_page = getattr(self.app, "current_page", None)
        recording_card_area = getattr(current_page, "recording_card_area", None)
        content = getattr(recording_card_area, "content", None)
        controls = getattr(content, "controls", None)
        if controls is None:
            return

        ordered_cards = []
        ordered_ids = set()
        for recording in self.app.record_manager.recordings:
            card_info = self.cards_obj.get(recording.rec_id)
            if card_info and card_info.get("card"):
                ordered_cards.append(card_info["card"])
                ordered_ids.add(card_info["card"].key)

        remaining_cards = [control for control in controls if getattr(control, "key", None) not in ordered_ids]
        new_controls = ordered_cards + remaining_cards
        if len(controls) == len(new_controls) and all(a is b for a, b in zip(controls, new_controls)):
            return
        controls[:] = new_controls
        try:
            recording_card_area.update()
        except (ft.FletPageDisconnectedException, AssertionError) as e:
            logger.debug(f"Reorder recording cards failed: {e}")

    async def pin_recording_button_on_click(self, _, recording: Recording):
        recording._ignore_record_button_until = time.monotonic() + 1.0
        pinned = await self.app.record_manager.toggle_pin_recording(recording)
        await self.update_card(recording)
        self.app.page.pubsub.send_others_on_topic("update", recording)
        message_key = "pin_record_success_tip" if pinned else "unpin_record_success_tip"
        await self.app.snack_bar.show_snack_bar(self._[message_key], bgcolor=ft.Colors.PRIMARY, duration=1500)

    async def update_duration(self, recording: Recording):
        """Update the duration text periodically."""
        while True:
            update_interval = 1
            await asyncio.sleep(update_interval)
            if not recording or recording.rec_id not in self.cards_obj:  # Stop task if card is removed
                break

            # Skip update when not on recordings page (cards are detached from page tree)
            current_page = getattr(self.app, "current_page", None)
            if not current_page or getattr(current_page, "page_name", None) != "recordings":
                continue

            if recording.is_recording:
                try:
                    duration_label = self.cards_obj[recording.rec_id]["duration_label"]
                    duration_label.value = self.app.record_manager.get_duration(recording)
                    duration_label.update()
                    speed_label = self.cards_obj[recording.rec_id]["speed_label"]
                    speed_label.value = recording.speed or ""
                    self.cards_obj[recording.rec_id]["speed_icon"].visible = bool(recording.speed)
                    self.cards_obj[recording.rec_id]["speed_row"].update()
                except (ft.FletPageDisconnectedException, AssertionError) as e:
                    logger.debug(f"Update duration failed: {e}")
                    break
                except Exception as e:
                    logger.debug(f"Update duration failed: {e}")

    def start_update_task(self, recording: Recording):
        """Start a background task to update the duration text."""
        self.update_duration_tasks[recording.rec_id] = self.app.page.run_task(self.update_duration, recording)

    async def on_card_click(self, recording: Recording):
        """Handle card click events."""
        try:
            now = time.monotonic()
            last_click_at = self.last_card_click_at.get(recording.rec_id, 0)
            self.last_card_click_at[recording.rec_id] = now
            if now - last_click_at <= 0.35:
                await self.show_recording_info_dialog(recording)
                return

            recording.selected = not recording.selected
            self.selected_cards[recording.rec_id] = recording
            self.apply_card_material(self.cards_obj[recording.rec_id]["card"].content, recording)
            try:
                self.cards_obj[recording.rec_id]["card"].update()
            except (ft.FletPageDisconnectedException, AssertionError) as e:
                logger.debug(f"Update card click state failed: {e}")
        except (ft.FletPageDisconnectedException, AssertionError) as e:
            logger.debug(f"Handle card click event failed: {e}")
        except Exception as e:
            logger.debug(f"Handle card click event failed: {e}")

    async def recording_dir_on_click(self, recording: Recording):
        if recording.recording_dir:
            if os.path.exists(recording.recording_dir):
                if not utils.open_folder(recording.recording_dir):
                    await self.app.snack_bar.show_snack_bar(self._["no_video_file"])
            else:
                await self.app.snack_bar.show_snack_bar(self._["no_recording_folder"])

    async def edit_recording_button_click(self, _, recording: Recording):
        """Handle edit button click by showing the edit dialog with existing recording info."""

        if recording.is_recording or recording.monitor_status:
            await self.app.snack_bar.show_snack_bar(self._["please_stop_monitor_tip"])
            return

        await RecordingDialog(
            self.app,
            on_confirm_callback=self.edit_recording_callback,
            recording=recording,
        ).show_dialog()

    async def recording_delete_button_click(self, _, recording: Recording):
        try:

            async def confirm_dlg(_):
                self.app.page.run_task(self.on_delete_recording, recording)
                await close_dialog(None)

            async def close_dialog(_):
                try:
                    delete_alert_dialog.open = False
                    delete_alert_dialog.update()
                except (ft.FletPageDisconnectedException, AssertionError) as err:
                    logger.debug(f"Close delete dialog failed: {err}")

            delete_alert_dialog = ft.AlertDialog(
                title=ft.Text(self._["confirm"]),
                content=ft.Text(self._["delete_confirm_tip"]),
                actions=[
                    ft.TextButton(content=self._["cancel"], on_click=close_dialog),
                    ft.TextButton(content=self._["sure"], on_click=confirm_dlg),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
                modal=False,
            )
            delete_alert_dialog.open = True
            self.app.dialog_area.content = delete_alert_dialog
            try:
                self.app.page.update()
            except (ft.FletPageDisconnectedException, AssertionError) as e:
                logger.debug(f"Update delete dialog failed: {e}")
        except (ft.FletPageDisconnectedException, AssertionError) as e:
            logger.debug(f"Show delete dialog failed: {e}")
        except Exception as e:
            logger.debug(f"Show delete dialog failed: {e}")

    async def preview_video_button_on_click(self, _, recording: Recording):
        if self.app.page.web and recording.record_url:
            video_player = VideoPlayer(self.app)
            await video_player.preview_video(recording.preview_url, is_file_path=False, room_url=recording.url)
        elif recording.recording_dir and os.path.exists(recording.recording_dir):
            video_files = []
            for root, _, files in os.walk(recording.recording_dir):
                for file in files:
                    file_str = str(file)
                    if utils.is_valid_video_file(file_str):
                        video_files.append(os.path.join(str(root), file_str))

            if video_files:
                video_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
                latest_video = video_files[0]
                await StoragePage(self.app).preview_file(latest_video, recording.url)
            else:
                await self.app.snack_bar.show_snack_bar(self._["no_video_file"])
        else:
            await self.app.snack_bar.show_snack_bar(self._["no_recording_folder"])

    async def recording_button_on_click(self, _, recording: Recording):
        await self.on_toggle_recording(recording)

    async def recording_dir_button_on_click(self, _, recording: Recording):
        await self.recording_dir_on_click(recording)

    async def recording_info_button_on_click(self, _, recording: Recording):
        await self.show_recording_info_dialog(recording)

    async def monitor_button_on_click(self, _, recording: Recording):
        await self.update_monitor_state(recording)

    async def recording_card_on_click(self, _, recording: Recording):
        await self.on_card_click(recording)

    async def subscribe_update_card(self, _, recording: Recording):
        await self.update_card(recording)

    async def subscribe_remove_cards(self, _, recordings: list[Recording]):
        await self.remove_recording_card(recordings)
