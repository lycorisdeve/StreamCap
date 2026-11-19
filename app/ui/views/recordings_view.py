import asyncio
import uuid

import flet as ft

from ...core.platforms.platform_handlers import get_platform_info
from ...core.recording.record_manager import RecordingManager
from ...models.recording.recording_model import Recording
from ...utils.logger import logger
from ..base_page import PageBase
from ..components.business.recording_dialog import RecordingDialog
from ..components.dialogs.help_dialog import HelpDialog
from ..filters import RecordingFilters
from ..themes.glass import CONTROL_HEIGHT, CONTROL_RADIUS, FILTER_HEIGHT, glass_border, glass_gradient, glass_shadows
from ..themes.theme_tokens import build_tokens


class RecordingsPage(PageBase):
    CARD_MIN_WIDTH = 280
    CARD_HEIGHT = 120
    CARD_SPACING = 12

    def __init__(self, app):
        super().__init__(app)
        self.page_name = "recordings"
        self.recording_card_area = None
        self.add_recording_dialog = None
        self.is_grid_view = app.settings.user_config.get("is_grid_view", True)
        self._grid_width = 0
        self.loading_indicator = None
        self.app.language_manager.add_observer(self)
        self.load_language()
        self.current_filter = "all"
        self.current_platform_filter = "all"
        self.platform_buttons = {}
        self.search_query = ""
        self.search_field = None
        self._search_task = None
        self._search_revision = 0
        self._filter_buttons = {}
        self._toolbar_surfaces = []
        self._field_surfaces = []
        self.init()
        theme_manager = getattr(self.app, "theme_manager", None)
        self._unsubscribe_theme = theme_manager.subscribe(self.refresh_theme) if theme_manager else None

    def load_language(self):
        language = self.app.language_manager.language
        for key in ("recordings_page", "video_quality", "base"):
            self._.update(language.get(key, {}))

    def init(self):
        self.loading_indicator = ft.ProgressRing(width=40, height=40, stroke_width=3, visible=False)

        if self.is_grid_view:
            initial_content = ft.GridView(
                expand=True,
                runs_count=1,
                spacing=self.CARD_SPACING,
                run_spacing=self.CARD_SPACING,
                child_aspect_ratio=self.CARD_MIN_WIDTH / self.CARD_HEIGHT,
                padding=0,
                controls=[],
            )
        else:
            initial_content = ft.Column(controls=[], spacing=5, expand=True)

        self.recording_card_area = ft.Container(
            content=initial_content,
            expand=True,
            on_size_change=self.update_grid_layout,
            size_change_interval=50,
        )
        self.add_recording_dialog = RecordingDialog(self.app, self.add_recording)
        self.pubsub_subscribe()

    async def load(self):
        """Load the recordings page content."""
        self.content_area.controls.extend(
            [self.create_recordings_title_area(), self.create_filter_area(), self.create_recordings_content_area()]
        )
        self.content_area.update()

        if not self.recording_card_area.content.controls:
            self.recording_card_area.content.controls.clear()
            await self.add_record_cards()
        else:
            # if cards exist, apply filter
            await self.apply_filter()

        if self.is_grid_view:
            await self.recalculate_grid_columns()

        self.page.on_keyboard_event = self.on_keyboard

    def pubsub_subscribe(self):
        self.app.page.pubsub.subscribe_topic("add", self.subscribe_add_cards)
        self.app.page.pubsub.subscribe_topic("delete_all", self.subscribe_del_all_cards)

    async def toggle_view_mode(self, _):
        self.is_grid_view = not self.is_grid_view
        current_content = self.recording_card_area.content
        current_controls = current_content.controls if hasattr(current_content, "controls") else []

        runs_count = self.get_grid_runs_count()
        child_aspect_ratio = self.get_grid_child_aspect_ratio()

        if self.is_grid_view:
            new_content = ft.GridView(
                expand=True,
                runs_count=runs_count,
                spacing=self.CARD_SPACING,
                run_spacing=self.CARD_SPACING,
                child_aspect_ratio=child_aspect_ratio,
                padding=0,
                controls=current_controls,
            )
        else:
            new_content = ft.Column(controls=current_controls, spacing=5, expand=True)

        self.recording_card_area.content = new_content
        self.content_area.controls.clear()
        self.content_area.controls.extend(
            [self.create_recordings_title_area(), self.create_filter_area(), self.create_recordings_content_area()]
        )
        self.content_area.update()

        if self.is_grid_view:
            await self.recalculate_grid_columns()

        self.app.settings.user_config["is_grid_view"] = self.is_grid_view
        self.app.services.run_coro(self.app.config_manager.save_user_config(self.app.settings.user_config))

    def theme_color(self, name, fallback):
        manager = getattr(self.app, "theme_manager", None)
        return getattr(manager.tokens, name, fallback) if manager else fallback

    def create_recordings_title_area(self):
        if self.search_field is None:
            self.search_field = ft.TextField(
                value=self.search_query,
                prefix_icon=ft.Icons.SEARCH,
                hint_text=self._["search_placeholder"],
                on_change=self.on_search_change,
                on_submit=self.on_search_submit,
                height=CONTROL_HEIGHT,
                text_size=13,
                dense=True,
                content_padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                border_radius=CONTROL_RADIUS,
                border_color=ft.Colors.TRANSPARENT,
                focused_border_color=self.theme_color("focus_ring", ft.Colors.PRIMARY),
                expand=True,
            )
        else:
            self.search_field.hint_text = self._["search_placeholder"]
        actions = [
            ft.FilledButton(self._["toolbar_add"], icon=ft.Icons.ADD, on_click=self.add_recording_on_click),
            ft.OutlinedButton(
                self._["toolbar_start_all"], icon=ft.Icons.PLAY_ARROW, on_click=self.start_monitor_recordings_on_click
            ),
            ft.OutlinedButton(
                self._["toolbar_stop_all"], icon=ft.Icons.STOP, on_click=self.stop_monitor_recordings_on_click
            ),
            ft.OutlinedButton(self._["refresh"], icon=ft.Icons.REFRESH, on_click=self.refresh_cards_on_click),
            ft.OutlinedButton(
                self._["batch_delete"],
                icon=ft.Icons.DELETE_SWEEP,
                on_click=self.delete_monitor_recordings_on_click,
                style=ft.ButtonStyle(color=ft.Colors.RED),
            ),
        ]
        self._toolbar_surfaces = []
        for index, button in enumerate(actions):
            button.height = CONTROL_HEIGHT
            surface = ft.Container(content=button, border_radius=CONTROL_RADIUS, on_hover=self.toolbar_hover)
            self._toolbar_surfaces.append((surface, index == 0, index == 4))
        search_surface = ft.Container(content=self.search_field, expand=True, border_radius=CONTROL_RADIUS)
        self._field_surfaces = [search_surface]
        self.refresh_materials()
        return ft.ResponsiveRow(
            [
                ft.Row(
                    [surface for surface, _, _ in self._toolbar_surfaces],
                    wrap=True,
                    spacing=8,
                    run_spacing=8,
                    col={"xs": 12, "xl": 8},
                ),
                ft.Row(
                    [
                        search_surface,
                        ft.IconButton(
                            ft.Icons.GRID_VIEW,
                            selected=self.is_grid_view,
                            tooltip=self._["grid_view"],
                            on_click=self.show_grid_view,
                        ),
                        ft.IconButton(
                            ft.Icons.LIST,
                            selected=not self.is_grid_view,
                            tooltip=self._["list_view"],
                            on_click=self.show_list_view,
                        ),
                    ],
                    spacing=0,
                    col={"xs": 12, "xl": 4},
                ),
            ],
            spacing=12,
            run_spacing=8,
        )

    async def show_grid_view(self, event):
        if not self.is_grid_view:
            await self.toggle_view_mode(event)

    async def toolbar_hover(self, event):
        manager = getattr(self.app, "theme_manager", None)
        if manager is None:
            return
        surface = event.control
        surface.data = event.data in (True, "true")
        duration = await manager.motion_duration()
        surface.animate = ft.Animation(duration, ft.AnimationCurve.EASE_OUT)
        surface.shadow = glass_shadows(manager.tokens, hovered=surface.data)
        surface.update()

    async def show_list_view(self, event):
        if self.is_grid_view:
            await self.toggle_view_mode(event)

    def filter_button_style(self, selected):
        return ft.ButtonStyle(
            color=self.theme_color("primary_foreground", ft.Colors.ON_PRIMARY) if selected else ft.Colors.ON_SURFACE,
            bgcolor={
                ft.ControlState.DEFAULT: self.theme_color("primary", ft.Colors.PRIMARY)
                if selected
                else ft.Colors.with_opacity(0.8, ft.Colors.SURFACE),
                ft.ControlState.HOVERED: self.theme_color("primary_hover", ft.Colors.PRIMARY)
                if selected
                else self.theme_color("primary_light", ft.Colors.SECONDARY_CONTAINER),
                ft.ControlState.PRESSED: self.theme_color("primary_active", ft.Colors.PRIMARY),
            },
            overlay_color={
                ft.ControlState.FOCUSED: ft.Colors.with_opacity(0.12, self.theme_color("focus_ring", ft.Colors.PRIMARY))
            },
            side={
                ft.ControlState.DEFAULT: ft.BorderSide(
                    1, self.theme_color("primary_border", ft.Colors.OUTLINE_VARIANT)
                ),
                ft.ControlState.FOCUSED: ft.BorderSide(2, self.theme_color("focus_ring", ft.Colors.PRIMARY)),
            },
            shape=ft.RoundedRectangleBorder(radius=18),
            padding=ft.Padding.symmetric(horizontal=12, vertical=6),
            elevation={ft.ControlState.DEFAULT: 1, ft.ControlState.HOVERED: 3},
            shadow_color=ft.Colors.with_opacity(0.18, self.theme_color("primary", ft.Colors.PRIMARY)),
        )

    def refresh_materials(self):
        manager = getattr(self.app, "theme_manager", None)
        tokens = manager.tokens if manager else build_tokens(None)
        for surface, primary, danger in getattr(self, "_toolbar_surfaces", []):
            surface.gradient = (
                ft.LinearGradient(
                    begin=ft.Alignment.TOP_LEFT,
                    end=ft.Alignment.BOTTOM_RIGHT,
                    colors=[tokens.primary_hover, tokens.primary, tokens.primary_active],
                )
                if primary
                else glass_gradient(tokens)
            )
            surface.border = glass_border(tokens)
            surface.shadow = glass_shadows(tokens)
            surface.content.style = ft.ButtonStyle(
                color=tokens.primary_foreground if primary else ft.Colors.RED if danger else tokens.interactive_accent,
                bgcolor=ft.Colors.TRANSPARENT,
                overlay_color={
                    ft.ControlState.HOVERED: ft.Colors.with_opacity(
                        0.12, tokens.primary_foreground if primary else tokens.primary
                    ),
                    ft.ControlState.FOCUSED: ft.Colors.with_opacity(0.16, tokens.focus_ring),
                },
                elevation=0,
                side=ft.BorderSide(0, ft.Colors.TRANSPARENT),
                shape=ft.RoundedRectangleBorder(radius=CONTROL_RADIUS),
            )
        for surface in getattr(self, "_field_surfaces", []):
            surface.gradient = glass_gradient(tokens)
            surface.border = None if isinstance(surface.content, ft.Dropdown) else glass_border(tokens)
            surface.shadow = glass_shadows(tokens)

    def refresh_theme(self):
        self.refresh_materials()
        if self.search_field is not None:
            self.search_field.focused_border_color = self.theme_color("focus_ring", ft.Colors.PRIMARY)
        for key, button in self._filter_buttons.items():
            button.style = self.filter_button_style(key == self.current_filter)
            button.content.controls[1].color = (
                self.theme_color("primary_foreground", ft.Colors.ON_PRIMARY)
                if key == self.current_filter
                else ft.Colors.ON_SURFACE
            )
        if getattr(self.app, "current_page", None) is self:
            try:
                self.content_area.update()
            except (ft.FletPageDisconnectedException, AssertionError):
                pass

    def create_filter_area(self):
        """Status, platform and search always intersect without replacing cards."""
        filters = (
            ("all", "filter_all", ft.Icons.APPS, ft.Colors.ON_SURFACE_VARIANT, self.filter_all_on_click),
            (
                "recording",
                "filter_recording",
                ft.Icons.FIBER_MANUAL_RECORD,
                ft.Colors.GREEN,
                self.filter_recording_on_click,
            ),
            ("living", "filter_living", ft.Icons.LIVE_TV, ft.Colors.BLUE, self.filter_living_on_click),
            ("offline", "filter_offline", ft.Icons.PAUSE_CIRCLE_OUTLINE, ft.Colors.AMBER, self.filter_offline_on_click),
            ("error", "filter_error", ft.Icons.ERROR_OUTLINE, ft.Colors.RED, self.filter_error_on_click),
            (
                "stopped",
                "filter_stopped",
                ft.Icons.VISIBILITY_OFF_OUTLINED,
                ft.Colors.GREY,
                self.filter_stopped_on_click,
            ),
        )
        self._filter_buttons = {}
        for key, label, icon, color, handler in filters:
            self._filter_buttons[key] = ft.Button(
                content=ft.Row(
                    [
                        ft.Icon(icon, size=14, color=color),
                        ft.Text(
                            self._[label],
                            size=13,
                            color=(
                                self.theme_color("primary_foreground", ft.Colors.ON_PRIMARY)
                                if key == self.current_filter
                                else ft.Colors.ON_SURFACE
                            ),
                        ),
                    ],
                    spacing=6,
                    tight=True,
                ),
                on_click=handler,
                height=FILTER_HEIGHT,
                style=self.filter_button_style(key == self.current_filter),
            )
        platforms = {
            recording.platform_key: recording.platform
            for recording in self.app.record_manager.recordings
            if recording.platform and recording.platform_key
        }
        if self.current_platform_filter not in {"all", *platforms}:
            self.current_platform_filter = "all"
        platform_dropdown = ft.Dropdown(
            options=[ft.dropdown.DropdownOption(key="all", text=self._["filter_all"])]
            + [ft.dropdown.DropdownOption(key=key, text=name) for key, name in platforms.items()],
            value=self.current_platform_filter,
            label=self._["platform_filter"],
            tooltip=self._["platform_filter"],
            on_select=self.on_platform_dropdown_change,
            width=140,
            height=FILTER_HEIGHT,
            text_size=13,
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=4),
            border_radius=12,
            border_color=ft.Colors.OUTLINE_VARIANT,
            focused_border_color=ft.Colors.PRIMARY,
            dense=True,
            menu_height=320 if len(platforms) > 7 else None,
        )
        platform_surface = ft.Container(
            content=platform_dropdown, height=FILTER_HEIGHT, border_radius=12, clip_behavior=ft.ClipBehavior.NONE
        )
        self._field_surfaces = getattr(self, "_field_surfaces", [])[:1] + [platform_surface]
        self.refresh_materials()
        return ft.ResponsiveRow(
            [
                ft.Row(
                    [
                        ft.Text(f"{self._['status_filter']}：", size=13, weight=ft.FontWeight.BOLD),
                        *self._filter_buttons.values(),
                    ],
                    wrap=True,
                    spacing=8,
                    run_spacing=8,
                    col={"xs": 12, "xl": 9},
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row(
                    [platform_surface],
                    spacing=8,
                    alignment=ft.MainAxisAlignment.END,
                    col={"xs": 12, "xl": 3},
                ),
            ],
            spacing=8,
            run_spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    async def on_search_change(self, event):
        self.search_query = event.control.value or ""
        self._search_revision += 1
        if self._search_task is not None:
            self._search_task.cancel()
        self._search_task = self.page.run_task(self._apply_search_after_delay, self._search_revision)

    async def _apply_search_after_delay(self, revision):
        try:
            await asyncio.sleep(0.25)
            if revision == self._search_revision:
                await self.apply_filter()
        except asyncio.CancelledError:
            pass

    async def on_search_submit(self, event):
        if self._search_task is not None:
            self._search_task.cancel()
        await self.filter_recordings(event.control.value or "")

    def dispose(self):
        if self._search_task is not None:
            self._search_task.cancel()
        if self._unsubscribe_theme is not None:
            self._unsubscribe_theme()
            self._unsubscribe_theme = None

    async def filter_all_on_click(self, _):
        self.current_filter = "all"
        await self.apply_filter()

    async def filter_recording_on_click(self, _):
        self.current_filter = "recording"
        await self.apply_filter()

    async def filter_living_on_click(self, _):
        self.current_filter = "living"
        await self.apply_filter()

    async def filter_error_on_click(self, _):
        self.current_filter = "error"
        await self.apply_filter()

    async def filter_offline_on_click(self, _):
        self.current_filter = "offline"
        await self.apply_filter()

    async def filter_stopped_on_click(self, _):
        self.current_filter = "stopped"
        await self.apply_filter()

    def matches_search(self, recording):
        query = getattr(self, "search_query", "").strip().casefold()
        return not query or any(
            query in str(getattr(recording, field, "") or "").casefold()
            for field in ("streamer_name", "url", "title", "display_title", "platform")
        )

    async def apply_filter(self):
        for key, button in getattr(self, "_filter_buttons", {}).items():
            button.style = self.filter_button_style(key == self.current_filter)
        cards_obj = self.app.record_card_manager.cards_obj
        visible_ids = set()
        for recording in self.app.record_manager.recordings:
            card_info = cards_obj.get(recording.rec_id)
            if not card_info:
                continue
            visible = RecordingFilters.should_show_recording(
                self.current_filter, self.current_platform_filter, recording
            ) and self.matches_search(recording)
            card_info["card"].visible = visible
            if visible:
                visible_ids.add(recording.rec_id)
        self.content_area.update()
        self.recording_card_area.update()
        return visible_ids

    async def reset_cards_visibility(self):
        self.search_query = ""
        if self.search_field is not None:
            self.search_field.value = ""
        await self.apply_filter()

    async def filter_recordings(self, query):
        self.search_query = query
        if self.search_field is not None:
            self.search_field.value = query
        return await self.apply_filter()

    def create_recordings_content_area(self):
        return ft.Column(
            expand=True,
            controls=[
                ft.Divider(height=1),
                ft.Container(content=self.loading_indicator, alignment=ft.alignment.Alignment.CENTER),
                self.recording_card_area,
            ],
            scroll=None if self.is_grid_view else ft.ScrollMode.AUTO,
        )

    async def add_record_cards(self):

        self.loading_indicator.visible = True
        self.loading_indicator.update()

        cards_to_create = []
        existing_cards = []

        for recording in self.app.record_manager.recordings:
            if recording.rec_id not in self.app.record_card_manager.cards_obj:
                cards_to_create.append(recording)
            else:
                existing_card = self.app.record_card_manager.cards_obj[recording.rec_id]["card"]
                existing_card.visible = True
                existing_cards.append(existing_card)

        async def create_card_with_time_range(_recording: Recording):
            _card = await self.app.record_card_manager.create_card(_recording)
            _recording.scheduled_time_range = await self.app.record_manager.get_scheduled_time_range(
                _recording.scheduled_start_time, _recording.monitor_hours
            )
            return _card, _recording

        if cards_to_create:
            results = await asyncio.gather(*[create_card_with_time_range(recording) for recording in cards_to_create])

            for card, recording in results:
                self.recording_card_area.content.controls.append(card)
                self.app.record_card_manager.cards_obj[recording.rec_id]["card"] = card

            if existing_cards:
                for card in existing_cards:
                    self.recording_card_area.content.controls.append(card)

        self.app.record_card_manager.reorder_recording_cards()
        self.loading_indicator.visible = False
        self.loading_indicator.update()
        self.recording_card_area.update()

        if not RecordingManager.is_periodic_task_running():
            self.page.run_task(
                self.app.record_manager.setup_periodic_live_check, self.app.record_manager.loop_time_seconds
            )

        await self.apply_filter()

    async def show_all_cards(self):
        cards_obj = self.app.record_card_manager.cards_obj
        for card in cards_obj.values():
            card["card"].visible = True
        self.recording_card_area.update()

        await self.apply_filter()

    async def add_recording(self, recordings_info):
        user_config = self.app.settings.user_config
        logger.info(f"Add items: {len(recordings_info)}")

        new_recordings = []
        for recording_info in recordings_info:
            if recording_info.get("record_format"):
                recording = Recording(
                    rec_id=str(uuid.uuid4()),
                    url=recording_info["url"],
                    streamer_name=recording_info["streamer_name"],
                    quality=recording_info["quality"],
                    record_format=recording_info["record_format"],
                    segment_record=recording_info["segment_record"],
                    segment_time=recording_info["segment_time"],
                    monitor_status=recording_info["monitor_status"],
                    scheduled_recording=recording_info["scheduled_recording"],
                    scheduled_start_time=recording_info["scheduled_start_time"],
                    monitor_hours=recording_info["monitor_hours"],
                    recording_dir=recording_info["recording_dir"],
                    enabled_message_push=recording_info["enabled_message_push"],
                    only_notify_no_record=recording_info["only_notify_no_record"],
                    flv_use_direct_download=recording_info["flv_use_direct_download"],
                    video_bitrate=recording_info["video_bitrate"],
                )
            else:
                recording = Recording(
                    rec_id=str(uuid.uuid4()),
                    url=recording_info["url"],
                    streamer_name=recording_info["streamer_name"],
                    quality=recording_info["quality"],
                    record_format=user_config.get("video_format", "TS"),
                    segment_record=user_config.get("segmented_recording_enabled", False),
                    segment_time=user_config.get("video_segment_time", "1800"),
                    monitor_status=True,
                    scheduled_recording=user_config.get("scheduled_recording", False),
                    scheduled_start_time=user_config.get("scheduled_start_time"),
                    monitor_hours=user_config.get("monitor_hours"),
                    recording_dir=None,
                    enabled_message_push=False,
                    only_notify_no_record=user_config.get("only_notify_no_record"),
                    flv_use_direct_download=user_config.get("flv_use_direct_download"),
                    video_bitrate=None,
                )

            platform, platform_key = get_platform_info(recording.url)
            if platform and platform_key:
                recording.platform = platform
                recording.platform_key = platform_key

            recording.loop_time_seconds = int(user_config.get("loop_time_seconds", 300))
            recording.update_title(self._[recording.quality])
            await self.app.record_manager.add_recording(recording)
            new_recordings.append(recording)

        if new_recordings:

            async def create_card_with_time_range(rec):
                _card = await self.app.record_card_manager.create_card(rec)
                rec.scheduled_time_range = await self.app.record_manager.get_scheduled_time_range(
                    rec.scheduled_start_time, rec.monitor_hours
                )
                return _card, rec

            results = await asyncio.gather(*[create_card_with_time_range(rec) for rec in new_recordings])

            for card, recording in results:
                self.recording_card_area.content.controls.append(card)
                self.app.record_card_manager.cards_obj[recording.rec_id]["card"] = card
                self.app.page.pubsub.send_others_on_topic("add", recording)

            self.app.record_card_manager.reorder_recording_cards()
            self.recording_card_area.update()

            self.content_area.controls[1] = self.create_filter_area()
            self.content_area.update()

            await self.app.snack_bar.show_snack_bar(self._["add_recording_success_tip"], bgcolor=ft.Colors.PRIMARY)

    async def search_on_click(self, _e):
        if self.search_field is not None:
            await self.search_field.focus()

    async def add_recording_on_click(self, _e):
        await self.add_recording_dialog.show_dialog()

    async def refresh_cards_on_click(self, _e):

        self.loading_indicator.visible = True
        self.loading_indicator.update()

        cards_obj = self.app.record_card_manager.cards_obj
        recordings = self.app.record_manager.recordings
        selected_cards = self.app.record_card_manager.selected_cards
        new_ids = {rec.rec_id for rec in recordings}
        to_remove = []
        for card_id, card in cards_obj.items():
            if card_id not in new_ids:
                to_remove.append(card)
                continue
            if card_id in selected_cards:
                selected_cards[card_id].selected = False
                self.app.record_card_manager.apply_card_material(card["card"].content, selected_cards[card_id])
                card["card"].update()

        for card in to_remove:
            card_key = card["card"].key
            cards_obj.pop(card_key, None)
            self.recording_card_area.content.controls.remove(card["card"])
        await self.show_all_cards()
        self.app.record_card_manager.reorder_recording_cards()

        self.content_area.controls[1] = self.create_filter_area()
        self.content_area.update()

        self.loading_indicator.visible = False
        self.loading_indicator.update()

        await self.app.snack_bar.show_snack_bar(self._["refresh_success_tip"], bgcolor=ft.Colors.PRIMARY)

    async def start_monitor_recordings_on_click(self, _):
        await self.app.record_manager.check_free_space()
        if self.app.recording_enabled:
            await self.app.record_manager.start_monitor_recordings()
            await self.app.snack_bar.show_snack_bar(self._["start_recording_success_tip"], bgcolor=ft.Colors.PRIMARY)

    async def stop_monitor_recordings_on_click(self, _):
        await self.app.record_manager.stop_monitor_recordings()
        await self.app.snack_bar.show_snack_bar(self._["stop_recording_success_tip"], bgcolor=ft.Colors.PRIMARY)

    async def delete_monitor_recordings_on_click(self, _):
        selected_recordings = await self.app.record_manager.get_selected_recordings()
        tips = self._["batch_delete_confirm_tip"] if selected_recordings else self._["clear_all_confirm_tip"]

        async def confirm_dlg(_):

            if selected_recordings:
                await self.app.record_manager.stop_monitor_recordings(selected_recordings)
                await self.app.record_manager.delete_recording_cards(selected_recordings)
            else:
                await self.app.record_manager.stop_monitor_recordings(self.app.record_manager.recordings)
                await self.app.record_manager.clear_all_recordings()
                await self.delete_all_recording_cards()
                self.app.page.pubsub.send_others_on_topic("delete_all", None)

            self.content_area.controls[1] = self.create_filter_area()
            self.content_area.update()

            self.recording_card_area.update()
            await self.app.snack_bar.show_snack_bar(
                self._["delete_recording_success_tip"], bgcolor=ft.Colors.PRIMARY, duration=2000
            )
            await close_dialog(None)

        async def close_dialog(_):
            batch_delete_alert_dialog.open = False
            batch_delete_alert_dialog.update()

        batch_delete_alert_dialog = ft.AlertDialog(
            title=ft.Text(self._["confirm"]),
            content=ft.Text(tips),
            actions=[
                ft.TextButton(content=self._["cancel"], on_click=close_dialog),
                ft.TextButton(content=self._["sure"], on_click=confirm_dlg),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            modal=False,
        )

        batch_delete_alert_dialog.open = True
        self.app.dialog_area.content = batch_delete_alert_dialog
        self.page.update()

    async def delete_all_recording_cards(self):
        self.recording_card_area.content.controls.clear()
        self.recording_card_area.update()
        self.app.record_card_manager.cards_obj = {}

        self.current_platform_filter = "all"

        self.content_area.controls[1] = self.create_filter_area()
        self.content_area.update()

    async def subscribe_del_all_cards(self, *_):
        await self.delete_all_recording_cards()

    async def subscribe_add_cards(self, _, recording: Recording):
        """Handle the subscription of adding cards from other clients"""

        self.loading_indicator.visible = True
        self.loading_indicator.update()

        if recording.rec_id not in self.app.record_card_manager.cards_obj:
            card = await self.app.record_card_manager.create_card(recording, subscribe_add_cards=True)
            recording.scheduled_time_range = await self.app.record_manager.get_scheduled_time_range(
                recording.scheduled_start_time, recording.monitor_hours
            )

            self.recording_card_area.content.controls.append(card)
            self.app.record_card_manager.cards_obj[recording.rec_id]["card"] = card

            self.app.record_card_manager.reorder_recording_cards()
            self.recording_card_area.update()

            self.content_area.controls[1] = self.create_filter_area()
            self.content_area.update()

        self.loading_indicator.visible = False
        self.loading_indicator.update()

    async def update_grid_layout(self, event):
        if event.width <= 0:
            return
        self._grid_width = event.width
        await self.recalculate_grid_columns()

    def get_grid_available_width(self):
        return self._grid_width or self.CARD_MIN_WIDTH

    def get_grid_runs_count(self):
        column_width = self.CARD_MIN_WIDTH
        available_width = self.get_grid_available_width()
        spacing = self.CARD_SPACING
        return max(1, int((available_width + spacing) / (column_width + spacing)))

    def get_grid_child_aspect_ratio(self):
        columns = self.get_grid_runs_count()
        card_width = (self.get_grid_available_width() - (columns - 1) * self.CARD_SPACING) / columns
        return card_width / self.CARD_HEIGHT

    async def recalculate_grid_columns(self):
        if not self.is_grid_view:
            return

        runs_count = self.get_grid_runs_count()
        child_aspect_ratio = self.get_grid_child_aspect_ratio()
        spacing = self.CARD_SPACING

        if isinstance(self.recording_card_area.content, ft.GridView):
            grid_view = self.recording_card_area.content
            if (
                grid_view.runs_count == runs_count
                and grid_view.child_aspect_ratio == child_aspect_ratio
                and grid_view.spacing == spacing
                and grid_view.run_spacing == spacing
                and grid_view.padding == 0
            ):
                return
            grid_view.runs_count = runs_count
            grid_view.child_aspect_ratio = child_aspect_ratio
            grid_view.spacing = spacing
            grid_view.run_spacing = spacing
            grid_view.padding = 0
            grid_view.update()

    async def on_keyboard(self, e: ft.KeyboardEvent):
        if e.alt and e.key == "H":
            self.app.dialog_area.content = HelpDialog(self.app)
            self.app.dialog_area.content.open = True
            self.app.dialog_area.update()
        if self.app.current_page == self:
            if e.ctrl and e.key == "F":
                self.page.run_task(self.search_on_click, e)
            elif e.ctrl and e.key == "R":
                self.page.run_task(self.refresh_cards_on_click, e)
            elif e.alt and e.key == "N":
                self.page.run_task(self.add_recording_on_click, e)
            elif e.alt and e.key == "B":
                self.page.run_task(self.start_monitor_recordings_on_click, e)
            elif e.alt and e.key == "P":
                self.page.run_task(self.stop_monitor_recordings_on_click, e)
            elif e.alt and e.key == "D":
                self.page.run_task(self.delete_monitor_recordings_on_click, e)

    def on_platform_dropdown_change(self, e):
        self.current_platform_filter = e.control.value
        self.page.run_task(self.apply_filter)
