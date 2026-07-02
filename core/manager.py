import time
import asyncio
import logging
from typing import List, Dict, Any, Optional, Callable
from database.db import Database

logger = logging.getLogger("ZohalManager")

class TaskProgress:
    def __init__(self, task_id: str, file_name: str, total_size: int, task_type: str, user_id: int):
        self.task_id = task_id
        self.file_name = file_name
        self.total_size = total_size
        self.type = task_type
        self.user_id = user_id
        
        self.start_time = time.time()
        self.last_update_time = 0.0
        self.bytes_completed = 0
        self.speed = 0.0
        self.status = "processing"
        self.is_cancelled = False
        self.error_message = ""
        self.s3_key = ""
        self.s3_url = ""

    def update(self, bytes_completed: int):
        now = time.time()
        self.bytes_completed = bytes_completed
        duration = now - self.start_time
        if duration > 0:
            self.speed = bytes_completed / duration

    def should_update_telegram(self, interval: float = 3.5) -> bool:
        """Rate limit telegram message edits to avoid flood waits."""
        now = time.time()
        if now - self.last_update_time >= interval:
            self.last_update_time = now
            return True
        return False

    def get_progress_percent(self) -> float:
        if self.total_size <= 0:
            return 0.0
        return min(100.0, (self.bytes_completed / self.total_size) * 100)

    def get_progress_bar(self) -> str:
        percent = self.get_progress_percent()
        filled_length = int(10 * percent // 100)
        bar = "█" * filled_length + "░" * (10 - filled_length)
        return bar

    def get_eta(self) -> str:
        if self.speed <= 0 or self.total_size <= 0:
            return "نامشخص"
        remaining_bytes = self.total_size - self.bytes_completed
        remaining_seconds = remaining_bytes / self.speed
        
        if remaining_seconds < 60:
            return f"{int(remaining_seconds)} ثانیه"
        elif remaining_seconds < 3600:
            minutes = int(remaining_seconds // 60)
            seconds = int(remaining_seconds % 60)
            return f"{minutes} دقیقه و {seconds} ثانیه"
        else:
            hours = int(remaining_seconds // 3600)
            minutes = int((remaining_seconds % 3600) // 60)
            return f"{hours} ساعت و {minutes} دقیقه"

    def format_size(self, size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.2f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.2f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

    def format_speed(self) -> str:
        return f"{self.format_size(int(self.speed))}/s"

    def get_persian_status_message(self) -> str:
        percent = self.get_progress_percent()
        bar = self.get_progress_bar()
        speed_str = self.format_speed()
        completed_str = self.format_size(self.bytes_completed)
        total_str = self.format_size(self.total_size)
        eta_str = self.get_eta()
        
        action_text = "آپلود به S3" if "to_s3" in self.type else "دانلود به تلگرام"
        
        return (
            f"⏳ **در حال {action_text}...**\n\n"
            f"📂 **نام فایل:** `{self.file_name}`\n"
            f"📊 **پیشرفت:** {percent:.1f}% `[{bar}]`\n"
            f"💾 **حجم:** {completed_str} از {total_str}\n"
            f"⚡️ **سرعت:** `{speed_str}`\n"
            f"⏰ **زمان باقیمانده:** `{eta_str}`"
        )


class TaskManager:
    _tasks: Dict[str, TaskProgress] = {}
    _lock = asyncio.Lock()

    @classmethod
    async def create_task(cls, task_id: str, file_name: str, total_size: int, task_type: str, user_id: int) -> TaskProgress:
        async with cls._lock:
            task = TaskProgress(task_id, file_name, total_size, task_type, user_id)
            cls._tasks[task_id] = task
            # Log to DB
            await Database.add_upload(
                upload_id=task_id,
                file_name=file_name,
                file_size=total_size,
                source="telegram" if "tg" in task_type else "url",
                user_id=user_id,
                status="processing"
            )
            return task

    @classmethod
    async def get_task(cls, task_id: str) -> Optional[TaskProgress]:
        async with cls._lock:
            return cls._tasks.get(task_id)

    @classmethod
    async def cancel_task(cls, task_id: str) -> bool:
        async with cls._lock:
            task = cls._tasks.get(task_id)
            if task:
                task.is_cancelled = True
                task.status = "cancelled"
                # Update DB
                await Database.update_upload_status(
                    upload_id=task_id,
                    status="failed",
                    error_message="توسط کاربر لغو شد"
                )
                return True
            return False

    @classmethod
    async def complete_task(cls, task_id: str, s3_key: str, s3_url: str, duration: float, speed: float) -> None:
        async with cls._lock:
            task = cls._tasks.get(task_id)
            if task:
                task.status = "completed"
                task.s3_key = s3_key
                task.s3_url = s3_url
                # Update DB
                await Database.update_upload_status(
                    upload_id=task_id,
                    status="completed",
                    s3_key=s3_key,
                    s3_url=s3_url,
                    duration=duration,
                    speed=speed
                )
                # Cleanup in-memory tracker after a short while or immediately
                cls._tasks.pop(task_id, None)

    @classmethod
    async def fail_task(cls, task_id: str, error_message: str, duration: float = 0) -> None:
        async with cls._lock:
            task = cls._tasks.get(task_id)
            if task:
                task.status = "failed"
                task.error_message = error_message
                # Update DB
                await Database.update_upload_status(
                    upload_id=task_id,
                    status="failed",
                    error_message=error_message,
                    duration=duration
                )
                cls._tasks.pop(task_id, None)

    @classmethod
    async def get_active_tasks(cls) -> List[Dict[str, Any]]:
        async with cls._lock:
            active = []
            for t in cls._tasks.values():
                active.append({
                    "task_id": t.task_id,
                    "file_name": t.file_name,
                    "total_size": t.total_size,
                    "bytes_completed": t.bytes_completed,
                    "progress": t.get_progress_percent(),
                    "speed": t.speed,
                    "eta": t.get_eta(),
                    "type": t.type,
                    "user_id": t.user_id,
                    "status": t.status
                })
            return active
