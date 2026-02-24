from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update

from db.models import Homework, Subject, User
from keyboards.reply import delete_prev_message
from keyboards.homework import (
    HWAction, get_homework_menu_kb, get_back_to_hw_menu_kb,
    get_navigation_only_kb, get_single_hw_edit_kb, get_edit_hw_choice_kb
)
from utils.states import HomeworkStates

router = Router()


# Вспоміжна функція для обробки порожнього вводу через "-"
def parse_input(text: str):
    return None if text.strip() == "-" else text.strip()


# --- 1. МЕНЮ ТА ВИБІР ПРЕДМЕТА ---

@router.message(F.text == "📝 Домашнє завдання")
async def cmd_hw_entrance(message: types.Message, session: AsyncSession):
    """Виклик меню через кнопку Reply-клавіатури"""
    await delete_prev_message(message)
    stmt = select(User).where(User.user_id == message.from_user.id)
    user = (await session.execute(stmt)).scalar_one()
    roles = [r.role.name for r in user.roles]
    await message.answer("📝 **Меню домашніх завдань**\nОберіть предмет:",
                         reply_markup=get_homework_menu_kb(0, "", roles), parse_mode="Markdown")


@router.callback_query(HWAction.filter(F.action == "select_subject"))
async def list_subjects(callback: types.CallbackQuery, session: AsyncSession):
    """Список предметів для вибору"""
    result = await session.execute(select(Subject))
    subjects = result.scalars().all()
    builder = InlineKeyboardBuilder()
    for s in subjects:
        builder.button(text=s.name, callback_data=HWAction(action="menu", subject_id=s.id).pack())
    builder.adjust(1)
    await callback.message.edit_text("Оберіть предмет з бази:", reply_markup=builder.as_markup())


@router.callback_query(HWAction.filter(F.action == "menu"))
async def hw_menu_selected(callback: types.CallbackQuery, callback_data: HWAction, session: AsyncSession):
    """Панель керування конкретним предметом"""
    subject = await session.get(Subject, callback_data.subject_id)
    stmt = select(User).where(User.user_id == callback.from_user.id)
    user = (await session.execute(stmt)).scalar_one()
    roles = [r.role.name for r in user.roles]
    await callback.message.edit_text(f"Ви обрали: **{subject.name}**\nЩо бажаєте зробити?",
                                     reply_markup=get_homework_menu_kb(subject.id, subject.name, roles),
                                     parse_mode="Markdown")


# --- 2. ПЕРЕГЛЯД ТА ПАГІНАЦІЯ ---

@router.callback_query(HWAction.filter(F.action == "last_homework"))
async def show_last_hw(callback: types.CallbackQuery, callback_data: HWAction, session: AsyncSession):
    """Вивід лише останнього запису"""
    stmt = select(Homework).where(Homework.subject_id == callback_data.subject_id).order_by(Homework.id.desc()).limit(1)
    hw = (await session.execute(stmt)).scalar_one_or_none()
    if not hw:
        await callback.answer("Завдань ще немає ✨", show_alert=True)
        return

    links = [f"[🔗 Завдання]({hw.task_link})" if hw.task_link else None,
             f"[📹 Відео]({hw.video_link})" if hw.video_link else None,
             f"[📁 Додатково]({hw.extra_link})" if hw.extra_link else None]
    links_str = "\n".join(filter(None, links)) or "_Посилання відсутні_"

    text = f"📌 **Останнє завдання**\n━━━━━━━━━━━━━━━\n{hw.description}\n\n{links_str}\n💡 **Примітка:** {hw.teacher_note or 'відсутня'}"
    await callback.message.edit_text(text, parse_mode="Markdown", disable_web_page_preview=True,
                                     reply_markup=get_back_to_hw_menu_kb(callback_data.subject_id))


