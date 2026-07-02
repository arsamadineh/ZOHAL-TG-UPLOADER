#!/usr/bin/env python3
import os
import re

INSTALL_DIR = "/root/zohal-uploader" if os.path.exists("/root/zohal-uploader") else "."

print(f"🪐 Starting Zohal Uploader VPS Auto-Patch in: {INSTALL_DIR}")

# --- 1. Create core/pyrogram_patch.py ---
pyrogram_patch_content = """import os
import math
import io
import asyncio
import inspect
import functools
import logging
from hashlib import md5
from typing import Union, BinaryIO, Callable, Optional

import pyrogram
from pyrogram import raw
from pyrogram.errors.exceptions.stop_transmission import StopTransmission
from pyrogram.session import Session

logger = logging.getLogger(\"ZohalPyrogramPatch\")

def apply_pyrogram_patch():
    \\\"\\\"\\\"
    Monkeypatches pyrogram.Client.save_file to use higher upload concurrency.
    Default Pyrogram uses 4 workers for files > 10MB and 1 worker for smaller files.
    This patch uses 16 workers for big files and 4 workers for smaller files to drastically increase speed.
    Also properly handles seekable streams (like AsyncToSyncStream).
    \\\"\\\"\\\"
    async def optimized_save_file(
        self: \"pyrogram.Client\",
        path: Union[str, BinaryIO],
        file_id: int = None,
        file_part: int = 0,
        progress: Callable = None,
        progress_args: tuple = ()
    ):
        async with self.save_file_semaphore:
            if path is None:
                return None

            part_size = 512 * 1024

            if isinstance(path, (str, os.PathLike)):
                fp = open(path, \"rb\")
                should_close = True
            elif isinstance(path, io.IOBase):
                fp = path
                should_close = False
            else:
                raise ValueError(\"Invalid file. Expected a file path as string or a binary (not text) file pointer\")

            file_name = getattr(fp, \"name\", \"file.bin\")

            fp.seek(0, os.SEEK_END)
            file_size = fp.tell()
            fp.seek(0)

            if file_size == 0:
                raise ValueError(\"File size equals to 0 B\")

            file_size_limit_mib = 4000 if self.me.is_premium else 2000

            if file_size > file_size_limit_mib * 1024 * 1024:
                raise ValueError(f\"Can't upload files bigger than {file_size_limit_mib} MiB\")

            file_total_parts = int(math.ceil(file_size / part_size))
            is_big = file_size > 10 * 1024 * 1024

            # SPEED OPTIMIZATION: Increase upload concurrency workers
            workers_count = 16 if is_big else 4

            is_missing_part = file_id is not None
            file_id = file_id or self.rnd_id()
            md5_sum = md5() if not is_big and not is_missing_part else None

            # Create queue BEFORE creating workers so they can reference it
            queue = asyncio.Queue(workers_count * 2)

            session = Session(
                self, await self.storage.dc_id(), await self.storage.auth_key(),
                await self.storage.test_mode(), is_media=True
            )

            async def worker(session):
                while True:
                    data = await queue.get()
                    if data is None:
                        return
                    try:
                        await session.invoke(data)
                    except Exception as e:
                        logger.exception(e)

            workers = [asyncio.get_event_loop().create_task(worker(session)) for _ in range(workers_count)]

            try:
                await session.start()
                fp.seek(part_size * file_part)

                while True:
                    chunk = fp.read(part_size)
                    if not chunk:
                        if not is_big and not is_missing_part:
                            md5_sum = \"\".join([hex(i)[2:].zfill(2) for i in md5_sum.digest()])
                        break

                    if is_big:
                        rpc = raw.functions.upload.SaveBigFilePart(
                            file_id=file_id,
                            file_part=file_part,
                            file_total_parts=file_total_parts,
                            bytes=chunk
                        )
                    else:
                        rpc = raw.functions.upload.SaveFilePart(
                            file_id=file_id,
                            file_part=file_part,
                            bytes=chunk
                        )

                    await queue.put(rpc)

                    if is_missing_part:
                        return

                    if not is_big and not is_missing_part:
                        md5_sum.update(chunk)

                    file_part += 1

                    if progress:
                        func = functools.partial(
                            progress,
                            min(file_part * part_size, file_size),
                            file_size,
                            *progress_args
                        )
                        if inspect.iscoroutinefunction(progress):
                            await func()
                        else:
                            await asyncio.get_event_loop().run_in_executor(self.executor, func)
            except StopTransmission:
                raise
            except Exception as e:
                logger.exception(e)
                raise
            else:
                if is_big:
                    return raw.types.InputFileBig(
                        id=file_id,
                        parts=file_total_parts,
                        name=file_name
                    )
                else:
                    return raw.types.InputFile(
                        id=file_id,
                        parts=file_total_parts,
                        name=file_name,
                        md5_checksum=md5_sum
                    )
            finally:
                for _ in workers:
                    await queue.put(None)
                await asyncio.gather(*workers)
                await session.stop()
                if should_close:
                    fp.close()

    # Apply monkeypatch
    pyrogram.Client.save_file = optimized_save_file
    logger.info(\"Successfully monkeypatched Pyrogram save_file with high-performance concurrent uploader.\")
"""

