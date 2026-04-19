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

# URL Google Таблиці (експорт в XLSX)
GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1UKq4fqAUUostw9TKjzZcmv8Tl4gqgJc9KHorvUyzGKQ/export?format=xlsx"

# Словник для нормалізації назв
HARD_REPLACEMENTS = {
    "твсгп": "технологія виробництва сільськогосподарської продукції",
}


# --- ДОПОМІЖНІ ФУНКЦІЇ ПАРСИНГУ ---

def normalize_name(name: str) -> str:
    """Приведення назви до єдиного формату для порівняння"""
    if not name or str(name) == "nan": return ""
    name = str(name).strip().lower()
    if name in HARD_REPLACEMENTS:
        name = HARD_REPLACEMENTS[name]
    # Видаляємо все в дужках (л), (пр) тощо
    return re.sub(r'\s*\(.*\)\s*', '', name).strip()


async def get_remote_schedule_for_day(target_day_ua: str):
    """Завантаження та парсинг таблиці на конкретний день"""
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
    lessons_res = await session.execute(
        select(Lesson).where(
            Lesson.day_of_week == day_name_en,
            Lesson.week_type.in_([active_color, "common"])
        ).options(selectinload(Lesson.subject).selectinload(Subject.teacher_user))
    )
    lessons_map = {l.lesson_number: l for l in lessons_res.scalars().all()}

    changes_res = await session.execute(
        select(ScheduleChange).where(ScheduleChange.change_date == target_date)
        .options(selectinload(ScheduleChange.new_subject).selectinload(Subject.teacher_user))
    )
    changes_map = {c.pair_number: c for c in changes_res.scalars().all()}

    return times, lessons_map, changes_map, active_color


# --- ГОЛОВНІ ЗАВДАННЯ ---

async def send_morning_schedule(bot: Bot, session_pool):
    """Ранкова розсилка з попередньою перевіркою Google Таблиці"""
    async with session_pool() as session:
        today = datetime.now(UA_TZ).date()
        if today.weekday() > 4: return  # Вихідні

        times, lessons, changes, color = await get_daily_data(session, today)
        day_name_ua = EN_TO_UA_DAYS.get(today.strftime("%A"), "")

        # 1. СИНХРОНІЗАЦІЯ З GOOGLE SHEETS
        remote_data = await get_remote_schedule_for_day(day_name_ua)
        updates_log = []

        if remote_data:
            for item in remote_data:
                pair_num = item['pair']
                current_lesson = changes.get(pair_num) or lessons.get(pair_num)

                if current_lesson and item['link']:
                    subj = current_lesson.new_subject if hasattr(current_lesson,
                                                                 'new_subject') else current_lesson.subject

                    if normalize_name(subj.name) == item['norm_name']:
                        if subj.zoom_link != item['link']:
                            old_link = subj.zoom_link
                            await session.execute(
                                update(Subject).where(Subject.id == subj.id).values(zoom_link=item['link'])
                            )
                            updates_log.append({
                                "pair": pair_num,
                                "subj": subj.name,
                                "old": old_link,
                                "new": item['link']
                            })
            await session.commit()

        # 2. ФОРМУВАННЯ ПОВІДОМЛЕННЯ
        color_display = COLOR_TO_EMOJI.get(color, f"({color})")
        group_text = f"☀️ **Розклад на сьогодні — {day_name_ua}** {color_display}\n\n"

        for t in times:
            if t.pair_number is None or getattr(t, 'is_big_break', False):
                group_text += f"🍎 **Велика перерва**\n⏱ `{t.start_time_1}` – `{t.end_time_2}`\n— — — — — — — — —\n"
                continue

            subj = None
            prefix = ""
            if t.pair_number in changes:
                subj = changes[t.pair_number].new_subject
                prefix = "🔄 [ЗАМІНА] "
            elif t.pair_number in lessons:
                subj = lessons[t.pair_number].subject

            if subj:
                lecturer = get_teacher_display_name(subj)
                group_text += f"📌 **{t.pair_number} пара:** {prefix}{subj.name}\n"
                group_text += f"👨‍🏫 Викладач: {lecturer}\n"
                group_text += f"⏱ `{t.start_time_1}` – `{t.end_time_2}`\n"
            else:
                group_text += f"❌ **{t.pair_number} пара:** Відсутня\n"
            group_text += "— — — — — — — — —\n"

        # Додаємо інформацію про оновлені лінки
        if updates_log:
            group_text += "\n⚠️ **Увага! Змінено посилання:**\n"
            for upd in updates_log:
                group_text += f"• {upd['pair']} пара: [НОВЕ]({upd['new']}) (було: {upd['old'] if upd['old'] else '—'})\n"

        # 3. РОЗСИЛКА СТУДЕНТАМ
        users_res = await session.execute(
            select(User).join(User.roles).join(Role).where(Role.name.in_(["student", "headman"]))
        )
        for u in users_res.unique().scalars().all():
            try:
                await bot.send_message(u.user_id, group_text, parse_mode="Markdown", disable_web_page_preview=True)
            except:
                continue


