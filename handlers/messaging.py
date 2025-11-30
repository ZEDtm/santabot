from aiogram import F, Router, types
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime
from typing import Optional

from database.models import Participant, SantaPair, SessionLocal
from database.crud import (
    get_participant_by_telegram, get_santa_pair, create_anonymous_message,
    get_messages_for_pair, is_user_admin
)
from services.pairing import get_recipient_info, get_santa_info
from utils.logging import get_logger

logger = get_logger(__name__)
router = Router()

class MessageStates(StatesGroup):
    waiting_for_message = State()
    waiting_for_reply = State()

def get_messaging_keyboard() -> InlineKeyboardMarkup:
    """Create messaging keyboard"""
    keyboard = [
        [
            InlineKeyboardButton(
                text="💌 Написать Санте",
                callback_data="message_santa"
            ),
            InlineKeyboardButton(
                text="📨 Написать получателю",
                callback_data="message_recipient"
            )
        ],
        [
            InlineKeyboardButton(
                text="📜 История сообщений",
                callback_data="message_history"
            ),
            InlineKeyboardButton(
                text="❌ Закрыть",
                callback_data="close_messaging"
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

async def check_pairing(telegram_id: int, event_id: int) -> tuple[bool, str]:
    """Check if user has a pair and return status message"""
    db = SessionLocal()
    try:
        participant = get_participant_by_telegram(db, event_id, telegram_id)
        if not participant:
            return False, "❌ Вы не зарегистрированы в этом мероприятии."
            
        pair = get_santa_pair(db, event_id, participant.id)
        if not pair:
            return False, "❌ Жеребьёвка ещё не проводилась."
            
        return True, ""
    finally:
        db.close()

@router.callback_query(F.data == "start_messaging")
async def start_messaging(callback: CallbackQuery):
    """Show messaging menu"""
    await callback.message.answer(
        "💬 <b>Анонимная переписка</b>\n\n"
        "Вы можете общаться со своим Тайным Сантой или получателем анонимно.",
        reply_markup=get_messaging_keyboard(),
        parse_mode='HTML'
    )
    await callback.answer()

@router.callback_query(F.data == "message_santa")
async def write_to_santa(callback: CallbackQuery, state: FSMContext):
    """Start writing a message to Santa"""
    db = SessionLocal()
    try:
        # Find the most recent event
        participant = db.query(Participant).filter(
            Participant.telegram_id == callback.from_user.id
        ).first()
        
        if not participant:
            await callback.answer("❌ Вы не зарегистрированы ни в одном мероприятии.")
            return
            
        # Ищем пару, где текущий пользователь - получатель (receiver), а санта - другой участник
        pair = db.query(SantaPair).filter(
            SantaPair.event_id == participant.event_id,
            SantaPair.receiver_id == participant.id  # Мы - получатель, хотим написать САНТЕ
        ).first()
        
        if not pair:
            await callback.answer("❌ Жеребьёвка ещё не проводилась или пара не найдена.")
            return
            
        # Получаем информацию о Санте (отправитель сообщения для санты)
        santa = db.query(Participant).filter(Participant.id == pair.santa_id).first()
        if not santa:
            await callback.answer("❌ Информация о Санте не найдена.")
            return
            
        await state.set_state(MessageStates.waiting_for_message)
        await state.update_data(
            recipient_type="santa",
            event_id=participant.event_id,
            recipient_id=pair.santa_id,  # ID санты - тот, кому отправляем
            sender_id=participant.id     # ID отправителя (нас)
        )
        
        await callback.message.answer(
            f"✍️ <b>Напишите сообщение вашему Тайному Санте</b>\n\n"
            "Вы можете отправить текст, голосовое или фото-сообщение.",
            parse_mode='HTML'
        )
        
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {str(e)}")
    finally:
        db.close()
    await callback.answer()

@router.callback_query(F.data == "message_recipient")
async def write_to_recipient(callback: CallbackQuery, state: FSMContext):
    """Start writing a message to recipient"""
    db = SessionLocal()
    try:
        # Find the most recent event
        participant = db.query(Participant).filter(
            Participant.telegram_id == callback.from_user.id
        ).first()
        
        if not participant:
            await callback.answer("❌ Вы не зарегистрированы ни в одном мероприятии.")
            return
            
        # Ищем пару, где текущий пользователь - санта, а получатель - другой участник
        pair = db.query(SantaPair).filter(
            SantaPair.event_id == participant.event_id,
            SantaPair.santa_id == participant.id  # Мы - санта, хотим написать ПОЛУЧАТЕЛЮ
        ).first()
        
        if not pair:
            await callback.answer("❌ Жеребьёвка ещё не проводилась или пара не найдена.")
            return
            
        # Получаем информацию о получателе
        recipient = db.query(Participant).filter(Participant.id == pair.receiver_id).first()
        if not recipient:
            await callback.answer("❌ Информация о получателе не найдена.")
            return
            
        await state.set_state(MessageStates.waiting_for_message)
        await state.update_data(
            recipient_type="recipient",
            event_id=participant.event_id,
            recipient_id=pair.receiver_id,  # ID получателя - тот, кому отправляем
            sender_id=participant.id        # ID отправителя (нас)
        )
        
        await callback.message.answer(
            f"✍️ <b>Напишите сообщение вашему получателю</b>\n\n"
            f"Получатель: {recipient.first_name or ''} {recipient.last_name or ''} ({recipient.username or ''})\n\n"
            "Вы можете отправить текст, голосовое или фото-сообщение.",
            parse_mode='HTML'
        )
        
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {str(e)}")
    finally:
        db.close()
    await callback.answer()

@router.message(MessageStates.waiting_for_message)
async def process_message(message: Message, state: FSMContext):
    """Process and send the message"""
    data = await state.get_data()
    db = SessionLocal()
    
    try:
        # Get recipient info
        recipient = db.query(Participant).get(data['recipient_id'])
        if not recipient:
            await message.answer("❌ Ошибка: получатель не найден.")
            return
            
        # Get sender info
        sender = db.query(Participant).get(data['sender_id'])
        if not sender:
            await message.answer("❌ Ошибка: отправитель не найден.")
            return
            
        # Find the pair
        pair = db.query(SantaPair).filter(
            SantaPair.event_id == data['event_id'],
            SantaPair.santa_id == (data['sender_id'] if data['recipient_type'] == 'recipient' else data['recipient_id']),
            SantaPair.receiver_id == (data['recipient_id'] if data['recipient_type'] == 'recipient' else data['sender_id'])
        ).first()
        
        if not pair:
            await message.answer("❌ Ошибка: пара не найдена.")
            return
            
        # Handle different message types
        if message.text:
            message_text = message.text
        elif message.caption:
            message_text = message.caption
        else:
            message_text = "[Медиа-сообщение]"
            
        # Create message record
        db_message = create_anonymous_message(
            db=db,
            pair_id=pair.id,
            message_text=message_text,
            from_santa=(data['recipient_type'] == 'recipient')  # True если сообщение ОТ санты
        )
        
        # Определяем имя отправителя для получателя
        if data['recipient_type'] == 'recipient':
            # Мы - санта, пишем получателю
            sender_display_name = "Ваш Тайный Санта"
        else:
            # Мы - получатель, пишем санте
            sender_display_name = "Ваш получатель"
        
        # Prepare reply keyboard
        reply_markup = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✉️ Ответить",
                    callback_data=f"reply_{pair.id}"
                )
            ]
        ])
        
        # Send the message to recipient
        try:
            if message.photo:
                await message.bot.send_photo(
                    chat_id=recipient.telegram_id,  # Важно: отправляем НАСТОЯЩЕМУ получателю
                    photo=message.photo[-1].file_id,
                    caption=f"💌 <b>Новое сообщение от {sender_display_name}:</b>\n\n{message_text}",
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )
            elif message.voice:
                await message.bot.send_voice(
                    chat_id=recipient.telegram_id,  # Важно: отправляем НАСТОЯЩЕМУ получателю
                    voice=message.voice.file_id,
                    caption=f"💌 <b>Новое сообщение от {sender_display_name}:</b>\n\n{message_text}",
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )
            else:
                await message.bot.send_message(
                    chat_id=recipient.telegram_id,  # Важно: отправляем НАСТОЯЩЕМУ получателю
                    text=f"💌 <b>Новое сообщение от {sender_display_name}:</b>\n\n{message_text}",
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )
            
            await message.answer("✅ Сообщение отправлено!")
            
        except Exception as e:
            await message.answer("❌ Не удалось отправить сообщение. Возможно, пользователь заблокировал бота.")
            
    except Exception as e:
        await message.answer(f"❌ Ошибка при отправке сообщения: {str(e)}")
    finally:
        db.close()
        await state.clear()

