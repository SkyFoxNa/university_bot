import os
import re

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from db.models import User, Subject, UserRole
from keyboards.reply import delete_prev_message
from utils.states import TeachingManage, ProfileEdit

router = Router()


@router.message(F.text == "👤 Особистий кабінет")
async def cmd_profile(event: types.Message | types.CallbackQuery, session: AsyncSession):
    await delete_prev_message(event)

    # Визначаємо, хто натиснув кнопку (з повідомлення або з колбеку)
    user_tg_id = event.from_user.id

    # Видаляємо попереднє повідомлення лише якщо це Message (текстова команда)
    if isinstance(event, types.Message):
        await delete_prev_message(event)

    # 1. Отримуємо дані користувача з ролями
    stmt = (
        select(User)
        .where(User.user_id == user_tg_id)
        .options(selectinload(User.roles).selectinload(UserRole.role))
    )
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        # Це про всяк випадок, якщо немає в БД
        return

    # Створюємо списки для логіки відображення
    user_roles_names = [r.role.name for r in user.roles]
    # Використовуємо description для гарного відображення
    roles_display = ", ".join([r.role.description for r in user.roles]) or "Користувач"

    # 2. Формуємо базовий текст
    text = (
        f"👤 **Ваш профіль**\n\n"
        f"📝 ПІБ: {user.user_name} {user.user_surname or ''}\n"
        f"🔑 Статус: `{roles_display}`\n"
    )

    # 3. Додаємо номер у журналі (тільки для студентів та старост)
    if any(role in user_roles_names for role in ["student", "headman"]):
        text += f"🔢 № у журналі: {user.number or '---'}\n"

    # 4. Логіка для викладача (rector)
    if "rector" in user_roles_names:
        # Шукаємо предмети, де призначено цей user.id (внутрішній)
        subj_stmt = select(Subject).where(Subject.teacher_id == user.id)
        subjects = (await session.execute(subj_stmt)).scalars().all()

        text += "━━━━━━━━━━━━━━━\n"
        if subjects:
            subj_names = ", ".join([s.name for s in subjects])
            text += f"🎓 Ваші предмети: **{subj_names}**\n"
        else:
            text += "🎓 Предмет: **Не призначено**\n"
            # Тут пізніше додамо кнопку для вибору предмета ректором

    # 5. Контактні дані
    text += (
        f"━━━━━━━━━━━━━━━\n"
        f"📞 Телефон: {user.phone or 'не вказано'}\n"
        f"📨 Email: {user.email or 'не вказано'}\n"
        f"🔮 Viber: {user.viber or 'не вказано'}\n"
        f"💬 Telegram: {user.telegram_contact or 'не вказано'}\n\n"
        f"Оберіть дані для редагування:"
    )

    # 6. Клавіатура
    builder = InlineKeyboardBuilder()  # Створюємо БІЛДЕР, а не Markup

    # Додаємо кнопку редагування ПІБ першим рядком
    builder.row(
        types.InlineKeyboardButton(text="📝 Редагувати ПІБ", callback_data="edit_full_name")
    )

    # Додаємо кнопки через білдер
    builder.row(
        types.InlineKeyboardButton(text="📞 Телефон", callback_data="edit_phone"),
        types.InlineKeyboardButton(text="📧 Email", callback_data="edit_email")
    )
    builder.row(
        types.InlineKeyboardButton(text="🟣 Viber", callback_data="edit_viber"),
        types.InlineKeyboardButton(text="✈️ Контакт TG", callback_data="edit_telegram_contact")
    )

    # Спеціальні кнопки для Ректора
    if "rector" in user_roles_names:
        builder.row(types.InlineKeyboardButton(text="📚 Обрати предмет", callback_data="choose_teaching_subject"))
        if subjects:
            builder.row(
                types.InlineKeyboardButton(text="🗑 Зняти предмет з себе", callback_data="detach_teaching_subject"))

    try:
        if isinstance(event, types.Message):
            await event.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
        else:
            # Якщо це CallbackQuery, ми редагуємо поточне вікно
            await event.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception:
        # Якщо повідомлення видалено або його неможливо редагувати — надсилаємо нове
        await event.message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")



# --- ВИБІР ПРЕДМЕТА ДЛЯ ВИКЛАДАННЯ ---

