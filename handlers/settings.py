import os

from aiogram import Router, F, types, Bot
from aiogram.types import FSInputFile
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import WeekType, User, Role, UserRole
from keyboards.reply import delete_prev_message, get_main_kb
from keyboards.settings import get_settings_reply_kb, get_week_inline_kb

router = Router()


@router.message(F.text == "⚙️ Налаштування")
async def cmd_settings(message: types.Message):  # session можна прибрати, якщо не використовуєте далі
    await delete_prev_message(message)

    # ПРАВИЛЬНО: Викликаємо без await і без аргументів
    kb = get_settings_reply_kb()

    await message.answer(
        "⚙️ **Панель керування**\n\nОберіть категорію для налаштування:",
        reply_markup=kb,
        parse_mode="Markdown"
    )


# 1. Вхід у меню (через Reply кнопку)
@router.message(F.text == "🎨 Колір тижня")
async def cmd_week_settings(message: types.Message, session: AsyncSession):
    res = await session.execute(select(WeekType).where(WeekType.is_active == True))
    current = res.scalar_one_or_none()
    current_name = current.name if current else "не визначено"

    emoji = "🟢" if current_name == "green" else "🔴"
    display_name = "зелений" if current_name == "green" else "червоний"

    await message.answer(
        f"🎨 **Налаштування тижня**\n\nЗараз активний: {emoji} **{display_name}**\n"
        "Оберіть колір для зміни та розсилки студентам:",
        reply_markup=get_week_inline_kb(current_name)
    )


# 2. Обробка натискання Inline-кнопки
@router.callback_query(F.data.startswith("set_week_"))
async def callback_set_week(callback: types.CallbackQuery, session: AsyncSession, bot: Bot):
    new_color = callback.data.split("_")[2]  # 'green' або 'red'

    # Перевіряємо поточний колір
    res = await session.execute(select(WeekType).where(WeekType.is_active == True))
    current = res.scalar_one_or_none()

    if current and current.name == new_color:
        return await callback.answer(f"Тиждень вже {new_color}!", show_alert=True)

    # Змінюємо в БД
    await session.execute(update(WeekType).values(is_active=False))
    await session.execute(update(WeekType).where(WeekType.name == new_color).values(is_active=True))
    await session.commit()

    # Оновлюємо інлайн-кнопки в поточному повідомленні
    try:
        await callback.message.edit_reply_markup(reply_markup=get_week_inline_kb(new_color))
    except TelegramBadRequest:
        pass

    await callback.answer(f"Колір змінено на {new_color.upper()}!")

    # 3. РОЗСИЛКА КОРИСТУВАЧАМ
    await broadcast_week_change(bot, session, new_color)


async def broadcast_week_change(bot: Bot, session: AsyncSession, color: str):
    """Функція масової розсилки фото відповідним ролям"""
    # Знаходимо всіх користувачів, які мають одну з ролей
    target_roles = ["student", "rector", "headman", "head"]

    # Складний запит: знайти юзерів, у яких є хоча б одна з цих ролей
    stmt = (
        select(User.user_id)
        .join(User.roles)
        .join(UserRole.role)
        .where(Role.name.in_(target_roles))
        .distinct()
    )
    result = await session.execute(stmt)
    user_ids = result.scalars().all()

    photo_path = f"pic/{color}.jpg"
    if not os.path.exists(photo_path):
        print(f"Помилка: Файл {photo_path} не знайдено!")
        return

    text = f"📢 **Увага! Колір тижня змінено!"

    for uid in user_ids:
        try:
            photo = FSInputFile(photo_path)
            await bot.send_photo(chat_id=uid, photo=photo, caption=text, parse_mode="Markdown")
        except Exception as e:
            print(f"Не вдалося надіслати повідомлення {uid}: {e}")


@router.message(F.text == "🏠 Головне меню")
async def back_to_main(message: types.Message, session: AsyncSession):
    """Повернення до головного меню з оновленням прав"""
    await delete_prev_message(message)

    # Отримуємо юзера з ролями для правильної клавіатури
    stmt = select(User).where(User.user_id == message.from_user.id).options(selectinload(User.roles))
    user = (await session.execute(stmt)).scalar_one()

    await message.answer(
        "Ви повернулися в головне меню.",
        reply_markup=get_main_kb(user)
    )