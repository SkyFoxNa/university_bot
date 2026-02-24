from aiogram import types
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from db.models import User


# Допоміжна функція для чищення чату
async def delete_prev_message(message: types.Message):
    try:
        # Видаляємо повідомлення користувача (команду/текст кнопки)
        await message.delete()
    except Exception:
        pass # Якщо прав немає або вже видалено


# Спільна кнопка для всіх меню
HOME_BUTTON = "🏠 Головне меню"

def get_main_kb(user: User) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()

    # Отримуємо список назв ролей користувача для зручності
    user_roles = [r.role.name for r in user.roles]
    is_admin = "admin" in user_roles

    # 1. Головне меню - доступ у всіх
    # builder.button(text="🏠 Головне меню")
    builder.row(KeyboardButton(text=HOME_BUTTON))  # Головна кнопка завжди зверху

    # 2. Навчання - доступ student, rector, head + admin
    if any(role in user_roles for role in ["student", "rector", "head"]) or is_admin:
        builder.button(text="📚 Навчання")

    # 3. Особистий кабінет - доступ у всіх
    builder.button(text="👤 Особистий кабінет")

    # 4. Налаштування - доступ admin, headman
    if "headman" in user_roles or is_admin:
        builder.button(text="⚙️ Налаштування")

    # 5. Про бота (О биті) - доступ у всіх
    builder.button(text="ℹ️ Про бота")

    # Налаштовуємо вигляд: кнопки у 2 стовпці
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)


def get_study_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()

    # Кнопки розділу навчання
    builder.button(text="📖 Предмети")
    builder.button(text="📅 Розклад занять")
    builder.button(text="🔔 Дзвоники")
    builder.button(text="📝 Домашнє завдання")
    builder.button(text="🏠")  # Скорочена кнопка повернення

    builder.adjust(2, 2, 1)
    return builder.as_markup(resize_keyboard=True)