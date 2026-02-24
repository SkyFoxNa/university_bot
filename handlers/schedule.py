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


# ==========================================================================================
# ЛОГІКА ВІДОБРАЖЕННЯ (RENDER)
# ==========================================================================================

async def render_day_schedule(event: types.Message | types.CallbackQuery, day_ua: str, session: AsyncSession,
                              user_id: int):
    """
    Формує розклад, групуючи різні типи тижнів (red/green) в межах однієї пари.
    """
    day_en = DAYS_MAP[day_ua]

    # Отримуємо всі уроки дня
    stmt = (
        select(Lesson)
        .where(Lesson.day_of_week == day_en)
        .options(selectinload(Lesson.subject))
        .order_by(Lesson.lesson_number)
    )
    lessons = (await session.execute(stmt)).scalars().all()

    # Групуємо уроки за номером пари: {1: [lesson_common], 2: [lesson_red, lesson_green]}
    schedule_dict = defaultdict(list)
    for l in lessons:
        schedule_dict[l.lesson_number].append(l)

    text = f"📅 **Розклад на {day_ua}**\n"
    text += "━━━━━━━━━━━━━━━\n\n"

    for i in range(1, 7):
        text += f"*{i} пара:* "
        lessons_list = schedule_dict.get(i)

        if not lessons_list:
            text += "_відсутня_\n\n"
        else:
            text += "\n"
            for lesson in lessons_list:
                subj = lesson.subject
                emoji = COLOR_EMOJI.get(lesson.week_type, "")
                text += f"  {emoji} **{subj.name}** ({lesson.lesson_type or '---'})\n"
                text += f"  👨‍🏫 {subj.teacher_name or 'Не вказано'}\n"
                if subj.zoom_link:
                    text += f"  🔗 [Zoom]({subj.zoom_link}) "
                    if subj.zoom_id: text += f"🆔 `{subj.zoom_id}`"
                    text += "\n"
            text += "\n"

    # Перевірка прав доступу для кнопок редагування
    user_stmt = select(User).where(User.user_id == user_id).options(
        selectinload(User.roles).selectinload(UserRole.role))
    user = (await session.execute(user_stmt)).scalar_one()
    user_roles = [r.role.name for r in user.roles]

    kb = None
    if any(role in {"admin", "rector", "headman"} for role in user_roles):
        builder = InlineKeyboardBuilder()
        for i in range(1, 7):
            builder.button(text=f"⚙️ {i}", callback_data=f"sch_edit_{day_en}_{i}")
        builder.adjust(3, 3)
        kb = builder.as_markup()

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

    # 1. Отримуємо користувача та його ролі з бази
    stmt = (
        select(User)
        .where(User.user_id == message.from_user.id)
        .options(selectinload(User.roles).selectinload(UserRole.role))
    )
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    # 2. Формуємо список назв ролей (якщо користувача немає, даємо порожній список)
    user_roles = []
    if user:
        user_roles = [r.role.name for r in user.roles]

    # 3. Передаємо список ролей у функцію клавіатури
    await message.answer(
        "Оберіть день тижня для перегляду розкладу:",
        reply_markup=get_schedule_reply_kb(user_roles)  # ТУТ БУЛА ПОМИЛКА
    )


@router.message(F.text.in_(DAYS_MAP.keys()))
async def show_day_schedule(message: types.Message, session: AsyncSession):
    await render_day_schedule(message, message.text, session, message.from_user.id)


# ==========================================================================================
# ХЕНДЛЕРИ РЕДАГУВАННЯ
# ==========================================================================================

