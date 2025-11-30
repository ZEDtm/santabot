from aiogram import F, Router, types
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from aiogram.filters import Command, StateFilter, Filter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types.input_file import BufferedInputFile
from datetime import datetime, timedelta
from typing import List, Optional, Union

from database.models import SessionLocal, Participant, Event
from database.crud import (
    create_event, get_events_by_admin, is_user_admin,
)
from services.pairing import generate_pairs, send_pairing_notifications
from utils.logging import get_logger

logger = get_logger(__name__)

router = Router()

class AdminStates(StatesGroup):
    waiting_for_event_title = State()
    waiting_for_registration_end = State()
    waiting_for_shipping_deadline = State()
    waiting_for_budget = State()
    waiting_for_group_chat = State()

class AnnouncementStates(StatesGroup):
    waiting_for_announcement = State()
    waiting_for_announcement_photo = State()

def get_admin_keyboard(event_id: int = None) -> InlineKeyboardMarkup:
    """Create admin keyboard for the single event per admin"""
    keyboard = []
    
    # Main admin keyboard when no specific event is selected
    if not event_id:
        keyboard.extend([
            [
                InlineKeyboardButton(text="📝 Создать мероприятие", callback_data="create_event"),
                #InlineKeyboardButton(text="📋 Моё мероприятие", callback_data="list_events")
            ],
        ])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    # Event-specific keyboard
    keyboard.extend([
        [
            InlineKeyboardButton(
                text="👥 Участники", 
                callback_data="event_participants"
            ),
            InlineKeyboardButton(
                text="🔗 Привязать чат", 
                callback_data=f"link_chat_{event_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="🎲 Запустить жеребьёвку", 
                callback_data=f"start_pairing_{event_id}"
            ),
            InlineKeyboardButton(
                text="📢 Сделать объявление", 
                callback_data=f"announce_{event_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="🔙 В главное меню", 
                callback_data="admin_back"
            )
        ]
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_event_keyboard(event_id: int) -> InlineKeyboardMarkup:
    """Create keyboard for event actions"""
    keyboard = [
        [
            InlineKeyboardButton(
                text="👥 Участники", 
                callback_data=f"event_participants_{event_id}"
            ),
            InlineKeyboardButton(
                text="🎲 Запустить жеребьёвку", 
                callback_data=f"start_pairing_{event_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="📢 Сделать объявление", 
                callback_data=f"announce_{event_id}"
            ),
            InlineKeyboardButton(
                text="❌ Закрыть", 
                callback_data="close"
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

@router.message(Command("admin"))
async def admin_panel(message: Union[Message, CallbackQuery]):
    """Show admin panel"""
    db = SessionLocal()

    admin_id = message.from_user.id

    events = get_events_by_admin(db, admin_id)
    if events:
        event_id = events[0].id
    else:
        event_id = None

    try:
        if not is_user_admin(db, message.from_user.id):
            if isinstance(message, Message):
                await message.answer("У вас нет прав администратора.")
            else:
                await message.answer("У вас нет прав администратора.", show_alert=True)
            return
    
    finally:
        db.close()
        
    text = "👨‍💻 Панель администратора"
    if event_id:
        db = SessionLocal()
        try:
            event = db.query(Event).filter(Event.id == event_id).first()
            if event:
                text = f"🎅 Управление мероприятием: {event.title}"
        finally:
            db.close()
    
    if isinstance(message, Message):
        await message.answer(text, reply_markup=get_admin_keyboard(event_id))
    else:
        await message.message.edit_text(text, reply_markup=get_admin_keyboard(event_id))

@router.callback_query(F.data == "admin_back")
async def back_to_admin_panel(callback: CallbackQuery, state: FSMContext):
    """Return to admin panel"""
    await state.clear()
    await admin_panel(callback)
    await callback.answer()

@router.callback_query(F.data == "create_event")
async def start_creating_event(callback: CallbackQuery, state: FSMContext):
    """Start event creation process"""
    db = SessionLocal()
    try:
        # Check if admin already has an active event
        admin_id = callback.from_user.id
        existing_events = get_events_by_admin(db, admin_id)
        
        if existing_events:
            event = existing_events[0]
            await callback.message.answer(
                "⚠️ У вас уже есть активное мероприятие. "
                "Вы можете иметь только одно активное мероприятие.\n\n"
                f"Текущее мероприятие: <b>{event.title}</b>\n"
                f"👥 Участников: {len(event.participants)}\n"
                f"📅 Регистрация до: {event.registration_end.strftime('%d.%m.%Y %H:%M')}",
                parse_mode='HTML',
                reply_markup=get_admin_keyboard()
            )
            return
            
        await state.clear()
        await callback.message.answer(
            "📝 Введите название мероприятия:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")
                ]]
            )
        )
        await state.set_state(AdminStates.waiting_for_event_title)
    finally:
        db.close()
    await callback.answer()

@router.message(AdminStates.waiting_for_event_title)
async def process_event_title(message: Message, state: FSMContext):
    """Process event title and ask for registration end date"""
    await state.update_data(event_title=message.text)
    
    await message.answer(
        "📅 Введите дату окончания регистрации (ДД.ММ.ГГГГ):"
    )
    await state.set_state(AdminStates.waiting_for_registration_end)

@router.message(AdminStates.waiting_for_registration_end)
async def process_registration_end(message: Message, state: FSMContext):
    """Process registration end date and ask for shipping deadline"""
    try:
        end_date = datetime.strptime(message.text, "%d.%m.%Y")
        if end_date < datetime.now():
            await message.answer("❌ Дата окончания регистрации не может быть в прошлом.")
            return
            
        await state.update_data(registration_end=end_date)
        
        await message.answer(
            "📦 Введите крайний срок отправки подарков (ДД.ММ.ГГГГ):"
        )
        await state.set_state(AdminStates.waiting_for_shipping_deadline)
    except ValueError:
        await message.answer("❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ")

@router.message(AdminStates.waiting_for_shipping_deadline)
async def process_shipping_deadline(message: Message, state: FSMContext):
    """Process shipping deadline and ask for budget"""
    try:
        data = await state.get_data()
        registration_end = data['registration_end']
        
        shipping_deadline = datetime.strptime(message.text, "%d.%m.%Y")
        if shipping_deadline <= registration_end:
            await message.answer("❌ Крайний срок отправки должен быть после даты окончания регистрации.")
            return
            
        await state.update_data(shipping_deadline=shipping_deadline)
        
        await message.answer(
            "💰 Введите бюджет подарка (в рублях) или 0, если бюджет не ограничен:"
        )
        await state.set_state(AdminStates.waiting_for_budget)
    except ValueError:
        await message.answer("❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ")

@router.message(AdminStates.waiting_for_budget)
async def process_budget_and_create_event(message: Message, state: FSMContext):
    """Process budget and create the event"""
    try:
        budget = int(message.text)
        if budget < 0:
            raise ValueError("Budget must be positive")
            
        data = await state.get_data()
        
        # Create the event
        db = SessionLocal()
        try:
# Get chat title if available
            chat_title = message.chat.title if hasattr(message.chat, 'title') else None
            
            # Create the event with all required parameters
            event = create_event(
                db=db,
                title=data['event_title'],
                registration_end=data['registration_end'],
                shipping_deadline=data['shipping_deadline'],
                admin_id=message.from_user.id,  # Store the admin's user ID
                group_id=message.chat.id,  # Store the chat ID where the event was created
                group_name=chat_title,  # Store the chat title if available
                budget=budget if budget > 0 else None  # Store NULL if budget is 0 or negative
            )
            
            # Generate a simple code for group chat linking (just EVENT + event ID)
            link_code = f"EVENT{event.id}"
            
            # Format the event details message
            event_details = (
                f"🎉 <b>Новое мероприятие создано!</b>\n\n"
                f"📌 <b>{event.title}</b>\n"
                f"📅 Регистрация до: {event.registration_end.strftime('%d.%m.%Y %H:%M')}\n"
                f"📦 Отправка подарков до: {event.shipping_deadline.strftime('%d.%m.%Y %H:%M')}\n"
                f"💰 Бюджет: {budget if budget else 'не ограничен'} руб.\n\n"
                f"🔗 Используйте команду /start в личных сообщениях с ботом, чтобы принять участие!"
            )
            
            # Send confirmation to admin
            await message.answer(
                f"✅ Мероприятие \"{event.title}\" успешно создано!\n\n"
                f"📅 Окончание регистрации: {event.registration_end.strftime('%d.%m.%Y %H:%M')}\n"
                f"📦 Крайний срок отправки подарков: {event.shipping_deadline.strftime('%d.%m.%Y %H:%M')}\n"
                f"💰 Бюджет: {budget} руб.\n\n"
                f"🔗 Код для привязки группового чата: `{link_code}`\n"
                "Отправьте этот код в групповом чате, чтобы привязать его к мероприятию.",
                reply_markup=get_admin_keyboard(event.id),
                parse_mode="Markdown"
            )
            
            # Store the link code in the state for verification
            await state.update_data(link_code=link_code, event_id=event.id)
            
        finally:
            db.close()
            
    except ValueError as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
    finally:
        await state.clear()

@router.callback_query(F.data == "event_participants")
async def show_event_participants(callback: CallbackQuery):
    """Show participants of the admin's event"""
    db = SessionLocal()
    try:
        admin_id = callback.from_user.id
        events = get_events_by_admin(db, admin_id)
        
        if not events:
            await callback.message.answer(
                "❌ У вас пока нет активного мероприятия."
            )
            return
            
        event = events[0]  # Get the admin's only event
        participants = event.participants
        
        if not participants:
            await callback.message.answer(
                "❌ В вашем мероприятии пока нет участников.\n\n"
                f"Пригласите участников, отправив им код: <code>EVENT{event.id}</code>"
            )
            return
            
        response = (
            f"👥 <b>Участники мероприятия \"{event.title}\":</b>\n\n"
            f"Всего участников: {len(participants)}\n\n"
        )
        
        for i, participant in enumerate(participants, 1):
            username = f" (@{participant.username})" if participant.username else ""
            wish_info = "🎁" if participant.wishes else ""
            address_info = "🏠" if participant.address else ""
            
            response += (
                f"{i}. {participant.first_name}{username} {wish_info}{address_info}\n"
            )
            
            # Add wish list and address if available
            if participant.wishes:
                wishes_preview = participant.wishes[:50] + ("..." if len(participant.wishes) > 50 else "")
                response += f"   📝 Пожелания: {wishes_preview}\n"
            
                
        response += "\n🔍 <i>Легенда: 🎁 - есть пожелания, 🏠 - указан адрес</i>"
            
        await callback.message.answer(
            response,
            reply_markup=get_admin_keyboard(event.id),
            parse_mode='HTML'
        )
        
    except Exception as e:
        logger.error(f"Error showing participants: {e}")
        await callback.message.answer(
            "❌ Произошла ошибка при загрузке списка участников. Пожалуйста, попробуйте позже."
        )
    finally:
        db.close()
    
    await callback.answer()

@router.callback_query(F.data == "list_events")
async def list_events(callback: CallbackQuery):
    """Show the admin's single event or create a new one"""
    db = SessionLocal()
    try:
        admin_id = callback.from_user.id
        events = get_events_by_admin(db, admin_id)
        
        if not events:
            await callback.message.answer(
                "🎅 У вас пока нет активного мероприятия.\n\n"
                "Нажмите кнопку \"Создать мероприятие\", чтобы начать."
            )
            return
        
        response = "📋 <b>Ваше мероприятие:</b>\n\n"
        
        for event in events:
            # Count participants
            participant_count = len(event.participants)
            status = "🟢" if event.status == "registration" else "🟡" if event.status == "in_progress" else "🔴"
            group_info = f"\n💬 Группа: {event.group_name}" if event.group_name else ""
            
            response += (
                f"{status} <b>{event.title}</b>{group_info}\n"
                f"👥 Участников: {participant_count}\n"
                f"📅 Регистрация до: {event.registration_end.strftime('%d.%m.%Y %H:%M')}\n"
                f"📦 Отправка до: {event.shipping_deadline.strftime('%d.%m.%Y %H:%M')}\n"
                f"💰 Бюджет: {event.budget if event.budget is not None else 'не ограничен'} руб.\n"
                f"🆔 ID: <code>{event.id}</code>\n"
                f"📅 Создано: {event.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
            )
        
        # Add pagination if needed (can be implemented later)
        
        await callback.message.answer(
            response,
            reply_markup=get_admin_keyboard(),
            parse_mode='HTML'
        )
        
    except Exception as e:
        logger.error(f"Error listing events: {e}")
        await callback.message.answer(
            "❌ Произошла ошибка при загрузке мероприятий. Пожалуйста, попробуйте позже."
        )
    finally:
        db.close()
    
    await callback.answer()

@router.callback_query(F.data.startswith("start_pairing_"))
async def start_pairing(callback: CallbackQuery):
    """Start the pairing process for an event"""
    try:
        event_id = int(callback.data.split("_")[2])
        db = SessionLocal()
        
        event = db.query(Event).get(event_id)
        if not event:
            await callback.message.answer("❌ Мероприятие не найдено.")
            return
            
        # Check if registration is still open
        if event.registration_end > datetime.now():
            await callback.message.answer(
                "❌ Регистрация ещё не закончилась. "
                f"Окончание регистрации: {event.registration_end.strftime('%d.%m.%Y')}"
            )
            return
            
        # Check if there are enough participants
        if len(event.participants) < 3:
            await callback.message.answer(
                "❌ Для жеребьёвки нужно минимум 3 участника. "
                f"Сейчас зарегистрировано: {len(event.participants)}"
            )
            return
            
        # Generate pairs
        success, message = generate_pairs(event_id)
        
        if success:
            # Send notifications to all participants         
            await send_pairing_notifications(callback.bot, event_id)
            
            # Update event status
            event.status = 'in_progress'
            db.commit()
            
            await callback.message.answer(
                f"✅ {message}\n\n"
                f"Участники уведомлены о своих парах."
            )
        else:
            await callback.message.answer(f"❌ {message}")
            
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка при проведении жеребьёвки: {str(e)}")
    finally:
        db.close()
    await callback.answer()

@router.callback_query(F.data == "close")
async def link_chat(callback: CallbackQuery):
    """Handle chat linking"""
    try:
        event_id = int(callback.data.split('_')[-1])
        db = SessionLocal()
        
        event = db.query(Event).get(event_id)
        if not event:
            await callback.answer("❌ Мероприятие не найдено")
            return
            
        # Generate a simple code for group chat linking
        link_code = f"EVENT{event.id}"
        
        await callback.message.answer(
            f"🔗 <b>Код для привязки чата:</b>\n\n"
            f"<code>/link {link_code}</code>\n\n"
            f"Отправьте этот код в групповом чате, чтобы привязать его к мероприятию.",
            parse_mode="HTML"
        )
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Error in link_chat: {e}")
        await callback.answer("❌ Произошла ошибка")
    finally:
        if 'db' in locals():
            db.close()

async def close_menu(callback: CallbackQuery):
    """Close the current menu"""
    try:
        await callback.message.delete()
    except:
        pass
    await callback.answer()

@router.callback_query(F.data.startswith("announce_"))
async def make_announcement(callback: CallbackQuery, state: FSMContext):
    """Handle announcement button click and ask for announcement text"""
    await callback.answer()
    
    # Get event_id from callback data (format: "announce_<event_id>")
    event_id = int(callback.data.split('_')[1])
    
    # Save event_id in state
    await state.update_data(event_id=event_id, has_photo=False)
    
    # Ask for announcement text
    await callback.message.answer(
        "✍️ Введите текст объявления, которое будет отправлено всем участникам:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin_back")]
        ])
    )
    
    # Set state to wait for announcement text
    await state.set_state(AnnouncementStates.waiting_for_announcement)


