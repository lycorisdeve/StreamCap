import json
import runpy
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app.core.runtime import paths
from scripts.build import arrange_windows_package


class WindowsLayoutTests(unittest.TestCase):
    def create_package(self, root):
        internal = root / "_internal"
        for name in ("config", "assets/icons", "locales", "ffmpeg", "node", "flet_desktop/app"):
            (internal / name).mkdir(parents=True)
        (internal / "config/default_settings.json").write_text('{"language":"zh_CN"}')
        (internal / "config/language.json").write_text("{}")
        (internal / "config/version.json").write_text(json.dumps({"version_updates": [{"version": "1.2.3"}]}))
        for name in ("assets/icon.ico", "locales/zh_CN.json", "ffmpeg/ffmpeg.exe", "node/node.exe", "python312.dll"):
            (internal / name).write_bytes(b"fixture")
        with zipfile.ZipFile(internal / "flet_desktop/app/flet-windows.zip", "w") as archive:
            archive.writestr("flet/flet.exe", b"client")
        arrange_windows_package(root)

    def load_paths(self, root, profile):
        with (
            patch.object(paths.sys, "frozen", True, create=True),
            patch.object(paths.sys, "platform", "win32"),
            patch.object(paths.sys, "executable", str(root / "StreamCap.exe")),
            patch.dict(paths.os.environ, {"APPDATA": str(profile)}),
        ):
            values = runpy.run_path(paths.__file__)
            values["prepare_user_data_dir"]()
            return values

    def test_fresh_package_uses_portable_application_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "package"
            self.create_package(root)
            values = self.load_paths(root, Path(directory) / "profile")
            assert values["user_data_dir"].samefile(root)
            assert values["assets_dir"].samefile(root / "resources")
            assert values["locales_dir"].samefile(root / "resources/locales")
            assert values["runtime_dir"].samefile(root / "runtime")
            assert values["log_dir"] == root.resolve() / "logs"
            for unused in (
                "logs",
                "data",
                "resources/templates",
                "resources/styles",
                "runtime/drivers",
                "runtime/plugins",
                "_internal/flet_desktop/app",
            ):
                assert not (root / unused).exists(), unused
            assert values["default_recordings_dir"].relative_to(root.resolve()) == Path("data/recordings")
            assert (root / "version.txt").read_text().strip() == "1.2.3"
            assert (root / "runtime/flet/flet.exe").read_bytes() == b"client"
            assert (root / "_internal/python312.dll").is_file()
            assert not (root / "_internal/assets").exists()
            assert not (root / "_internal/config").exists()
            assert not (root / "locales").exists()

    def test_existing_profile_database_stays_in_place(self):
        with tempfile.TemporaryDirectory() as directory:
            root, profile = Path(directory) / "package", Path(directory) / "profile"
            self.create_package(root)
            data = profile / "StreamCap"
            (data / "data/database").mkdir(parents=True)
            database = data / "data/database/recordings.db"
            database.write_bytes(b"existing history")
            values = self.load_paths(root, profile)
            assert values["user_data_dir"].samefile(data)
            assert database.read_bytes() == b"existing history"
            assert not (root / "data/database/recordings.db").exists()
            assert values["locales_dir"].samefile(root / "resources/locales")

    def test_portable_data_wins_over_profile_and_keeps_existing_recording_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root, profile = Path(directory) / "package", Path(directory) / "profile"
            self.create_package(root)
            (root / "config/user_settings.json").write_text('{"custom":true}')
            (root / "downloads").mkdir()
            (profile / "StreamCap/config").mkdir(parents=True)
            (profile / "StreamCap/config/user_settings.json").write_text("{}")
            values = self.load_paths(root, profile)
            assert values["user_data_dir"].samefile(root)
            assert values["default_recordings_dir"].samefile(root / "downloads")
            assert (root / "config/user_settings.json").read_text() == '{"custom":true}'
