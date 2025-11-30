from utils.logging import get_logger
from datetime import datetime
from typing import Optional

from aiogram import F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database.models import SessionLocal, Event, Participant
from database.crud import (
    get_participant_by_telegram, create_participant,
    get_events_by_group, get_event, get_event_by_id
)

# Configure logger
logger = get_logger(__name__)

router = Router()

class RegistrationStates(StatesGroup):
    waiting_for_wishes = State()
    waiting_for_address = State()
    waiting_for_delivery = State()
    
class EditProfileStates(StatesGroup):
    waiting_for_field = State()
    waiting_for_wishes = State()
    waiting_for_address = State()
    waiting_for_delivery = State()

def get_profile_keyboard() -> InlineKeyboardMarkup:
    """Create profile management keyboard"""
    keyboard = [
        [
            InlineKeyboardButton(text="✏️ Редактировать профиль", callback_data="edit_profile"),
            InlineKeyboardButton(text="👀 Мой получатель", callback_data="view_recipient")
        ],
        [
            InlineKeyboardButton(text="💌 Написать Санте", callback_data="message_santa"),
            InlineKeyboardButton(text="📬 Написать получателю", callback_data="message_recipient")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
def get_edit_profile_keyboard() -> InlineKeyboardMarkup:
    """Create keyboard for editing profile fields"""
    keyboard = [
        [InlineKeyboardButton(text="✏️ Изменить пожелания", callback_data="edit_wishes")],
        [InlineKeyboardButton(text="🏠 Изменить адрес доставки", callback_data="edit_address")],
        [InlineKeyboardButton(text="🚚 Изменить способ доставки", callback_data="edit_delivery")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_profile")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

@router.message(Command("register"))
async def start_registration(message: Message, state: FSMContext):
    """Start registration process"""
    db = SessionLocal()
    try:
        # For private messages, find all active events
        if message.chat.type == 'private':
            # Get all active events where registration is still open
            events = db.query(Event).filter(
                Event.registration_end > datetime.now(),
                Event.status == 'registration'
            ).all()
            
            if not events:
                await message.answer("❌ В данный момент нет активных мероприятий с открытой регистрацией.")
                return
                
            # If there's only one event, use it
            if len(events) == 1:
                event = events[0]
            else:
                # If multiple events, ask user to choose
                keyboard = []
                for event in events:
                    keyboard.append([
                        InlineKeyboardButton(
                            text=f"{event.title} (до {event.registration_end.strftime('%d.%m.%Y')})",
                            callback_data=f"select_event_{event.id}"
                        )
                    ])
                await message.answer(
                    "Выберите мероприятие для регистрации:",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
                )
                return
        else:
            # For group chats, get events for this group
            events = get_events_by_group(db, message.chat.id)
            if not events:
                await message.answer("❌ В этом чате нет активных мероприятий.")
                return
                
            # Use the most recent event
            event = events[-1]
        
        # Check if registration is still open
        if event.registration_end < datetime.now():
            await message.answer("❌ Регистрация на это мероприятие уже закрыта.")
            return
            
        # Check if user is already registered
        participant = get_participant_by_telegram(db, event.id, message.from_user.id)
        if participant:
            await message.answer(
                "✅ Вы уже зарегистрированы в этом мероприятии!",
                reply_markup=get_profile_keyboard()
            )
            return
            
        # Start registration process
        await state.set_state(RegistrationStates.waiting_for_wishes)
        await state.update_data(event_id=event.id)
        
        await message.answer(
            "🎅 <b>Регистрация в Тайном Санте</b>\n\n"
            f"Мероприятие: <b>{event.title}</b>\n"
            f"Бюджет: {event.budget if event.budget else 'не ограничен'} руб.\n\n"
            "📝 <b>Напишите, что бы вы хотели получить в подарок (пожелания):</b>"
        )
        
    finally:
        db.close()

@router.message(RegistrationStates.waiting_for_wishes)
async def process_wishes(message: Message, state: FSMContext):
    """Process user's wishes and ask for address"""
    await state.update_data(wishes=message.text)
    await state.set_state(RegistrationStates.waiting_for_address)
    
    await message.answer(
        "🏠 <b>Укажите адрес для доставки подарка:</b>\n\n"
        "(Город, улица, дом, квартира, индекс)"
    )

@router.message(RegistrationStates.waiting_for_address)
async def process_address(message: Message, state: FSMContext):
    """Process user's address and ask for preferred delivery methods"""
    await state.update_data(address=message.text)
    await state.set_state(RegistrationStates.waiting_for_delivery)
    
    await message.answer(
        "🚚 <b>Укажите предпочтительные способы доставки:</b>\n\n"
        "Например: Почта России, СДЭК, Ozon, Wildberries и т.д."
    )

@router.message(RegistrationStates.waiting_for_delivery)
async def process_delivery_and_register(message: Message, state: FSMContext):
    """Process delivery methods and complete registration"""
    data = await state.get_data()
    
    db = SessionLocal()
    try:
        # Create new participant
        participant = create_participant(
            db=db,
            event_id=data['event_id'],
            telegram_id=message.from_user.id,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            username=message.from_user.username,
            wishes=data.get('wishes', ''),
            address=data.get('address', ''),
            delivery_methods=message.text
        )
        
        await message.answer(
            "🎉 <b>Поздравляем! Вы успешно зарегистрированы в игре Тайный Санта!</b>\n\n"
            f"Мероприятие: <b>{participant.event.title}</b>\n"
            f"Дата жеребьёвки: {participant.event.registration_end.strftime('%d.%m.%Y')}\n\n"
            "После жеребьёвки вы узнаете, кому будете дарить подарок!",
            reply_markup=get_profile_keyboard(),
            parse_mode='HTML'
        )
        
    finally:
        db.close()
        await state.clear()

@router.callback_query(F.data == "edit_profile")
async def edit_profile(callback: CallbackQuery, state: FSMContext):
    """Show edit profile menu"""
    db = SessionLocal()
    try:
        participant = db.query(Participant).filter(
            Participant.telegram_id == callback.from_user.id,
        ).first()

        if not participant:
            await callback.message.edit_text(
                "❌ Профиль участника не найден.",
                parse_mode='HTML'
            )
            return

        event = db.query(Event).filter(
            Event.id == participant.event_id,
        ).first()

        if not event or event.status != 'registration':
            await callback.message.edit_text(
                "❌ Мероприятие не найдено или регистрация на нем закрыта. Связывайтесь с сантой через сообщения!",
                parse_mode='HTML'
            )
            return
        
        await callback.message.edit_text(
            "✏️ <b>Что вы хотите изменить в профиле?</b>\n\n"
            f"Пожелания: {participant.wishes}\n\n"
            f"Адрес: {participant.address}\n\n"
            f"Способы доставки: {participant.delivery_methods}",
            reply_markup=get_edit_profile_keyboard(),
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Error getting participant: {e}")
        await callback.message.edit_text(
            "❌ Произошла ошибка при получении профиля. Попробуйте снова.",
            parse_mode='HTML'
        )
    finally:
        db.close()
        await callback.answer()

@router.callback_query(F.data == "edit_wishes")
async def edit_wishes_handler(callback: CallbackQuery, state: FSMContext):
    """Start editing wishes"""
    await state.set_state(EditProfileStates.waiting_for_wishes)
    await callback.message.edit_text(
        "📝 <b>Напишите, что бы вы хотели получить в подарок (пожелания):</b>\n\n"
        "<i>Текущие пожелания будут перезаписаны.</i>",
        parse_mode='HTML'
    )
    await callback.answer()

@router.message(EditProfileStates.waiting_for_wishes)
async def process_edit_wishes(message: Message, state: FSMContext):
    """Process updated wishes"""
    db = SessionLocal()
    try:
        # Get user's active event
        participant = db.query(Participant).filter(
            Participant.telegram_id == message.from_user.id,
        ).first()
        
        if participant:
            participant.wishes = message.text
            db.commit()
            await message.answer("✅ <b>Пожелания успешно обновлены!</b>", parse_mode='HTML')
        else:
            await message.answer("❌ Профиль участника не найден.")
    except Exception as e:
        logger.error(f"Error updating wishes: {e}")
        await message.answer("❌ Произошла ошибка при обновлении пожеланий.")
    finally:
        db.close()
        await state.clear()

@router.callback_query(F.data == "edit_address")
async def edit_address_handler(callback: CallbackQuery, state: FSMContext):
    """Start editing delivery address"""
    await state.set_state(EditProfileStates.waiting_for_address)
    await callback.message.edit_text(
        "🏠 <b>Введите новый адрес доставки:</b>\n\n"
        "(Город, улица, дом, квартира, индекс)\n"
        "<i>Текущий адрес будет перезаписан.</i>",
        parse_mode='HTML'
    )
    await callback.answer()

@router.message(EditProfileStates.waiting_for_address)
async def process_edit_address(message: Message, state: FSMContext):
    """Process updated delivery address"""
    db = SessionLocal()
    try:
        # Get user's active event
        participant = db.query(Participant).filter(
            Participant.telegram_id == message.from_user.id,
        ).first()
        
        if participant:
            participant.address = message.text
            db.commit()
            await message.answer("✅ <b>Адрес доставки успешно обновлён!</b>", parse_mode='HTML')
        else:
            await message.answer("❌ Профиль участника не найден.")
    except Exception as e:
        logger.error(f"Error updating address: {e}")
        await message.answer("❌ Произошла ошибка при обновлении адреса доставки.")
    finally:
        db.close()
        await state.clear()

@router.callback_query(F.data == "edit_delivery")
async def edit_delivery_handler(callback: CallbackQuery, state: FSMContext):
    """Start editing delivery methods"""
    await state.set_state(EditProfileStates.waiting_for_delivery)
    await callback.message.edit_text(
        "🚚 <b>Укажите предпочтительные способы доставки:</b>\n\n"
        "Например: Почта России, СДЭК, Ozon, Wildberries и т.д.\n"
        "<i>Текущие способы доставки будут перезаписаны.</i>",
        parse_mode='HTML'
    )
    await callback.answer()

@router.message(EditProfileStates.waiting_for_delivery)
async def process_edit_delivery(message: Message, state: FSMContext):
    """Process updated delivery methods"""
    db = SessionLocal()
    try:
        # Get user's active event
        participant = db.query(Participant).filter(
            Participant.telegram_id == message.from_user.id,
        ).first()
        
        if participant:
            participant.delivery_methods = message.text
            db.commit()
            await message.answer("✅ <b>Способы доставки успешно обновлены!</b>", parse_mode='HTML')
        else:
            await message.answer("❌ Профиль участника не найден.")
    except Exception as e:
        logger.error(f"Error updating delivery methods: {e}")
        await message.answer("❌ Произошла ошибка при обновлении способов доставки.")
    finally:
        db.close()
        await state.clear()

@router.callback_query(F.data == "back_to_profile")
async def back_to_profile(callback: CallbackQuery, state: FSMContext):
    """Return to profile view"""
    await callback.message.edit_text(
        "👤 <b>Ваш профиль</b>\n\n"
        "Используйте кнопки ниже для управления профилем:",
        reply_markup=get_profile_keyboard(),
        parse_mode='HTML'
    )
    await callback.answer()

@router.callback_query(F.data == "view_recipient")
async def view_recipient(callback: CallbackQuery):
    """Show recipient information to the user"""
    db = SessionLocal()
    try:
        # This is a simplified example - in a real app, you'd need to implement
        # the logic to find the user's recipient based on the event and pairing
        await callback.message.answer(
            "👤 <b>Информация о вашем получателе появится после жеребьёвки.</b>",
            parse_mode='HTML'
        )
    finally:
        db.close()
    await callback.answer()

@router.callback_query(F.data.startswith("select_event_"))
async def select_event(callback: CallbackQuery, state: FSMContext):
    """Handle event selection from the list"""
    try:
        event_id = int(callback.data.split("_")[2])
        db = SessionLocal()
        try:
            event = get_event_by_id(db, event_id)
            if not event:
                await callback.message.answer("❌ Мероприятие не найдено.")
                return
                
            # Check if registration is still open
            if event.registration_end < datetime.now():
                await callback.message.answer("❌ Регистрация на это мероприятие уже закрыта.")
                return
                
            # Start registration for this event
            await state.update_data(event_id=event.id)
            await callback.message.answer(
                "✏️ Напишите ваши пожелания к подарку (что бы вы хотели получить):"
            )
            await state.set_state(RegistrationStates.waiting_for_wishes)
            
        finally:
            db.close()
    except (IndexError, ValueError) as e:
        await callback.message.answer("❌ Произошла ошибка. Пожалуйста, попробуйте снова.")
        logger.error(f"Error in select_event: {e}")
    await callback.answer()

def register_handlers(dp):
    """Register all user handlers"""
    dp.include_router(router)
