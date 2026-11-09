from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, insert, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import datetime, date
from collections import defaultdict

from db.models import Lesson, Subject, User, UserRole, ScheduleChange
from keyboards.reply import delete_prev_message
from keyboards.schedule_kb import get_schedule_reply_kb
from utils.states import ScheduleEdit

router = Router()

# ==========================================================================================
# КОНСТАНТИ ТА СЛОВНИКИ
# ==========================================================================================

DAYS_MAP = {
    "Понеділок": "Monday",
    "Вівторок": "Tuesday",
    "Середа": "Wednesday",
    "Четвер": "Thursday",
    "П'ятниця": "Friday"
}

EN_TO_UA_DAYS = {
    "Monday": "Понеділок", "Tuesday": "Вівторок", "Wednesday": "Середа",
    "Thursday": "Четвер", "Friday": "П'ятниця", "Saturday": "Субота", "Sunday": "Неділя"
}

REVERSE_DAYS_MAP = {v: k for k, v in DAYS_MAP.items()}

COLOR_MAP = {
    "green": "🟢 Зелений",
    "red": "🔴 Червоний",
    "common": "⚪️ Звичайний"
}

COLOR_EMOJI = {"green": "🟢", "red": "🔴", "common": "⚪️"}

SUBGROUP_MAP = {
    "all": "👥 Вся група",
    "sub1": "1️⃣ 1 підгрупа",
    "sub2": "2️⃣ 2 підгрупа"
}


# ==========================================================================================
# ЛОГІКА ВІДОБРАЖЕННЯ (RENDER)
# ==========================================================================================

async def render_day_schedule(event: types.Message | types.CallbackQuery, day_ua: str, session: AsyncSession,
                              user_id: int):
    """
    Формує розклад з урахуванням підгруп та додає кнопку видалення під кожним предметом для адмінів.
    """
    day_en = DAYS_MAP[day_ua]

    stmt = (
        select(Lesson)
        .where(Lesson.day_of_week == day_en)
        .options(selectinload(Lesson.subject))
        .order_by(Lesson.lesson_number)
    )
    lessons = (await session.execute(stmt)).scalars().all()

    schedule_dict = defaultdict(list)
    for l in lessons:
        schedule_dict[l.lesson_number].append(l)

    # Перевірка прав доступу для кнопки видалення / редагування
    user_stmt = select(User).where(User.user_id == user_id).options(
        selectinload(User.roles).selectinload(UserRole.role))
    user = (await session.execute(user_stmt)).scalar_one()
    user_roles = [r.role.name for r in user.roles]
    is_privileged = any(role in {"admin", "rector", "headman"} for role in user_roles)

    text = f"📅 **Розклад на {day_ua}**\n"
    text += "━━━━━━━━━━━━━━━\n\n"

    # Створюємо клавіатуру для всього повідомлення, якщо є права редагування
    builder = InlineKeyboardBuilder()

    for i in range(1, 7):
        text += f"*{i} пара:* "
        lessons_list = schedule_dict.get(i)

        if not lessons_list:
            text += "_відсутня_\n"
            if is_privileged:
                builder.button(text=f"➕ Додати ({i} пар.)", callback_data=f"sch_edit_{day_en}_{i}")
            text += "\n"
        else:
            text += "\n"
            for lesson in lessons_list:
                subj = lesson.subject
                emoji = COLOR_EMOJI.get(lesson.week_type, "")
                sub_label = f" [{SUBGROUP_MAP.get(lesson.subgroup, '')}]" if lesson.subgroup != "all" else ""

                text += f"  {emoji} **{subj.name}**{sub_label}\n"
                if lesson.lesson_type:
                    text += f"  📝 Тип: {lesson.lesson_type}\n"
                text += f"  👨‍🏫 {subj.teacher_name or 'Не вказано'}\n"
                if subj.zoom_link:
                    text += f"  🔗 [Zoom]({subj.zoom_link}) "
                    if subj.zoom_id: text += f"🆔 `{subj.zoom_id}`"
                    text += "\n"

                # Якщо є права, додаємо кнопку видалення конкретного елемента
                if is_privileged:
                    builder.button(text=f"🗑 Видалити ({i} пар. / {subj.name[:10]}..)",
                                   callback_data=f"sch_del_item_{lesson.id}")

                text += "  — — — — — — — — —\n"

            if is_privileged:
                builder.button(text=f"➕ Додати ще ({i} пар.)", callback_data=f"sch_edit_{day_en}_{i}")
            text += "\n"

    if is_privileged:
        builder.adjust(1)  # Кожна кнопка в новий рядок для зручності
        kb = builder.as_markup()
    else:
        kb = None

    if isinstance(event, types.Message):
        await event.answer(text, reply_markup=kb, parse_mode="Markdown", disable_web_page_preview=True)
    else:
        await event.message.answer(text, reply_markup=kb, parse_mode="Markdown", disable_web_page_preview=True)


