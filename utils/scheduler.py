import logging
import pytz
import aiohttp
import pandas as pd
import io
import re
from datetime import datetime, date
from sqlalchemy import select, func, update
from sqlalchemy.orm import selectinload
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot

from db.models import User, Role, Lesson, ScheduleChange, ScheduleTime, WeekType, Subject
from handlers.settings import broadcast_week_change

# --- НАЛАШТУВАННЯ ТА КОНСТАНТИ ---

UA_TZ = pytz.timezone("Europe/Kyiv")

COLOR_TO_EMOJI = {
    "green": "🟢 (зелений)",
    "red": "🔴 (червоний)",
    "common": "⚪️ (загальний)"
}

EN_TO_UA_DAYS = {
    "Monday": "Понеділок", "Tuesday": "Вівторок", "Wednesday": "Середа",
    "Thursday": "Четвер", "Friday": "П'ятниця", "Saturday": "Субота", "Sunday": "Неділя"
}

SUBGROUP_MAP = {
    "all": "👥 Вся група",
    "sub1": "1️⃣ 1 підгрупа",
    "sub2": "2️⃣ 2 підгрупа"
}

# URL Google Таблиці (експорт в XLSX)
GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1UKq4fqAUUostw9TKjzZcmv8Tl4gqgJc9KHorvUyzGKQ/export?format=xlsx"

HARD_REPLACEMENTS = {
    "твсгп": "технологія виробництва сільськогосподарської продукції",
}


# --- ДОПОМІЖНІ ФУНКЦІЇ ПАРСИНГУ ---

def normalize_name(name: str) -> str:
    if not name or str(name) == "nan": return ""
    name = str(name).strip().lower()
    if name in HARD_REPLACEMENTS:
        name = HARD_REPLACEMENTS[name]
    return re.sub(r'\s*\(.*\)\s*', '', name).strip()