py_patch_path = os.path.join(INSTALL_DIR, "core/pyrogram_patch.py")
os.makedirs(os.path.dirname(py_patch_path), exist_ok=True)
with open(py_patch_path, "w", encoding="utf-8") as f:
    f.write(pyrogram_patch_content)
print("Created core/pyrogram_patch.py")


# Helper to modify files
def patch_file(rel_path, target, replacement, count=1):
    path = os.path.join(INSTALL_DIR, rel_path)
    if not os.path.exists(path):
        print(f"Warning: File {rel_path} not found. Skipping.")
        return False
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    
    if target not in content:
        print(f"Warning: Target string not found in {rel_path}.")
        return False
        
    new_content = content.replace(target, replacement, count)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"Patched: {rel_path}")
    return True

# --- 2. Patch core/config.py ---
patch_file("core/config.py", '"web_port": 8080,', '"web_port": 3002,')

# --- 3. Patch main.py ---
patch_file("main.py", 'config.get("web_port", 8080)', 'config.get("web_port", 3002)')

# --- 4. Patch cli.py ---
patch_file("cli.py", 'config.get("web_port", 8080)', 'config.get("web_port", 3002)', count=3)

# --- 5. Patch bot/keyboards.py ---
patch_file("bot/keyboards.py", 'config.get("web_port", 8080)', 'config.get("web_port", 3002)')

# --- 6. Patch scripts/install.sh ---
patch_file("scripts/install.sh", "PORT=8080", "PORT=3002")
patch_file("scripts/install.sh", "get('web_port', 8080)", "get('web_port', 3002)")

# --- 7. Patch core/downloader.py ---
patch_file("core/downloader.py", 
           '"timeout": httpx.Timeout(30.0, read=300.0),', 
           '"timeout": httpx.Timeout(30.0, read=300.0),\n            "trust_env": False,')
patch_file("core/downloader.py", 
           '"timeout": httpx.Timeout(15.0),', 
           '"timeout": httpx.Timeout(15.0),\n            "trust_env": False,')

# --- 8. Patch web/server.py ---
patch_file("web/server.py",
           '        async with httpx.AsyncClient(\n            proxy=proxy_url,\n            timeout=10.0\n        ) as client:',
           '        async with httpx.AsyncClient(\n            proxy=proxy_url,\n            timeout=10.0,\n            trust_env=False\n        ) as client:')

# --- 9. Patch bot/bot.py ---
bot_import = "from database.db import Database"
bot_replacement = "from database.db import Database\nfrom core.pyrogram_patch import apply_pyrogram_patch\n\napply_pyrogram_patch()"
patch_file("bot/bot.py", bot_import, bot_replacement)

