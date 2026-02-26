from aiogram import Router, F, types, Bot, html
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import User, Role, UserRole
from keyboards.inline import get_users_list_kb, get_user_edit_kb
from keyboards.reply import get_main_kb
from utils.states import UserEditStates, UserManage
from aiogram.filters.callback_data import CallbackData

router = Router()


# --- 1. СПИСОК КОРИСТУВАЧІВ ---

@router.message(F.text == "👥 Користувачі")
async def cmd_users_list(message: types.Message, session: AsyncSession):
    await show_users_page(message, session, page=0)


async def show_users_page(event: types.Message | types.CallbackQuery, session: AsyncSession, page: int):
    limit = 10
    offset = page * limit

    # Рахуємо загальну кількість для пагінації
    count_stmt = select(func.count()).select_from(User)
    total_count = (await session.execute(count_stmt)).scalar()
    total_pages = (total_count + limit - 1) // limit

    # Отримуємо користувачів
    stmt = select(User).order_by(User.user_name).limit(limit).offset(offset)
    users = (await session.execute(stmt)).scalars().all()

    kb = get_users_list_kb(users, page, total_pages)
    # Використовуємо html.bold замість зірочок
    text = f"👥 {html.bold('Список користувачів')}\nСторінка {page + 1} з {total_pages}:"

    if isinstance(event, types.Message):
        await event.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


# Навігація по списку
@router.callback_query(UserManage.filter(F.action == "list"))
async def navigate_users(callback: types.CallbackQuery, callback_data: UserManage, session: AsyncSession):
    await show_users_page(callback, session, page=callback_data.page)
    await callback.answer()


# --- 2. КАРТКА КОРИСТУВАЧА ---

@router.callback_query(UserManage.filter(F.action == "details"))
async def user_details(callback: types.CallbackQuery, callback_data: UserManage, session: AsyncSession):
    # Завантажуємо цільового юзера
    stmt = select(User).where(User.user_id == callback_data.user_id).options(selectinload(User.roles))
    target = (await session.execute(stmt)).scalar_one_or_none()

    # Завантажуємо менеджера (хто натиснув)
    mgr_stmt = select(User).where(User.user_id == callback.from_user.id).options(selectinload(User.roles))
    manager = (await session.execute(mgr_stmt)).scalar_one()

    if not target:
        return await callback.answer("Користувача не знайдено", show_alert=True)

    target_roles = [r.role.name for r in target.roles]
    mgr_roles = [r.role.name for r in manager.roles]

    text = (f"👤 {html.bold('Керування:')} {html.quote(target.user_name)} {html.quote(target.user_surname or '')}\n"
            f"🔗 Юзернейм: @{html.quote(target.username or '---')}\n"
            f"🆔 ID: {html.code(target.user_id)}\n"
            f"🔢 № у журналі: {html.bold(target.number or 'не вказано')}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"Оберіть роль для перемикання (✅ = є):")

    await callback.message.edit_text(
        text,
        reply_markup=get_user_edit_kb(target.user_id, target_roles, mgr_roles),
        parse_mode="HTML"
    )


# --- 3. ЛОГІКА ЗМІНИ РОЛЕЙ ---

@router.callback_query(UserManage.filter(F.action == "edit_role"))
async def toggle_user_role(callback: types.CallbackQuery, callback_data: UserManage, session: AsyncSession, bot: Bot):
    # callback_data.user_id — це Telegram ID
    tg_id = callback_data.user_id
    role_name = callback_data.role_name
    manager_tg_id = callback.from_user.id

    # 1. Отримуємо внутрішні ID користувачів
    stmt_target = select(User).where(User.user_id == tg_id)
    target = (await session.execute(stmt_target)).scalar_one()

    # Захист: Адмін не може зняти адміна з себе (порівнюємо саме Telegram ID)
    if tg_id == manager_tg_id and role_name == "admin":
        return await callback.answer("🚨 Ви не можете зняти роль admin із себе!", show_alert=True)

    # 2. Отримуємо об'єкт ролі
    role_stmt = select(Role).where(Role.name == role_name)
    role_obj = (await session.execute(role_stmt)).scalar_one()

    # 3. Перевіряємо роль, використовуючи ВНУТРІШНІЙ target.id
    link_stmt = select(UserRole).where(
        UserRole.user_id == target.id,  # ПРИВ'ЯЗКА ДО PRIMARY KEY
        UserRole.role_id == role_obj.id
    )
    existing_link = (await session.execute(link_stmt)).scalar_one_or_none()

    if existing_link:
        await session.delete(existing_link)
        action_text = f"❌ Роль **{role_name}** знято."
    else:
        new_link = UserRole(user_id=target.id, role_id=role_obj.id)
        session.add(new_link)
        action_text = f"✅ Роль **{role_name}** надано."

    await session.commit()

    # Рефрешимо об'єкт, щоб SQLAlchemy побачила зміни у відносинах (relationship)
    await session.refresh(target)

    # 4. Оновлюємо меню юзера (використовуємо Telegram ID для відправки)
    try:
        await bot.send_message(
            chat_id=tg_id,
            text=f"{action_text}\nВаше меню оновлено.",
            reply_markup=get_main_kb(target)
        )
    except Exception:
        pass

    # 5. Оновлюємо вікно адміна
    await user_details(callback, callback_data, session)


# --- 4. ЗМІНА НОМЕРА В ЖУРНАЛІ ---

@router.callback_query(UserManage.filter(F.action == "edit_num"))
async def start_edit_number(callback: types.CallbackQuery, callback_data: UserManage, state: FSMContext):
    await state.update_data(target_id=callback_data.user_id)
    await state.set_state(UserEditStates.waiting_for_number)
    await callback.message.answer("🔢 Введіть номер користувача за журналом (або '-' для видалення):")
    await callback.answer()


@router.message(UserEditStates.waiting_for_number)
async def save_user_number(message: types.Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    target_id = data['target_id']

    new_val = None
    if message.text.isdigit():
        new_val = int(message.text)
    elif message.text != "-":
        return await message.answer("Будь ласка, введіть число або '-'")

    await session.execute(update(User).where(User.user_id == target_id).values(number=new_val))
    await session.commit()

    await message.answer(f"✅ Номер у журналі оновлено.")
    await state.clear()