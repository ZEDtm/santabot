from aiogram import F, Router, types
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime
from typing import Optional, List

from database.models import SessionLocal, Participant, SantaPair, GiftConfirmation
from database.crud import (
    get_participant_by_telegram, get_santa_pair, create_gift_confirmation,
    get_gift_confirmations, has_gift_confirmation
)
from services.pairing import get_recipient_info
from utils.logging import get_logger

logger = get_logger(__name__)
router = Router()

class GiftConfirmationStates(StatesGroup):
    waiting_for_tracking = State()
    waiting_for_message = State()

def get_gifts_keyboard() -> InlineKeyboardMarkup:
    """Create gifts management keyboard"""
    keyboard = [
        [
            InlineKeyboardButton(
                text="✅ Подтвердить отправку",
                callback_data="confirm_gift_sent"
            )
        ],
        [
            InlineKeyboardButton(
                text="📦 История отправок",
                callback_data="gift_history"
            )
        ],
        [
            InlineKeyboardButton(
                text="❌ Закрыть",
                callback_data="close_gifts"
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

@router.callback_query(F.data == "gift_menu")
async def gift_menu(callback: CallbackQuery):
    """Show gift management menu"""
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
            
        recipient_info = get_recipient_info(participant.id, participant.event_id)
        if not recipient_info:
            await callback.answer("❌ Информация о получателе не найдена.")
            return
            
        # Check if gift was already confirmed
        gift_sent = has_gift_confirmation(db, pair.id)
        
        message = (
            f"🎁 <b>Управление подарком</b>\n\n"
            f"Получатель: {recipient_info['name']} {recipient_info['username']}\n"
            f"Статус: {'✅ Подарок отправлен' if gift_sent else '❌ Подарок ещё не отправлен'}\n\n"
            "Здесь вы можете подтвердить отправку подарка и добавить информацию для получателя."
        )
        
        await callback.message.edit_text(
            message,
            reply_markup=get_gifts_keyboard()
        )
        
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {str(e)}")
    finally:
        db.close()
    await callback.answer()

@router.callback_query(F.data == "confirm_gift_sent")
async def start_gift_confirmation(callback: CallbackQuery, state: FSMContext):
    """Start gift confirmation process"""
    db = SessionLocal()
    try:
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
            
        # Check if already confirmed
        if has_gift_confirmation(db, pair.id):
            await callback.answer("✅ Вы уже подтвердили отправку подарка.")
            return
            
        await state.set_state(GiftConfirmationStates.waiting_for_tracking)
        await state.update_data(pair_id=pair.id)
        
        await callback.message.answer(
            "📦 <b>Подтверждение отправки подарка</b>\n\n"
            "Пожалуйста, укажите номер отслеживания (если есть) или нажмите /skip, чтобы пропустить:"
        )
        
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {str(e)}")
    finally:
        db.close()
    await callback.answer()

@router.message(GiftConfirmationStates.waiting_for_tracking, F.text != "/skip")
async def process_tracking_number(message: Message, state: FSMContext):
    """Process tracking number and ask for optional message"""
    await state.update_data(tracking_number=message.text)
    await state.set_state(GiftConfirmationStates.waiting_for_message)
    
    await message.answer(
        "💌 Хотите оставить сообщение получателю? (необязательно)\n\n"
        "Напишите ваше сообщение или нажмите /skip, чтобы пропустить:"
    )

@router.message(GiftConfirmationStates.waiting_for_tracking, F.text == "/skip")
async def skip_tracking_number(message: Message, state: FSMContext):
    """Skip tracking number and ask for optional message"""
    await state.update_data(tracking_number=None)
    await state.set_state(GiftConfirmationStates.waiting_for_message)
    
    await message.answer(
        "💌 Хотите оставить сообщение получателю? (необязательно)\n\n"
        "Напишите ваше сообщение или нажмите /skip, чтобы пропустить:"
    )

@router.message(GiftConfirmationStates.waiting_for_message)
async def process_gift_message(message: Message, state: FSMContext):
    """Process gift confirmation"""
    data = await state.get_data()
    db = SessionLocal()
    
    try:
        # Get message text (or None if skipped)
        message_text = message.text if message.text != "/skip" else None
        
        # Create gift confirmation
        confirmation = create_gift_confirmation(
            db=db,
            pair_id=data['pair_id'],
            tracking_number=data.get('tracking_number'),
            message=message_text
        )
        
        # Get pair and recipient info
        pair = db.query(SantaPair).get(data['pair_id'])
        recipient = pair.receiver
        
        # Notify recipient
        try:
            notification_text = (
                "🎁 <b>Ваш Тайный Санта отправил вам подарок!</b>\n\n"
            )
            
            if confirmation.tracking_number:
                notification_text += f"📦 Номер отслеживания: {confirmation.tracking_number}\n\n"
                
            if confirmation.message:
                notification_text += f"💌 Сообщение от Санты:\n{confirmation.message}\n\n"
                
            notification_text += "Скоро подарок будет у вас!"
            
            await message.bot.send_message(
                chat_id=recipient.telegram_id,
                text=notification_text
            )
        except Exception as e:
            logger.error(f"Failed to notify recipient: {e}")
        
        await message.answer(
            "✅ <b>Спасибо за подтверждение!</b>\n\n"
            "Получатель уведомлен о том, что подарок отправлен.",
            reply_markup=get_gifts_keyboard()
        )
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при подтверждении отправки: {str(e)}")
    finally:
        db.close()
        await state.clear()

@router.callback_query(F.data == "gift_history")
async def show_gift_history(callback: CallbackQuery):
    """Show gift sending history"""
    db = SessionLocal()
    try:
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
            
        confirmations = get_gift_confirmations(db, pair.id)
        
        if not confirmations:
            await callback.answer("❌ У вас ещё нет подтверждений отправки подарков.")
            return
            
        response = "📜 <b>История отправленных подарков</b>\n\n"
        
        for i, conf in enumerate(confirmations, 1):
            response += f"📅 <b>Отправлено:</b> {conf.sent_at.strftime('%d.%m.%Y %H:%M')}\n"
            if conf.tracking_number:
                response += f"📦 <b>Трек-номер:</b> {conf.tracking_number}\n"
            if conf.message:
                response += f"💬 <b>Сообщение:</b> {conf.message}\n"
            response += "\n"
        
        await callback.message.answer(
            response,
            reply_markup=get_gifts_keyboard()
        )
        
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка при загрузке истории: {str(e)}")
    finally:
        db.close()
    await callback.answer()

@router.callback_query(F.data == "close_gifts")
async def close_gifts_menu(callback: CallbackQuery):
    """Close gifts menu"""
    try:
        await callback.message.delete()
    except:
        pass
    await callback.answer()

def register_handlers(dp):
    """Register all gift handlers"""
    dp.include_router(router)
