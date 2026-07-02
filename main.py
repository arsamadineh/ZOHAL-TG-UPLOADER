import asyncio
import logging
from core.config import ConfigManager
from database.db import Database
from bot.bot import BotService

# Configure logging to console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("ZohalLauncher")

async def main():
    logger.info("Initializing Zohal Uploader...")
    
    # Load configuration
    config = ConfigManager.load()
    
    # If setup completed, initialize DB and start the bot
    if config.get("setup_completed"):
        logger.info("Setup is completed. Initializing database and launching Telegram bot...")
        await Database.init_db()
        
        # Start Pyrogram client
        success = await BotService.start()
        if success:
            logger.info("Zohal Bot is running.")
            # Keep running until interrupted or stopped
            try:
                while BotService.is_running():
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                pass
        else:
            logger.error("Failed to start Zohal Bot. Please check configurations or run zohal-up to configure.")
    else:
        logger.warning("==========================================================")
        logger.warning("⚠️  پیکربندی ربات کامل نشده است!")
        logger.warning("لطفاً دستور 'zohal-up' را در ترمینال اجرا کنید تا تنظیمات انجام شود.")
        logger.warning("==========================================================")
        
        # Keep process alive so systemd doesn't restart-loop rapidly
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass

    # Cleanup bot connection on exit
    if BotService.is_running():
        logger.info("Stopping Bot Service on exit...")
        await BotService.stop()
        
    logger.info("Zohal Uploader shutdown complete.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application interrupted by user.")
