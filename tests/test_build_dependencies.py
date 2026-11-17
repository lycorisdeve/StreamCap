import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import build


class DesktopArchiveTests(unittest.TestCase):
    def test_package_includes_defaults_and_never_local_user_data(self):
        args = SimpleNamespace(bundle_ffmpeg=False, bundle_node=False, clean=False)
        command = build.pyinstaller_command(args, "windows")
        data = [command[index + 1] for index, value in enumerate(command) if value == "--add-data"]
        config = [item for item in data if item.endswith(";config")]
        assert len(config) == 3
        assert all(
            Path(item.split(";")[0]).name
            in {
                "default_settings.json",
                "language.json",
                "version.json",
            }
            for item in config
        )

    def test_upgrade_does_not_reuse_legacy_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "windows").mkdir()
            (root / "windows/flet-windows.zip").write_bytes(b"old runtime")
            (root / "flet-windows.zip").write_bytes(b"older runtime")

            def download(url, destination):
                Path(destination).write_bytes(b"current runtime")

            with (
                patch.object(build, "FLET_ARCHIVE_DIR", root),
                patch.object(build, "get_flet_version", return_value="1.1.2"),
                patch.object(build.urllib.request, "urlretrieve", side_effect=download) as fetch,
            ):
                path = build.prepare_flet_archive("windows", False)
            assert path == root / "1.1.2/windows"
            assert (path / "flet-windows.zip").read_bytes() == b"current runtime"
            assert fetch.call_args.args[0].endswith("/v1.1.2/flet-windows.zip")
            assert (root / "windows/flet-windows.zip").read_bytes() == b"old runtime"

    def test_current_version_archive_is_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "1.1.2/macos"
            cache.mkdir(parents=True)
            (cache / "flet-macos.tar.gz").write_bytes(b"current runtime")
            with (
                patch.object(build, "FLET_ARCHIVE_DIR", root),
                patch.object(build, "get_flet_version", return_value="1.1.2"),
                patch.object(build.urllib.request, "urlretrieve") as fetch,
            ):
                assert build.prepare_flet_archive("macos", False) == cache
            fetch.assert_not_called()
