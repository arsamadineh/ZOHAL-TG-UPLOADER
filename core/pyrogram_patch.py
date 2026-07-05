import os
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
from pyrogram.session import Session

# StopTransmission moved across pyrogram versions — try all known paths
try:
    from pyrogram.errors.exceptions.stop_transmission import StopTransmission
except ImportError:
    try:
        from pyrogram.errors import StopTransmission
    except ImportError:
        try:
            from pyrogram.errors.exceptions import StopTransmission
        except ImportError:
            # Final fallback: define a sentinel exception so the code won't break
            class StopTransmission(Exception):  # type: ignore
                pass

logger = logging.getLogger("ZohalPyrogramPatch")

def apply_pyrogram_patch():
    """
    Monkeypatches pyrogram.Client.save_file to use higher upload concurrency.
    Default Pyrogram uses 4 workers for files > 10MB and 1 worker for smaller files.
    This patch uses 16 workers for big files and 4 workers for smaller files to drastically increase speed.
    Also properly handles seekable streams (like AsyncToSyncStream).
    """
    async def optimized_save_file(
        self: "pyrogram.Client",
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
                fp = open(path, "rb")
                should_close = True
            elif isinstance(path, io.IOBase):
                fp = path
                should_close = False
            else:
                raise ValueError("Invalid file. Expected a file path as string or a binary (not text) file pointer")

            file_name = getattr(fp, "name", "file.bin")

            loop = asyncio.get_running_loop()

            # Determine file size using seek/tell (run in executor for AsyncToSyncStream)
            await loop.run_in_executor(None, fp.seek, 0, os.SEEK_END)
            file_size = await loop.run_in_executor(None, fp.tell)
            await loop.run_in_executor(None, fp.seek, 0)

            if file_size == 0:
                raise ValueError("File size equals to 0 B")

            file_size_limit_mib = 4000 if self.me.is_premium else 2000

            if file_size > file_size_limit_mib * 1024 * 1024:
                raise ValueError(f"Can't upload files bigger than {file_size_limit_mib} MiB")

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

            workers = [asyncio.get_running_loop().create_task(worker(session)) for _ in range(workers_count)]

            try:
                await session.start()

                # Seek to the right part start position (run in executor for AsyncToSyncStream)
                await loop.run_in_executor(None, fp.seek, part_size * file_part)

                while True:
                    chunk = await loop.run_in_executor(None, fp.read, part_size)
                    if not chunk:
                        if not is_big and not is_missing_part:
                            md5_sum = "".join([hex(i)[2:].zfill(2) for i in md5_sum.digest()])
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
                            await asyncio.get_running_loop().run_in_executor(self.executor, func)
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
    logger.info("Successfully monkeypatched Pyrogram save_file with high-performance concurrent uploader.")