async def return_to_schedule(event: types.CallbackQuery, day_en: str, session: AsyncSession):
    await render_day_schedule(event, REVERSE_DAYS_MAP[day_en], session, event.from_user.id)


# ==========================================================================================
# ХЕНДЛЕРИ ПЕРЕГЛЯДУ
# ==========================================================================================

@router.message(F.text == "📅 Розклад занять")
async def cmd_schedule_menu(message: types.Message, session: AsyncSession):
    await delete_prev_message(message)

    stmt = (
        select(User)
        .where(User.user_id == message.from_user.id)
        .options(selectinload(User.roles).selectinload(UserRole.role))
    )
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    user_roles = [r.role.name for r in user.roles] if user else []

    await message.answer(
        "Оберіть день тижня для перегляду розкладу:",
        reply_markup=get_schedule_reply_kb(user_roles)
    )


@router.message(F.text.in_(DAYS_MAP.keys()))
async def show_day_schedule(message: types.Message, session: AsyncSession):
    await render_day_schedule(message, message.text, session, message.from_user.id)


# ==========================================================================================
# ХЕНДЛЕРИ РЕДАГУВАННЯ ТА ДОДАВАННЯ
# ==========================================================================================

@router.callback_query(F.data.startswith("sch_edit_"))
async def start_sch_edit(callback: types.CallbackQuery, state: FSMContext):
    """Початкове меню редагування пари (додавання нового запису)"""
    data = callback.data.split("_")
    day_en, lesson_num = data[2], int(data[3])
    await state.update_data(edit_day=day_en, edit_num=lesson_num)

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="📚 Додати предмет", callback_data="sch_step_subject"))
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад до розкладу", callback_data=f"back_to_day_{day_en}"))

    await callback.message.edit_text(
        f"🛠 **Додавання заняття: {REVERSE_DAYS_MAP[day_en]}, {lesson_num} пара**",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data == "sch_step_subject")
