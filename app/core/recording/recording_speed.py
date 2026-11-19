import os
import re
import time
from pathlib import Path


class RecordingSpeedSampler:
    """Sample output growth without rescanning completed segments."""

    def __init__(self, path=None, segmented=False):
        self.path = Path(path) if path else None
        self.segmented = segmented
        self.index = 0
        self.completed = 0
        self.current = 0
        self.baseline = {}
        self.last_bytes = 0
        self.last_time = time.monotonic()
        if self.path:
            if segmented:
                prefix, suffix = self.path.name.rsplit("%03d", 1)
                self.prefix, self.suffix = prefix, suffix
                pattern = re.compile(re.escape(prefix) + r"[0-9]{3,}" + re.escape(suffix))
                try:
                    with os.scandir(self.path.parent) as entries:
                        for entry in entries:
                            if pattern.fullmatch(entry.name):
                                stat = entry.stat()
                                self.baseline[entry.name] = (stat.st_size, stat.st_mtime_ns)
                except OSError:
                    pass
            else:
                try:
                    stat = self.path.stat()
                    self.baseline[self.path.name] = (stat.st_size, stat.st_mtime_ns)
                except FileNotFoundError:
                    pass

    def _size(self, path):
        try:
            stat = path.stat()
        except FileNotFoundError:
            return None
        if self.baseline.get(path.name) == (stat.st_size, stat.st_mtime_ns):
            return None
        return stat.st_size

    def sample(self, total_bytes=None):
        try:
            if total_bytes is None:
                if not self.segmented:
                    size = self._size(self.path)
                    self.current = max(self.current, size or 0)
                else:
                    while True:
                        current = self.path.parent / f"{self.prefix}{self.index:03d}{self.suffix}"
                        size = self._size(current)
                        self.current = max(self.current, size or 0)
                        following = self.path.parent / f"{self.prefix}{self.index + 1:03d}{self.suffix}"
                        if self._size(following) is None:
                            break
                        self.completed += self.current
                        self.current = 0
                        self.index += 1
                total_bytes = self.completed + self.current
            now = time.monotonic()
            elapsed = now - self.last_time
            if elapsed <= 0:
                return "—"
            rate = max(0, total_bytes - self.last_bytes) / elapsed
            self.last_time, self.last_bytes = now, total_bytes
            if rate >= 1024 * 1024:
                return f"{rate / (1024 * 1024):.1f} MB/s"
            return f"{rate / 1024:.0f} KB/s"
        except OSError:
            return "—"