@router.callback_query(AnnouncementStates.waiting_for_announcement, F.data == "add_photo")
async def add_photo_to_announcement(callback: CallbackQuery, state: FSMContext):
    """Handle add photo button click"""
    await callback.answer()
    
    # Update state to indicate we're expecting a photo
    await state.update_data(has_photo=True)
    
    # Ask for photo
    await callback.message.answer(
        "📸 Отправьте фото для объявления:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_announcement")]
        ])
    )
    
    # Set state to wait for photo
    await state.set_state(AnnouncementStates.waiting_for_announcement_photo)


@router.callback_query(AnnouncementStates.waiting_for_announcement, F.data == "cancel_announcement")
async def cancel_announcement(callback: CallbackQuery, state: FSMContext):
    """Handle announcement cancellation"""
    data = await state.get_data()
    event_id = data.get('event_id')
    await state.clear()
    
    await callback.answer("❌ Создание объявления отменено")
    await callback.message.answer(
        "Вы вернулись к управлению мероприятием.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 К управлению", callback_data="admin_back")]
        ])
    )

@router.message(AnnouncementStates.waiting_for_announcement)
async def process_announcement_text(message: Message, state: FSMContext):
    """Process announcement text and ask for photo or send announcement"""
    # Save text to state
    await state.update_data(announcement_text=message.text)
    
    data = await state.get_data()
    has_photo = data.get('has_photo')
    
    if has_photo:
        await message.answer(
            "📸 Фото ожидается. Отправьте его для объявления.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_announcement")]
            ])
        )
    else:
        await message.answer(
            "📝 Текст объявления сохранён. Хотите добавить фото?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📷 Отправить с фото", callback_data="add_photo")],
                [InlineKeyboardButton(text="📤 Отправить без фото", callback_data="send_without_photo")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_announcement")]
            ])
        )


