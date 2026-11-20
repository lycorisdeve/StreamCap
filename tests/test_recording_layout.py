import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

from app.ui.views.recordings_view import RecordingsPage


class RecordingLayoutTests(unittest.IsolatedAsyncioTestCase):
    def make_view(self):
        view = RecordingsPage.__new__(RecordingsPage)
        view.is_grid_view = True
        view._grid_width = 0
        view.app = SimpleNamespace(is_mobile=False, current_page=view)
        view.page = SimpleNamespace(width=1920, window=SimpleNamespace(width=1920), run_task=Mock())
        cards = [ft.Card(key="pinned", visible=False, data="selected"), ft.Card(key="recording")]
        view.recording_card_area = ft.Container(content=ft.GridView(controls=cards))
        return view

    async def test_resizing_keeps_height_and_card_state_at_column_boundaries(self):
        view = self.make_view()
        grid = view.recording_card_area.content
        original = list(grid.controls)
        with patch.object(grid, "update"):
            for width in (240, 280, 571, 572, 863, 864, 958, 963, 1155, 1156, 1703, 280):
                await view.update_grid_layout(SimpleNamespace(width=width))
                columns = grid.runs_count
                card_width = (width - (columns - 1) * grid.run_spacing) / columns
                assert abs(card_width / grid.child_aspect_ratio - 108) < 0.001
                assert card_width >= min(width, 280)
                assert grid.padding == 0
                assert grid.spacing == grid.run_spacing == 12
                assert grid.controls == original
                assert grid.controls[0] is original[0]
                assert not grid.controls[0].visible
                assert grid.controls[0].data == "selected"

    async def test_mobile_round_trip_preserves_spacing_and_ignores_height_only_events(self):
        view = self.make_view()
        grid = view.recording_card_area.content
        with patch.object(grid, "update") as update:
            await view.update_grid_layout(SimpleNamespace(width=700))
            update.reset_mock()
            await view.update_grid_layout(SimpleNamespace(width=700))
            await view.update_grid_layout(SimpleNamespace(width=0))
            update.assert_not_called()
            view.app.is_mobile = True
            await view.update_grid_layout(SimpleNamespace(width=390))
            assert grid.spacing == grid.run_spacing == 12
            assert grid.child_aspect_ratio == 390 / 108
            view.app.is_mobile = False
            await view.update_grid_layout(SimpleNamespace(width=700))
            assert grid.spacing == grid.run_spacing == 12
            assert grid.padding == 0

    async def test_loading_recordings_preserves_global_resize_handler(self):
        view = self.make_view()
        handler = Mock()
        view.page.on_resize = handler
        view.content_area = SimpleNamespace(controls=[], update=Mock())
        view.create_recordings_title_area = Mock()
        view.create_filter_area = Mock()
        view.create_recordings_content_area = Mock()
        view.apply_filter = AsyncMock()
        view.recalculate_grid_columns = AsyncMock()
        await view.load()
        assert view.page.on_resize is handler
