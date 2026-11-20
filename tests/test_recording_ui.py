import asyncio
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

from app.models.recording.recording_status_model import RecordingStatus
from app.ui.components.business.recording_card import RecordingCardManager
from app.ui.themes.glass import FILTER_HEIGHT
from app.ui.themes.theme_tokens import build_tokens
from app.ui.views.recordings_view import RecordingsPage
from tests.test_recording_sort import room


class RecordingUiTests(unittest.IsolatedAsyncioTestCase):
    def make_view(self):
        view = RecordingsPage.__new__(RecordingsPage)
        view.page_name = "recordings"
        view.current_filter = "all"
        view.current_platform_filter = "all"
        view.search_query = ""
        view.search_field = None
        view._search_task = None
        view._search_revision = 0
        view._filter_buttons = {}
        view.is_grid_view = True
        view._grid_width = 0
        view._unsubscribe_theme = Mock()
        language = json.loads((Path(__file__).parents[1] / "locales/en.json").read_text(encoding="utf-8"))
        view._ = language["recordings_page"] | language["base"]
        view._.update(
            toolbar_add="Add", toolbar_start_all="Start all", toolbar_stop_all="Stop all", search_placeholder="Search"
        )
        recordings = [
            room("a", streamer_name="Alpha", platform="One", platform_key="one", monitor_status=True),
            room("b", streamer_name="Alpha", platform="Two", platform_key="two", monitor_status=True),
            room("c", streamer_name="Gamma", platform="One", platform_key="one", monitor_status=True),
        ]
        recordings[0].is_recording = True
        recordings[0].selected = True
        recordings[1].is_recording = True
        cards = {r.rec_id: {"card": ft.Card(key=r.rec_id)} for r in recordings}
        view.app = SimpleNamespace(
            current_page=view,
            is_mobile=False,
            record_manager=SimpleNamespace(recordings=recordings),
            record_card_manager=SimpleNamespace(cards_obj=cards),
        )
        view.page = SimpleNamespace(run_task=lambda fn, *args: asyncio.create_task(fn(*args)))
        view.content_area = SimpleNamespace(update=Mock(), controls=[])
        view.recording_card_area = SimpleNamespace(
            update=Mock(), content=ft.GridView(controls=[c["card"] for c in cards.values()])
        )
        return view

    async def test_search_status_platform_intersect_and_keep_card_identity(self):
        view = self.make_view()
        original = list(view.recording_card_area.content.controls)
        view.current_filter = "recording"
        view.current_platform_filter = "one"
        assert await view.filter_recordings("aLPha") == {"a"}
        await view.filter_stopped_on_click(None)
        assert not any(card.visible for card in original)
        assert view.search_query == "aLPha"
        await view.filter_all_on_click(None)
        assert original[0].visible
        assert not original[1].visible
        assert await view.filter_recordings(" ") == {"a", "c"}
        assert all(a is b for a, b in zip(original, view.recording_card_area.content.controls))
        assert view.app.record_manager.recordings[0].selected

    async def test_search_debounces_latest_value_and_ctrl_f_focuses_existing_field(self):
        view = self.make_view()
        toolbar = view.create_recordings_title_area()
        assert toolbar.controls[0].wrap
        assert view.search_field is toolbar.controls[1].controls[0].content
        field = view.search_field
        with patch.object(field, "focus", new_callable=AsyncMock) as focus:
            await view.on_keyboard(SimpleNamespace(ctrl=True, alt=False, key="F"))
            await asyncio.sleep(0)
            focus.assert_awaited_once()
        await view.on_search_change(SimpleNamespace(control=SimpleNamespace(value="Alpha")))
        first = view._search_task
        await view.on_search_change(SimpleNamespace(control=SimpleNamespace(value="Gamma")))
        await asyncio.gather(first, view._search_task, return_exceptions=True)
        assert first.cancelled()
        assert [c.key for c in view.recording_card_area.content.controls if c.visible] == ["c"]
        view.create_recordings_title_area()
        assert view.search_field is field
        view.dispose()

    async def test_filter_selection_uses_theme_and_keeps_semantic_icon_colors(self):
        view = self.make_view()
        tokens = build_tokens("#123456")
        view.app.theme_manager = SimpleNamespace(tokens=tokens)
        filters = view.create_filter_area()
        assert filters.controls[0].controls[0].value == f"{view._['status_filter']}："
        assert filters.controls[0].controls[0].weight == ft.FontWeight.BOLD
        dropdown = filters.controls[1].controls[0].content
        assert dropdown.label == view._["platform_filter"]
        assert dropdown.height == FILTER_HEIGHT
        assert all(button.height == dropdown.height for button in view._filter_buttons.values())
        button = view._filter_buttons["recording"]
        color = button.content.controls[0].color
        await view.filter_recording_on_click(None)
        assert button.style.bgcolor[ft.ControlState.DEFAULT] == "#123456"
        view.app.theme_manager.tokens = build_tokens("#654321")
        view.refresh_theme()
        assert view._filter_buttons["recording"] is button
        assert button.style.bgcolor[ft.ControlState.DEFAULT] == "#654321"
        assert button.content.controls[0].color == color == ft.Colors.GREEN

    def make_card_manager(self):
        language = json.loads((Path(__file__).parents[1] / "locales/en.json").read_text(encoding="utf-8"))
        callbacks = []
        unsubscribe = Mock()
        theme = SimpleNamespace(
            tokens=build_tokens("#7555F6"),
            subscribe=lambda callback: callbacks.append(callback) or unsubscribe,
            motion_duration=AsyncMock(return_value=200),
        )
        app = SimpleNamespace(
            language_manager=SimpleNamespace(language=language, add_observer=Mock()),
            theme_manager=theme,
            page=SimpleNamespace(pubsub=SimpleNamespace(subscribe_topic=Mock()), update=Mock()),
            record_manager=SimpleNamespace(get_duration=Mock(return_value="0:01:00")),
            current_page=SimpleNamespace(page_name="recordings"),
        )
        manager = RecordingCardManager(app)
        return manager, theme, callbacks, unsubscribe

    async def test_existing_card_refreshes_status_metrics_and_actions_together(self):
        manager, _, _, _ = self.make_card_manager()
        manager.app.record_manager.sort_recordings = Mock()
        manager.app.current_page.apply_filter = AsyncMock()
        rec = room("a", monitor_status=True)
        data = manager._create_card_components(rec)
        manager.cards_obj[rec.rec_id] = data
        badge = data["status_label"]
        for active in (True, False):
            rec.is_recording = active
            rec.speed = "12.3 MB/s" if active else ""
            await manager.update_card(rec)
            assert data["status_label"] is badge
            assert badge.content.value == manager._["recording" if active else "offline"]
            assert data["duration_icon"].icon == (ft.Icons.FIBER_MANUAL_RECORD if active else ft.Icons.SCHEDULE)
            assert data["speed_icon"].visible == active
            assert data["speed_label"].value == rec.speed
            assert data["record_button"].icon == (ft.Icons.STOP_CIRCLE if active else ft.Icons.PLAY_CIRCLE)
        manager.dispose()

    async def test_card_theme_changes_preserve_status_skip_speed_and_actions(self):
        manager, theme, callbacks, unsubscribe = self.make_card_manager()
        rec = room("a", skip_current_live=True, selected=True, monitor_status=True)
        rec.selected = True
        rec.speed = "1.2 MB/s"
        card_data = manager._create_card_components(rec)
        manager.cards_obj[rec.rec_id] = card_data
        card = card_data["card"]
        status = card_data["status_label"]
        border = card.content.border
        assert card.content.bgcolor == theme.tokens.selected_background
        assert card_data["speed_label"].value == "1.2 MB/s"
        assert card_data["speed_icon"].icon == ft.Icons.DOWNLOAD_ROUNDED
        assert card_data["speed_icon"].visible
        assert card_data["duration_label"].value == "0:01:00"
        assert card_data["duration_icon"].icon == ft.Icons.SCHEDULE
        assert border.top.width == 1
        assert border.top.color == ft.Colors.with_opacity(0.76, ft.Colors.AMBER)
        assert status.tooltip == manager._["skip_condition"]
        assert len(card_data["action_buttons"]) == 7
        assert all(button.on_click and button.expand for button in card_data["action_buttons"])
        theme.tokens = build_tokens("#0EAFA0", dark=True)
        callbacks[0]()
        assert manager.cards_obj[rec.rec_id]["card"] is card
        assert card.content.bgcolor == theme.tokens.selected_background
        assert card.content.border == border
        assert card_data["status_label"] is status
        assert all(
            button.focus_color == ft.Colors.with_opacity(0.12, theme.tokens.focus_ring)
            for button in card_data["action_buttons"]
        )
        assert all(
            button.style.side[ft.ControlState.FOCUSED].color == theme.tokens.focus_ring
            for button in card_data["action_buttons"]
        )
        with patch.object(card.content, "update"):
            await manager.on_card_hover(SimpleNamespace(data=True, control=card.content), rec)
            theme.motion_duration.assert_awaited_once()
            assert card.content.bgcolor == theme.tokens.selected_background
            assert card.content.offset.y < 0
            assert card.content.border.top.width == 1
            assert card.content.border.top.color == ft.Colors.with_opacity(1, ft.Colors.AMBER)
            rec.selected = False
            assert await manager.update_record_hover(rec) == theme.tokens.primary_light
        manager.dispose()
        unsubscribe.assert_called_once()

    async def test_reduced_motion_hover_keeps_card_stationary_and_preserves_interaction(self):
        manager, theme, _, _ = self.make_card_manager()
        theme.motion_duration.return_value = 0
        rec = room("a", monitor_status=True)
        card = manager._create_card_components(rec)["card"]
        with patch.object(card.content, "update"):
            await manager.on_card_hover(SimpleNamespace(data=True, control=card.content), rec)
            assert card.content.offset.x == card.content.offset.y == 0
            assert card.content.animate.duration == card.content.animate_offset.duration == 0
            assert card.content.bgcolor == theme.tokens.primary_light
            await manager.on_card_hover(SimpleNamespace(data=False, control=card.content), rec)
            assert card.content.offset.y == 0
            assert card.content.bgcolor is None
        manager.dispose()

    async def test_state_borders_and_duration_icons_remain_semantic_under_both_themes(self):
        manager, theme, _, _ = self.make_card_manager()
        states = (
            ({"is_recording": True}, ft.Colors.GREEN),
            ({"is_live": True}, ft.Colors.BLUE),
            ({"is_checking": True}, ft.Colors.PURPLE),
            ({}, ft.Colors.AMBER),
            ({"status_info": RecordingStatus.RECORDING_ERROR}, ft.Colors.RED),
            ({"monitor_status": False}, ft.Colors.GREY_200),
        )
        for dark in (False, True):
            theme.tokens = build_tokens("#EC599A", dark=dark)
            for values, color in states:
                with self.subTest(dark=dark, state=values):
                    rec = room("a", monitor_status=True)
                    rec.speed = ""
                    for name, value in values.items():
                        setattr(rec, name, value)
                    data = manager._create_card_components(rec)
                    border = data["card"].content.border
                    for side in (border.top, border.bottom, border.left, border.right):
                        assert side.width == 1
                        assert side.color == ft.Colors.with_opacity(0.76, color)
                    expected_icon = ft.Icons.FIBER_MANUAL_RECORD if rec.is_recording else ft.Icons.SCHEDULE
                    assert data["duration_icon"].icon == expected_icon
                    assert data["speed_label"].value == ""
                    assert not data["speed_icon"].visible
        manager.dispose()