@router.callback_query(AnnouncementStates.waiting_for_announcement, F.data == "send_without_photo")
async def send_announcement_without_photo(callback: CallbackQuery, state: FSMContext):
    """Send announcement without photo"""
    await callback.answer()
    data = await state.get_data()
    await state.update_data(photo_id=None)
    await send_announcement(callback.message, state, data)


@router.message(AnnouncementStates.waiting_for_announcement_photo, F.photo)
async def process_announcement_photo(message: Message, state: FSMContext):
    """Process announcement photo and send announcement"""
    # Get the highest quality photo
    photo = message.photo[-1]
    await state.update_data(photo_id=photo.file_id)
    
    data = await state.get_data()
    await send_announcement(message, state, data)


@router.message(AnnouncementStates.waiting_for_announcement_photo)
async def invalid_photo_message(message: Message):
    """Handle invalid photo message"""
    await message.answer("Пожалуйста, отправьте фото для объявления или отмените операцию.")


async def send_announcement(message: Message, state: FSMContext, data: dict):
    """Send announcement to all participants"""
    event_id = data.get('event_id')
    announcement_text = data.get('announcement_text')
    photo_id = data.get('photo_id')
    
    # Clear the state
    await state.clear()
    
    # Get event and participants from database
    db = SessionLocal()
    try:
        event = db.query(Event).filter(Event.id == event_id).first()
        if not event:
            await message.answer("❌ Ошибка: мероприятие не найдено.")
            return
        
        # Format the announcement message
        message_text = (
            f"📢 *Объявление от организатора мероприятия \"{event.title}\"*\n\n"
            f"{announcement_text if announcement_text else ''}"
        )
        try:
            if photo_id:
                # Send message with photo
                await message.bot.send_photo(
                    chat_id=event.group_chat_id,
                    photo=photo_id,
                    caption=message_text,
                    parse_mode='Markdown'
                )
            else:
                # Send text-only message
                await message.bot.send_message(
                    chat_id=event.group_chat_id,
                    text=message_text,
                    parse_mode='Markdown'
                )
                
        except Exception as e:
            logger.error(f"Failed to send announcement to group {event.group_chat_id}: {str(e)}")
        
        # Send confirmation to admin
        photo_status = "с фото" if photo_id else "без фото"
        result_message = (
            f"✅ Объявление {photo_status} отправлено."
        )
        
        await message.answer(
            result_message,
            reply_markup=get_admin_keyboard(event.id)
        )
        
    except Exception as e:
        logger.error(f"Error in send_announcement: {str(e)}", exc_info=True)
        await message.answer("❌ Произошла ошибка при отправке объявления.")
        
    finally:
        db.close()

def register_handlers(dp):
    """Register all admin handlers"""
    # Register command handlers
    dp.include_router(router)
    
    # Explicitly register callback handlers
    dp.callback_query.register(admin_panel, F.data == "admin")
    dp.callback_query.register(back_to_admin_panel, F.data == "admin_back")
    dp.callback_query.register(start_creating_event, F.data == "create_event")
    dp.callback_query.register(list_events, F.data == "list_events")
    dp.callback_query.register(close_menu, F.data == "close")
    
    # Register dynamic callbacks
    dp.callback_query.register(show_event_participants, F.data.startswith("event_participants_"))
    dp.callback_query.register(start_pairing, F.data.startswith("start_pairing_"))
    dp.callback_query.register(link_chat, F.data.startswith("link_chat_"))
    dp.callback_query.register(make_announcement, F.data.startswith("announce_"))
