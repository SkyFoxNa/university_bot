from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select

from db.models import Subject, User
from utils.states import SubjectStates

router = Router()


# Допоміжна функція для очищення вводу
def parse_input(text: str):
    """Якщо введено '-', повертаємо None або дефолтне значення"""
    return None if text.strip() == "-" else text.strip()


# 1. Початок процесу (кнопка "➕ Додати новий предмет")
@router.callback_query(F.data == "add_new_subject")
async def start_add_subject(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    # Перевірка ролей
    stmt = select(User).where(User.user_id == callback.from_user.id).options(selectinload(User.roles))
    user = (await session.execute(stmt)).scalar_one()

    user_roles = [r.role.name for r in user.roles]
    if not any(role in user_roles for role in ["admin", "headman", "head"]):
        await callback.answer("❌ У вас немає прав для додавання предметів.", show_alert=True)
        return

    await state.set_state(SubjectStates.waiting_for_name)
    await callback.message.answer("📝 Крок 1: Введіть **назву предмета**\n(Це поле обов'язкове):")
    await callback.answer()


# 2. Отримання назви -> Питаємо про викладача
@router.message(SubjectStates.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    if message.text == "-":
        await message.answer("❌ Назва предмета не може бути порожньою. Будь ласка, введіть назву:")
        return

    await state.update_data(name=message.text.strip())
    await state.set_state(SubjectStates.waiting_for_teacher)
    await message.answer("👤 Крок 2: ПІБ викладача\n(Введіть ім'я або '-' щоб пропустити):")


# 3. Отримання викладача -> Питаємо Zoom лінк
@router.message(SubjectStates.waiting_for_teacher)
async def process_teacher(message: types.Message, state: FSMContext):
    # Тепер тут теж можна пропустити через '-'
    teacher = parse_input(message.text) or "Не призначено"
    await state.update_data(teacher_name=teacher)

    await state.set_state(SubjectStates.waiting_for_zoom_link)
    await message.answer("🌐 Крок 3: Посилання на Zoom\n(Вставте лінк або '-' щоб пропустити):")


# 4. Отримання лінка -> Питаємо Zoom ID
@router.message(SubjectStates.waiting_for_zoom_link)
async def process_zoom_link(message: types.Message, state: FSMContext):
    await state.update_data(zoom_link=parse_input(message.text))
    await state.set_state(SubjectStates.waiting_for_zoom_id)
    await message.answer("🆔 Крок 4: Ідентифікатор Zoom (ID)\n(Введіть цифри або '-' щоб пропустити):")


# 5. Отримання ID -> Питаємо пароль
@router.message(SubjectStates.waiting_for_zoom_id)
async def process_zoom_id(message: types.Message, state: FSMContext):
    await state.update_data(zoom_id=parse_input(message.text))
    await state.set_state(SubjectStates.waiting_for_zoom_password)
    await message.answer("🔑 Крок 5: Пароль до Zoom\n(Введіть пароль або '-' щоб пропустити):")


# 6. Фінальний етап та збереження
@router.message(SubjectStates.waiting_for_zoom_password)
async def process_final_subject(message: types.Message, state: FSMContext, session: AsyncSession):
    await state.update_data(zoom_password=parse_input(message.text))

    data = await state.get_data()

    # Створюємо об'єкт у базі
    new_subject = Subject(
        name=data['name'],
        teacher_name=data['teacher_name'],
        zoom_link=data.get('zoom_link'),
        zoom_id=data.get('zoom_id'),
        zoom_password=data.get('zoom_password')
    )

    session.add(new_subject)
    await session.commit()

    # Виводимо підтвердження
    res_text = (
        f"✅ **Предмет успішно додано!**\n\n"
        f"📘 Назва: {data['name']}\n"
        f"👤 Викладач: {data['teacher_name']}\n"
        f"🌐 Zoom: {'Вказано' if data['zoom_link'] else '—'}"
    )

    await message.answer(res_text, parse_mode="Markdown")
    await state.clear()