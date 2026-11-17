import os
import sys

from loguru import logger

from app.core.runtime.paths import log_dir, windows_package_layout

os.makedirs(log_dir, exist_ok=True)
app_log_path = os.path.join(log_dir, "app.log" if windows_package_layout else "streamget.log")
use_multiprocessing_queue = not (getattr(sys, "frozen", False) and sys.platform == "darwin")
logger.add(
    app_log_path,
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
    filter=lambda i: i["level"].name != "STREAM",
    serialize=False,
    enqueue=use_multiprocessing_queue,
    retention=3,
    rotation="3 MB",
    encoding="utf-8",
)

if windows_package_layout:
    logger.add(
        os.path.join(log_dir, "error.log"),
        level="ERROR",
        rotation="3 MB",
        retention=3,
        encoding="utf-8",
        enqueue=use_multiprocessing_queue,
    )

logger.level("STREAM", no=22, color="<blue>")
logger.add(
    os.path.join(log_dir, "play_url.log"),
    level="STREAM",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {message}",
    filter=lambda i: i["level"].name == "STREAM",
    serialize=False,
    enqueue=use_multiprocessing_queue,
    retention=1,
    rotation="500 KB",
    encoding="utf-8",
)
