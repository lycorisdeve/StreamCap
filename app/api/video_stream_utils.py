from pathlib import Path

import aiofiles

STREAM_CHUNK_SIZE = 65536


class InvalidVideoPathError(ValueError):
    pass


class InvalidByteRangeError(ValueError):
    pass


def resolve_video_path(video_root: Path, filename: str, subfolder: str | None = None) -> Path:
    """Resolve a requested video path and keep it inside ``video_root``."""
    if "/" in filename or "\\" in filename:
        raise InvalidVideoPathError("Invalid filename")

    try:
        resolved_root = video_root.resolve(strict=True)
        relative_folder = Path(subfolder) if subfolder else Path()
        if relative_folder.is_absolute():
            raise InvalidVideoPathError("Absolute subfolders are not allowed")
        video_path = (resolved_root / relative_folder / filename).resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise InvalidVideoPathError("Invalid file path") from exc

    if not video_path.is_relative_to(resolved_root):
        raise InvalidVideoPathError("Video path escapes the configured root")

    return video_path


def parse_range_header(range_header: str, file_size: int) -> tuple[int, int]:
    """Parse one HTTP byte range and return an inclusive ``(start, end)``."""
    if not range_header.startswith("bytes=") or "," in range_header or file_size <= 0:
        raise InvalidByteRangeError("Invalid byte range")

    range_spec = range_header.removeprefix("bytes=").strip()
    if range_spec.count("-") != 1:
        raise InvalidByteRangeError("Invalid byte range")

    start_text, end_text = range_spec.split("-", maxsplit=1)
    if not start_text and not end_text:
        raise InvalidByteRangeError("Invalid byte range")
    if (start_text and not start_text.isdecimal()) or (end_text and not end_text.isdecimal()):
        raise InvalidByteRangeError("Invalid byte range")

    if not start_text:
        suffix_length = int(end_text)
        if suffix_length <= 0:
            raise InvalidByteRangeError("Invalid byte range")
        return max(0, file_size - suffix_length), file_size - 1

    start = int(start_text)
    if start >= file_size:
        raise InvalidByteRangeError("Range starts beyond end of file")

    end = int(end_text) if end_text else file_size - 1
    if end < start:
        raise InvalidByteRangeError("Range end precedes start")
    return start, min(end, file_size - 1)


async def file_sender_range(video_path: Path, start: int, end: int):
    """Yield a byte range without buffering the complete range in memory."""
    async with aiofiles.open(video_path, "rb") as file:
        await file.seek(start)
        while start <= end:
            chunk_size = min(STREAM_CHUNK_SIZE, end - start + 1)
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            start += len(chunk)
            yield chunk
