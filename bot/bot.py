import os
import asyncio
import logging
from typing import Optional
from pyrogram import Client
from core.config import ConfigManager
from database.db import Database
from core.pyrogram_patch import apply_pyrogram_patch

# Apply Pyrogram high-performance uploader monkeypatch
apply_pyrogram_patch()

logger = logging.getLogger("ZohalBot")

class BotService:
    client: Optional[Client] = None
    _is_running = False

    @classmethod
    async def start(cls) -> bool:
        if cls._is_running:
            logger.info("Bot is already running.")
            return True

        config = await ConfigManager.get_config()
        if not config.get("setup_completed"):
            logger.warning("Setup not completed. Bot cannot be started.")
            return False

        api_id = config.get("telegram_api_id")
        api_hash = config.get("telegram_api_hash")
        bot_token = config.get("telegram_bot_token")

        if not api_id or not api_hash or not bot_token:
            logger.error("Missing Telegram configuration parameters.")
            return False

        # Load proxy settings
        proxy = await ConfigManager.get_active_pyrogram_proxy()
        if proxy:
            logger.info(f"Starting bot using proxy: {proxy['scheme']}://{proxy['hostname']}:{proxy['port']}")
        else:
            logger.info("Starting bot without proxy.")

        try:
            # We store session in the root folder
            cls.client = Client(
                name="zohal_uploader_bot",
                api_id=int(api_id),
                api_hash=api_hash,
                bot_token=bot_token,
                proxy=proxy,
                workdir=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )

            # Register handlers
            from bot.handlers import register_all_handlers, setup_commands
            register_all_handlers(cls.client)
            
            await cls.client.start()
            await setup_commands(cls.client)
            cls._is_running = True
            logger.info("Zohal Uploader Bot started successfully.")
            
            # Ensure owner is in the authorized users database
            owner_id = int(config.get("owner_id", 0))
            if owner_id > 0:
                await Database.add_user(owner_id, "owner", "مدیر ربات", is_admin=True)

            return True
        except Exception as e:
            logger.error(f"Failed to start Pyrogram Client: {e}")
            cls.client = None
            cls._is_running = False
            return False

    @classmethod
    async def stop(cls) -> bool:
        if not cls._is_running or not cls.client:
            logger.info("Bot is not running.")
            return True

        try:
            logger.info("Stopping Zohal Uploader Bot...")
            await cls.client.stop()
            cls.client = None
            cls._is_running = False
            logger.info("Bot stopped successfully.")
            return True
        except Exception as e:
            logger.error(f"Error stopping Pyrogram Client: {e}")
            return False

    @classmethod
    async def restart(cls) -> bool:
        await cls.stop()
        # Wait a moment for cleanup
        await asyncio.sleep(2)
        return await cls.start()

    @classmethod
    def is_running(cls) -> bool:
        return cls._is_running