@router.callback_query(HWAction.filter(F.action == "all_homework"))
async def show_all_homework_clean(callback: types.CallbackQuery, callback_data: HWAction, session: AsyncSession):
    """Повідомлення по 3 штуки з кнопками Ред/Вид під кожним"""
    items_per_page = 3
    current_page = callback_data.page

    count_stmt = select(func.count()).select_from(Homework).where(Homework.subject_id == callback_data.subject_id)
    total_count = (await session.execute(count_stmt)).scalar()
    total_pages = (total_count + items_per_page - 1) // items_per_page

    stmt = select(Homework).where(Homework.subject_id == callback_data.subject_id).order_by(Homework.id.desc()).limit(
        items_per_page).offset(current_page * items_per_page)
    hws = (await session.execute(stmt)).scalars().all()

    await callback.message.delete()  # Очищуємо чат перед виводом сторінки

    stmt_user = select(User).where(User.user_id == callback.from_user.id)
    user = (await session.execute(stmt_user)).scalar_one()
    roles = [r.role.name for r in user.roles]

    for hw in hws:
        links = [f"[🔗 Завдання]({hw.task_link})" if hw.task_link else None,
                 f"[📹 Відео]({hw.video_link})" if hw.video_link else None,
                 f"[📁 Додатково]({hw.extra_link})" if hw.extra_link else None]
        links_str = "\n".join(filter(None, links)) or "_Посилання відсутні_"
        text = f"📅 **Завдання**\n━━━━━━━━━━━━━━━\n{hw.description}\n\n{links_str}\n💡 **Примітка:** {hw.teacher_note or 'відсутня'}"
        await callback.message.answer(text, parse_mode="Markdown", disable_web_page_preview=True,
                                      reply_markup=get_single_hw_edit_kb(callback_data.subject_id, hw.id, roles))

    await callback.message.answer(f"📖 Сторінка {current_page + 1} з {total_pages}",
                                  reply_markup=get_navigation_only_kb(callback_data.subject_id, current_page,
                                                                      total_pages))


# --- 3. ДОДАВАННЯ (FSM) ---

@router.callback_query(HWAction.filter(F.action == "add_homework"))
async def start_add_hw(callback: types.CallbackQuery, callback_data: HWAction, state: FSMContext):
    await state.update_data(subject_id=callback_data.subject_id)
    await state.set_state(HomeworkStates.waiting_for_description)
    await callback.message.edit_text("📝 **Крок 1**: Введіть текст завдання:")


