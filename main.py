import asyncio
from datetime import timedelta
import logging
from pathlib import Path
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.strategy import FSMStrategy
from aiogram import BaseMiddleware
from typing import Callable, Dict, Any, Awaitable

from config import settings
from database import models
from utils.logging import setup_logging, get_logger

class GroupChatMiddleware(BaseMiddleware):
    """Middleware to handle group chat commands"""
    async def __call__(
        self,
        handler: Callable[[types.Message, Dict[str, Any]], Awaitable[Any]],
        event: types.Message,
        data: Dict[str, Any]
    ) -> Any:
        # Skip if not a command
        if not event.text or not event.text.startswith('/'):
            return await handler(event, data)
            
        # Get the command without bot username and parameters
        command = event.text.split('@')[0].split(' ')[0][1:].lower()
        
        # Allow only specific commands in groups
        allowed_commands = ['start', 'help', 'link', 'link_chat']
        
        # if event.chat.type in ['group', 'supergroup'] and command not in allowed_commands:
        #     if event.text.startswith('/'):
        #         await event.reply(
        #             "❌ Эта команда недоступна в групповых чатах. "
        #             "Используйте личные сообщения для управления ботом."
        #         )
        #     return None
            
        return await handler(event, data)

# Setup logging
setup_logging()
logger = get_logger(__name__)

# Initialize bot and dispatcher
bot = Bot(token=settings.BOT_TOKEN)
storage = MemoryStorage()

dp = Dispatcher(storage=storage, fsm_strategy=FSMStrategy.USER_IN_CHAT)

# Import handlers after dp is defined to avoid circular imports
from handlers import common, admin, user, messaging, group_chat

# Register handlers
common.register_handlers(dp)
admin.register_handlers(dp)
user.register_handlers(dp)
messaging.register_handlers(dp)
group_chat.register_group_handlers(dp, bot)  # Pass bot instance to group chat handlers

# Disable commands in groups
dp.message.middleware(GroupChatMiddleware())

async def on_startup() -> None:
    """Actions on bot startup"""
    logger.info("Starting bot...")
    # Initialize database
    models.init_db()
    logger.info("Database initialized")
    
    # Initialize notification service
    from services.notifications import init_notification_service
    await init_notification_service(bot)
    logger.info("Notification service started")
    
    
    # db = models.SessionLocal()
    
    
    # santa_pairs = db.query(models.SantaPair).all()
    # for s in santa_pairs:
    #     db.delete(s)

    # messages = db.query(models.AnonymousMessage).all()
    # for m in messages:
    #     db.delete(m)
    # event = db.query(models.Event).filter(models.Event.id == 1).first()
    # event.status = 'registration'


    # event.registration_end = event.registration_end - timedelta(days=1)
    
    # db.commit()

async def on_shutdown() -> None:
    """Actions on bot shutdown"""
    logger.info("Shutting down...")
    
    # Stop notification service
    from services.notifications import stop_notification_service
    await stop_notification_service()
    logger.info("Notification service stopped")
    
    await dp.storage.close()
    await dp.storage.wait_closed()
    logger.info("Bot stopped")

async def main() -> None:
    """Main function to start the bot"""
    # Set up startup and shutdown handlers
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    # Start polling
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        raise