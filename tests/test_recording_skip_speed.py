import asyncio
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.core.recording.recording_repository import RecordingRepository
from app.core.recording.recording_speed import RecordingSpeedSampler
from app.core.recording.stream_manager import LiveStreamRecorder
from app.models.recording.recording_model import Recording
from app.ui.components.business.recording_card import RecordingCardManager
from tests.test_recording_sort import manager, room


class SpeedTests(unittest.TestCase):
    def test_direct_counter_and_zero_growth(self):
        with patch("app.core.recording.recording_speed.time.monotonic", side_effect=[0, 1, 2, 3]):
            sampler = RecordingSpeedSampler()
            assert sampler.sample(1024) == "1 KB/s"
            assert sampler.sample(1024) == "0 KB/s"
            assert sampler.sample(1024 + 1048576) == "1.0 MB/s"

    def test_old_segments_and_completed_segment_deletion(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = [Path(directory) / f"room_{i:03d}.ts" for i in range(2)]
            first.write_bytes(b"x" * 10)
            second.write_bytes(b"x" * 20)
            with patch("app.core.recording.recording_speed.time.monotonic", side_effect=[0, 1, 2, 3]):
                sampler = RecordingSpeedSampler(str(Path(directory) / "room_%03d.ts"), True)
                first.write_bytes(b"a" * 1024)
                assert sampler.sample() == "1 KB/s"
                assert sampler.index == 0
                second.write_bytes(b"b" * 2048)
                assert sampler.sample() == "2 KB/s"
                first.unlink()
                assert sampler.sample() == "0 KB/s"

    def test_skip_roundtrip_preserves_history_and_resets_observations(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = RecordingRepository(SimpleNamespace(config_path=directory, database_path=directory))
            repo.initialize()
            rec = room("test", skip_current_live=True)
            rec.offline_confirmation_count = 1
            repo.save_recordings_sync([rec.to_dict()])
            loaded = Recording.from_dict(repo.load_recordings()[0])
            assert loaded.skip_current_live
            assert loaded.offline_confirmation_count == 0
            with repo._connect() as conn:
                assert conn.execute("SELECT value FROM recording_meta WHERE key='schema_version'").fetchone()[0] == "3"


class SkipTests(unittest.IsolatedAsyncioTestCase):
    def setup_room(self):
        rec = room(
            "test", monitor_status=True, skip_current_live=True, quality="OD", platform="test", platform_key="test"
        )
        rec.loop_time_seconds = 180
        mgr = manager(rec)
        mgr.loop_time_seconds = 180
        mgr.settings = SimpleNamespace(user_config={}, get_video_save_path=lambda: ".")
        mgr.platform_semaphores = defaultdict(lambda: asyncio.Semaphore(1))
        mgr.check_free_space = AsyncMock()
        mgr.repository = SimpleNamespace(save_recordings=AsyncMock())
        mgr._.update(live_room="room", OD="original", is_live="live")
        return rec, mgr

    async def test_offline_confirmation_requires_two_spaced_observations(self):
        rec, mgr = self.setup_room()
        recorder = SimpleNamespace(
            fetch_stream=AsyncMock(return_value=SimpleNamespace(anchor_name="test", is_live=False))
        )
        with (
            patch("app.core.recording.record_manager.LiveStreamRecorder", return_value=recorder),
            patch("app.core.recording.record_manager.get_platform_info", return_value=("test", "test")),
            patch("app.core.recording.record_manager.time.monotonic", side_effect=[0, 1, 181]),
        ):
            await mgr.check_if_live(rec)
            await mgr.check_if_live(rec)
            assert rec.skip_current_live
            assert rec.offline_confirmation_count == 1
            await mgr.check_if_live(rec)
            assert not rec.skip_current_live
        mgr.repository.save_recordings.assert_awaited_once()

    async def test_live_check_keeps_skip_and_resets_offline_observation(self):
        rec, mgr = self.setup_room()
        rec.is_live = True
        rec.offline_confirmation_count = 1
        recorder = SimpleNamespace(
            fetch_stream=AsyncMock(return_value=SimpleNamespace(anchor_name="test", is_live=True, title="live")),
            start_recording=AsyncMock(),
        )
        with (
            patch("app.core.recording.record_manager.LiveStreamRecorder", return_value=recorder),
            patch("app.core.recording.record_manager.get_platform_info", return_value=("test", "test")),
            patch(
                "app.core.recording.record_manager.message_pusher.MessagePusher.should_push_message", return_value=False
            ),
        ):
            await mgr.check_if_live(rec)
        assert rec.skip_current_live
        assert rec.offline_confirmation_count == 0
        assert not rec.is_recording
        recorder.start_recording.assert_not_called()

    async def test_invalid_result_resets_offline_confirmation(self):
        rec, mgr = self.setup_room()
        rec.offline_confirmation_count = 1
        recorder = SimpleNamespace(fetch_stream=AsyncMock(return_value=None))
        with (
            patch("app.core.recording.record_manager.LiveStreamRecorder", return_value=recorder),
            patch("app.core.recording.record_manager.get_platform_info", return_value=("test", "test")),
        ):
            await mgr.check_if_live(rec)
        assert rec.skip_current_live
        assert rec.offline_confirmation_count == 0

    async def test_overlapping_checks_only_count_once(self):
        rec, mgr = self.setup_room()
        entered, release = asyncio.Event(), asyncio.Event()

        async def fetch():
            entered.set()
            await release.wait()
            return SimpleNamespace(anchor_name="test", is_live=False)

        recorder = SimpleNamespace(fetch_stream=AsyncMock(side_effect=fetch))
        with (
            patch("app.core.recording.record_manager.LiveStreamRecorder", return_value=recorder),
            patch("app.core.recording.record_manager.get_platform_info", return_value=("test", "test")),
        ):
            task = asyncio.create_task(mgr.check_if_live(rec))
            await entered.wait()
            await mgr.check_if_live(rec)
            release.set()
            await task
        assert rec.offline_confirmation_count == 1
        recorder.fetch_stream.assert_awaited_once()

    async def test_stop_preserves_live_and_waits_for_owner(self):
        rec, mgr = self.setup_room()
        rec.is_live = rec.is_recording = True
        owner = SimpleNamespace(request_stop=Mock())
        mgr.active_recorders[rec.rec_id] = owner
        assert await mgr.request_recording_stop(rec)
        assert rec.is_live
        assert rec.skip_current_live
        assert rec.stopping_in_progress
        assert await mgr.request_recording_start(rec) == "busy"
        owner.request_stop.assert_called_once()

    async def test_save_failure_keeps_skip(self):
        rec, mgr = self.setup_room()
        mgr.repository.save_recordings.side_effect = OSError("disk unavailable")
        assert await mgr.request_recording_start(rec) == "save_failed"
        assert rec.skip_current_live
        assert not await mgr.request_recording_stop(rec)
        assert rec.skip_current_live

    async def test_stale_owner_cannot_clear_new_owner(self):
        rec, mgr = self.setup_room()
        owner = LiveStreamRecorder.__new__(LiveStreamRecorder)
        owner.recording = rec
        owner.services = SimpleNamespace(recording_manager=mgr, broadcast_card_update=Mock())
        replacement = object()
        mgr.active_recorders[rec.rec_id] = replacement
        rec.speed = "2 MB/s"
        await owner.remove_active_recorder()
        assert mgr.active_recorders[rec.rec_id] is replacement
        assert rec.speed == "2 MB/s"

    async def test_ui_tick_refreshes_speed_with_duration(self):
        rec, mgr = self.setup_room()
        rec.is_recording = True
        rec.speed = "512 KB/s"
        duration, speed = SimpleNamespace(value="", update=Mock()), SimpleNamespace(value="", update=Mock())
        ui = RecordingCardManager.__new__(RecordingCardManager)
        ui._ = {"recording_speed": "Rate"}
        ui.cards_obj = {rec.rec_id: {"duration_label": duration, "speed_label": speed}}
        ui.app = SimpleNamespace(current_page=SimpleNamespace(page_name="recordings"), record_manager=mgr)
        mgr.get_duration = Mock(return_value="00:00:01")
        calls = 0

        async def tick(_):
            nonlocal calls
            calls += 1
            if calls == 2:
                ui.cards_obj.clear()

        with patch("app.ui.components.business.recording_card.asyncio.sleep", side_effect=tick):
            await ui.update_duration(rec)
        assert speed.value == "Rate: 512 KB/s"
        assert duration.value == "00:00:01"
        speed.update.assert_called_once()

    async def test_schedule_does_not_count_as_offline(self):
        rec, mgr = self.setup_room()
        rec.scheduled_recording = True
        rec.offline_confirmation_count = 1
        mgr.get_scheduled_time_range = AsyncMock(return_value=["01:00~02:00"])
        with patch("app.core.recording.record_manager.utils.is_current_time_within_range", return_value=False):
            await mgr.check_if_live(rec)
        assert rec.skip_current_live
        assert rec.offline_confirmation_count == 0
