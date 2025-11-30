import asyncio
import random
from aiogram import Bot
from typing import List, Dict, Tuple, Optional
from database.models import SessionLocal, Participant, SantaPair, Event
from database.crud import get_participant_by_telegram, create_santa_pair
from utils.logging import get_logger
from datetime import datetime

logger = get_logger(__name__)

def generate_pairs(event_id: int) -> Tuple[bool, str]:
    """
    Generate secret santa pairs for an event
    Returns (success: bool, message: str)
    """
    db = SessionLocal()
    try:
        participants = db.query(Participant).filter(
            Participant.event_id == event_id
        ).all()
        
        if len(participants) < 3:
            return False, "❌ Для жеребьёвки нужно минимум 3 участника."
            
        existing_pairs = db.query(SantaPair).filter(
            SantaPair.event_id == event_id
        ).count()
        
        if existing_pairs > 0:
            return False, "❌ Жеребьёвка уже была проведена для этого мероприятия."
        
        # Create a list of participant IDs
        participant_ids = [p.id for p in participants]
        # Shuffle ids
        random.shuffle(participant_ids)
        # Create a list of random recipients and reverse it to avoid getting the same ID
        receivers = participant_ids.copy()
        # If the list is not even, swap the beginning and middle
        if len(receivers) % 2 != 0:
            receivers[len(receivers) // 2], receivers[0] = receivers[0], receivers[len(receivers) // 2]

        receivers.reverse()

        try:
            for santa_id, receiver_id in zip(participant_ids, receivers):
                create_santa_pair(db, event_id, santa_id, receiver_id)
            
            # Update event status
            event = db.query(Event).get(event_id)
            if event:
                event.status = 'in_progress'
                db.commit()
            
            return True, "✅ Жеребьёвка успешно проведена!"
        
        except Exception as e:
            db.rollback()
        
        return False, "❌ Не удалось сгенерировать пары. Попробуйте снова."
    
    except Exception as e:
        db.rollback()
        return False, f"❌ Ошибка при проведении жеребьёвки: {str(e)}"
    finally:
        db.close()


def get_recipient_info(participant_id: int, event_id: int) -> Optional[Dict]:
    """Get recipient information for a santa"""
    db = SessionLocal()
    try:
        pair = db.query(SantaPair).filter(
            SantaPair.event_id == event_id,
            SantaPair.santa_id == participant_id
        ).first()
        
        if not pair or not pair.receiver:
            return None
            
        receiver = pair.receiver
        return {
            'name': receiver.first_name,
            'username': f"@{receiver.username}" if receiver.username else "не указан",
            'wishes': receiver.wishes or "не указаны",
            'address': receiver.address or "не указан",
            'delivery_methods': receiver.delivery_methods or "не указаны"
        }
    except Exception as e:
        return None
    finally:
        db.close()

def get_santa_info(participant_id: int, event_id: int) -> Optional[Dict]:
    """Get santa information for a recipient"""
    db = SessionLocal()
    try:
        pair = db.query(SantaPair).filter(
            SantaPair.event_id == event_id,
            SantaPair.receiver_id == participant_id
        ).first()
        
        if not pair or not pair.santa:
            return None
            
        santa = pair.santa
        return {
            'name': santa.first_name,
            'username': f"@{santa.username}" if santa.username else "не указан"
        }
    except Exception as e:
        return None
    finally:
        db.close()

async def send_pairing_notifications(bot: Bot, event_id: int) -> None:
    """Send notifications to all participants about their pairs"""
    db = SessionLocal()
    try:
        pairs = db.query(SantaPair).filter(
            SantaPair.event_id == event_id
        ).all()
        
        for pair in pairs:
            try:
                # Get recipient info
                recipient_info = get_recipient_info(pair.santa_id, event_id)
                if not recipient_info:
                    continue
                
                # Prepare message for santa
                message = (
                    "🎅 <b>Жеребьёвка проведена!</b>\n\n"
                    f"Вы дарите подарок: <b>{recipient_info['name']}</b>\n"
                    f"Ник: {recipient_info['username']}\n\n"
                    "<b>Пожелания получателя:</b>\n"
                    f"{recipient_info['wishes']}\n\n"
                    "<b>Адрес доставки:</b>\n"
                    f"{recipient_info['address']}\n\n"
                    "<b>Предпочтительные способы доставки:</b>\n"
                    f"{recipient_info['delivery_methods']}"
                )
                
                # Send message to santa
                await bot.send_message(pair.santa.telegram_id, message, parse_mode='HTML')
            except Exception as e:
                logger.error(f"Error sending notification to {pair.santa_id}: {str(e)}")
                continue
                
    except Exception as e:
        logger.error(f"Error in send_pairing_notifications: {str(e)}")
    finally:
        db.close()