# --- 10. Patch core/proxy.py ---
old_test_proxy = """    @classmethod
    async def test_proxy(cls, proxy_config: Dict[str, Any]) -> Dict[str, Any]:
        \"\"\"
        Tests SOCKS5/HTTP/HTTPS proxy connection.
        Measures latency and fetches country details using a geolocation API.
        \"\"\"
        scheme = proxy_config.get("scheme", "socks5")
        host = proxy_config.get("hostname")
        port = proxy_config.get("port")
        user = proxy_config.get("username")
        pwd = proxy_config.get("password")
        
        if not host or not port:
            return {"status": "error", "message": "Missing host or port"}

        auth_str = f"{user}:{pwd}@" if user and pwd else ""
        proxy_url = f"{scheme}://{auth_str}{host}:{port}"
        
        # Test targets: ip-api.com or ipapi.co (HTTPS)
        test_url = "https://ipapi.co/json/"
        
        start_time = time.time()
        try:
            async with httpx.AsyncClient(proxy=proxy_url, timeout=12.0) as client:
                response = await client.get(test_url)
                latency = (time.time() - start_time) * 1000
                
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "status": "success",
                        "latency_ms": round(latency, 1),
                        "ip": data.get("ip", "Unknown"),
                        "country": data.get("country_name", "Unknown"),
                        "country_code": data.get("country_code", "Unknown"),
                        "city": data.get("city", "Unknown"),
                        "org": data.get("org", "Unknown")
                    }
                else:
                    return {
                        "status": "error",
                        "message": f"HTTP Error {response.status_code}"
                    }
        except Exception as e:
            logger.error(f"Proxy test failed for {proxy_url}: {e}")
            return {
                "status": "error",
                "message": str(e)
            }"""

new_test_proxy = """    @classmethod
    async def test_proxy(cls, proxy_config: dict) -> dict:
        \"\"\"
        Tests SOCKS5/HTTP/HTTPS proxy connection.
        Measures latency and fetches country details using a geolocation API.
        Attempts multiple API targets for failover resilience.
        \"\"\"
        scheme = proxy_config.get("scheme", "socks5")
        host = proxy_config.get("hostname")
        port = proxy_config.get("port")
        user = proxy_config.get("username")
        pwd = proxy_config.get("password")
        
        if not host or not port:
            return {"status": "error", "message": "Missing host or port"}

        auth_str = f"{user}:{pwd}@" if user and pwd else ""
        proxy_url = f"{scheme}://{auth_str}{host}:{port}"
        
        targets = [
            {
                "url": "https://freeipapi.com/api/json",
                "ip_field": "ipAddress",
                "country_field": "countryName",
                "country_code_field": "countryCode",
                "city_field": "cityName",
                "org_field": None
            },
            {
                "url": "https://ipapi.co/json/",
                "ip_field": "ip",
                "country_field": "country_name",
                "country_code_field": "country_code",
                "city_field": "city",
                "org_field": "org"
            },
            {
                "url": "http://ip-api.com/json/",
                "ip_field": "query",
                "country_field": "country",
                "country_code_field": "countryCode",
                "city_field": "city",
                "org_field": "isp"
            }
        ]
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        last_error = None
        for target in targets:
            start_time = time.time()
            try:
                async with httpx.AsyncClient(proxy=proxy_url, timeout=10.0, headers=headers, trust_env=False) as client:
                    response = await client.get(target["url"])
                    latency = (time.time() - start_time) * 1000
                    
                    if response.status_code == 200:
                        data = response.json()
                        ip = data.get(target["ip_field"], "Unknown")
                        country = data.get(target["country_field"], "Unknown")
                        country_code = data.get(target["country_code_field"], "Unknown")
                        city = data.get(target["city_field"], "Unknown")
                        org = data.get(target["org_field"], "Unknown") if target["org_field"] else "Unknown"
                        
                        return {
                            "status": "success",
                            "latency_ms": round(latency, 1),
                            "ip": ip,
                            "country": country,
                            "country_code": country_code,
                            "city": city,
                            "org": org
                        }
                    else:
                        last_error = f"HTTP Error {response.status_code} from {target['url']}"
            except Exception as e:
                logger.warning(f"Proxy test target {target['url']} failed: {e}")
                last_error = str(e)
                continue
                
        logger.error(f"Proxy test failed for {proxy_url}: {last_error}")
        return {
            "status": "error",
            "message": last_error or "All test targets failed"
        }"""

