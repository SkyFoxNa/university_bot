import os
from aiogram import Router, F, types
from aiogram.types import FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from db.models import Subject, User
from keyboards.reply import get_study_kb, delete_prev_message
from keyboards.inline import get_subjects_kb

router = Router()


# --- МЕНЮ НАВЧАННЯ ---

@router.message(F.text == "📚 Навчання")
async def cmd_study(message: types.Message):
    """Головне меню розділу 'Навчання'"""
    await delete_prev_message(message)
    await message.answer(
        "📚 **Розділ навчання**\nОберіть потрібний пункт:",
        reply_markup=get_study_kb()
    )


# --- РОЗКЛАД ДЗВОНИКІВ ---

@router.message(F.text == "🔔 Дзвоники")
async def cmd_calls(message: types.Message):
    """Відправка зображення з розкладом пар"""
    await delete_prev_message(message)
    photo_path = "pic/call_schedule.jpg"

    if os.path.exists(photo_path):
        photo = FSInputFile(photo_path)
        await message.answer_photo(
            photo,
            caption="🕒 **Розклад дзвоників (пар)**"
        )
    else:
        await message.answer("❌ Файл з розкладом дзвоників не знайдено.")


# --- СПИСОК ПРЕДМЕТІВ ---

@router.message(F.text == "📖 Предмети")
async def cmd_subjects(message: types.Message, session: AsyncSession):
    """Виводить список усіх предметів як Inline-кнопки"""
    await delete_prev_message(message)

    # 1. Отримуємо користувача разом з його ролями
    stmt_user = (
        select(User)
        .where(User.user_id == message.from_user.id)
        .options(selectinload(User.roles))
    )
    result_user = await session.execute(stmt_user)
    user = result_user.scalar_one()

    # Витягуємо назви ролей у список
    user_roles = [r.role.name for r in user.roles]

    # 2. Отримуємо список предметів
    result_subjects = await session.execute(select(Subject))
    subjects = result_subjects.scalars().all()

    if not subjects:
        # Навіть якщо предметів немає, адмін має бачити кнопку "Додати"
        # Тому передаємо порожній список предметів, але список ролей обов'язково
        await message.answer(
            "Перелік предметів наразі порожній.",
            reply_markup=get_subjects_kb([], user_roles)
        )
        return

    # 3. ТЕПЕР ПЕРЕДАЄМО ОБИДВА АРГУМЕНТИ
    await message.answer(
        "Оберіть предмет для перегляду деталей:",
        reply_markup=get_subjects_kb(subjects, user_roles)
    )


# --- ДЕТАЛІ ПРЕДМЕТА ---

@router.callback_query(F.data.startswith("sub_"))
async def handle_subject_selection(callback: types.CallbackQuery, session: AsyncSession):
    """Обробка вибору конкретного предмета зі списку"""
    subject_id = int(callback.data.split("_")[1])
    subject = await session.get(Subject, subject_id)

    if not subject:
        await callback.answer("Помилка: предмет не знайдено.")
        return

    # Формуємо блок посилань Zoom
    zoom_link = f"[Приєднатися до конференції]({subject.zoom_link})" if subject.zoom_link else "Не вказано"

    # Додаємо нове поле zoom_id (Ідентифікатор) у вивід тексту
    text = (
        f"📘 **Предмет:** {subject.name}\n"
        f"👤 **Викладач:** {subject.teacher_name}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🌐 **Zoom:** {zoom_link}\n"
        f"🆔 **ID конференції:** `{subject.zoom_id or 'не вказано'}`\n"
        f"🔑 **Пароль:** `{subject.zoom_password or 'відсутній'}`"
    )

    # Створюємо кнопки дій для предмета
    builder = InlineKeyboardBuilder()
    # Кнопка для переходу до ДЗ саме цього предмета (логіка буде в homework.py)
    builder.button(text="📝 Домашнє завдання", callback_data=f"hw_subject_{subject_id}")
    # Кнопка назад до списку предметів
    builder.button(text="⬅️ Назад до списку", callback_data="back_to_subjects")
    builder.adjust(1)

    # Видаляємо попереднє повідомлення зі списком
    try:
        await callback.message.delete()
    except Exception:
        pass

    # Надсилаємо нове повідомлення з детальною інформацією
    await callback.message.answer(
        text,
        parse_mode="Markdown",
        disable_web_page_preview=True,
        reply_markup=builder.as_markup()
    )
    await callback.answer()


# --- НАВІГАЦІЯ НАЗАД ---

@router.callback_query(F.data == "back_to_subjects")
async def back_to_subjects(callback: types.CallbackQuery, session: AsyncSession):
    """Повернення до повного списку предметів"""
    await callback.message.delete()

    # Отримуємо ролі
    stmt_user = select(User).where(User.user_id == callback.from_user.id).options(selectinload(User.roles))
    user = (await session.execute(stmt_user)).scalar_one()
    user_roles = [r.role.name for r in user.roles]

    # Отримуємо предмети
    result = await session.execute(select(Subject))
    subjects = result.scalars().all()

    await callback.message.answer(
        "Оберіть предмет для перегляду деталей:",
        reply_markup=get_subjects_kb(subjects, user_roles)  # Додано user_roles
    )
    await callback.answer()