async def get_remote_schedule_for_day(target_day_ua: str):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(GOOGLE_SHEET_URL) as resp:
                if resp.status != 200: return None
                data = await resp.read()

        df = pd.read_excel(io.BytesIO(data), header=None, engine='openpyxl')
        df = df.iloc[5:].reset_index(drop=True)

        day_results = []
        current_day = ""
        last_pair = None

        for _, row in df.iterrows():
            day_raw = str(row[1]).strip()
            if day_raw != "nan" and any(
                    d in day_raw for d in ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця"]):
                current_day = day_raw

            if current_day != target_day_ua: continue

            try:
                pair_num = int(float(str(row[2]).strip()))
                last_pair = pair_num
            except:
                pair_num = last_pair

            subject_name = str(row[3]).strip()
            if subject_name == "nan" or not subject_name: continue

            link = None
            for col in range(4, 8):
                cell = str(row[col]).strip()
                if "https:" in cell:
                    link = cell
                    break

            day_results.append({
                "pair": pair_num,
                "norm_name": normalize_name(subject_name),
                "link": link
            })
        return day_results
    except Exception as e:
        logging.error(f"❌ Помилка парсингу Google Sheets: {e}")
        return None


# --- ДОПОМІЖНІ ФУНКЦІЇ БД ---

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

    times_res = await session.execute(select(ScheduleTime).order_by(ScheduleTime.pair_number))
    times = times_res.scalars().all()

    day_name_en = target_date.strftime("%A")

    # Витягуємо всі уроки на день (усі підгрупи)
    lessons_res = await session.execute(
        select(Lesson).where(
            Lesson.day_of_week == day_name_en,
            Lesson.week_type.in_([active_color, "common"])
        ).options(selectinload(Lesson.subject).selectinload(Subject.teacher_user))
        .order_by(Lesson.lesson_number)
    )

    # Групуємо уроки у словник за номером пари: {1: [lesson1, lesson2], 2: [lesson3]}
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


# --- ГОЛОВНІ ЗАВДАННЯ ---

async def send_morning_schedule(bot: Bot, session_pool):
    """Ранкова розсилка з підтримкою підгруп"""
    async with session_pool() as session:
        today = datetime.now(UA_TZ).date()
        if today.weekday() > 4: return  # Вихідні

        times, lessons_map, changes_map, color = await get_daily_data(session, today)
        day_name_ua = EN_TO_UA_DAYS.get(today.strftime("%A"), "")

        color_display = COLOR_TO_EMOJI.get(color, f"({color})")
        group_text = f"☀️ **Розклад на сьогодні — {day_name_ua}** {color_display}\n\n"

        for t in times:
            if t.pair_number is None or getattr(t, 'is_big_break', False):
                group_text += f"🍎 **Велика перерва**\n⏱ `{t.start_time_1}` – `{t.end_time_2}`\n— — — — — — — — —\n"
                continue

            pair_num = t.pair_number
            group_text += f"📌 **{pair_num} пара:**\n"

            # Перевіряємо заміни для цієї пари
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
                # Виводимо всі заняття (підгрупи) для цієї пари
                for lesson in lessons_map[pair_num]:
                    subj = lesson.subject
                    sub_label = f" [{SUBGROUP_MAP.get(lesson.subgroup, '')}]" if lesson.subgroup != "all" else ""
                    type_str = f" ({lesson.lesson_type})" if lesson.lesson_type else ""
                    lecturer = get_teacher_display_name(subj)

                    group_text += f"  • **{subj.name}**{type_str}{sub_label}\n"
                    group_text += f"    👨‍🏫 {lecturer}\n"
                    if subj.zoom_link:
                        group_text += f"    🔗 [Zoom]({subj.zoom_link}) "
                        if subj.zoom_id: group_text += f"🆔 `{subj.zoom_id}`"
                        group_text += "\n"
            else:
                group_text += "  _відсутня_\n"

            group_text += f"  ⏱ `{t.start_time_1}` – `{t.end_time_2}`\n"
            group_text += "— — — — — — — — —\n"

        # Розсилка студентам та старостам
        users_res = await session.execute(
            select(User).join(User.roles).join(Role).where(Role.name.in_(["student", "headman"]))
        )
        for u in users_res.unique().scalars().all():
            try:
                await bot.send_message(u.user_id, group_text, parse_mode="Markdown", disable_web_page_preview=True)
            except:
                continue


async def check_and_notify(bot: Bot, session_pool):
    """Щохвилинна перевірка початку пар (з 08:00 по 20:00)"""
    now_ua = datetime.now(UA_TZ)

    if not (8 <= now_ua.hour < 20):
        return

    now_mins = now_ua.hour * 60 + now_ua.minute

    async with session_pool() as session:
        times, lessons_map, changes_map, _ = await get_daily_data(session, now_ua.date())

        for t in times:
            if not t.pair_number: continue
            pair_num = t.pair_number

            subjects_to_notify = []
            if pair_num in changes_map:
                subjects_to_notify.append(changes_map[pair_num].new_subject)
            elif pair_num in lessons_map:
                for lesson in lessons_map[pair_num]:
                    subjects_to_notify.append(lesson.subject)

            if not subjects_to_notify: continue

            if t.start_time_1:
                sh, sm = map(int, t.start_time_1.split(":"))
                if (sh * 60 + sm) - now_mins == 5:
                    for subj in subjects_to_notify:
                        lecturer = get_teacher_display_name(subj)

                        # ✨ Оновлене повідомлення з часом початку і кінця
                        msg = (f"🔔 **Нагадування: {pair_num} ПАРА**\n"
                               f"📚 **{subj.name}**\n"
                               f"👨‍🏫 Лектор: **{lecturer}**\n\n"
                               f"⏱️ Початок: `{t.start_time_1}`\n"
                               f"🏁 Кінець: `{t.end_time_2}`\n"
                               f"🔗 [Увійти в Zoom]({subj.zoom_link})\n"
                               f"🆔 `{subj.zoom_id or '-'}` | 🔑 `{subj.zoom_password or '-'}`")

                        std_res = await session.execute(
                            select(User).join(User.roles).join(Role).where(Role.name.in_(["student", "headman"])))
                        for u in std_res.unique().scalars().all():
                            try:
                                await bot.send_message(u.user_id, msg, parse_mode="Markdown",
                                                       disable_web_page_preview=True)
                            except:
                                continue


# --- Зміна кольору розкладу ---

async def auto_toggle_week(bot: Bot, session_pool):
    """Автоматичне перемикання кольору тижня (Понеділок 08:25)"""
    async with session_pool() as session:
        res = await session.execute(select(WeekType).where(WeekType.is_active == True))
        current = res.scalar_one_or_none()

        if not current:
            logging.error("Авто-перемикання: Активний тиждень не знайдено в БД!")
            return

        new_color = "red" if current.name == "green" else "green"

        await session.execute(update(WeekType).values(is_active=False))
        await session.execute(update(WeekType.where(WeekType.name == new_color).values(is_active=True)))
        await session.commit()

        logging.info(f"Автоматично змінено колір тижня на: {new_color}")
        await broadcast_week_change(bot, session, new_color)


# --- ІНІЦІАЛІЗАЦІЯ ---

def setup_scheduler(bot: Bot, session_pool):
    """Запуск шедулера з обмеженням часу моніторингу"""
    scheduler = AsyncIOScheduler(timezone=UA_TZ)

    # 1. Ранкова розсилка розкладу (щодня о 08:30)
    scheduler.add_job(send_morning_schedule, "cron", hour=8, minute=30, args=[bot, session_pool])

    # 2. Щохвилинний моніторинг (працюватиме щохвилини, але в середині функції стоїть перевірка годин 08:00–20:00)
    scheduler.add_job(check_and_notify, "interval", minutes=1, args=[bot, session_pool])

    # 3. АВТОМАТИЧНЕ ПЕРЕМИКАННЯ КОЛЬОРУ (щопонеділка о 08:25)
    scheduler.add_job(
        auto_toggle_week,
        "cron",
        day_of_week='mon',
        hour=8,
        minute=25,
        args=[bot, session_pool]
    )

    scheduler.start()
    logging.info("🚀 APScheduler успішно запущено (моніторинг активний з 08:00 по 20:00).")