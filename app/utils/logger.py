import os
import sys

from loguru import logger

from app.core.runtime.paths import user_data_dir

log_dir = os.path.join(user_data_dir, "log")
os.makedirs(log_dir, exist_ok=True)
use_multiprocessing_queue = not (getattr(sys, "frozen", False) and sys.platform == "darwin")
logger.add(
    os.path.join(log_dir, "streamget.log"),
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
    filter=lambda i: i["level"].name != "STREAM",
    serialize=False,
    enqueue=use_multiprocessing_queue,
    retention=3,
    rotation="3 MB",
    encoding="utf-8",
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
