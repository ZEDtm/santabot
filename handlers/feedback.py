from aiogram import F, Router, types
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime
from typing import Optional, List

from database.models import SessionLocal, Participant, SantaPair, Feedback
from database.crud import (
    get_participant_by_telegram, get_santa_pair, create_feedback,
    get_feedback_for_pair, has_feedback, get_average_rating
)
from services.pairing import get_recipient_info, get_santa_info
from utils.logging import get_logger

logger = get_logger(__name__)
router = Router()

class FeedbackStates(StatesGroup):
    waiting_for_rating = State()
    waiting_for_message = State()

def get_feedback_keyboard(has_feedback: bool = False) -> InlineKeyboardMarkup:
    """Create feedback management keyboard"""
    keyboard = [
        [
            InlineKeyboardButton(
                text="⭐ Оставить благодарность",
                callback_data="leave_feedback"
            ) if not has_feedback else
            InlineKeyboardButton(
                text="✏️ Изменить отзыв",
                callback_data="leave_feedback"
            )
        ],
        [
            InlineKeyboardButton(
                text="📜 История отзывов",
                callback_data="view_feedback_history"
            )
        ],
        [
            InlineKeyboardButton(
                text="🔙 Назад",
                callback_data="back_to_main"
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_rating_keyboard() -> InlineKeyboardMarkup:
    """Create rating selection keyboard"""
    keyboard = [
        [
            InlineKeyboardButton(text="⭐", callback_data="rate_1"),
            InlineKeyboardButton(text="⭐⭐", callback_data="rate_2"),
            InlineKeyboardButton(text="⭐⭐⭐", callback_data="rate_3"),
            InlineKeyboardButton(text="⭐⭐⭐⭐", callback_data="rate_4"),
            InlineKeyboardButton(text="⭐⭐⭐⭐⭐", callback_data="rate_5"),
        ],
        [
            InlineKeyboardButton(
                text="Пропустить оценку",
                callback_data="skip_rating"
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

@router.callback_query(F.data == "feedback_menu")
async def feedback_menu(callback: CallbackQuery):
    """Show feedback management menu"""
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
            
        # Check if feedback was already left
        feedback_exists = has_feedback(db, pair.id)
        
        message = (
            "💌 <b>Благодарность вашему Тайному Санте</b>\n\n"
            "Здесь вы можете оставить отзыв и поблагодарить вашего Тайного Санту. "
            "Ваш отзыв будет анонимным и поможет сделать будущие мероприятия лучше!"
        )
        
        await callback.message.edit_text(
            message,
            reply_markup=get_feedback_keyboard(feedback_exists)
        )
        
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {str(e)}")
    finally:
        db.close()
    await callback.answer()

@router.callback_query(F.data == "leave_feedback")
async def start_feedback(callback: CallbackQuery, state: FSMContext):
    """Start the feedback process"""
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
            
        await state.set_state(FeedbackStates.waiting_for_rating)
        await state.update_data(pair_id=pair.id)
        
        await callback.message.edit_text(
            "⭐ <b>Оцените подарок от вашего Тайного Санты</b>\n\n"
            "Пожалуйста, выберите оценку от 1 до 5 звёзд. Это необязательно, но поможет нам стать лучше!",
            reply_markup=get_rating_keyboard()
        )
        
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {str(e)}")
    finally:
        db.close()
    await callback.answer()

@router.callback_query(F.data.startswith("rate_"), FeedbackStates.waiting_for_rating)
async def process_rating(callback: CallbackQuery, state: FSMContext):
    """Process rating selection"""
    try:
        rating = int(callback.data.split("_")[1])
        await state.update_data(rating=rating)
        await state.set_state(FeedbackStates.waiting_for_message)
        
        await callback.message.edit_text(
            "💬 <b>Напишите ваше сообщение</b>\n\n"
            "Напишите несколько слов благодарности вашему Тайному Санте. "
            "Вы можете рассказать, что вам понравилось в подарке, или просто оставить добрые пожелания."
        )
        
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {str(e)}")
    await callback.answer()

@router.callback_query(F.data == "skip_rating", FeedbackStates.waiting_for_rating)
async def skip_rating(callback: CallbackQuery, state: FSMContext):
    """Skip rating and ask for message"""
    await state.update_data(rating=None)
    await state.set_state(FeedbackStates.waiting_for_message)
    
    await callback.message.edit_text(
        "💬 <b>Напишите ваше сообщение</b>\n\n"
        "Напишите несколько слов благодарности вашему Тайному Санте. "
        "Вы можете рассказать, что вам понравилось в подарке, или просто оставить добрые пожелания."
    )
    await callback.answer()

@router.message(FeedbackStates.waiting_for_message, F.text)
async def process_feedback_message(message: Message, state: FSMContext):
    """Process feedback message and save it"""
    data = await state.get_data()
    db = SessionLocal()
    
    try:
        # Create feedback
        feedback = create_feedback(
            db=db,
            pair_id=data['pair_id'],
            message=message.text,
            rating=data.get('rating')
        )
        
        # Get pair and santa info
        pair = db.query(SantaPair).get(data['pair_id'])
        santa = pair.santa
        
        # Notify Santa if they have a username
        try:
            notification_text = (
                "🎉 <b>Вы получили благодарность от получателя!</b>\n\n"
            )
            
            if feedback.rating:
                notification_text += f"⭐ Оценка: {feedback.rating}/5\n\n"
                
            notification_text += f"💌 Сообщение:\n{feedback.message}"
            
            await message.bot.send_message(
                chat_id=santa.telegram_id,
                text=notification_text
            )
        except Exception as e:
            logger.error(f"Failed to notify Santa: {e}")
        
        await message.answer(
            "✅ <b>Спасибо за ваш отзыв!</b>\n\n"
            "Ваша благодарность была отправлена вашему Тайному Санте.",
            reply_markup=get_feedback_keyboard(has_feedback=True)
        )
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при сохранении отзыва: {str(e)}")
    finally:
        db.close()
        await state.clear()

@router.callback_query(F.data == "view_feedback_history")
async def view_feedback_history(callback: CallbackQuery):
    """Show feedback history"""
    db = SessionLocal()
    try:
        participant = db.query(Participant).filter(
            Participant.telegram_id == callback.from_user.id
        ).order_by(Participant.id.desc()).first()
        
        if not participant:
            await callback.answer("❌ Вы не зарегистрированы ни в одном мероприятии.")
            return
            
        # Get all pairs where user was a Santa (to see feedback they received)
        santa_pairs = (
            db.query(SantaPair)
            .join(Participant, SantaPair.receiver_id == Participant.id)
            .filter(
                SantaPair.santa_id == participant.id,
                SantaPair.event_id == participant.event_id
            )
            .all()
        )
        
        response = "📜 <b>История ваших отзывов</b>\n\n"
        
        if not santa_pairs:
            response += "У вас пока нет отзывов от получателей."
        else:
            for pair in santa_pairs:
                feedback_list = get_feedback_for_pair(db, pair.id)
                if feedback_list:
                    receiver = pair.receiver
                    response += f"👤 <b>Получатель:</b> {receiver.first_name}"
                    if receiver.username:
                        response += f" (@{receiver.username})"
                    response += "\n"
                    
                    for feedback in feedback_list:
                        response += f"📅 {feedback.created_at.strftime('%d.%m.%Y %H:%M')}\n"
                        if feedback.rating:
                            response += f"⭐ Оценка: {feedback.rating}/5\n"
                        response += f"💬 {feedback.message}\n\n"
        
        await callback.message.edit_text(
            response,
            reply_markup=get_feedback_keyboard()
        )
        
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка при загрузке истории: {str(e)}")
    finally:
        db.close()
    await callback.answer()

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    """Return to main menu"""
    from handlers.common import get_main_keyboard
    
    await callback.message.edit_text(
        "🏠 <b>Главное меню</b>\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

def register_handlers(dp):
    """Register all feedback handlers"""
    dp.include_router(router)