@router.callback_query(F.data.startswith("reply_"))
async def prepare_reply(callback: CallbackQuery, state: FSMContext):
    """Prepare to reply to a message"""
    try:
        pair_id = int(callback.data.split("_")[1])
        await state.set_state(MessageStates.waiting_for_reply)
        await state.update_data(pair_id=pair_id)
        
        await callback.message.answer("✍️ Напишите ваш ответ:")
        
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {str(e)}")
    await callback.answer()

@router.message(MessageStates.waiting_for_reply)
async def send_reply(message: Message, state: FSMContext):
    """Send reply to a message"""
    data = await state.get_data()
    db = SessionLocal()
    
    try:
        pair = db.query(SantaPair).get(data['pair_id'])
        if not pair:
            await message.answer("❌ Ошибка: пара не найдена.")
            return
            
        # Determine sender and recipient
        sender = get_participant_by_telegram(db, pair.event_id, message.from_user.id)
        if not sender:
            await message.answer("❌ Ошибка: участник не найден.")
            return
            
        # Check if user is part of this pair
        if sender.id not in [pair.santa_id, pair.receiver_id]:
            await message.answer("❌ Ошибка: у вас нет прав отвечать на это сообщение.")
            return
            
        # Determine recipient
        recipient_id = pair.receiver_id if sender.id == pair.santa_id else pair.santa_id
        recipient = db.query(Participant).get(recipient_id)
        if not recipient:
            await message.answer("❌ Ошибка: получатель не найден.")
            return
            
        # Save message to database
        db_message = create_anonymous_message(
            db=db,
            pair_id=pair.id,
            message_text=message.text,
            from_santa=(sender.id == pair.santa_id)
        )
        
        # Send notification to recipient
        sender_name = "Тайный Санта" if sender.id == pair.santa_id else "Ваш получатель"
        
        # Prepare reply keyboard
        reply_markup = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✉️ Ответить",
                    callback_data=f"reply_{pair.id}"
                )
            ]
        ])
        
        # Send the message
        await message.bot.send_message(
            chat_id=recipient.telegram_id,
            text=f"💌 <b>Ответ от {sender_name}:</b>\n\n{message.text}",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
        await message.answer("✅ Ответ отправлен!")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при отправке ответа: {str(e)}")
    finally:
        db.close()
        await state.clear()

@router.callback_query(F.data == "message_history")
async def show_message_history(callback: CallbackQuery):
    """Show message history for current user"""
    db = SessionLocal()
    try:
        # Find the most recent event
        participant = db.query(Participant).filter(
            Participant.telegram_id == callback.from_user.id
        ).order_by(Participant.id.desc()).first()
        
        if not participant:
            await callback.answer("❌ Вы не зарегистрированы ни в одном мероприятии.")
            return
            
        pair = get_santa_pair(db, participant.event_id, participant.id)
        if not pair:
            await callback.answer("❌ Жеребьёвка ещё не проводилась.")
            return
            
        # Get message history
        messages = get_messages_for_pair(db, pair.id, limit=20)  # Last 20 messages
        
        if not messages:
            await callback.message.answer("📭 У вас пока нет сообщений.")
            return
            
        # Group messages by date
        messages_by_date = {}
        for msg in messages:
            date_str = msg.created_at.strftime("%d.%m.%Y")
            if date_str not in messages_by_date:
                messages_by_date[date_str] = []
            messages_by_date[date_str].append(msg)
        
        # Format message history
        response = "📜 <b>История переписки</b>\n\n"
        
        for date_str, msgs in messages_by_date.items():
            response += f"📅 <b>{date_str}</b>\n"
            for msg in msgs:
                time_str = msg.created_at.strftime("%H:%M")
                sender = "Вы" if (msg.from_santa and participant.id == pair.santa_id) or \
                             (not msg.from_santa and participant.id == pair.receiver_id) \
                          else "Тайный Санта" if msg.from_santa else "Ваш получатель"
                response += f"{time_str} <b>{sender}:</b> {msg.message_text[:50]}"
                if len(msg.message_text) > 50:
                    response += "..."
                response += "\n"
            response += "\n"
        
        await callback.message.answer(
            response,
            reply_markup=get_messaging_keyboard(),
            parse_mode='HTML'
        )
        
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка при загрузке истории: {str(e)}")
    finally:
        db.close()
    await callback.answer()

@router.callback_query(F.data == "close_messaging")
async def close_messaging(callback: CallbackQuery):
    """Close messaging menu"""
    try:
        await callback.message.delete()
    except:
        pass
    await callback.answer()

def register_handlers(dp):
    """Register all messaging handlers"""
    dp.include_router(router)