@router.callback_query(F.data == "choose_teaching_subject")
async def list_free_subjects(callback: types.CallbackQuery, session: AsyncSession):
    # Шукаємо предмети, де викладач ще не призначений
    stmt = select(Subject).where(Subject.teacher_id == None)
    result = await session.execute(stmt)
    free_subjects = result.scalars().all()

    if not free_subjects:
        return await callback.answer("Наразі немає вільних предметів для вибору.", show_alert=True)

    builder = InlineKeyboardBuilder()
    for subj in free_subjects:
        builder.button(
            text=subj.name,
            callback_data=TeachingManage(action="confirm", subject_id=subj.id).pack()
        )
    builder.adjust(1)
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_profile"))

    await callback.message.edit_text(
        "📚 **Оберіть предмет, який ви викладаєте:**\n\n"
        "Це дозволить вам керувати домашніми завданнями та посиланнями Zoom для цієї дисципліни.",
        reply_markup=builder.as_markup()
    )

@router.callback_query(TeachingManage.filter(F.action == "confirm"))
async def confirm_subject(callback: types.CallbackQuery, callback_data: TeachingManage, session: AsyncSession):
    # 1. Отримуємо дані користувача (внутрішній ID та ПІБ)
    stmt_user = select(User).where(User.user_id == callback.from_user.id)
    user = (await session.execute(stmt_user)).scalar_one()

    # Формуємо повне ім'я викладача
    full_name = f"{user.user_name} {user.user_surname or ''}".strip()

    # 2. Оновлюємо предмет: записуємо і ID, і текстове ім'я
    await session.execute(
        update(Subject)
        .where(Subject.id == callback_data.subject_id)
        .values(
            teacher_id=user.id,
            teacher_name=full_name  # Тепер розклад побачить викладача!
        )
    )
    await session.commit()

    await callback.answer(f"✅ Предмет '{full_name}' закріплено!", show_alert=True)
    await cmd_profile(callback, session) # Повертаємось у профіль

# --- ЗНЯТТЯ ПРЕДМЕТА ---

@router.callback_query(F.data == "detach_teaching_subject")
async def detach_list(callback: types.CallbackQuery, session: AsyncSession):
    # Отримуємо внутрішній ID користувача
    stmt_user = select(User).where(User.user_id == callback.from_user.id)
    user = (await session.execute(stmt_user)).scalar_one()

    # Шукаємо його предмети
    stmt = select(Subject).where(Subject.teacher_id == user.id)
    my_subjects = (await session.execute(stmt)).scalars().all()

    builder = InlineKeyboardBuilder()
    for subj in my_subjects:
        builder.button(
            text=f"❌ Видалити: {subj.name}",
            callback_data=TeachingManage(action="detach", subject_id=subj.id).pack()
        )
    builder.adjust(1)
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_profile"))

    await callback.message.edit_text(
        "🗑 **Оберіть предмет, який хочете зняти з себе:**",
        reply_markup=builder.as_markup()
    )

@router.callback_query(TeachingManage.filter(F.action == "detach"))
async def process_detach(callback: types.CallbackQuery, callback_data: TeachingManage, session: AsyncSession):
    # Очищаємо і зв'язок, і текстове ім'я
    await session.execute(
        update(Subject)
        .where(Subject.id == callback_data.subject_id)
        .values(
            teacher_id=None,
            teacher_name=None  # Очищаємо текстове поле
        )
    )
    await session.commit()

    await callback.answer("Предмет знято. Тепер він знову вільний.", show_alert=False)
    # Зверніть увагу: передаємо callback, щоб cmd_profile спрацював коректно
    await cmd_profile(callback, session)

# Повернення до профілю (для кнопок "Назад")
@router.callback_query(F.data == "back_to_profile")
async def back_to_profile(callback: types.CallbackQuery, session: AsyncSession):
    await callback.message.delete()
    await cmd_profile(callback.message, session)


# Хендлер натискання на кнопку редагування
@router.callback_query(F.data.startswith("edit_"))
async def start_editing(callback: types.CallbackQuery, state: FSMContext):
    # field = callback.data.split("_")[1]
    field = callback.data.replace("edit_", "")
    field_names = {
        "full_name": "Прізвище та Ім'я",  # Нове поле
        "phone": "📞 номер телефону",
        "email": "📨 Email адресу",
        "viber": "🔮 Viber контакт",
        "telegram_contact": "💬 Telegram нікнейм"
    }

    await state.update_data(editing_field=field)
    await state.set_state(ProfileEdit.waiting_for_input)

    # Створюємо кнопку скасування
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="❌ Скасувати редагування", callback_data="cancel_profile_edit")]
    ])

    prompt_text = f"Введіть новий **{field_names[field]}**:"
    if field == "full_name":
        prompt_text += "\n\n⚠️ Будь ласка, введеть через пробіл: *Прізвище Ім'я*"

    await callback.message.answer(
        f"{prompt_text}\n\n"
        "👉 Натисніть кнопку нижче для скасування:",
        reply_markup=kb,
        parse_mode="Markdown"
    )
    await callback.answer()


