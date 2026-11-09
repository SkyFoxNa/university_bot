import logging
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from aiogram import Bot
from db.models import User, Role, Lesson, ScheduleChange, ScheduleTime, WeekType, Subject

COLOR_TO_EMOJI = {
    "green": "🟢 (зелений)",
    "red": "🔴 (червоний)",
    "common": "⚪️ (загальний)"
}

SUBGROUP_MAP = {
    "all": "👥 Вся група",
    "sub1": "1️⃣ 1 підгрупа",
    "sub2": "2️⃣ 2 підгрупа"
}

EN_TO_UA_DAYS = {
    "Monday": "Понеділок", "Tuesday": "Вівторок", "Wednesday": "Середа",
    "Thursday": "Четвер", "Friday": "П'ятниця", "Saturday": "Субота", "Sunday": "Неділя"
}


def get_teacher_display_name(subj: Subject) -> str:
    if subj.teacher_user:
        name = subj.teacher_user.user_name
        surname = subj.teacher_user.user_surname or ""
        return f"{name} {surname}".strip()
    return subj.teacher_name or "Не призначено"


async def get_daily_data(session, target_date: date):
    week_res = await session.execute(select(WeekType).where(WeekType.is_active == True))
    week_color_obj = week_res.scalar_one_or_none()
    active_color = week_color_obj.name if week_color_obj else "common"

    # Отримуємо сітку дзвінків, відсортовану за часом початку
    times_res = await session.execute(select(ScheduleTime).order_by(ScheduleTime.start_time_1))
    times = times_res.scalars().all()

    day_name_en = target_date.strftime("%A")

    lessons_res = await session.execute(
        select(Lesson).where(
            Lesson.day_of_week == day_name_en,
            Lesson.week_type.in_([active_color, "common"])
        ).options(selectinload(Lesson.subject).selectinload(Subject.teacher_user))
        .order_by(Lesson.lesson_number)
    )

    lessons_map = {}
    for l in lessons_res.scalars().all():
        if l.lesson_number not in lessons_map:
            lessons_map[l.lesson_number] = []
        lessons_map[l.lesson_number].append(l)

    changes_res = await session.execute(
        select(ScheduleChange).where(ScheduleChange.change_date == target_date)
        .options(selectinload(ScheduleChange.new_subject).selectinload(Subject.teacher_user))
    )
    changes_map = {c.pair_number: c for c in changes_res.scalars().all()}

    return times, lessons_map, changes_map, active_color


async def get_today_schedule_text(session, target_date: date) -> str:
    """Формує гарний текст розкладу на день з урахуванням часу великих перерв та підгруп"""
    times, lessons_map, changes_map, color = await get_daily_data(session, target_date)
    day_name_ua = EN_TO_UA_DAYS.get(target_date.strftime("%A"), "")

    color_display = COLOR_TO_EMOJI.get(color, f"({color})")
    group_text = f"☀️ **Розклад на сьогодні — {day_name_ua}** {color_display}\n\n"

    for t in times:
        # --- ВЕЛИКА ПЕРЕРВА НА СВОЄМУ МІСЦІ ЗА ЧАСОМ ---
        if t.pair_number is None or getattr(t, 'is_big_break', False):
            group_text += f"🍎 **Велика перерва**\n"
            # ВИПРАВЛЕНО ТУТ: додано правильні бектіки навколо всього діапазону часу
            group_text += f"⏱️ `{t.start_time_1} – {t.end_time_2}`\n"
            group_text += "— — — — — — — — —\n"
            continue

        pair_num = t.pair_number
        group_text += f"📌 **{pair_num} пара:**\n"

        # Перевірка на заміну або звичайні заняття (підгрупи)
        if pair_num in changes_map:
            change = changes_map[pair_num]
            subj = change.new_subject
            lecturer = get_teacher_display_name(subj)
            group_text += f"  🔄 **[ЗАМІНА]** {subj.name}\n"
            group_text += f"  👨‍🏫 {lecturer}\n"
            if subj.zoom_link:
                group_text += f"  🔗 [Zoom]({subj.zoom_link}) "
                if subj.zoom_id: group_text += f"🆔 `{subj.zoom_id}`"
                group_text += "\n"
        elif pair_num in lessons_map:
            for lesson in lessons_map[pair_num]:
                subj = lesson.subject
                sub_label = f" [{SUBGROUP_MAP.get(lesson.subgroup, '')}]" if lesson.subgroup != "all" else ""
                type_str = f" ({lesson.lesson_type})" if lesson.lesson_type else ""
                lecturer = get_teacher_display_name(subj)

                group_text += f"  • **{subj.name}**{type_str}\n"
                group_text += f"  {sub_label}\n"
                group_text += f"    👨‍🏫 {lecturer}\n"
                if subj.zoom_link:
                    group_text += f"    🔗 [Zoom]({subj.zoom_link}) "
                    if subj.zoom_id: group_text += f"🆔 `{subj.zoom_id}`"
                    group_text += "\n"
        else:
            group_text += "  _відсутня_\n"

        group_text += f"  ⏱️ `{t.start_time_1} – {t.end_time_2}`\n"
        group_text += "— — — — — — — — —\n"

    return group_text
