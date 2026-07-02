import asyncio
import logging
import uvicorn
from core.config import ConfigManager
from database.db import Database
from bot.bot import BotService
from web.server import app

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
        # Start Pyrogram client in the background of this event loop
        asyncio.create_task(BotService.start())
    else:
        logger.warning("Setup is NOT completed. Bot will start after Setup Wizard is completed at WebUI.")

    # Start FastAPI Webserver (runs both the setup wizard and the dashboard)
    # Using 0.0.0.0 to make it accessible outside, and dynamic port from config
    port = int(config.get("web_port", 7531))
    uvicorn_config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=port,
        log_level="info",
        loop="asyncio"
    )
    server = uvicorn.Server(uvicorn_config)
    
    logger.info(f"Starting Webserver on http://0.0.0.0:{port}")
    await server.serve()
    
    # Cleanup bot connection on webserver shutdown
    if BotService.is_running():
        logger.info("Stopping Bot Service on exit...")
        await BotService.stop()
        
    logger.info("Zohal Uploader shutdown complete.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application interrupted by user.")
