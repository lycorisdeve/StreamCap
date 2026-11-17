import asyncio
import threading

from ...utils.logger import logger


class BackgroundService:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = BackgroundService()
        return cls._instance

    def __init__(self):
        self.tasks = []
        self.is_running = False
        self.worker_thread = None

    def add_task(self, task_func, *args, **kwargs):
        self.tasks.append((task_func, args, kwargs))
        logger.info(f"Added background task: {task_func.__name__}")

        if not self.is_running:
            self.start()

    def start(self):
        if self.is_running:
            return

        self.is_running = True
        self.worker_thread = threading.Thread(target=self._process_tasks, daemon=True)
        self.worker_thread.start()
        logger.info("Background service started")

    def _process_tasks(self):
        while self.tasks:
            task_func, args, kwargs = self.tasks.pop(0)
            try:
                logger.info(f"Executing background task: {task_func.__name__}")
                task_func(*args, **kwargs)
                logger.info(f"Background task completed: {task_func.__name__}")
            except Exception as e:
                logger.error(f"Background task execution failed: {e}")

        logger.info("All background tasks completed, service stopped")
        self.is_running = False


class AsyncProcessManager:
    def __init__(self):
        self.ffmpeg_processes = []
        self.closing = False
        self._launches = set()
        self._cleanup_task = None

    def add_process(self, process):
        self.ffmpeg_processes.append(process)

    async def create_process(self, *args, **kwargs):
        if self.closing:
            raise RuntimeError("Application is shutting down")

        async def spawn():
            process = await asyncio.create_subprocess_exec(*args, **kwargs)
            self.add_process(process)
            return process

        task = asyncio.create_task(spawn())
        self._launches.add(task)
        try:
            return await asyncio.shield(task)
        finally:
            task.add_done_callback(self._launches.discard)

    async def cleanup(self, timeout=15.0):
        if self._cleanup_task is None:
            self.closing = True
            self._cleanup_task = asyncio.create_task(self._cleanup(timeout))
        await asyncio.shield(self._cleanup_task)

    async def _cleanup(self, timeout):
        if self._launches:
            await asyncio.gather(*list(self._launches), return_exceptions=True)

        async def stop(process):
            try:
                if process.returncode is None:
                    try:
                        async with asyncio.timeout(timeout):
                            try:
                                if process.stdin:
                                    process.stdin.write(b"q\n")
                                    await process.stdin.drain()
                                else:
                                    process.terminate()
                            except (BrokenPipeError, ConnectionResetError, ProcessLookupError):
                                pass
                            await process.wait()
                    except TimeoutError:
                        process.kill()
                        await process.wait()
            except ProcessLookupError:
                pass
            finally:
                if process in self.ffmpeg_processes:
                    self.ffmpeg_processes.remove(process)

        await asyncio.gather(*(stop(process) for process in self.ffmpeg_processes[:]))
        logger.debug("All owned processes stopped")
