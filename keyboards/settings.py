from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from db.models import WeekType
from sqlalchemy import select


def get_settings_reply_kb() -> ReplyKeyboardMarkup:
    """Статичне реплай-меню налаштувань"""
    builder = ReplyKeyboardBuilder()
    builder.button(text="👥 Користувачі")
    builder.button(text="🎨 Колір тижня")  # Просто назва
    builder.button(text="🏠 Головне меню")
    builder.adjust(2, 1)
    return builder.as_markup(resize_keyboard=True)


def get_week_inline_kb(current_week_name: str) -> InlineKeyboardMarkup:
    """Інлайн-кнопки для вибору кольору тижня"""
    builder = InlineKeyboardBuilder()

    colors = [("green", "🟢 Зелений"), ("red", "🔴 Червоний")]

    for code, label in colors:
        # Додаємо позначку ✅ до активного кольору
        prefix = "✅ " if current_week_name == code else ""
        builder.button(text=f"{prefix}{label}", callback_data=f"set_week_{code}")

    builder.adjust(2)
    return builder.as_markup()