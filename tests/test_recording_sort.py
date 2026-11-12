import asyncio
import runpy
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.core.recording.record_manager import GlobalRecordingState, RecordingManager
from app.core.recording.recording_repository import RecordingRepository
from app.core.runtime import paths
from app.core.runtime.scheduled_shutdown import ScheduledShutdownManager
from app.models.recording.recording_model import Recording
from app.ui.components.business.recording_card import RecordingCardManager


def room(rec_id, **values):
    return Recording.from_dict(
        {
            "rec_id": rec_id,
            "url": "https://example.com/live",
            "streamer_name": rec_id,
            "created_at": "2026-01-01",
            **values,
        }
    )


def manager(*rooms):
    result = RecordingManager.__new__(RecordingManager)
    result.services = SimpleNamespace(
        recording_enabled=True,
        broadcast_card_update=Mock(),
        broadcast_pubsub=Mock(),
        run_coro=lambda coro: coro.close(),
    )
    result.active_recorders = {}
    result._ = {"monitor_stopped": "stopped"}
    GlobalRecordingState.recordings = list(rooms)
    return result


class OrderingTests(unittest.TestCase):
    def tearDown(self):
        GlobalRecordingState.recordings = []

    def test_groups_and_stopped_history(self):
        never = room("never", created_at="2026-12-01")
        old = room("old", last_recorded_at="2026-01-01")
        new = room("new", last_recorded_at="2026-02-01")
        watching = room("watching", monitor_status=True)
        recording = room("recording")
        recording.is_recording = True
        pinned = room("pinned", pinned_at="2026-01-01", pin_order=1)
        recent_pin = room("recent-pin", pinned_at="2026-01-02", pin_order=2)
        mgr = manager(never, new, watching, old, recording, pinned, recent_pin)
        mgr.sort_recordings()
        assert [r.rec_id for r in mgr.recordings] == [
            "recent-pin",
            "pinned",
            "recording",
            "watching",
            "new",
            "old",
            "never",
        ]

    def test_stable_ties_and_monitor_recency(self):
        first, second = room("first"), room("second")
        recent = room("recent", monitor_status=True, last_recorded_at="2026-05-01")
        older = room("older", monitor_status=True, last_recorded_at="2026-03-01")
        mgr = manager(first, second, older, recent)
        mgr.sort_recordings()
        mgr.sort_recordings()
        assert [r.rec_id for r in mgr.recordings] == ["recent", "older", "first", "second"]

    def test_auto_start_and_stop(self):
        rec, other = room("rec", monitor_status=True), room("other", monitor_status=True)
        other.is_recording = True
        other.recording_sort_time = 1
        mgr = manager(other, rec)
        rec.is_live = True
        mgr.start_update(rec)
        mgr.sort_recordings()
        assert mgr.recordings[0] is rec
        mgr.stop_recording(rec)
        assert mgr.recordings[0] is other
        assert not rec.is_recording

    def test_reorder_preserves_controls_and_visibility_in_two_sessions(self):
        a, b = room("a"), room("b", pinned_at="2026-01-01", pin_order=1)
        mgr = manager(a, b)
        mgr.sort_recordings()
        for _ in range(2):
            ca = SimpleNamespace(key="a", visible=False, selected=True)
            cb = SimpleNamespace(key="b", visible=True)
            area = SimpleNamespace(content=SimpleNamespace(controls=[ca, cb]), update=Mock())
            cards = RecordingCardManager.__new__(RecordingCardManager)
            cards.app = SimpleNamespace(record_manager=mgr, current_page=SimpleNamespace(recording_card_area=area))
            cards.cards_obj = {"a": {"card": ca}, "b": {"card": cb}}
            cards.reorder_recording_cards()
            cards.reorder_recording_cards()
            assert area.content.controls == [cb, ca]
            assert not ca.visible
            assert ca.selected
            area.update.assert_called_once()


class RequestTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        GlobalRecordingState.recordings = []

    async def test_immediate_promotion_duplicate_guard_and_offline_restore(self):
        pinned = room("pinned", pinned_at="2026-01-01")
        active = room("active")
        active.is_recording = True
        active.recording_sort_time = 1
        rec = room("request", monitor_status=True)
        mgr = manager(pinned, active, rec)
        entered, release = asyncio.Event(), asyncio.Event()

        async def slow_check(_):
            entered.set()
            await release.wait()

        mgr.check_if_live = AsyncMock(side_effect=slow_check)
        task = asyncio.create_task(mgr.request_recording_start(rec))
        await entered.wait()
        assert [r.rec_id for r in mgr.recordings] == ["pinned", "request", "active"]
        assert not rec.is_recording
        assert rec.last_recorded_at is None
        await mgr.request_recording_start(rec)
        mgr.check_if_live.assert_awaited_once()
        release.set()
        await task
        assert not rec.recording_start_pending
        assert [r.rec_id for r in mgr.recordings] == ["pinned", "active", "request"]

    async def test_failure_and_cancellation_clear_pending(self):
        for error in (RuntimeError("offline"), asyncio.CancelledError()):
            rec = room("rec", monitor_status=True)
            mgr = manager(rec)
            mgr.check_if_live = AsyncMock(side_effect=error)
            with self.assertRaises(type(error)):  # noqa: PT027 - standard-library unittest suite
                await mgr.request_recording_start(rec)
            assert not rec.recording_start_pending
            assert rec.last_recorded_at is None

    async def test_success_keeps_request_order_without_persisting_pending_state(self):
        rec = room("rec", monitor_status=True)
        mgr = manager(rec)
        request_times = []

        async def start(recording):
            request_times.append(recording.recording_sort_time)
            recording.is_live = True
            mgr.start_update(recording)

        mgr.check_if_live = AsyncMock(side_effect=start)
        await mgr.request_recording_start(rec)
        assert rec.is_recording
        assert not rec.recording_start_pending
        assert rec.recording_sort_time == request_times[0]
        assert "recording_start_pending" not in rec.to_dict()
        assert mgr.services.broadcast_card_update.call_count == 2

    async def test_ineligible_request_does_not_start(self):
        rec = room("rec", monitor_status=False)
        mgr = manager(rec)
        mgr.check_if_live = AsyncMock()
        await mgr.request_recording_start(rec)
        mgr.check_if_live.assert_not_called()

    async def test_stop_monitor_during_real_check_discards_live_result(self):
        rec = room("rec", monitor_status=True, platform="test", platform_key="test")
        mgr = manager(rec)
        mgr.settings = SimpleNamespace(user_config={}, get_video_save_path=lambda: ".")
        mgr.platform_semaphores = defaultdict(lambda: asyncio.Semaphore(1))
        mgr.check_free_space = AsyncMock()
        entered, release = asyncio.Event(), asyncio.Event()

        async def fetch():
            entered.set()
            await release.wait()
            return SimpleNamespace(anchor_name="live", is_live=True)

        recorder = SimpleNamespace(fetch_stream=AsyncMock(side_effect=fetch), start_recording=AsyncMock())
        with (
            patch("app.core.recording.record_manager.get_platform_info", return_value=("test", "test")),
            patch("app.core.recording.record_manager.LiveStreamRecorder", return_value=recorder),
        ):
            task = asyncio.create_task(mgr.request_recording_start(rec))
            await entered.wait()
            await mgr.stop_monitor_recording(rec, auto_save=False)
            release.set()
            await task
        assert not rec.is_recording
        assert not rec.recording_start_pending
        assert not rec.monitor_status
        recorder.start_recording.assert_not_called()

    async def test_clear_history_reorders_and_notifies(self):
        a = room("a", last_recorded_at="2026-04-01", created_at="2026-01-01")
        b = room("b", created_at="2026-02-01")
        mgr = manager(a, b)
        mgr.repository = SimpleNamespace(clear_recording_history=AsyncMock(return_value=1))
        assert await mgr.clear_recording_history() == 1
        assert [r.rec_id for r in mgr.recordings] == ["b", "a"]
        assert mgr.services.broadcast_card_update.call_count == 2