#  Універсальний обробник введення даних
EMAIL_REGEX = re.compile(r'[^@]+@[^@]+\.[^@]+')


@router.message(ProfileEdit.waiting_for_input)
async def process_profile_input(message: types.Message, state: FSMContext, session: AsyncSession):
    user_data = await state.get_data()
    field = user_data.get("editing_field")
    new_value = message.text.strip()

    # Створюємо кнопку скасування для всіх випадків помилок
    cancel_kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="❌ Скасувати редагування", callback_data="cancel_profile_edit")]
    ])

    # --- 1. ЛОГІКА ДЛЯ ПІБ (full_name) ---
    if field == "full_name":
        # Заборона видалення ПІБ через "-"
        if new_value == "-":
            return await message.answer(
                "⚠️ **ПІБ не можна видалити!**\n\n"
                "Будь ласка, введіть ваші справжні Прізвище та Ім'я через пробіл "
                "або натисніть кнопку скасування:",
                reply_markup=cancel_kb,
                parse_mode="Markdown"
            )

        parts = new_value.split(maxsplit=1)
        # Перевірка на кількість слів (має бути мінімум два)
        if len(parts) < 2:
            return await message.answer(
                "❌ **Помилка у форматі!**\n\n"
                "Введіть Прізвище та Ім'я через пробіл (наприклад: *Петренко Іван*):",
                reply_markup=cancel_kb,
                parse_mode="Markdown"
            )

        surname, name = parts[0], parts[1]

        # Оновлюємо ПІБ у базі
        await session.execute(
            update(User)
            .where(User.user_id == message.from_user.id)
            .values(user_name=name, user_surname=surname)
        )

    # --- 2. ВАЛІДАЦІЯ EMAIL ---
    elif field == "email" and new_value != "-":
        if not EMAIL_REGEX.match(new_value):
            return await message.answer(
                "❌ **Помилка у форматі Email!**\n"
                "Приклад: `student@univ.ua`\n\n"
                "Спробуйте ще раз або скасуйте дію:",
                reply_markup=cancel_kb,
                parse_mode="Markdown"
            )

        await session.execute(
            update(User).where(User.user_id == message.from_user.id).values(email=new_value)
        )

    # --- 3. ЛОГІКА ДЛЯ ВСІХ ІНШИХ ПОЛІВ (phone, viber, telegram_contact) ---
    else:
        # Тут видалення через "-" дозволено (телефон або пошту можна приховати)
        val_to_save = None if new_value == "-" else new_value

        await session.execute(
            update(User)
            .where(User.user_id == message.from_user.id)
            .values({field: val_to_save})
        )

    # --- ЗАВЕРШЕННЯ ---
    await session.commit()

    # Видаляємо повідомлення бота з проханням "Введіть дані"
    try:
        await delete_prev_message(message)
    except:
        pass

    await state.clear()
    await message.answer("✅ Дані успішно оновлено!")

    # Повертаємо користувача в профіль
    await cmd_profile(message, session)


# @router.message(ProfileEdit.waiting_for_input)
# async def process_profile_input(message: types.Message, state: FSMContext, session: AsyncSession):
#     user_data = await state.get_data()
#     field = user_data.get("editing_field")
#     new_value = message.text.strip()
#
#     # Валідація Email (тільки якщо редагуємо поле email і це не видалення)
#     if field == "email" and new_value != "-":
#         if not EMAIL_REGEX.match(new_value):
#             kb = types.InlineKeyboardMarkup(inline_keyboard=[
#                 [types.InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_profile_edit")]
#             ])
#             return await message.answer(
#                 "❌ **Помилка у форматі Email!**\n"
#                 "Приклад: `student@univ.edu.ua`\n"
#                 "Спробуйте ще раз або натисніть скасувати:",
#                 reply_markup=kb,
#                 parse_mode="Markdown"
#             )
#
#     # Обробка видалення через "-"
#     if new_value == "-":
#         new_value = None
#
#     # Оновлення в БД
#     await session.execute(
#         update(User)
#         .where(User.user_id == message.from_user.id)
#         .values({field: new_value})
#     )
#     await session.commit()
#
#     await delete_prev_message(message)
#
#     await state.clear()
#     await message.answer("✅ Дані успішно оновлено!")
#
#     # Повертаємо профіль
#     await cmd_profile(message, session)


# хендлер для кнопки скасування
@router.callback_query(F.data == "cancel_profile_edit")
async def cancel_profile_edit_callback(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    await state.clear()
    await callback.answer("Редагування скасовано")
    # Видаляємо повідомлення з проханням про введення, щоб не засмічувати чат
    await callback.message.delete()
    # Повертаємо користувача в профіль
    await cmd_profile(callback.message, session)

