from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup
from aiogram.filters.callback_data import CallbackData
from aiogram import types


# Універсальна структура даних для кнопок ДЗ
class HWAction(CallbackData, prefix="h_w"):
    action: str  # 'menu', 'select_subject', 'add_homework', 'last', 'all'
    subject_id: int  # ID предмета з бази даних
    page: int = 0  # Додаємо номер сторінки за замовчуванням
    hw_id: int = 0 # Додаємо ID конкретного завдання для редагування/видалення


def get_homework_menu_kb(subject_id: int, subject_name: str, user_roles: list) -> InlineKeyboardMarkup:
    """Головне меню ДЗ з трьома рядами кнопок"""
    builder = InlineKeyboardBuilder()

    # Перевірка прав на додавання (адміни, ректори, старости, ДЗ-менеджери)
    is_editor = any(role in user_roles for role in ["admin", "rector", "headman", "homework"])

    # Ряд 1: Кнопка-заголовок (відображає обраний предмет)
    display_name = f"📌 {subject_name}" if subject_id > 0 else "❌ Предмет не обрано"
    builder.button(text=display_name, callback_data="ignore")

    # Ряд 2: Керування вибором та додаванням
    builder.button(
        text="🔍 Обрати предмет",
        callback_data=HWAction(action="select_subject", subject_id=subject_id).pack()
    )

    # Кнопка додавання з'являється тільки якщо предмет обрано і є права
    if subject_id > 0 and is_editor:
        builder.button(
            text="➕ Додати ДЗ",
            callback_data=HWAction(action="add_homework", subject_id=subject_id).pack()
        )

    # Ряд 3: Перегляд завдань
    if subject_id > 0:
        builder.button(
            text="📄 Останнє",
            callback_data=HWAction(action="last_homework", subject_id=subject_id).pack()
        )
        builder.button(
            text="📚 Усі завдання",
            callback_data=HWAction(action="all_homework", subject_id=subject_id).pack()
        )

    # Налаштування сітки: 1 кнопка в першому ряду, по 2 в наступних
    builder.adjust(1, 2, 2)
    return builder.as_markup()


def get_back_to_hw_menu_kb(subject_id: int) -> InlineKeyboardMarkup:
    """Кнопка повернення до панелі керування предметом"""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⬅️ Назад до меню ДЗ",
        callback_data=HWAction(action="menu", subject_id=subject_id).pack()
    )
    return builder.as_markup()


# Усі завдання

def get_single_hw_edit_kb(subject_id: int, hw_id: int, user_roles: list) -> InlineKeyboardMarkup:
    """Кнопки під кожним окремим завданням"""
    builder = InlineKeyboardBuilder()
    is_editor = any(role in user_roles for role in ["admin", "rector", "headman", "homework"])

    if is_editor:
        builder.button(
            text="📝 Ред.",
            callback_data=HWAction(action="edit_hw", subject_id=subject_id, hw_id=hw_id).pack()
        )
        builder.button(
            text="🗑 Вид.",
            callback_data=HWAction(action="delete_hw", subject_id=subject_id, hw_id=hw_id).pack()
        )

    builder.adjust(2)
    return builder.as_markup()


def get_navigation_only_kb(subject_id: int, current_page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Окрема панель навігації, яка йде останнім повідомленням"""
    builder = InlineKeyboardBuilder()

    nav_buttons = []
    if current_page > 0:
        nav_buttons.append(types.InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=HWAction(action="all_homework", subject_id=subject_id, page=current_page - 1).pack()
        ))
    if current_page < total_pages - 1:
        nav_buttons.append(types.InlineKeyboardButton(
            text="Вперед ➡️",
            callback_data=HWAction(action="all_homework", subject_id=subject_id, page=current_page + 1).pack()
        ))

    if nav_buttons:
        builder.row(*nav_buttons)

    builder.row(types.InlineKeyboardButton(
        text="⬅️ До меню ДЗ",
        callback_data=HWAction(action="menu", subject_id=subject_id).pack()
    ))

    return builder.as_markup()


def get_edit_hw_choice_kb(subject_id: int, hw_id: int) -> InlineKeyboardMarkup:
    """Клавіатура вибору конкретного поля для редагування"""
    builder = InlineKeyboardBuilder()

    # Кнопки для кожного поля
    # Використовуємо action="edit_field" і передаємо через hw_id або додаткове поле,
    # але для простоти зробимо окремі callback_data
    fields = [
        ("📝 Завдання", "edit_desc"),
        ("🔗 Посилання", "edit_task"),
        ("📹 Відео", "edit_video"),
        ("📁 Додатково", "edit_extra"),
        ("💡 Примітка", "edit_note"),
    ]

    for text, field in fields:
        builder.button(text=text, callback_data=f"hw_field_{field}_{hw_id}")

    # Кнопка завершення
    builder.button(text="✅ Закінчити редагування", callback_data=HWAction(action="menu", subject_id=subject_id).pack())

    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()