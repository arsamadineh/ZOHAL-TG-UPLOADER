import os
import sqlite3
import aiosqlite
import time
from typing import List, Dict, Any, Optional

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "zohal.db")

class Database:
    @classmethod
    def get_db(cls):
        return aiosqlite.connect(DB_PATH)

    @classmethod
    async def init_db(cls):
        async with cls.get_db() as db:
            # Table for authorized users
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    is_admin INTEGER DEFAULT 0,
                    created_at INTEGER
                )
            """)
            
            # Table for uploads history
            await db.execute("""
                CREATE TABLE IF NOT EXISTS uploads (
                    id TEXT PRIMARY KEY,
                    file_name TEXT,
                    file_size INTEGER,
                    source TEXT, -- 'telegram' or 'url'
                    status TEXT, -- 'pending', 'uploading', 'completed', 'failed'
                    s3_key TEXT,
                    s3_url TEXT,
                    error_message TEXT,
                    duration REAL DEFAULT 0,
                    speed REAL DEFAULT 0,
                    user_id INTEGER,
                    created_at INTEGER
                )
            """)

            # Table for queue tasks
            await db.execute("""
                CREATE TABLE IF NOT EXISTS queue (
                    task_id TEXT PRIMARY KEY,
                    file_name TEXT,
                    file_size INTEGER,
                    type TEXT, -- 'tg_to_s3', 'url_to_s3', 's3_to_tg'
                    status TEXT, -- 'queued', 'processing', 'paused', 'cancelled', 'completed', 'failed'
                    progress REAL DEFAULT 0, -- percentage
                    speed REAL DEFAULT 0, -- bytes/sec
                    eta TEXT,
                    user_id INTEGER,
                    created_at INTEGER
                )
            """)

            # Table for proxies
            await db.execute("""
                CREATE TABLE IF NOT EXISTS proxies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    scheme TEXT,
                    host TEXT,
                    port INTEGER,
                    username TEXT,
                    password TEXT,
                    is_active INTEGER DEFAULT 0,
                    latency REAL DEFAULT -1,
                    country TEXT DEFAULT 'نامشخص',
                    country_code TEXT DEFAULT 'UN',
                    status TEXT DEFAULT 'untested',
                    created_at INTEGER
                )
            """)
            
            await db.commit()

    @classmethod
    async def add_user(cls, user_id: int, username: Optional[str], first_name: Optional[str], is_admin: bool = False) -> bool:
        async with cls.get_db() as db:
            try:
                await db.execute(
                    "INSERT INTO users (user_id, username, first_name, is_admin, created_at) VALUES (?, ?, ?, ?, ?)",
                    (user_id, username or "", first_name or "", 1 if is_admin else 0, int(time.time()))
                )
                await db.commit()
                return True
            except sqlite3.IntegrityError:
                # User already exists, update properties
                await db.execute(
                    "UPDATE users SET username = ?, first_name = ?, is_admin = ? WHERE user_id = ?",
                    (username or "", first_name or "", 1 if is_admin else 0, user_id)
                )
                await db.commit()
                return True
            except Exception as e:
                print(f"Error adding user: {e}")
                return False

    @classmethod
    async def remove_user(cls, user_id: int) -> bool:
        async with cls.get_db() as db:
            try:
                await db.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
                await db.commit()
                return True
            except Exception:
                return False

    @classmethod
    async def is_user_authorized(cls, user_id: int) -> bool:
        async with cls.get_db() as db:
            async with db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                return row is not None

    @classmethod
    async def get_users(cls) -> List[Dict[str, Any]]:
        async with cls.get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users ORDER BY created_at DESC") as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    @classmethod
    async def add_upload(cls, upload_id: str, file_name: str, file_size: int, source: str, user_id: int, status: str = "pending") -> bool:
        async with cls.get_db() as db:
            try:
                await db.execute(
                    "INSERT INTO uploads (id, file_name, file_size, source, status, user_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (upload_id, file_name, file_size, source, status, user_id, int(time.time()))
                )
                await db.commit()
                return True
            except Exception as e:
                print(f"Error adding upload: {e}")
                return False

    @classmethod
    async def update_upload_status(cls, upload_id: str, status: str, s3_key: Optional[str] = None, s3_url: Optional[str] = None, error_message: Optional[str] = None, duration: float = 0, speed: float = 0) -> bool:
        async with cls.get_db() as db:
            try:
                query = "UPDATE uploads SET status = ?, duration = ?, speed = ?"
                params = [status, duration, speed]
                
                if s3_key is not None:
                    query += ", s3_key = ?"
                    params.append(s3_key)
                if s3_url is not None:
                    query += ", s3_url = ?"
                    params.append(s3_url)
                if error_message is not None:
                    query += ", error_message = ?"
                    params.append(error_message)
                    
                query += " WHERE id = ?"
                params.append(upload_id)
                
                await db.execute(query, tuple(params))
                await db.commit()
                return True
            except Exception as e:
                print(f"Error updating upload status: {e}")
                return False

    @classmethod
    async def get_uploads(cls, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        async with cls.get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM uploads ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    @classmethod
    async def get_upload_stats(cls) -> Dict[str, Any]:
        async with cls.get_db() as db:
            db.row_factory = aiosqlite.Row
            stats = {
                "total_count": 0,
                "total_size": 0,
                "completed_count": 0,
                "failed_count": 0,
                "tg_source_count": 0,
                "url_source_count": 0
            }
            try:
                async with db.execute("SELECT COUNT(*) as count, SUM(file_size) as size FROM uploads") as cursor:
                    row = await cursor.fetchone()
                    if row:
                        stats["total_count"] = row["count"] or 0
                        stats["total_size"] = row["size"] or 0

                async with db.execute("SELECT COUNT(*) as count FROM uploads WHERE status = 'completed'") as cursor:
                    row = await cursor.fetchone()
                    if row:
                        stats["completed_count"] = row["count"] or 0

                async with db.execute("SELECT COUNT(*) as count FROM uploads WHERE status = 'failed'") as cursor:
                    row = await cursor.fetchone()
                    if row:
                        stats["failed_count"] = row["count"] or 0

                async with db.execute("SELECT COUNT(*) as count FROM uploads WHERE source = 'telegram'") as cursor:
                    row = await cursor.fetchone()
                    if row:
                        stats["tg_source_count"] = row["count"] or 0

                async with db.execute("SELECT COUNT(*) as count FROM uploads WHERE source = 'url'") as cursor:
                    row = await cursor.fetchone()
                    if row:
                        stats["url_source_count"] = row["count"] or 0
            except Exception as e:
                print(f"Error getting upload stats: {e}")
            return stats

    @classmethod
    async def add_proxy(cls, name: str, scheme: str, host: str, port: int, username: Optional[str] = "", password: Optional[str] = "") -> bool:
        async with cls.get_db() as db:
            try:
                await db.execute(
                    "INSERT INTO proxies (name, scheme, host, port, username, password, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (name, scheme, host, port, username or "", password or "", int(time.time()))
                )
                await db.commit()
                return True
            except Exception as e:
                print(f"Error adding proxy: {e}")
                return False

    @classmethod
    async def delete_proxy(cls, proxy_id: int) -> bool:
        async with cls.get_db() as db:
            try:
                await db.execute("DELETE FROM proxies WHERE id = ?", (proxy_id,))
                await db.commit()
                return True
            except Exception as e:
                print(f"Error deleting proxy: {e}")
                return False

    @classmethod
    async def get_proxies(cls) -> List[Dict[str, Any]]:
        async with cls.get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM proxies ORDER BY created_at DESC") as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    @classmethod
    async def get_active_proxy(cls) -> Optional[Dict[str, Any]]:
        async with cls.get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM proxies WHERE is_active = 1 LIMIT 1") as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    @classmethod
    async def get_proxy_by_id(cls, proxy_id: int) -> Optional[Dict[str, Any]]:
        async with cls.get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM proxies WHERE id = ?", (proxy_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    @classmethod
    async def set_active_proxy(cls, proxy_id: Optional[int]) -> bool:
        async with cls.get_db() as db:
            try:
                await db.execute("UPDATE proxies SET is_active = 0")
                if proxy_id is not None and proxy_id > 0:
                    await db.execute("UPDATE proxies SET is_active = 1 WHERE id = ?", (proxy_id,))
                await db.commit()
                return True
            except Exception as e:
                print(f"Error setting active proxy: {e}")
                return False

    @classmethod
    async def update_proxy_test_result(cls, proxy_id: int, status: str, latency: float, country: str, country_code: str) -> bool:
        async with cls.get_db() as db:
            try:
                await db.execute(
                    "UPDATE proxies SET status = ?, latency = ?, country = ?, country_code = ? WHERE id = ?",
                    (status, latency, country, country_code, proxy_id)
                )
                await db.commit()
                return True
            except Exception as e:
                print(f"Error updating proxy test result: {e}")
                return False