# Try to patch core/proxy.py
proxy_path = os.path.join(INSTALL_DIR, "core/proxy.py")
if os.path.exists(proxy_path):
    with open(proxy_path, "r", encoding="utf-8") as f:
        proxy_content = f.read()
    
    # Do replacements for test_proxy signature and body
    # We can use regex to replace everything inside test_proxy or just replace the old block
    # Let's replace the type hints and the old test_proxy block
    proxy_content = proxy_content.replace('async def test_proxy(cls, proxy_config: Dict[str, Any]) -> Dict[str, Any]:', 
                                          'async def test_proxy(cls, proxy_config: dict) -> dict:')
    
    # Replace old target and client block
    old_block_part = '        # Test targets: ip-api.com or ipapi.co (HTTPS)\n        test_url = "https://ipapi.co/json/"'
    if old_block_part in proxy_content:
        # If the file hasn't been modified yet, let's write the clean version
        with open(proxy_path, "w", encoding="utf-8") as f:
            # We can just replace the old method with the new one
            # Find the start of test_proxy and end of class
            # Since the file is short, let's just do a clean replace of old_test_proxy
            if old_test_proxy in proxy_content:
                proxy_content = proxy_content.replace(old_test_proxy, new_test_proxy)
            else:
                # Fallback: rewrite test_proxy with regex or target replace
                # Let's look for test_proxy start to end of file
                idx = proxy_content.find("    @classmethod\n    async def test_proxy")
                if idx != -1:
                    proxy_content = proxy_content[:idx] + new_test_proxy + "\n"
        with open(proxy_path, "w", encoding="utf-8") as f:
            f.write(proxy_content)
        print("Patched: core/proxy.py")
else:
    print("Warning: core/proxy.py not found.")

# --- 11. Patch core/s3.py ---
# We add list_dir_contents and get_file_info to core/s3.py
s3_path = os.path.join(INSTALL_DIR, "core/s3.py")
if os.path.exists(s3_path):
    with open(s3_path, "r", encoding="utf-8") as f:
        s3_content = f.read()
        
    if "async def list_dir_contents" not in s3_content:
        target_s3 = "    async def delete_file(self, key: str) -> bool:"
        replacement_s3 = """    async def list_dir_contents(self, prefix: str = "") -> dict:
        \"\"\"
        List subfolders and files in S3 under a specific prefix (folder level).
        Returns a dictionary containing:
        - folders: List of folder paths (strings)
        - files: List of file dictionaries (key, size, last_modified, etag)
        \"\"\"
        try:
            async with self.session.client(**self._get_client_args()) as s3:
                response = await s3.list_objects_v2(
                    Bucket=self.bucket,
                    Prefix=prefix,
                    Delimiter="/"
                )
                
                folders = []
                for p in response.get("CommonPrefixes", []):
                    folders.append(p["Prefix"])
                    
                files = []
                for obj in response.get("Contents", []):
                    key = obj["Key"]
                    if key.endswith("/") or key == prefix:
                        continue
                    files.append({
                        "key": key,
                        "size": obj["Size"],
                        "last_modified": obj["LastModified"].timestamp() if "LastModified" in obj else 0,
                        "etag": obj["ETag"].strip('"') if "ETag" in obj else ""
                    })
                    
                folders.sort()
                files.sort(key=lambda x: x["key"])
                
                return {
                    "folders": folders,
                    "files": files
                }
        except Exception as e:
            logger.error(f"Failed to list S3 directory contents for prefix '{prefix}': {e}")
            return {"folders": [], "files": []}

    async def get_file_info(self, key: str) -> Optional[dict]:
        \"\"\"Get metadata of a single file (size, content type, etag).\"\"\"
        try:
            async with self.session.client(**self._get_client_args()) as s3:
                response = await s3.head_object(Bucket=self.bucket, Key=key)
                return {
                    "size": response.get("ContentLength", 0),
                    "content_type": response.get("ContentType", "application/octet-stream"),
                    "etag": response.get("ETag", "").strip('"'),
                    "last_modified": response.get("LastModified").timestamp() if response.get("LastModified") else 0
                }
        except Exception as e:
            logger.error(f"Failed to get file info for {key}: {e}")
            return None

    async def delete_file(self, key: str) -> bool:"""
        s3_content = s3_content.replace(target_s3, replacement_s3)
        with open(s3_path, "w", encoding="utf-8") as f:
            f.write(s3_content)
        print("Patched: core/s3.py")
