from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram import types

from utils.states import UserManage

def get_users_list_kb(users, page: int, total_pages: int):
    builder = InlineKeyboardBuilder()
    # from handlers.admin_users import UserManage  # Локальний імпорт для уникнення циклу

    for u in users:
        display_name = f"{u.user_name} {u.user_surname or ''} (@{u.username or '?'})"
        builder.button(
            text=display_name,
            callback_data=UserManage(action="details", user_id=u.user_id).pack()
        )

    builder.adjust(1)

    nav_row = []
    if page > 0:
        nav_row.append(types.InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=UserManage(action="list", page=page - 1).pack())
        )
    if page < total_pages - 1:
        nav_row.append(types.InlineKeyboardButton(
            text="Вперед ➡️",
            callback_data=UserManage(action="list", page=page + 1).pack())
        )

    if nav_row:
        builder.row(*nav_row)

    return builder.as_markup()


def get_user_edit_kb(target_user_id: int, current_roles: list, manager_roles: list):
    builder = InlineKeyboardBuilder()
    # from handlers.admin_users import UserManage

    # Список ролей
    roles_to_show = ["student", "rector", "headman", "head", "homework"]
    if "admin" in manager_roles:
        roles_to_show.append("admin")

    for r in roles_to_show:
        prefix = "✅ " if r in current_roles else "❌ "
        builder.button(
            text=f"{prefix}{r}",
            callback_data=UserManage(action="edit_role", user_id=target_user_id, role_name=r).pack()
        )

    builder.adjust(2)
    builder.row(types.InlineKeyboardButton(
        text="🔢 Змінити № журналу",
        callback_data=UserManage(action="edit_num", user_id=target_user_id).pack())
    )
    builder.row(types.InlineKeyboardButton(
        text="⬅️ До списку",
        callback_data=UserManage(action="list", page=0).pack())
    )

    return builder.as_markup()

# Виводимо перелік прадметів
def get_subjects_kb(subjects, user_roles: list):
    builder = InlineKeyboardBuilder()

    for s in subjects:
        builder.button(text=s.name, callback_data=f"sub_{s.id}")

    builder.adjust(1)  # Список предметів по одному в ряд

    # Додаємо кнопку "Додати" тільки для обраних ролей
    if any(role in user_roles for role in ["admin", "headman", "head"]):
        builder.row(types.InlineKeyboardButton(
            text="➕ Додати новий предмет",
            callback_data="add_new_subject")
        )

    return builder.as_markup()

# def get_subjects_kb(subjects: list[Subject]) -> InlineKeyboardMarkup:
#     builder = InlineKeyboardBuilder()
#
#     for subject in subjects:
#         # callback_data допоможе нам зрозуміти, який саме предмет обрано
#         builder.button(
#             text=f"📖 {subject.name}",
#             callback_data=f"sub_{subject.id}"
#         )
#
#     builder.adjust(1)  # Кожен предмет з нового рядка
#     return builder.as_markup()
