from aiogram import Router, types, Bot
from aiogram.filters import CommandStart
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.models import User, Role, UserRole
from keyboards.reply import get_main_kb

router = Router()

@router.message(CommandStart())
async def start_handler(message: types.Message, session: AsyncSession, bot: Bot):
    # Пошук користувача
    stmt = select(User).where(User.user_id == message.from_user.id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        # Реєстрація нового
        user = User(
            user_id=message.from_user.id,
            user_name=message.from_user.first_name,
            user_surname=message.from_user.last_name,
            username=message.from_user.username,
            visit=1
        )
        session.add(user)
        await session.flush()

        # Роль за замовчуванням
        role_res = await session.execute(select(Role).where(Role.name == "user"))
        default_role = role_res.scalar_one_or_none()
        if default_role:
            session.add(UserRole(user_id=user.id, role_id=default_role.id))

        await session.commit()
        await session.refresh(user)

        # Сповіщення адмінів та старост
        staff_stmt = select(User).join(User.roles).join(Role).where(Role.name.in_(["admin", "headman"]))
        staff_list = (await session.execute(staff_stmt)).unique().scalars().all()

        alert = (f"🆕 **Нова реєстрація!**\n"
                 f"👤 {user.user_name} {user.user_surname or ''}\n"
                 f"🆔 `{user.user_id}` | @{user.username or '—'}\n"
                 f"🔐 Надайте права доступу користувачу.")

        for staff in staff_list:
            try:
                await bot.send_message(staff.user_id, alert, parse_mode="Markdown")
            except: continue

        await message.answer("Вітаю! Ви зареєстровані. Очікуйте підтвердження прав адміністратором. 🎓")
    else:
        user.visit += 1
        await session.commit()
        await message.answer("З поверненням! 😊")

    await message.answer(f"Привіт, {user.user_name}!", reply_markup=get_main_kb(user))


# from aiogram import Router, types
# from aiogram.filters import CommandStart
# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy import select
# from db.models import User, Role, UserRole
# from keyboards.reply import get_main_kb
#
# router = Router()
#
#
# @router.message(CommandStart())
# async def start_handler(message: types.Message, session: AsyncSession):
#     # Перевіряємо, чи є користувач у базі
#     stmt = select(User).where(User.user_id == message.from_user.id)
#     result = await session.execute(stmt)
#     user = result.scalar_one_or_none()
#
#     if not user:
#         # Створюємо нового користувача
#         user = User(
#             user_id=message.from_user.id,
#             user_name=message.from_user.first_name,
#             user_surname=message.from_user.last_name,
#             username=message.from_user.username,
#             visit=1
#         )
#         session.add(user)
#         await session.flush()  # Отримуємо ID користувача перед комітом
#
#         # Додаємо роль 'user' за замовчуванням
#         role_stmt = select(Role).where(Role.name == "user")
#         role_res = await session.execute(role_stmt)
#         default_role = role_res.scalar_one_or_none()
#
#         if default_role:
#             session.add(UserRole(user_id=user.id, role_id=default_role.id))
#
#         await session.commit()
#         # Оновлюємо об'єкт користувача, щоб підтягнути роль для клавіатури
#         await session.refresh(user)
#
#         # Генеруємо клавіатуру на основі ролей користувача
#         kb = get_main_kb(user)
#         await message.answer("Вітаю у боті університету! 🎓")
#
#         await message.answer(
#             f"Вітаю, {user.user_name}! 🎓\nВаші ролі: " +
#             ", ".join([r.role.name for r in user.roles]),
#             reply_markup=kb
#         )
#
#     else:
#         user.visit += 1
#         await session.commit()
#         # Генеруємо клавіатуру на основі ролей користувача
#         kb = get_main_kb(user)
#
#         await message.answer("З поверненням! 😊")
#
#         await message.answer(
#             f"Вітаю, {user.user_name}! 🎓\nВаші ролі: " +
#             ", ".join([r.role.name for r in user.roles]),
#             reply_markup=kb
#         )