else:
    print("Warning: core/s3.py not found.")

# --- 12. Patch bot/handlers.py ---
handlers_path = os.path.join(INSTALL_DIR, "bot/handlers.py")
if os.path.exists(handlers_path):
    with open(handlers_path, "r", encoding="utf-8") as f:
        handlers_content = f.read()

    # 12a. Add math import
    if "import math" not in handlers_content:
        handlers_content = handlers_content.replace("import uuid", "import uuid\nimport math")
        
    # 12b. Replace AsyncToSyncStream class
    # We locate class AsyncToSyncStream(io.RawIOBase): until the end of the class
    # To be extremely safe, we do regex search or find boundaries
    class_start = handlers_content.find("class AsyncToSyncStream(io.RawIOBase):")
    if class_start != -1:
        # Find def register_short_key(key: str) -> str:
        class_end = handlers_content.find("def register_short_key(key: str) -> str:")
        if class_end != -1:
            new_async_stream_class = """class AsyncToSyncStream(io.RawIOBase):
    \"\"\"
    Bridges an async generator (e.g. S3 download stream) into a synchronous read stream.
    Used to upload directly to Telegram via Pyrogram with 0 disk and constant memory usage.
    Pyrogram calls save_file which reads this stream from a thread pool executor.

    IMPORTANT: Prefetch is lazy (started on first readinto call) so that Pyrogram's
    initial seek(0, SEEK_END)/seek(0) probing does NOT consume any stream data.
    \"\"\"
    def __init__(self, async_generator, size: int, loop=None):
        self.async_generator = async_generator
        self.size = size
        self.loop = loop or asyncio.get_event_loop()
        self.buffer = bytearray()
        self.closed_gen = False
        self.position = 0
        # Lazy: initialized on first actual read
        self._queue = None
        self._prefetch_started = False

    def readable(self):
        return True

    def seekable(self):
        return True

    def seek(self, offset, whence=0):
        if whence == 0:  # SEEK_SET
            new_pos = offset
        elif whence == 1:  # SEEK_CUR
            new_pos = self.position + offset
        elif whence == 2:  # SEEK_END - used by Pyrogram to probe file size
            new_pos = self.size + offset
        else:
            raise ValueError(f"Invalid whence: {whence}")

        if not self._prefetch_started:
            self.position = new_pos
            return self.position

        if new_pos > self.position:
            diff = new_pos - self.position
            discarded = 0
            while discarded < diff:
                to_read = min(diff - discarded, 128 * 1024)
                chunk = self.read(to_read)
                if not chunk:
                    break
                discarded += len(chunk)

        self.position = new_pos
        return self.position

    def tell(self):
        return self.position

    async def _prefetch_loop(self):
        try:
            async for chunk in self.async_generator:
                if chunk:
                    await self._queue.put(chunk)
            await self._queue.put(None)
        except Exception as e:
            logger.error(f"AsyncToSyncStream prefetch error: {e}")
            try:
                await self._queue.put(None)
            except Exception:
                pass

    def _ensure_prefetch_started(self):
        if self._prefetch_started or self.closed_gen:
            return

        async def _create_and_start():
            self._queue = asyncio.Queue(maxsize=32)
            asyncio.ensure_future(self._prefetch_loop())

        fut = asyncio.run_coroutine_threadsafe(_create_and_start(), self.loop)
        fut.result(timeout=15)
        self._prefetch_started = True

    def readinto(self, b):
        required = len(b)
        self._ensure_prefetch_started()

        while len(self.buffer) < required and not self.closed_gen:
            future = asyncio.run_coroutine_threadsafe(self._queue.get(), self.loop)
            try:
                chunk = future.result(timeout=120)
                if chunk is None:
                    self.closed_gen = True
                else:
                    self.buffer.extend(chunk)
            except Exception as e:
                logger.error(f"AsyncToSyncStream read error: {e}")
                self.closed_gen = True
                break

        if not self.buffer:
            return 0

        take = min(len(self.buffer), required)
        chunk_to_return = bytes(self.buffer[:take])
        del self.buffer[:take]
        b[:take] = chunk_to_return
        self.position += take
        return take

    def read(self, size=-1):
        if size == -1:
            res = bytearray()
            while True:
                chunk = self.read(128 * 1024)
                if not chunk:
                    break
                res.extend(chunk)
            return bytes(res)

        b = bytearray(size)
        n = self.readinto(b)
        return bytes(b[:n])

    def close(self):
        super().close()
        self.closed_gen = True
        if self._prefetch_started and self._queue is not None:
            try:
                while not self._queue.empty():
                    self._queue.get_nowait()
            except Exception:
                pass

"""
            handlers_content = handlers_content[:class_start] + new_async_stream_class + handlers_content[class_end:]

    # 12c. Replace S3 Files List handler with Render S3 Browser
    browser_start = handlers_content.find("    # S3 Files List handler")
    if browser_start != -1:
        # Find next handler start (e.g. File Options callback handler)
        browser_end = handlers_content.find("    # File Options callback handler")
        if browser_end != -1:
            new_browser_code = r"""    # Helper to render S3 Browser with folders and pagination
    async def render_s3_browser(client: Client, chat_id: int, message_id: Optional[int], prefix: str, page: int):
        config = await ConfigManager.get_config()
        s3 = S3Client(config)
        
        if not message_id:
            msg = await client.send_message(chat_id, "⏳ در حال دریافت لیست فایل‌های S3...")
            message_id = msg.id
            
        result = await s3.list_dir_contents(prefix)
        folders = result.get("folders", [])
        files = result.get("files", [])
        
        items = []
        for fld in folders:
            rel_name = fld[len(prefix):]
            items.append({
                "type": "folder",
                "name": f"📁 {rel_name}",
                "path": fld
            })
            
        for fl in files:
            rel_name = fl["key"][len(prefix):]
            size_mb = fl["size"] / (1024 * 1024)
            items.append({
                "type": "file",
                "name": f"📄 {rel_name} ({size_mb:.2f} MB)",
                "key": fl["key"]
            })
            
        total_items = len(items)
        items_per_page = 10
        total_pages = max(1, math.ceil(total_items / items_per_page))
        
        if page < 1:
            page = 1
        elif page > total_pages:
            page = total_pages
            
        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        page_items = items[start_idx:end_idx]
        
        path_display = f"Root/{prefix}" if prefix else "Root"
        text = (
            f"📁 **مدیریت فایل‌های S3**\\n\\n"
            f"📂 **مسیر فعلی:** `{path_display}`\\n"
            f"📊 تعداد آیتم‌های این پوشه: {total_items}\\n"
            f"📄 صفحه {page} از {total_pages}\\n\\n"
            f"👇 برای مدیریت فایل یا ورود به پوشه کلیک کنید:"
        )
        
        buttons = []
        for item in page_items:
            if item["type"] == "folder":
                short_id = register_short_key(item["path"])
                buttons.append([InlineKeyboardButton(item["name"], callback_data=f"s3list:{short_id}:1")])
            else:
                short_id = register_short_key(item["key"])
                buttons.append([InlineKeyboardButton(item["name"], callback_data=f"opt:{short_id}")])
                
        nav_row = []
        current_prefix_short = "root" if not prefix else register_short_key(prefix)
        
        if page > 1:
            nav_row.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"s3list:{current_prefix_short}:{page-1}"))
        else:
            nav_row.append(InlineKeyboardButton("▫️", callback_data="noop"))
            
        nav_row.append(InlineKeyboardButton(f"صفحه {page}/{total_pages}", callback_data="noop"))
        
        if page < total_pages:
            nav_row.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"s3list:{current_prefix_short}:{page+1}"))
        else:
            nav_row.append(InlineKeyboardButton("▫️", callback_data="noop"))
            
        buttons.append(nav_row)
        
        control_row = []
        if prefix:
            parts = prefix.rstrip("/").split("/")
            if len(parts) > 1:
                parent_prefix = "/".join(parts[:-1]) + "/"
            else:
                parent_prefix = ""
            parent_short = "root" if not parent_prefix else register_short_key(parent_prefix)
            control_row.append(InlineKeyboardButton("⬆️ پوشه قبلی", callback_data=f"s3list:{parent_short}:1"))
            
        control_row.append(InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"s3list:{current_prefix_short}:{page}"))
        control_row.append(InlineKeyboardButton("❌ بستن", callback_data="close_menu"))
        buttons.append(control_row)
        
        try:
            await client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        except Exception as e:
            if "MESSAGE_NOT_MODIFIED" not in str(e):
                logger.error(f"Error updating S3 browser: {e}")

    # S3 Files List handler
    @app.on_message(filters.text & filters.private & filters.regex(r"^📁 مدیریت فایل‌های S3$"))
    async def list_s3_files_handler_text(client: Client, message: Message):
        if not await check_auth(client, message):
            return
        await render_s3_browser(client, message.chat.id, None, "", 1)

    # S3 Browser Callback query handler
    @app.on_callback_query(filters.regex(r"^s3list:(root|s_[a-f0-9]+):(\d+)$"))
    async def s3_browser_callback(client: Client, callback_query: CallbackQuery):
        if not await check_auth(client, callback_query.message):
            return
            
        short_id = callback_query.matches[0].group(1)
        page = int(callback_query.matches[0].group(2))
        
        prefix = resolve_short_key(short_id)
        if prefix is None:
            if short_id == "root":
                prefix = ""
            else:
                await callback_query.answer("مسیر یافت نشد یا منقضی شده است.", show_alert=True)
                return
                
        await callback_query.answer()
        await render_s3_browser(client, callback_query.message.chat.id, callback_query.message.id, prefix, page)

    # No-op callback handler to answer dummy buttons
    @app.on_callback_query(filters.regex(r"^noop$"))
    async def noop_callback(client: Client, callback_query: CallbackQuery):
        await callback_query.answer()

"""
            handlers_content = handlers_content[:browser_start] + new_browser_code + handlers_content[browser_end:]

    # 12d. Optimize S3 to TG stream metadata lookup
    old_meta_lookup = """        # Get file metadata to check size (we list and match keys)
        files = await s3.list_files()
        file_obj = next((f for f in files if f["key"] == key), None)
        size = file_obj["size"] if file_obj else 0"""
        
    new_meta_lookup = """        # Optimized: Get file metadata via head_object instead of listing all files
        file_info = await s3.get_file_info(key)
        size = file_info["size"] if file_info else 0"""
        
    handlers_content = handlers_content.replace(old_meta_lookup, new_meta_lookup)

    with open(handlers_path, "w", encoding="utf-8") as f:
        f.write(handlers_content)
    print("Patched: bot/handlers.py")
else:
    print("Warning: bot/handlers.py not found.")

print("🪐 All VPS files patched successfully!")
