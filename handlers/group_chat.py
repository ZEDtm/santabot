from datetime import timedelta
from utils.logging import get_logger
from typing import Optional, List, Dict, Any
from aiogram import F, Router, types, Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database.models import SessionLocal, Event
from database.crud import is_user_admin, get_event_by_id, update_event

# Configure logging
logger = get_logger(__name__)

router = Router()

class GroupChatStates(StatesGroup):
    waiting_for_link_code = State()

@router.message(Command(commands=["start", "help"]), F.chat.type.in_(["group", "supergroup"]))
async def handle_group_commands(message: Message, state: FSMContext = None):
    """Handle commands in group chats"""
    db = SessionLocal()
    try:
        # First check if this is a group that's already linked to an event
        event = db.query(Event).filter(Event.group_chat_id == message.chat.id).first()
        
        if event:
            # If group is already linked, show event info
            await message.reply(
                f"✅ Этот чат привязан к мероприятию: {event.title}\n"
                f"📅 Окончание регистрации: {event.registration_end.strftime('%d.%m.%Y %H:%M')}\n"
                f"📦 Крайний срок отправки: {event.shipping_deadline.strftime('%d.%m.%Y %H:%M')}"
            )
            return
            
        # If we get here, the group is not linked yet
        if not is_user_admin(db, message.from_user.id):
            # For non-admin users, just show a message
            await message.reply(
                "👋 Я бот для организации Тайного Санты. "
                "Обратитесь к администратору для настройки мероприятия."
            )
            return
            
        # For admin users, show the link button
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🔗 Привязать к мероприятию",
                callback_data="start_linking"
            )]
        ])
        await message.reply(
            "👋 Этот чат не привязан к мероприятию.\n"
            "Нажмите кнопку ниже, чтобы начать привязку:",
            reply_markup=keyboard
        )
            
    except Exception as e:
        logger.error(f"Error in group command handler: {e}")
        await message.reply("❌ Произошла ошибка. Пожалуйста, попробуйте позже.")
    finally:
        db.close()

@router.message(Command(commands=["link", "link_chat"]))
async def start_linking_chat(message: Message, state: FSMContext):
    """Start the process of linking a group chat to an event"""
    # Only respond to group chats and supergroups
    if message.chat.type not in ["group", "supergroup"]:
        return
        
    # Check if user is admin
    db = SessionLocal()
    try:
        if not is_user_admin(db, message.from_user.id):
            await message.reply("❌ Только администраторы могут привязывать чаты к мероприятиям.")
            return
    finally:
        db.close()
        
    # Check if chat is already linked
    db = SessionLocal()
    try:
        existing_event = db.query(Event).filter(Event.group_chat_id == message.chat.id).first()
        if existing_event:
            await message.reply(
                f"❌ Этот чат уже привязан к мероприятию: {existing_event.title}"
            )
            return
    finally:
        db.close()
    
    # Check if link code was provided with the command
    args = message.text.split()
    if len(args) > 1:
        # Process the link code directly
        link_code = args[1].strip().upper()
        if link_code.startswith('EVENT'):
            await process_link_code_with_state(
                message=message,
                link_code=link_code,
                chat_id=message.chat.id,
                admin_id=message.from_user.id
            )
            return
    
    # If no valid code provided, ask for it
    await message.reply(
        "🔑 Введите код привязки, который вы получили при создании мероприятия:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_linking")]
        ])
    )
    
    await state.set_state(GroupChatStates.waiting_for_link_code)
    await state.update_data(chat_id=message.chat.id, admin_id=message.from_user.id)