@router.message(HomeworkStates.waiting_for_description)
async def process_desc(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(HomeworkStates.waiting_for_task_link)
    await message.answer("🔗 **Крок 2**: Посилання на завдання (або '-'):")


@router.message(HomeworkStates.waiting_for_task_link)
async def process_task(message: types.Message, state: FSMContext):
    await state.update_data(task_link=parse_input(message.text))
    await state.set_state(HomeworkStates.waiting_for_video_link)
    await message.answer("📹 **Крок 3**: Посилання на відео (або '-'):")


@router.message(HomeworkStates.waiting_for_video_link)
async def process_video(message: types.Message, state: FSMContext):
    await state.update_data(video_link=parse_input(message.text))
    await state.set_state(HomeworkStates.waiting_for_extra_link)
    await message.answer("📁 **Крок 4**: Додаткові матеріали (або '-'):")


@router.message(HomeworkStates.waiting_for_extra_link)
async def process_extra(message: types.Message, state: FSMContext):
    await state.update_data(extra_link=parse_input(message.text))
    await state.set_state(HomeworkStates.waiting_for_note)
    await message.answer("💡 **Крок 5**: Примітка (або '-'):")


@router.message(HomeworkStates.waiting_for_note)
async def process_confirm(message: types.Message, state: FSMContext):
    await state.update_data(teacher_note=parse_input(message.text))
    data = await state.get_data()
    await state.set_state(HomeworkStates.confirm_add)
    text = (f"🧐 **Перевірте дані:**\n\n📝 {data['description']}\n🔗 Завдання: {data['task_link'] or '—'}\n"
            f"📹 Відео: {data['video_link'] or '—'}\n📁 Дод: {data['extra_link'] or '—'}\n💡 Прим: {data['teacher_note'] or '—'}")
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Зберегти", callback_data="confirm_save_hw")
    builder.button(text="❌ Скасувати", callback_data="cancel_hw_process")
    await message.answer(text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "confirm_save_hw", HomeworkStates.confirm_add)
async def save_hw_db(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    new_hw = Homework(subject_id=data['subject_id'], description=data['description'],
                      task_link=data['task_link'], video_link=data['video_link'],
                      extra_link=data['extra_link'], teacher_note=data['teacher_note'])
    session.add(new_hw)
    await session.commit()
    await state.clear()
    await callback.message.edit_text("✅ Додано успішно!")


@router.callback_query(F.data == "cancel_hw_process")
async def cancel_hw(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("🚫 Скасовано.")


# --- 4. ВИДАЛЕННЯ ---

@router.callback_query(HWAction.filter(F.action == "delete_hw"))
async def confirm_delete_hw(callback: types.CallbackQuery, callback_data: HWAction):
    builder = InlineKeyboardBuilder()
    builder.button(text="🔥 Видалити", callback_data=f"real_del_{callback_data.hw_id}")
    builder.button(text="❌ Назад",
                   callback_data=HWAction(action="all_homework", subject_id=callback_data.subject_id).pack())
    await callback.message.edit_text("🚨 Видалити завдання безповоротно?", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("real_del_"))
async def delete_hw_final(callback: types.CallbackQuery, session: AsyncSession):
    hw_id = int(callback.data.split("_")[-1])
    hw = await session.get(Homework, hw_id)
    if hw:
        await session.delete(hw)
        await session.commit()
        await callback.answer("🗑 Видалено", show_alert=True)
        await callback.message.delete()


# --- 5. РЕДАГУВАННЯ (Циклічне) ---

@router.callback_query(HWAction.filter(F.action == "edit_hw"))
async def show_edit_menu(event: types.CallbackQuery | types.Message, callback_data: HWAction, session: AsyncSession):
    """Універсальне відображення меню редагування"""
    hw = await session.get(Homework, callback_data.hw_id)
    links = [f"[🔗 Завдання]({hw.task_link})" if hw.task_link else None,
             f"[📹 Відео]({hw.video_link})" if hw.video_link else None,
             f"[📁 Додатково]({hw.extra_link})" if hw.extra_link else None]
    links_str = "\n".join(filter(None, links)) or "_Посилання відсутні_"

    text = (f"🛠 **Редагування завдання**\n━━━━━━━━━━━━━━━\n{hw.description}\n\n"
            f"{links_str}\n💡 **Примітка:** {hw.teacher_note or 'відсутня'}\n\nОберіть поле:")

    kb = get_edit_hw_choice_kb(hw.subject_id, hw.id)
    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text(text, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=kb)
    else:
        await event.answer(text, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=kb)


@router.callback_query(F.data.startswith("hw_field_"))
async def ask_new_value(callback: types.CallbackQuery, state: FSMContext):
    """Перехід у стан очікування нового тексту для поля"""
    data = callback.data.split("_")
    hw_id, field = int(data[-1]), data[-2]

    await state.update_data(edit_hw_id=hw_id, edit_field=field)
    await state.set_state(HomeworkStates.waiting_for_new_value)

    names = {"desc": "текст", "task": "посилання", "video": "відео", "extra": "додатково", "note": "примітку"}
    await callback.message.edit_text(f"📝 Введіть нове значення для: **{names.get(field)}** (або '-')")


@router.message(HomeworkStates.waiting_for_new_value)
async def update_hw_field(message: types.Message, state: FSMContext, session: AsyncSession):
    """Оновлення бази та повернення в меню редагування"""
    data = await state.get_data()
    hw_id, field = data.get('edit_hw_id'), data.get('edit_field')
    new_value = parse_input(message.text)

    if field == "desc" and (not new_value or new_value == "-"):
        await message.answer("❌ Опис не може бути порожнім!")
        return

    field_map = {"desc": Homework.description, "task": Homework.task_link,
                 "video": Homework.video_link, "extra": Homework.extra_link, "note": Homework.teacher_note}

    if field in field_map:
        await session.execute(update(Homework).where(Homework.id == hw_id).values({field_map[field]: new_value}))
        await session.commit()
        await message.answer("✅ Оновлено!")

    await state.clear()
    hw = await session.get(Homework, hw_id)
    fake_cb = HWAction(action="edit_hw", subject_id=hw.subject_id, hw_id=hw.id)
    await show_edit_menu(message, fake_cb, session)
