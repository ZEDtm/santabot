from aiogram import F, Router
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database.models import SessionLocal
from database.crud import get_participant_by_telegram, is_user_admin
from utils.logging import get_logger

logger = get_logger(__name__)
router = Router()

def get_main_keyboard() -> InlineKeyboardMarkup:
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

@router.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: Message):
    """Handle /start command"""
    db = SessionLocal()
    try:
        # Check if user is admin
        if is_user_admin(db, message.from_user.id):
            await message.answer(
                "👋 Привет, администратор! Используй /admin для управления мероприятиями.",
                reply_markup=get_main_keyboard()
            )
        else:
            await message.answer(
                "🎅 Добро пожаловать в Тайного Санту! "
                "Используй /register для регистрации в игре.",
                reply_markup=get_main_keyboard(),
                parse_mode='HTML'
            )
    finally:
        db.close()

@router.message(Command("help"), F.chat.type == "private")
async def cmd_help(message: Message):
    """Show help message"""
    help_text = (
        "🎄 <b>Тайный Санта - Помощь</b> 🎄\n\n"
        "<b>Основные команды:</b>\n"
        "/start - Начать работу с ботом\n"
        "/help - Показать это сообщение\n"
        "/register - Зарегистрироваться в игре\n"
        "\n<b>Для администраторов:</b>\n"
        "/admin - Панель управления"
    )
    await message.answer(help_text, parse_mode='HTML')


def register_handlers(dp):
    """Register all common handlers"""
    dp.include_router(router)