async def process_link_code_with_state(message: Message, link_code: str, chat_id: int, admin_id: int):
    """Process link code with the given state data"""
    # Verify the link code format
    if not link_code.startswith('EVENT'):
        await message.reply("❌ Неверный формат кода. Код должен начинаться с 'EVENT'.")
        return
    
    try:
        # Extract the numeric part after 'EVENT'
        number_part = link_code[5:]
        if not number_part:  # If nothing after 'EVENT'
            raise ValueError("No number after EVENT")
            
        # The link code is now in format: EVENT + event_id
        # For example: EVENT1, EVENT42, etc.
        event_id = int(number_part)  # Convert the remaining part to integer
        
        if event_id < 0:
            raise ValueError("Negative event ID")
            
        db = SessionLocal()
        try:
            # Find the event
            event = get_event_by_id(db, event_id)
            if not event:
                await message.reply("❌ Мероприятие не найдено. Проверьте код и попробуйте снова.")
                return
                
            # Link the chat to the event
            event.group_chat_id = chat_id
            db.commit()
            
            # Notify the group with event details
            event_message = (
                f"🎉 <b>Этот чат привязан к мероприятию: {event.title}</b>\n\n"
                f"📅 <b>Регистрация открыта до:</b> {event.registration_end.strftime('%d.%m.%Y %H:%M')}\n"
                f"📦 <b>Отправка подарков до:</b> {event.shipping_deadline.strftime('%d.%m.%Y %H:%M')}\n"
                f"💰 <b>Бюджет подарка:</b> {event.budget if event.budget else 'не ограничен'} руб.\n\n"
                "🎁 <b>Как принять участие?</b>\n"
                "1. Напишите боту в личные сообщения @SantaSecretBot\n"
                "2. Нажмите /start и следуйте инструкциям\n"
                "3. Укажите свои пожелания и адрес доставки"
            )
            
            await message.reply(
                event_message,
                parse_mode="HTML"
            )
            
            # Notify the admin in private
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=f"✅ Групповой чат успешно привязан к мероприятию: {event.title}\n\n"
                         f"Теперь участники могут писать боту в личные сообщения, чтобы зарегистрироваться."
                )
            except Exception as e:
                logger.error(f"Error sending notification to admin: {e}")
                
            # Update the event status if needed
            if event.status != 'registration':
                event.status = 'registration'
                db.commit()
                
        finally:
            db.close()
            
    except (ValueError, IndexError) as e:
        await message.reply("❌ Неверный формат кода. Пожалуйста, проверьте и попробуйте снова.")
        logger.error(f"Invalid link code format: {e}")
    except Exception as e:
        logger.error(f"Error linking chat: {e}")
        await message.reply("❌ Произошла ошибка при привязке чата. Пожалуйста, попробуйте позже.")

@router.message(GroupChatStates.waiting_for_link_code)
async def process_link_code(message: Message, state: FSMContext):
    """Process the link code and connect the chat to the event"""
    link_code = message.text.strip().upper()
    data = await state.get_data()
    
    # Verify the link code format
    if not (link_code.startswith('EVENT')):
        await message.reply("❌ Неверный формат кода. Код должен начинаться с 'EVENT'.")
        return
    
    try:
        # Extract numeric part after 'EVENT'
        number_part = link_code[5:].lstrip('0')  # Remove leading zeros
        if not number_part:  # If only zeros after EVENT
            number_part = '0'
            
        # Convert to integer
        event_id = int(number_part)
        
        if event_id < 0:
            raise ValueError("Negative event ID")
        
        db = SessionLocal()
        try:
            # Find the event
            event = get_event_by_id(db, event_id)
            if not event:
                await message.reply("❌ Мероприятие не найдено. Проверьте код и попробуйте снова.")
                return
                
            # Link the chat to the event
            event.group_chat_id = data['chat_id']
            db.commit()
            
            # Notify the group
            await message.reply(
                f"✅ Чат успешно привязан к мероприятию: {event.title}\n\n"
                f"Теперь участники смогут получать уведомления о мероприятии в этом чате."
            )
            
            # Notify the admin in private
            try:
                await bot.send_message(
                    chat_id=data['admin_id'],
                    text=f"✅ Групповой чат успешно привязан к мероприятию: {event.title}"
                )
            except Exception as e:
                logger.error(f"Error sending notification to admin: {e}")
                
        finally:
            db.close()
            
    except (ValueError, IndexError):
        await message.reply("❌ Неверный формат кода. Пожалуйста, проверьте и попробуйте снова.")
    except Exception as e:
        logger.error(f"Error linking chat: {e}")
        await message.reply("❌ Произошла ошибка при привязке чата. Пожалуйста, попробуйте позже.")
    finally:
        await state.clear()

@router.callback_query(F.data == "start_linking")
async def start_linking_callback(callback: CallbackQuery, state: FSMContext):
    """Start the linking process from inline button"""
    await start_linking_chat(callback.message, state)
    await callback.answer()

@router.callback_query(F.data == "cancel_linking")
async def cancel_linking(callback: CallbackQuery, state: FSMContext):
    """Cancel the linking process"""
    await state.clear()
    await callback.message.edit_text("❌ Привязка чата отменена.")
    await callback.answer()

@router.message(Command(commands=["link_event"]))
async def link_event(message: Message):
    """Handle link_event command in private messages"""
    if message.chat.type != "private":
        return
        
    # This will be implemented in the admin.py handler
    pass

# Global bot instance
bot = None

def register_group_handlers(dispatcher, bot_instance):
    """Register group chat handlers"""
    global bot
    bot = bot_instance
    dispatcher.include_router(router)
