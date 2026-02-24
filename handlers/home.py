from aiogram import Router, F, types
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from datetime import date

from db.models import User, UserRole
from keyboards.reply import get_main_kb, HOME_BUTTON
from utils.format_schedule import get_today_schedule_text

router = Router()

@router.message(F.text.in_({HOME_BUTTON, "🏠 Головне меню", "🏠"}))
async def cmd_home(message: types.Message, session: AsyncSession):
    # 1. Видаляємо повідомлення користувача ("🏠 Головне меню")
    try:
        await message.delete()
    except Exception:
        # Іноді видалення може не спрацювати (напр. якщо бот не адмін у групі,
        # але в особистих повідомленнях працює завжди)
        pass

    # 2. Отримуємо дані користувача з ролями для клавіатури
    # Використовуємо selectinload для підвантаження ролей
    stmt = (
        select(User)
        .where(User.user_id == message.from_user.id)
        .options(selectinload(User.roles).selectinload(UserRole.role))
    )
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        return # Або логіка реєстрації

    # 3. Формуємо розклад
    schedule = await get_today_schedule_text(session, date.today())

    welcome_text = "🏠 **Головне меню**\n\n"
    if schedule:
        welcome_text += schedule
    else:
        welcome_text += "🏝 Сьогодні вихідний, насолоджуйтесь відпочинком!"

    # 4. Відправляємо нове повідомлення
    await message.answer(
        welcome_text,
        reply_markup=get_main_kb(user),
        parse_mode="Markdown",
        disable_web_page_preview=True
    )

# from aiogram import Router, F, types
# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy import select
#
# from db.models import User
# from keyboards.reply import get_main_kb, HOME_BUTTON, delete_prev_message
#
# router = Router()
# # --- ПОВЕРНЕННЯ ---
#
# # Повернення до головного меню (обробляє і повну назву, і іконку)
# @router.message(F.text.in_({HOME_BUTTON, "🏠"}))
# async def cmd_home(message: types.Message, session: AsyncSession):
#     await delete_prev_message(message) # Видаляємо повідомлення від натискання кнопок
#
#     stmt = select(User).where(User.user_id == message.from_user.id)
#     user = (await session.execute(stmt)).scalar_one()
#
#     await message.answer(
#         "Ви повернулися в головне меню",
#         reply_markup=get_main_kb(user)
#     )
