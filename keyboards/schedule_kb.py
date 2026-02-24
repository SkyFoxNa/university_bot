from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.types import ReplyKeyboardMarkup


def get_schedule_reply_kb(user_roles: list) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()

    # Дні тижня
    builder.button(text="Понеділок")
    builder.button(text="Вівторок")
    builder.button(text="Середа")
    builder.button(text="Четвер")
    builder.button(text="П'ятниця")

    # Перевірка ролей для спеціальної кнопки
    privileged_roles = {"admin", "rector", "headman", "head"}
    if any(role in privileged_roles for role in user_roles):
        builder.button(text="Зміни у розкладу")

    # Головне меню
    builder.button(text="🏠 Головне меню")

    # Налаштовуємо сітку: 3 дні, 2 дні, потім спецкнопка та меню
    # Якщо кнопка "Зміни" є, то в останньому ряду буде 2 кнопки, якщо немає — 1.
    if any(role in privileged_roles for role in user_roles):
        builder.adjust(3, 2, 2)
    else:
        builder.adjust(3, 2, 1)

    return builder.as_markup(resize_keyboard=True)