async def sch_step_subject(callback: types.CallbackQuery, session: AsyncSession, state: FSMContext):
    subjects = (await session.execute(select(Subject))).scalars().all()
    builder = InlineKeyboardBuilder()
    for s in subjects:
        builder.button(text=s.name, callback_data=f"sch_subj_set_{s.id}")
    builder.adjust(1)
    builder.row(types.InlineKeyboardButton(text="🚫 Скасувати", callback_data="sch_cancel"))

    await state.set_state(ScheduleEdit.waiting_for_subject)
    await callback.message.edit_text("🎯 Оберіть предмет:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("sch_subj_set_"), ScheduleEdit.waiting_for_subject)
async def sch_step_type(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(selected_subject_id=int(callback.data.split("_")[3]))
    await state.set_state(ScheduleEdit.waiting_for_type)
    await callback.message.answer("📝 Введіть тип пари (напр. *Лекція*, *Лабораторна*) або `-`:", parse_mode="Markdown")


@router.message(ScheduleEdit.waiting_for_type)
async def sch_step_subgroup(message: types.Message, state: FSMContext):
    val = message.text.strip()
    await state.update_data(selected_type=None if val == "-" else val)

    # 🟢 ВИБІР ПІДГРУПИ
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="👥 Вся група", callback_data="sch_subgroup_all"),
        types.InlineKeyboardButton(text="1️⃣ 1 підгрупа", callback_data="sch_subgroup_sub1"),
        types.InlineKeyboardButton(text="2️⃣ 2 підгрупа", callback_data="sch_subgroup_sub2")
    )

    await state.set_state(ScheduleEdit.waiting_for_subgroup if hasattr(ScheduleEdit,
                                                                       'waiting_for_subgroup') else ScheduleEdit.waiting_for_color)
    await message.answer("👥 Оберіть підгрупу для цього заняття:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("sch_subgroup_"))
async def sch_step_color(callback: types.CallbackQuery, state: FSMContext):
    subgroup = callback.data.split("_")[2]
    await state.update_data(selected_subgroup=subgroup)

    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🟢 Зелений", callback_data="sch_color_green"),
        types.InlineKeyboardButton(text="🔴 Червоний", callback_data="sch_color_red")
    )
    builder.row(types.InlineKeyboardButton(text="⚪️ Звичайний", callback_data="sch_color_common"))

    await state.set_state(ScheduleEdit.waiting_for_color)
    await callback.message.edit_text("🎨 Оберіть тип тижня для цього предмета:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("sch_color_"), ScheduleEdit.waiting_for_color)
async def sch_final_confirm(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    color = callback.data.split("_")[2]
    await state.update_data(selected_color=color)
    data = await state.get_data()

    subj = (await session.execute(select(Subject).where(Subject.id == data['selected_subject_id']))).scalar_one()

    summary = (
        f"📝 **Зберегти цей предмет у розклад?**\n\n"
        f"📅 День: {REVERSE_DAYS_MAP[data['edit_day']]}\n"
        f"🔢 Пара: {data['edit_num']}\n"
        f"📚 Предмет: {subj.name}\n"
        f"👥 Підгрупа: {SUBGROUP_MAP.get(data['selected_subgroup'], 'Вся група')}\n"
        f"🎨 Тиждень: {COLOR_MAP[color]}"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Так, зберегти", callback_data="sch_save")
    builder.button(text="❌ Скасувати", callback_data="sch_cancel")
    await callback.message.edit_text(summary, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.callback_query(F.data == "sch_save")
async def sch_save_db(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """
    Збереження нового заняття без перезапису попередніх (дозволяє створювати підгрупи).
    """
    data = await state.get_data()

    new_lesson = Lesson(
        day_of_week=data['edit_day'],
        lesson_number=data['edit_num'],
        week_type=data['selected_color'],
        subject_id=data['selected_subject_id'],
        lesson_type=data['selected_type'],
        subgroup=data.get('selected_subgroup', 'all')
    )

    session.add(new_lesson)
    await session.commit()

    day_en = data['edit_day']
    await state.clear()
    await callback.message.delete()
    await return_to_schedule(callback, day_en, session)


# ==========================================================================================
# ВИДАЛЕННЯ
# ==========================================================================================

@router.callback_query(F.data.startswith("sch_del_item_"))
async def sch_delete_single_lesson(callback: types.CallbackQuery, session: AsyncSession):
    """Видалення конкретного заняття за його ID"""
    lesson_id = int(callback.data.split("_")[3])

    lesson = (await session.execute(select(Lesson).where(Lesson.id == lesson_id))).scalar_one_or_none()
    if lesson:
        day_en = lesson.day_of_week
        await session.delete(lesson)
        await session.commit()
        await callback.answer("🗑 Предмет видалено з розкладу")
        await return_to_schedule(callback, day_en, session)
    else:
        await callback.answer("❌ Предмет не знайдено", show_alert=True)


@router.callback_query(F.data == "sch_cancel")
async def sch_cancel(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    day_en = data.get('edit_day')
    await state.clear()
    await callback.message.delete()
    if day_en: await return_to_schedule(callback, day_en, session)


@router.callback_query(F.data.startswith("back_to_day_"))
async def back_to_day_handler(callback: types.CallbackQuery, session: AsyncSession):
    day_en = callback.data.split("_")[3]
    await callback.message.delete()
    await return_to_schedule(callback, day_en, session)


# ==========================================================================================
# ЗАМІНИ (БЕЗ ЗМІН)
# ==========================================================================================

@router.callback_query(F.data == "back_to_main_schedule")
async def start_sub(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    subjects = (await session.execute(select(Subject))).scalars().all()
    builder = InlineKeyboardBuilder()
    for s in subjects: builder.button(text=s.name, callback_data=f"subj_sub_{s.id}")
    builder.adjust(1)
    builder.row(types.InlineKeyboardButton(text="❌ Скасувати", callback_data="sch_cancel"))
    await callback.message.edit_text("🔄 **Створення заміни**\nОберіть предмет:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("subj_sub_"))
async def sub_date(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(sub_subject_id=int(callback.data.split("_")[2]))
    await state.set_state(ScheduleEdit.subj_waiting_for_type)
    await callback.message.edit_text("📅 Введіть дату (`ДД.ММ.РРРР`):")


@router.message(ScheduleEdit.subj_waiting_for_type)
async def sub_proc(message: types.Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    try:
        input_date = datetime.strptime(message.text.strip(), "%d.%m.%Y").date()
        if input_date.strftime("%A") != data['edit_day']:
            return await message.answer(f"❌ Дата не збігається з {REVERSE_DAYS_MAP[data['edit_day']]}")

        subj = (await session.execute(select(Subject).where(Subject.id == data['sub_subject_id']))).scalar_one()
        await state.update_data(sub_date=input_date)

        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Підтвердити", callback_data="sub_save_final")
        builder.button(text="❌ Скасувати", callback_data="sch_cancel")
        await message.answer(f"Заміна на {message.text}: {subj.name}?", reply_markup=builder.as_markup())
    except:
        await message.answer("❌ Формат: ДД.ММ.РРРР")


@router.callback_query(F.data == "sub_save_final")
async def sub_save(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    new_change = ScheduleChange(
        change_date=data['sub_date'],
        pair_number=data['edit_num'],
        new_subject_id=data['sub_subject_id'],
        weekday=data['sub_date'].weekday() + 1
    )
    session.add(new_change)
    await session.commit()
    await callback.answer("✅ Заміну додано")
    await callback.message.delete()
    await return_to_schedule(callback, data['edit_day'], session)


# --- ПЕРЕГЛЯД ЗАМІН ---
@router.message(F.text == "Зміни у розкладу")
async def list_subs(message: types.Message, session: AsyncSession):
    changes = (await session.execute(
        select(ScheduleChange).where(ScheduleChange.change_date >= date.today())
        .options(selectinload(ScheduleChange.new_subject))
    )).scalars().all()

    if not changes: return await message.answer("📭 Замін немає")

    for c in changes:
        txt = f"📅 {c.change_date} | Пара №{c.pair_number}\n📚 {c.new_subject.name}"
        btn = InlineKeyboardBuilder().button(text="🗑", callback_data=f"del_sub_conf_{c.id}").as_markup()
        await message.answer(txt, reply_markup=btn)


@router.callback_query(F.data.startswith("del_sub_conf_"))
async def del_sub(callback: types.CallbackQuery, session: AsyncSession):
    await session.execute(delete(ScheduleChange).where(ScheduleChange.id == int(callback.data.split("_")[3])))
    await session.commit()
    await callback.message.delete()
