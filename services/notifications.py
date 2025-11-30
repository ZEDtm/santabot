from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import asyncio
import logging
from pathlib import Path

from database.models import SessionLocal, Event, Participant
from database.crud import get_events_with_active_registration, get_events_with_upcoming_deadline
from services.pairing import get_recipient_info
from utils.logging import get_logger

logger = get_logger(__name__)

class NotificationService:
    def __init__(self, bot):
        self.bot = bot
        self.running = False
        self.task = None
        self.logger = get_logger(f"{__name__}.NotificationService")

    async def start(self):
        """Start the notification service"""
        if self.running:
            self.logger.warning("Notification service is already running")
            return
            
        self.running = True
        self.task = asyncio.create_task(self._run())
        self.logger.info("Notification service started")
        
    async def stop(self):
        """Stop the notification service"""
        if not self.running:
            self.logger.warning("Notification service is not running")
            return
            
        self.logger.info("Stopping notification service...")
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                self.logger.info("Notification service task was cancelled")
            except Exception as e:
                self.logger.error(f"Error stopping notification service: {e}", exc_info=True)
        self.logger.info("Notification service stopped")
            
    async def _run(self):
        """Main notification loop"""
        while self.running:
            try:
                await self._check_and_send_notifications()
            except Exception as e:
                logger.error(f"Error in notification service: {e}", exc_info=True)
                
            # Check every 30 minutes
            await asyncio.sleep(1800)
            
    async def _check_and_send_notifications(self):
        """Check for notifications that need to be sent"""
        db = SessionLocal()
        try:
            # Check for registration end reminders
            await self._check_registration_reminders(db)
            
            # Check for shipping deadline reminders
            await self._check_shipping_reminders(db)
            
            # Check for event start/end notifications
            await self._check_event_status_changes(db)
            
        except Exception as e:
            logger.error(f"Error checking notifications: {e}")
        finally:
            db.close()
            
    async def _check_registration_reminders(self, db):
        """Send reminders about registration end"""
        # Get events where registration ends in 24 hours or 1 hour
        events_24h = get_events_with_active_registration(
            db, 
            time_left=timedelta(hours=24),
            min_time_left=timedelta(hours=23)
        )
        
        events_1h = get_events_with_active_registration(
            db,
            time_left=timedelta(hours=1),
            min_time_left=timedelta(minutes=59)
        )
        
        for event in events_24h + events_1h:
            time_left = event.registration_end - datetime.now()
            if time_left > timedelta(hours=24) or time_left < timedelta(hours=0):
                continue
                
            hours = int(time_left.total_seconds() // 3600)
            minutes = int((time_left.total_seconds() % 3600) // 60)
            
            if hours > 0:
                time_str = f"{hours} час(ов)"
            else:
                time_str = f"{minutes} минут"
                
            message = (
                f"⏳ <b>Напоминание о завершении регистрации</b>\n\n"
                f"До окончания регистрации на мероприятие \"{event.title}\" осталось {time_str}.\n\n"
                f"📅 Окончание: {event.registration_end.strftime('%d.%m.%Y %H:%M')}\n"
                f"👥 Участников: {len(event.participants)}"
            )
            
            await self._notify_participants(event, message)
            
    async def _check_shipping_reminders(self, db):
        """Send reminders about shipping deadline"""
        # Get events where shipping deadline is in 3 days or 1 day
        events_3d = get_events_with_upcoming_deadline(
            db,
            time_left=timedelta(days=3),
            min_time_left=timedelta(days=2, hours=23)
        )
        
        events_1d = get_events_with_upcoming_deadline(
            db,
            time_left=timedelta(days=1),
            min_time_left=timedelta(hours=23)
        )
        
        for event in events_3d + events_1d:
            time_left = event.shipping_deadline - datetime.now()
            if time_left > timedelta(days=3) or time_left < timedelta(hours=0):
                continue
                
            days = time_left.days
            hours = int((time_left.seconds // 3600) % 24)
            
            if days > 0:
                time_str = f"{days} {self._plural_days(days)}"
            else:
                time_str = f"{hours} {self._plural_hours(hours)}"
                
            message = (
                f"📦 <b>Напоминание о сроках отправки подарков</b>\n\n"
                f"До крайнего срока отправки подарков для мероприятия \"{event.title}\" осталось {time_str}.\n\n"
                f"📅 Крайний срок: {event.shipping_deadline.strftime('%d.%m.%Y')}\n"
                f"🎁 Получатель: {self._get_recipient_info_message(event)}"
            )
            
            await self._notify_participants(event, message, only_with_recipients=True)
            
    async def _check_event_status_changes(self, db):
        """Send notifications about event status changes"""
        # Check for events that just started (registration ended)
        events_started = get_events_with_active_registration(
            db,
            time_left=timedelta(minutes=-5),
            min_time_left=timedelta(minutes=-10),
            status='registration'
        )
        
        for event in events_started:
            # Update event status
            event.status = 'in_progress'
            db.commit()
            
            message = (
                f"🎉 <b>Регистрация завершена!</b>\n\n"
                f"Мероприятие \"{event.title}\" началось!\n\n"
                f"👥 Участников: {len(event.participants)}\n"
                f"📦 Крайний срок отправки: {event.shipping_deadline.strftime('%d.%m.%Y')}"
            )
            
            await self._notify_group(event, message)
            
        # Check for events that just ended (shipping deadline passed)
        events_ended = get_events_with_upcoming_deadline(
            db,
            time_left=timedelta(minutes=-5),
            min_time_left=timedelta(minutes=-10),
            status='in_progress'
        )
        
        for event in events_ended:
            # Update event status
            event.status = 'completed'
            db.commit()
            
            message = (
                f"🏁 <b>Мероприятие завершено!</b>\n\n"
                f"Спасибо за участие в \"{event.title}\"!\n\n"
                f"Надеемся, вам понравилось! 🎅🎄"
            )
            
            await self._notify_group(event, message)
    
    async def _notify_participants(self, event: Event, message: str, only_with_recipients: bool = False):
        """Send notification to all participants"""
        for participant in event.participants:
            try:
                if only_with_recipients:
                    # Check if participant has a recipient
                    has_recipient = any(
                        p.santa_id == participant.id 
                        for p in event.pairs
                    )
                    if not has_recipient:
                        continue
                        
                await self.bot.send_message(
                    chat_id=participant.telegram_id,
                    text=message
                )
            except Exception as e:
                logger.error(f"Failed to send notification to {participant.telegram_id}: {e}")
    
    async def _notify_group(self, event: Event, message: str):
        """Send notification to the group chat"""
        try:
            await self.bot.send_message(
                chat_id=event.group_id,
                text=message
            )
        except Exception as e:
            logger.error(f"Failed to send group notification for event {event.id}: {e}")
    
    def _get_recipient_info_message(self, event: Event) -> str:
        """Get formatted recipient info for notification"""
        if not event.pairs:
            return "Информация о получателе недоступна"
            
        pair = event.pairs[0]  # Just get first pair for the message
        recipient = pair.receiver
        return (
            f"👤 {recipient.first_name} "
            f"({f'@{recipient.username}' if recipient.username else 'без username'})\n"
            f"🏠 Адрес: {recipient.address or 'не указан'}\n"
            f"📦 Предпочтения: {recipient.delivery_methods or 'не указаны'}"
        )
    
    @staticmethod
    def _plural_days(n: int) -> str:
        """Get correct plural form for days"""
        if n % 10 == 1 and n % 100 != 11:
            return "день"
        elif 2 <= n % 10 <= 4 and (n % 100 < 10 or n % 100 >= 20):
            return "дня"
        else:
            return "дней"
    
    @staticmethod
    def _plural_hours(n: int) -> str:
        """Get correct plural form for hours"""
        if n % 10 == 1 and n % 100 != 11:
            return "час"
        elif 2 <= n % 10 <= 4 and (n % 100 < 10 or n % 100 >= 20):
            return "часа"
        else:
            return "часов"

# Global notification service instance
notification_service = None

async def init_notification_service(bot):
    """Initialize the global notification service"""
    global notification_service
    notification_service = NotificationService(bot)
    await notification_service.start()
    return notification_service

async def stop_notification_service():
    """Stop the global notification service"""
    global notification_service
    if notification_service:
        await notification_service.stop()
        notification_service = None