@router.callback_query(F.data.startswith("sch_edit_"))
async def start_sch_edit(callback: types.CallbackQuery, state: FSMContext):
    """Початкове меню редагування пари"""
    data = callback.data.split("_")
    day_en, lesson_num = data[2], int(data[3])
    await state.update_data(edit_day=day_en, edit_num=lesson_num)

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="📚 Додати/Змінити предмет", callback_data="sch_step_subject"))
    builder.row(types.InlineKeyboardButton(text="🗑 Очистити слот (всі типи)", callback_data="sch_quick_delete"))
    builder.row(
        types.InlineKeyboardButton(text="📅 Заміна", callback_data="back_to_main_schedule"),
        types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back_to_day_{day_en}")
    )

    await callback.message.edit_text(
        f"🛠 **Редагування: {REVERSE_DAYS_MAP[day_en]}, {lesson_num} пара**",
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
    await callback.message.answer("📝 Введіть тип пари (напр. *Лекція*) або `-`:", parse_mode="Markdown")


@router.message(ScheduleEdit.waiting_for_type)
async def sch_step_color(message: types.Message, state: FSMContext):
    val = message.text.strip()
    await state.update_data(selected_type=None if val == "-" else val)

    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🟢 Зелений", callback_data="sch_color_green"),
        types.InlineKeyboardButton(text="🔴 Червоний", callback_data="sch_color_red")
    )
    builder.row(types.InlineKeyboardButton(text="⚪️ Звичайний", callback_data="sch_color_common"))

    await state.set_state(ScheduleEdit.waiting_for_color)
    await message.answer("🎨 Оберіть тип тижня для цього предмета:", reply_markup=builder.as_markup())


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
        f"🎨 Тиждень: {COLOR_MAP[color]}"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Так", callback_data="sch_save")
    builder.button(text="❌ Скасувати", callback_data="sch_cancel")
    await callback.message.edit_text(summary, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.callback_query(F.data == "sch_save")
async def sch_save_db(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """
    Збереження з урахуванням кольору тижня.
    Якщо для цього кольору вже є пара — вона оновиться.
    Якщо немає — створиться нова, не зачіпаючи інший колір.
    """
    data = await state.get_data()

    # Шукаємо пару саме для цього дня, номера ТА ТИПУ ТИЖНЯ
    stmt = select(Lesson).where(
        Lesson.day_of_week == data['edit_day'],
        Lesson.lesson_number == data['edit_num'],
        Lesson.week_type == data['selected_color']
    )
    lesson = (await session.execute(stmt)).scalar_one_or_none()

    if not lesson:
        lesson = Lesson(
            day_of_week=data['edit_day'],
            lesson_number=data['edit_num'],
            week_type=data['selected_color']
        )
        session.add(lesson)

    lesson.subject_id = data['selected_subject_id']
    lesson.lesson_type = data['selected_type']

    await session.commit()
    await state.clear()
    await callback.message.delete()
    await return_to_schedule(callback, data['edit_day'], session)


# ==========================================================================================
# ВИДАЛЕННЯ
# ==========================================================================================

@router.callback_query(F.data == "sch_quick_delete")
async def sch_del_confirm(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Повне очищення слоту (видалення і червоної, і зеленої пари)"""
    data = await state.get_data()
    day_en = data['edit_day']

    stmt = delete(Lesson).where(
        Lesson.day_of_week == day_en,
        Lesson.lesson_number == data['edit_num']
    )
    await session.execute(stmt)
    await session.commit()

    await state.clear()
    await callback.answer("🗑 Слот повністю очищено")
    await callback.message.delete()
    await return_to_schedule(callback, day_en, session)


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
# ЗАМІНИ (ЛОГІКА ЗАЛИШАЄТЬСЯ БЕЗ ЗМІН, БО ПРАЦЮЄ З КОНКРЕТНОЮ ДАТОЮ)
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


# --- ПЕРЕГЛЯД ЗАМІН (СПРОЩЕНО) ---
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



# from aiogram import Router, F, types
# from aiogram.fsm.context import FSMContext
# from sqlalchemy import select, insert
# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy.orm import selectinload
# from aiogram.utils.keyboard import InlineKeyboardBuilder
# from datetime import datetime
#
# from db.models import Lesson, Subject, User, UserRole, ScheduleChange
# from keyboards.reply import delete_prev_message
# from keyboards.schedule_kb import get_schedule_reply_kb
# from utils.states import ScheduleEdit
#
#
# router = Router()
#
# # ==========================================================================================
# # КОНСТАНТИ ТА СЛОВНИКИ ПЕРЕКЛАДУ
# # ==========================================================================================
#
# DAYS_MAP = {
#     "Понеділок": "Monday",
#     "Вівторок": "Tuesday",
#     "Середа": "Wednesday",
#     "Четвер": "Thursday",
#     "П'ятниця": "Friday"
# }
#
# EN_TO_UA_DAYS = {
#             "Monday": "Понеділок",
#             "Tuesday": "Вівторок",
#             "Wednesday": "Середа",
#             "Thursday": "Четвер",
#             "Friday": "П'ятниця",
#             "Saturday": "Субота",
#             "Sunday": "Неділя"
#         }
#
# REVERSE_DAYS_MAP = {v: k for k, v in DAYS_MAP.items()}
#
# COLOR_MAP = {
#     "green": "🟢 Зелений",
#     "red": "🔴 Червоний",
#     "common": "⚪️ Звичайний"
# }
#
#
# # ==========================================================================================
# # ЛОГІКА ВІДОБРАЖЕННЯ (RENDER)
# # ==========================================================================================
#
# async def render_day_schedule(event: types.Message | types.CallbackQuery, day_ua: str, session: AsyncSession,
#                               user_id: int):
#     """
#     Універсальна функція для формування та відправки тексту розкладу.
#     Вирішує проблему Frozen Instance, не змінюючи атрибути message.text.
#     """
#     day_en = DAYS_MAP[day_ua]
#
#     # Отримуємо уроки дня
#     stmt = (
#         select(Lesson)
#         .where(Lesson.day_of_week == day_en)
#         .options(selectinload(Lesson.subject))
#         .order_by(Lesson.lesson_number)
#     )
#     lessons = (await session.execute(stmt)).scalars().all()
#     schedule_dict = {l.lesson_number: l for l in lessons}
#
#     text = f"📅 **Розклад на {day_ua}**\n"
#     text += "━━━━━━━━━━━━━━━\n\n"
#
#     for i in range(1, 7):
#         lesson = schedule_dict.get(i)
#         text += f"*{i} пара:* "
#
#         if not lesson or not lesson.subject:
#             text += "_відсутня_\n\n"
#             continue
#
#         subj = lesson.subject
#         color_tag = " 🟢" if lesson.week_type == "green" else " 🔴" if lesson.week_type == "red" else ""
#
#         text += f"**{subj.name}** ({lesson.lesson_type or '---'}){color_tag}\n"
#         text += f"👨‍🏫 Викладач: {subj.teacher_name or 'Не вказано'}\n"
#
#         if subj.zoom_link:
#             text += f"🔗 [Приєднатися]({subj.zoom_link})\n"
#             if subj.zoom_id: text += f"🆔 ID: `{subj.zoom_id}` "
#             if subj.zoom_password: text += f"🔑 Код: `{subj.zoom_password}`"
#             text += "\n"
#         text += "\n"
#
#     # Перевірка прав для кнопок редагування
#     user_stmt = (
#         select(User)
#         .where(User.user_id == user_id)
#         .options(selectinload(User.roles).selectinload(UserRole.role))
#     )
#     user = (await session.execute(user_stmt)).scalar_one()
#     user_roles = [r.role.name for r in user.roles]
#
#     kb = None
#     privileged_roles = {"admin", "rector", "headman", "head"}
#     if any(role in privileged_roles for role in user_roles):
#         builder = InlineKeyboardBuilder()
#         for i in range(1, 7):
#             builder.button(text=f"⚙️ {i} пара", callback_data=f"sch_edit_{day_en}_{i}")
#         builder.adjust(3, 3)
#         kb = builder.as_markup()
#
#     # Відправка результату
#     if isinstance(event, types.Message):
#         await event.answer(text, reply_markup=kb, parse_mode="Markdown", disable_web_page_preview=True)
#     else:
#         await event.message.answer(text, reply_markup=kb, parse_mode="Markdown", disable_web_page_preview=True)
#
#
# async def return_to_schedule(event: types.CallbackQuery | types.Message, day_en: str, session: AsyncSession):
#     """Допоміжна функція для швидкого повернення до розкладу"""
#     day_ua = REVERSE_DAYS_MAP.get(day_en)
#     user_id = event.from_user.id
#     await render_day_schedule(event, day_ua, session, user_id)
#
#
# # ==========================================================================================
# # ХЕНДЛЕРИ ПЕРЕГЛЯДУ
# # ==========================================================================================
#
# @router.message(F.text == "📅 Розклад занять")
# async def cmd_schedule_menu(message: types.Message):
#     await delete_prev_message(message)
#     await message.answer(
#         "Оберіть день тижня для перегляду розкладу:",
#         reply_markup=get_schedule_reply_kb()
#     )
#
#
# @router.message(F.text.in_(DAYS_MAP.keys()))
# async def show_day_schedule(message: types.Message, session: AsyncSession):
#     """Хендлер для текстових кнопок днів тижня"""
#     await render_day_schedule(message, message.text, session, message.from_user.id)
#
#
# # ==========================================================================================
# # ХЕНДЛЕРИ РЕДАГУВАННЯ
# # ==========================================================================================
#
# @router.callback_query(F.data.startswith("sch_edit_"))
# async def start_sch_edit(callback: types.CallbackQuery, state: FSMContext):
#     data = callback.data.split("_")
#     day_en, lesson_num = data[2], int(data[3])
#     await state.update_data(edit_day=day_en, edit_num=lesson_num)
#
#     builder = InlineKeyboardBuilder()
#     builder.row(types.InlineKeyboardButton(text="📚 Обрати предмет", callback_data="sch_step_subject"))
#     builder.row(types.InlineKeyboardButton(text="🗑 Видалити з розкладу", callback_data="sch_quick_delete"))
#     builder.row(
#         types.InlineKeyboardButton(text="📅 Зміна розкладу", callback_data="back_to_main_schedule"),
#         types.InlineKeyboardButton(text="⬅️ Назад до дня", callback_data=f"back_to_day_{day_en}")
#     )
#
#     day_ua = REVERSE_DAYS_MAP.get(day_en, day_en)
#     await callback.message.edit_text(
#         f"🛠 **Редагування: {day_ua}, {lesson_num} пара**",
#         reply_markup=builder.as_markup()
#     )
#
#
# @router.callback_query(F.data == "sch_step_subject")
# async def sch_step_subject(callback: types.CallbackQuery, session: AsyncSession, state: FSMContext):
#     subjects = (await session.execute(select(Subject))).scalars().all()
#     builder = InlineKeyboardBuilder()
#     for s in subjects:
#         builder.button(text=s.name, callback_data=f"sch_subj_set_{s.id}")
#     builder.button(text="🚫 Скасувати", callback_data="sch_cancel")
#     builder.adjust(1)
#     await state.set_state(ScheduleEdit.waiting_for_subject)
#     await callback.message.edit_text("🎯 Оберіть предмет із бази:", reply_markup=builder.as_markup())
#
#
# @router.callback_query(F.data.startswith("sch_subj_set_"), ScheduleEdit.waiting_for_subject)
# async def sch_step_type(callback: types.CallbackQuery, state: FSMContext):
#     subject_id = int(callback.data.split("_")[3])
#     await state.update_data(selected_subject_id=subject_id)
#     await state.set_state(ScheduleEdit.waiting_for_type)
#     await callback.message.delete()
#     await callback.message.answer("📝 Введіть тип пари (напр. *Лекція*) або `-`:", parse_mode="Markdown")
#
#
# @router.message(ScheduleEdit.waiting_for_type)
# async def sch_step_color(message: types.Message, state: FSMContext):
#     val = message.text.strip()
#     await state.update_data(selected_type=None if val == "-" else val)
#     builder = InlineKeyboardBuilder()
#     builder.row(
#         types.InlineKeyboardButton(text="🟢 Зелений", callback_data="sch_color_green"),
#         types.InlineKeyboardButton(text="🔴 Червоний", callback_data="sch_color_red")
#     )
#     builder.row(types.InlineKeyboardButton(text="⚪️ Звичайний", callback_data="sch_color_common"))
#     await state.set_state(ScheduleEdit.waiting_for_color)
#     await message.answer("🎨 Оберіть колір тижня:", reply_markup=builder.as_markup())
#
#
# @router.callback_query(F.data.startswith("sch_color_"), ScheduleEdit.waiting_for_color)
# async def sch_final_confirm(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
#     color = callback.data.split("_")[2]
#     await state.update_data(selected_color=color)
#     data = await state.get_data()
#
#     res = await session.execute(select(Subject).where(Subject.id == data['selected_subject_id']))
#     subject_obj = res.scalar_one_or_none()
#     subj_name = f"{subject_obj.name} ({subject_obj.teacher_name})" if subject_obj else "???"
#
#     summary = (
#         f"📝 **Зберегти зміни?**\n\n"
#         f"📅 День: {REVERSE_DAYS_MAP.get(data['edit_day'])}\n"
#         f"🔢 Пара: {data['edit_num']}\n"
#         f"📚 Предмет: {subj_name}\n"
#         f"📝 Тип: {data['selected_type'] or '---'}\n"
#         f"🎨 Тиждень: {COLOR_MAP.get(color)}"
#     )
#     builder = InlineKeyboardBuilder()
#     builder.button(text="✅ Так", callback_data="sch_save")
#     builder.button(text="❌ Скасувати", callback_data="sch_cancel")
#     await callback.message.edit_text(summary, reply_markup=builder.as_markup(), parse_mode="Markdown")
#
#
# @router.callback_query(F.data == "sch_save")
# async def sch_save_db(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
#     data = await state.get_data()
#     day_en = data['edit_day']
#
#     stmt = select(Lesson).where(Lesson.day_of_week == day_en, Lesson.lesson_number == data['edit_num'])
#     lesson = (await session.execute(stmt)).scalar_one_or_none()
#
#     if not lesson:
#         lesson = Lesson(day_of_week=day_en, lesson_number=data['edit_num'])
#         session.add(lesson)
#
#     lesson.subject_id = data['selected_subject_id']
#     lesson.lesson_type = data['selected_type']
#     lesson.week_type = data['selected_color']
#
#     await session.commit()
#     await state.clear()
#     await callback.answer("✅ Збережено")
#     await callback.message.delete()
#     await return_to_schedule(callback, day_en, session)
#
#
# # ==========================================================================================
# # ВИДАЛЕННЯ ТА СКАСУВАННЯ
# # ==========================================================================================
#
# @router.callback_query(F.data == "sch_quick_delete")
# async def sch_quick_delete(callback: types.CallbackQuery, state: FSMContext):
#     data = await state.get_data()
#     builder = InlineKeyboardBuilder()
#     builder.button(text="✅ Видалити", callback_data="sch_del_confirm")
#     builder.button(text="🔙 Назад", callback_data="sch_cancel")
#     await callback.message.edit_text(f"❓ Видалити {data['edit_num']} пару?", reply_markup=builder.as_markup())
#
#
# @router.callback_query(F.data == "sch_del_confirm")
# async def sch_del_confirm(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
#     data = await state.get_data()
#     day_en = data['edit_day']
#     stmt = select(Lesson).where(Lesson.day_of_week == day_en, Lesson.lesson_number == data['edit_num'])
#     lesson = (await session.execute(stmt)).scalar_one_or_none()
#     if lesson:
#         await session.delete(lesson)
#         await session.commit()
#     await state.clear()
#     await callback.answer("🗑 Видалено")
#     await callback.message.delete()
#     await return_to_schedule(callback, day_en, session)
#
#
# @router.callback_query(F.data == "sch_cancel")
# async def sch_cancel(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
#     data = await state.get_data()
#     day_en = data.get('edit_day')
#     await state.clear()
#     await callback.message.delete()
#     if day_en:
#         await return_to_schedule(callback, day_en, session)
#
#
# # Хендлер для кнопки "⬅️ Назад до дня"
# @router.callback_query(F.data.startswith("back_to_day_"))
# async def back_to_day_handler(callback: types.CallbackQuery, session: AsyncSession, state: FSMContext):
#     day_en = callback.data.split("_")[3]
#     await state.clear()  # Очищуємо стан редагування
#     await callback.message.delete()  # Видаляємо меню редагування
#
#     # Повертаємо розклад дня через нашу універсальну функцію
#     await return_to_schedule(callback, day_en, session)
#
#
# # ==========================================================================================
# # Зміна розкладу
# # ==========================================================================================
#
# # Хендлер для кнопки "📅 Зміна розкладу" (повернення до списку днів)
# # @router.callback_query(F.data == "back_to_main_schedule")
# # async def back_to_main_menu_handler(callback: types.CallbackQuery, state: FSMContext):
# #     await state.clear()
# #     await callback.message.delete()
# #
# #     # Викликаємо головне меню вибору днів
# #     await cmd_schedule_menu(callback.message)
# #     await callback.answer()
#
#
# # --- КРОК 1: ВИБІР ПРЕДМЕТА ДЛЯ ЗАМІНИ ---
# @router.callback_query(F.data == "back_to_main_schedule")
# async def start_schedule_substitution(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
#     subjects = (await session.execute(select(Subject))).scalars().all()
#
#     builder = InlineKeyboardBuilder()
#     for s in subjects:
#         builder.button(text=s.name, callback_data=f"subj_sub_{s.id}")
#
#     builder.row(types.InlineKeyboardButton(text="❌ Скасувати", callback_data="sch_cancel"))
#     builder.adjust(1)
#
#     await state.set_state(ScheduleEdit.waiting_for_subject)  # Використовуємо існуючий або новий клас станів
#     await callback.message.edit_text(
#         "🔄 **Створення заміни на дату**\n\nОберіть предмет, який буде на заміні:",
#         reply_markup=builder.as_markup()
#     )
#
#
# # --- КРОК 2: ВВЕДЕННЯ ДАТИ ---
# @router.callback_query(F.data.startswith("subj_sub_"))
# async def sub_step_date(callback: types.CallbackQuery, state: FSMContext):
#     subj_id = int(callback.data.split("_")[2])
#     await state.update_data(sub_subject_id=subj_id)
#
#     await state.set_state(ScheduleEdit.subj_waiting_for_type)  # Тимчасово перевикористаємо стан для вводу дати
#     await callback.message.edit_text(
#         "📅 **Введіть дату заміни**\n\nФормат: `ДД.ММ.РРРР` (наприклад: `25.02.2026`)\n\n"
#         "Бот перевірить, чи збігається дата з обраним днем тижня.",
#         parse_mode="Markdown"
#     )
#
#
# # --- КРОК 3: ВАЛІДАЦІЯ ДАТИ ТА ПІДТВЕРДЖЕННЯ ---
# @router.message(ScheduleEdit.subj_waiting_for_type)  # Або створіть окремий стан
# async def sub_process_date(message: types.Message, state: FSMContext, session: AsyncSession):
#     data = await state.get_data()
#     target_day_en = data.get('edit_day')  # Напр. "Monday"
#     input_text = message.text.strip()
#
#     try:
#         # 1. Спроба розпарсити дату
#         input_date = datetime.strptime(input_text, "%d.%m.%Y").date()
#
#         # 2. Отримуємо день тижня з введеної дати (Monday, Tuesday...)
#         actual_day_en = input_date.strftime("%A")
#
#         # 3. ПЕРЕВІРКА: чи ввів користувач дату, що відповідає обраному дню в розкладі
#         if actual_day_en != target_day_en:
#             day_ua_needed = REVERSE_DAYS_MAP.get(target_day_en)
#             # Отримуємо українську назву для введеного (помилкового) дня
#             actual_day_ua = EN_TO_UA_DAYS.get(actual_day_en, actual_day_en)
#
#             return await message.answer(
#                 f"❌ **Помилка дня тижня!**\n\n"
#                 f"Ви редагуєте слот для дня: **{day_ua_needed}**.\n"
#                 f"Введена дата ({input_text}) — це **{actual_day_ua}**.\n\n"
#                 f"Будь ласка, введіть дату, яка припадає на **{day_ua_needed.lower()}**:"
#             )
#
#         # 4. Формуємо підсумок
#         subj_res = await session.execute(select(Subject).where(Subject.id == data['sub_subject_id']))
#         subject = subj_res.scalar_one()
#
#         await state.update_data(sub_date=input_date)
#
#         builder = InlineKeyboardBuilder()
#         builder.row(
#             types.InlineKeyboardButton(text="✅ Підтвердити", callback_data="subjective_save_confirm"),
#             types.InlineKeyboardButton(text="❌ Скасувати", callback_data="sch_cancel")
#         )
#
#         await message.answer(
#              f"📝 **Підтвердження заміни:**\n\n"
#              f"📅 Дата: **{input_text}** ({REVERSE_DAYS_MAP[target_day_en]})\n"
#              f"🔢 Пара: **{data['edit_num']}**\n"
#              f"📚 Предмет: **{subject.name}**\n\n"
#              "Додати цю заміну в базу?",
#              reply_markup=builder.as_markup()
#         )
#
#     except ValueError:
#         await message.answer("❌ **Невірний формат!**\nВведіть дату як `ДД.ММ.РРРР` (напр. 25.02.2026)")
#
#
# # --- КРОК 4: ЗАПИС У БАЗУ ---
# @router.callback_query(F.data == "subjective_save_confirm")
# async def sub_save_to_db(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
#     data = await state.get_data()
#
#     try:
#         new_change = ScheduleChange(
#             change_date=data['sub_date'],
#             pair_number=data['edit_num'],
#             new_subject_id=data['sub_subject_id'],
#             weekday=data['sub_date'].weekday()  # Додаємо, щоб уникнути помилки NOT NULL
#         )
#
#         session.add(new_change)
#         await session.commit()
#
#         await callback.answer("✅ Заміну додано!", show_alert=True)
#
#         day_en = data['edit_day']
#         await state.clear()
#         await callback.message.delete()
#         await return_to_schedule(callback, day_en, session)
#
#     except Exception as e:
#         await session.rollback()
#         await callback.message.answer(f"❌ Помилка при збереженні: {e}")
#
#
# from datetime import date
# from sqlalchemy import delete
#
#
# # --- ПЕРЕГЛЯД УСІХ ЗАМІН ---
# @router.message(F.text == "Зміни у розкладу")
# async def show_all_substitutions(message: types.Message, session: AsyncSession):
#     await delete_prev_message(message)
#
#     # Отримуємо заміни від сьогодні
#     today = date.today()
#     stmt = (
#         select(ScheduleChange)
#         .where(ScheduleChange.change_date >= today)
#         .options(selectinload(ScheduleChange.new_subject))
#         .order_by(ScheduleChange.change_date, ScheduleChange.pair_number)
#     )
#     result = await session.execute(stmt)
#     changes = result.scalars().all()
#
#     if not changes:
#         return await message.answer("📭 Наразі немає запланованих замін у розкладі.")
#
#     await message.answer("🔄 **Список активних замін:**")
#
#     for change in changes:
#         day_ua = EN_TO_UA_DAYS.get(change.change_date.strftime("%A"), "---")
#         date_str = change.change_date.strftime("%d.%m.%Y")
#
#         text = (
#             f"📅 **{date_str} ({day_ua})**\n"
#             f"🔢 Пара №{change.pair_number}\n"
#             f"📚 Предмет: **{change.new_subject.name}**\n"
#             f"👨‍🏫 Викладач: {change.new_subject.teacher_name or 'Не вказано'}"
#         )
#
#         builder = InlineKeyboardBuilder()
#         builder.button(text="🗑 Видалити заміну", callback_data=f"del_sub_ask_{change.id}")
#
#         await message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
#
#
# # --- ПІДТВЕРДЖЕННЯ ВИДАЛЕННЯ ---
# @router.callback_query(F.data.startswith("del_sub_ask_"))
# async def ask_delete_substitution(callback: types.CallbackQuery):
#     change_id = callback.data.split("_")[3]
#
#     builder = InlineKeyboardBuilder()
#     builder.row(
#         types.InlineKeyboardButton(text="✅ Так, видалити", callback_data=f"del_sub_conf_{change_id}"),
#         types.InlineKeyboardButton(text="❌ Скасувати", callback_data="del_sub_cancel")
#     )
#
#     await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
#     await callback.answer("Ви впевнені?")
#
#
# # --- ВИКОНАННЯ ВИДАЛЕННЯ ---
# @router.callback_query(F.data.startswith("del_sub_conf_"))
# async def confirm_delete_substitution(callback: types.CallbackQuery, session: AsyncSession):
#     change_id = int(callback.data.split("_")[3])
#
#     stmt = delete(ScheduleChange).where(ScheduleChange.id == change_id)
#     await session.execute(stmt)
#     await session.commit()
#
#     await callback.answer("🗑 Заміну видалено", show_alert=True)
#     await callback.message.delete()
#
#
# # --- СКАСУВАННЯ ВИДАЛЕННЯ ---
# @router.callback_query(F.data == "del_sub_cancel")
# async def cancel_delete_substitution(callback: types.CallbackQuery):
#     # Повертаємо кнопку "Видалити" назад
#     change_id = callback.message.reply_markup.inline_keyboard[0][0].callback_data.split("_")[3]
#
#     builder = InlineKeyboardBuilder()
#     builder.button(text="🗑 Видалити заміну", callback_data=f"del_sub_ask_{change_id}")
#
#     await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
#     await callback.answer("Скасовано")