async def check_and_notify(bot: Bot, session_pool):
    """Щохвилинна перевірка початку пар"""
    now_ua = datetime.now(UA_TZ)
    now_mins = now_ua.hour * 60 + now_ua.minute

    async with session_pool() as session:
        times, lessons, changes, _ = await get_daily_data(session, now_ua.date())

        for t in times:
            if not t.pair_number: continue
            subj = changes[t.pair_number].new_subject if t.pair_number in changes else (
                lessons[t.pair_number].subject if t.pair_number in lessons else None)

            if not subj: continue

            if t.start_time_1:
                sh, sm = map(int, t.start_time_1.split(":"))
                if (sh * 60 + sm) - now_mins == 5:
                    lecturer = get_teacher_display_name(subj)
                    msg = (f"🔔 **{t.pair_number} ПАРА: {subj.name}**\n"
                           f"👨‍🏫 Лектор: **{lecturer}**\n\n"
                           f"⏱ Початок: `{t.start_time_1}`\n"
                           f"🔗 [Увійти в Zoom]({subj.zoom_link})\n"
                           f"🆔 `{subj.zoom_id or '-'}` | 🔑 `{subj.zoom_password or '-'}`")

                    # Універсальна розсилка
                    std_res = await session.execute(
                        select(User).join(User.roles).join(Role).where(Role.name.in_(["student", "headman"])))
                    for u in std_res.unique().scalars().all():
                        try:
                            await bot.send_message(u.user_id, msg, parse_mode="Markdown", disable_web_page_preview=True)
                        except:
                            continue


# --- Зміна кольору розкладу ---

async def auto_toggle_week(bot: Bot, session_pool):
    """Автоматичне перемикання кольору тижня (Понеділок 08:25)"""
    async with session_pool() as session:
        # 1. Отримуємо поточний активний колір
        res = await session.execute(select(WeekType).where(WeekType.is_active == True))
        current = res.scalar_one_or_none()

        if not current:
            logging.error("Авто-перемикання: Активний тиждень не знайдено в БД!")
            return

        # 2. Визначаємо новий колір
        new_color = "red" if current.name == "green" else "green"

        # 3. Оновлюємо БД
        await session.execute(update(WeekType).values(is_active=False))
        await session.execute(update(WeekType).where(WeekType.name == new_color).values(is_active=True))
        await session.commit()

        logging.info(f"Автоматично змінено колір тижня на: {new_color}")

        # 4. Викликаємо масову розсилку (ту саму, що використовується при ручному перемиканні)
        # Примітка: Функція broadcast_week_change має бути доступна для імпорту
        from handlers.settings import broadcast_week_change
        await broadcast_week_change(bot, session, new_color)


# def setup_scheduler(bot: Bot, session_pool):
#     scheduler = AsyncIOScheduler(timezone=UA_TZ)
#     scheduler.add_job(send_morning_schedule, "cron", hour=8, minute=30, args=[bot, session_pool])
#     scheduler.add_job(check_and_notify, "interval", minutes=1, args=[bot, session_pool])
#     scheduler.add_job(auto_toggle_week, "cron", day_of_week='mon', hour=8, minute=25, args=[bot, session_pool])
#     scheduler.start()
#     logging.info("🚀 APScheduler запущено.")
#

# --- ІНІЦІАЛІЗАЦІЯ ---

def setup_scheduler(bot: Bot, session_pool):
    """Запуск шедулера"""
    scheduler = AsyncIOScheduler(timezone=UA_TZ)

    # 1. Ранкова розсилка розкладу (щодня о 08:30)
    scheduler.add_job(send_morning_schedule, "cron", hour=8, minute=30, args=[bot, session_pool])

    # 2. Щохвилинний моніторинг (дзвінки, Zoom)
    scheduler.add_job(check_and_notify, "interval", minutes=1, args=[bot, session_pool])

    # 3. АВТОМАТИЧНЕ ПЕРЕМИКАННЯ КОЛЬОРУ (щопонеділка о 08:25)
    # day_of_week=0 означає понеділок (або 'mon')
    scheduler.add_job(
        auto_toggle_week,
        "cron",
        day_of_week='mon',
        hour=8,
        minute=25,
        args=[bot, session_pool]
    )

    scheduler.start()
    logging.info("APScheduler успішно запущено для часового поясу Europe/Kyiv.")