class PersistenceTests(unittest.TestCase):
    def test_old_schema_upgrade_and_bitrate_roundtrip_preserve_history(self):
        with tempfile.TemporaryDirectory() as directory:
            config = SimpleNamespace(
                config_path=str(Path(directory) / "config"), database_path=str(Path(directory) / "data")
            )
            repo = RecordingRepository(config)
            repo.initialize()
            rec = room("room", pinned_at="2026-01-01", pin_order=42)
            repo.save_recordings_sync([rec.to_dict()])
            repo.add_recording_history_sync(
                {"rec_id": "room", "status": "completed", "ended_at": "2026-03-01", "file_path": "old.ts"}
            )
            with repo._connect() as conn:
                conn.execute("ALTER TABLE recording_rooms DROP COLUMN video_bitrate")
                conn.execute("UPDATE recording_meta SET value = '1' WHERE key = 'schema_version'")
            repo.initialize()
            loaded = Recording.from_dict(repo.load_recordings()[0])
            assert loaded.pin_order == 42
            assert loaded.last_recorded_at == "2026-03-01"
            assert loaded.video_bitrate is None
            loaded.video_bitrate = 2500
            loaded.recording_start_pending = True
            repo.save_recordings_sync([loaded.to_dict()])
            restored = Recording.from_dict(repo.load_recordings()[0])
            assert restored.video_bitrate == 2500
            assert not restored.recording_start_pending
            assert repo.list_recording_history("room")[0]["file_path"] == "old.ts"

    def test_existing_portable_installation_keeps_data_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "_internal").mkdir()
            (root / "data/database").mkdir(parents=True)
            (root / "data/database/recordings.db").touch()
            with (
                patch.object(paths.sys, "frozen", True, create=True),
                patch.object(paths.sys, "platform", "win32"),
                patch.object(paths.sys, "executable", str(root / "StreamCap.exe")),
            ):
                values = runpy.run_path(paths.__file__)
            assert values["user_data_dir"] == root
            assert values["resource_dir"] == root / "_internal"

    def test_bundled_defaults_do_not_overwrite_user_config(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "bundle", Path(directory) / "user"
            (source / "config").mkdir(parents=True)
            (target / "config").mkdir(parents=True)
            (source / "config/user_settings.json").write_text("defaults")
            (source / "config/default_settings.json").write_text("new default")
            (target / "config/user_settings.json").write_text("custom")
            with patch.object(paths, "resource_dir", source), patch.object(paths, "user_data_dir", target):
                paths.prepare_user_data_dir()
            assert (target / "config/user_settings.json").read_text() == "custom"
            assert (target / "config/default_settings.json").read_text() == "new default"


class ShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_quick_shutdown_and_cancel_use_mocked_system_command(self):
        app = SimpleNamespace(
            page=SimpleNamespace(web=False), settings=SimpleNamespace(user_config={}), subprocess_start_up_info=None
        )
        mgr = ScheduledShutdownManager(app)
        with (
            patch("app.core.runtime.scheduled_shutdown.sys.platform", "win32"),
            patch.object(mgr, "_translations", return_value={"quick_shutdown_system_message": "{hours}"}),
            patch(
                "app.core.runtime.scheduled_shutdown.subprocess.run", return_value=SimpleNamespace(returncode=0)
            ) as run,
        ):
            await mgr.start_quick_shutdown(1)
            assert mgr.quick_shutdown_at is not None
            await mgr.cancel_quick_shutdown()
            assert mgr.quick_shutdown_at is None
            assert run.call_count == 2


if __name__ == "__main__":
    unittest.main()
