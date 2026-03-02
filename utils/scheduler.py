import logging
import pytz
from datetime import datetime, date
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot

from db.models import User, Role, Lesson, ScheduleChange, ScheduleTime, WeekType, Subject


COLOR_TO_EMOJI = {
    "green": "🟢 (зелений)",
    "red": "🔴 (червоний)",
    "common": "⚪️ (загальний)"
}


# Словник для перекладу назв днів
EN_TO_UA_DAYS = {
    "Monday": "Понеділок", "Tuesday": "Вівторок", "Wednesday": "Середа",
    "Thursday": "Четвер", "Friday": "П'ятниця", "Saturday": "Субота", "Sunday": "Неділя"
}

# Часовий пояс для України
UA_TZ = pytz.timezone("Europe/Kyiv")


# --- ДОПОМІЖНІ ФУНКЦІЇ ---

def get_teacher_display_name(subj: Subject) -> str:
    """Формує ПІБ лектора або повертає дефолтне значення"""
    if subj.teacher_user:
        name = subj.teacher_user.user_name
        surname = subj.teacher_user.user_surname if subj.teacher_user.user_surname else ""
        return f"{name} {surname}".strip()

    if subj.teacher_name and subj.teacher_name.strip():
        return subj.teacher_name

    return "Не призначено"


async def get_daily_data(session, target_date: date):
    """Збирає всі дані на день одним запитом"""
    # 1. Визначаємо активний колір тижня
    week_res = await session.execute(select(WeekType).where(WeekType.is_active == True))
    week_color_obj = week_res.scalar_one_or_none()
    active_color = week_color_obj.name if week_color_obj else "common"

    # 2. Отримуємо сітку дзвінків
    times_res = await session.execute(select(ScheduleTime).order_by(ScheduleTime.pair_number))
    times = times_res.scalars().all()

    # 3. Отримуємо уроки
    day_name_en = target_date.strftime("%A")
    lessons_res = await session.execute(
        select(Lesson).where(
            Lesson.day_of_week == day_name_en,
            Lesson.week_type.in_([active_color, "common"])
        ).options(selectinload(Lesson.subject).selectinload(Subject.teacher_user))
    )
    lessons_map = {l.lesson_number: l for l in lessons_res.scalars().all()}

    # 4. Отримуємо заміни
    changes_res = await session.execute(
        select(ScheduleChange).where(ScheduleChange.change_date == target_date)
        .options(selectinload(ScheduleChange.new_subject).selectinload(Subject.teacher_user))
    )
    changes_map = {c.pair_number: c for c in changes_res.scalars().all()}

    return times, lessons_map, changes_map, active_color


# --- ГОЛОВНІ ЗАВДАННЯ ---

async def send_morning_schedule(bot: Bot, session_pool):
    """Ранкова розсилка о 08:30 (по Києву)"""
    async with session_pool() as session:
        # Отримуємо сьогоднішню дату саме в часовому поясі України
        today = datetime.now(UA_TZ).date()

        if today.weekday() > 4: return  # Ігноруємо Сб та Нд

        times, lessons, changes, color = await get_daily_data(session, today)
        day_name = EN_TO_UA_DAYS.get(today.strftime("%A"), "")

        # 1. Отримуємо емодзі для кольору тижня
        color_display = COLOR_TO_EMOJI.get(color, f"({color})")

        group_text = f"☀️ **Розклад на сьогодні — {day_name}** {color_display}\n\n"

        for t in times:
            # --- ОБРОБКА ВЕЛИКОЇ ПЕРЕРВИ (якщо pair_number == None або is_big_break) ---
            if t.pair_number is None or (hasattr(t, 'is_big_break') and t.is_big_break):
                group_text += f"🍎 **Велика перерва**\n"
                group_text += f"⏱ `{t.start_time_1}` – `{t.end_time_2}`\n"
                group_text += "— — — — — — — — —\n"
                continue

            # --- ОБРОБКА ЗВИЧАЙНОЇ ПАРИ ---
            subj = None
            prefix = ""

            # Перевіряємо заміну або звичайний розклад
            if t.pair_number in changes:
                subj = changes[t.pair_number].new_subject
                prefix = "🔄 [ЗАМІНА] "
            elif t.pair_number in lessons:
                subj = lessons[t.pair_number].subject

            if subj:
                lecturer = get_teacher_display_name(subj)
                group_text += f"📌 **{t.pair_number} пара:** {prefix}{subj.name}\n"
                group_text += f"👨‍🏫 Викладач: {lecturer}\n"
                group_text += f"⏱ `{t.start_time_1}` – `{t.end_time_2}` (Пер. {t.break_start}-{t.break_end})\n"
            else:
                group_text += f"❌ **{t.pair_number} пара:** Відсутня\n"

            group_text += "— — — — — — — — —\n"

        # Розсилка
        std_res = await session.execute(
            select(User).join(User.roles).join(Role).where(Role.name.in_(["student", "headman"])))
        for u in std_res.unique().scalars().all():
            try:
                await bot.send_message(u.user_id, group_text, parse_mode="Markdown")
            except:
                continue

        # Ректору
        rectors_res = await session.execute(select(User).join(User.roles).join(Role).where(Role.name == "rector"))
        for rector in rectors_res.unique().scalars().all():
            rec_pairs = []
            for t in times:
                if t.pair_number is None: continue  # Пропускаємо перерви для ректора

                s = changes[t.pair_number].new_subject if t.pair_number in changes else (
                    lessons[t.pair_number].subject if t.pair_number in lessons else None)

                if s and s.teacher_id == rector.id:
                    rec_pairs.append(f"👨‍🏫 **{t.pair_number} пара:** {s.name}\n⏱ `{t.start_time_1}-{t.end_time_2}`")

            if rec_pairs:
                msg = f"👨‍🏫 **Пане Ректоре, сьогодні у Вас такі пари:**\n\n" + "\n\n".join(rec_pairs)
                try:
                    await bot.send_message(rector.user_id, msg, parse_mode="Markdown")
                except:
                    continue


async def check_and_notify(bot: Bot, session_pool):
    """Щохвилинна перевірка з корекцією часового поясу"""
    # Отримуємо поточний час у Києві
    now_ua = datetime.now(UA_TZ)
    now_mins = now_ua.hour * 60 + now_ua.minute
    today = now_ua.date()

    async with session_pool() as session:
        times, lessons, changes, _ = await get_daily_data(session, today)

        for t in times:
            subj = changes[t.pair_number].new_subject if t.pair_number in changes else (
                lessons[t.pair_number].subject if t.pair_number in lessons else None)
            if not subj: continue

            # --- ПОЧАТОК ПАРИ ---
            if t.start_time_1:
                sh, sm = map(int, t.start_time_1.split(":"))
                if (sh * 60 + sm) - now_mins == 5:
                    lecturer = get_teacher_display_name(subj)
                    msg = (f"🔔 **{t.pair_number} ПАРА: {subj.name}**\n"
                           f"👨‍🏫 Лектор: **{lecturer}**\n\n"
                           f"⏱ Початок: `{t.start_time_1}`\n"
                           f"☕️ Перерва: `{t.break_start} — {t.break_end}`\n"
                           f"🏁 Кінець: `{t.end_time_2}`\n\n"
                           f"🔗 [Увійти в Zoom]({subj.zoom_link})\n"
                           f"🆔 `{subj.zoom_id or '-'}` | 🔑 `{subj.zoom_password or '-'}`")
                    await broadcast_event(bot, session, msg, subj.teacher_id)

            # --- ВНУТРІШНЯ ПЕРЕРВА ---
            # if t.break_start:
            #     bh, bm = map(int, t.break_start.split(":"))
            #     if (bh * 60 + bm) - now_mins == 2:
            #         prefix = f"☕️ **Перерва всередині {t.pair_number}-ї пари**"
            #         msg = f"{prefix} розпочнеться за 2 хв!\n⏱ Час: `{t.break_start} — {t.break_end}`"
            #         await broadcast_event(bot, session, msg, subj.teacher_id)


async def broadcast_event(bot: Bot, session, text: str, teacher_db_id: int = None):
    """Універсальна розсилка"""
    std_res = await session.execute(
        select(User).join(User.roles).join(Role).where(Role.name.in_(["student", "headman"])))
    for u in std_res.unique().scalars().all():
        try:
            await bot.send_message(u.user_id, text, parse_mode="Markdown", disable_web_page_preview=True)
        except:
            continue

    if teacher_db_id:
        r_res = await session.execute(select(User).where(User.id == teacher_db_id))
        rector = r_res.scalar_one_or_none()
        if rector:
            try:
                await bot.send_message(rector.user_id, text, parse_mode="Markdown")
            except:
                pass


# --- ІНІЦІАЛІЗАЦІЯ ---

def setup_scheduler(bot: Bot, session_pool):
    """Запуск шедулера"""
    # Вказуємо часовий пояс і для самого шедулера
    scheduler = AsyncIOScheduler(timezone=UA_TZ)

    # 1. Ранкова розсилка
    scheduler.add_job(send_morning_schedule, "cron", hour=8, minute=30, args=[bot, session_pool])

    # 2. Щохвилинний моніторинг
    scheduler.add_job(check_and_notify, "interval", minutes=1, args=[bot, session_pool])

    scheduler.start()
    logging.info("APScheduler успішно запущено для часового поясу Europe/Kyiv.")

# import logging
# from datetime import datetime, date
# import pytz
# from sqlalchemy import select, func
# from sqlalchemy.orm import selectinload
# from apscheduler.schedulers.asyncio import AsyncIOScheduler
# from aiogram import Bot
#
# from db.models import User, Role, Lesson, ScheduleChange, ScheduleTime, WeekType, Subject
#
# # Словник для перекладу назв днів
# EN_TO_UA_DAYS = {
#     "Monday": "Понеділок", "Tuesday": "Вівторок", "Wednesday": "Середа",
#     "Thursday": "Четвер", "Friday": "П'ятниця", "Saturday": "Субота", "Sunday": "Неділя"
# }
#
#
# # --- ДОПОМІЖНІ ФУНКЦІЇ ---
#
# def get_teacher_display_name(subj: Subject) -> str:
#     """Формує ПІБ лектора або повертає дефолтне значення"""
#     if subj.teacher_user:
#         name = subj.teacher_user.user_name
#         surname = subj.teacher_user.user_surname if subj.teacher_user.user_surname else ""
#         return f"{name} {surname}".strip()
#
#     # Якщо користувач не прив'язаний, перевіряємо текстове поле
#     if subj.teacher_name and subj.teacher_name.strip():
#         return subj.teacher_name
#
#     return "Не призначено"
#
#
# async def get_daily_data(session, target_date: date):
#     """Збирає всі дані на день одним запитом з підвантаженням зв'язків"""
#     # 1. Визначаємо активний колір тижня
#     week_res = await session.execute(select(WeekType).where(WeekType.is_active == True))
#     week_color_obj = week_res.scalar_one_or_none()
#     active_color = week_color_obj.name if week_color_obj else "common"
#
#     # 2. Отримуємо сітку дзвінків (часові рамки)
#     times_res = await session.execute(select(ScheduleTime).order_by(ScheduleTime.pair_number))
#     times = times_res.scalars().all()
#
#     # 3. Отримуємо уроки (common + поточний колір) з підвантаженням викладачів
#     # Отримуємо назву дня англійською (Monday, Tuesday...)
#     day_name_en = target_date.strftime("%A")
#
#     # 3. Отримуємо уроки
#     lessons_res = await session.execute(
#         select(Lesson).where(
#             Lesson.day_of_week == day_name_en,  # Тепер порівнюємо рядки "Monday" == "Monday"
#             Lesson.week_type.in_([active_color, "common"])
#         ).options(selectinload(Lesson.subject).selectinload(Subject.teacher_user))
#     )
#     lessons_map = {l.lesson_number: l for l in lessons_res.scalars().all()}
#
#     # 4. Отримуємо заміни на конкретну дату
#     changes_res = await session.execute(
#         select(ScheduleChange).where(ScheduleChange.change_date == target_date)
#         .options(selectinload(ScheduleChange.new_subject).selectinload(Subject.teacher_user))
#     )
#     changes_map = {c.pair_number: c for c in changes_res.scalars().all()}
#
#     return times, lessons_map, changes_map, active_color
#
#
# # --- ГОЛОВНІ ЗАВДАННЯ ---
#
# async def send_morning_schedule(bot: Bot, session_pool):
#     """Ранкова розсилка о 08:30"""
#     async with session_pool() as session:
#         today = date.today()
#         if today.weekday() > 4: return  # Ігноруємо Сб та Нд
#
#         times, lessons, changes, color = await get_daily_data(session, today)
#         day_name = EN_TO_UA_DAYS.get(today.strftime("%A"), "")
#
#         # Формування тексту для студентів
#         group_text = f"☀️ **Розклад на сьогодні — {day_name}** ({color})\n\n"
#         for t in times:
#             subj = None
#             prefix = ""
#             if t.pair_number in changes:
#                 subj = changes[t.pair_number].new_subject
#                 prefix = "🔄 [ЗАМІНА] "
#             elif t.pair_number in lessons:
#                 subj = lessons[t.pair_number].subject
#
#             if subj:
#                 lecturer = get_teacher_display_name(subj)
#                 group_text += f"🔹 **{t.pair_number} пара:** {prefix}{subj.name}\n"
#                 group_text += f"👨‍🏫 Викладач: {lecturer}\n"
#                 group_text += f"⏱ `{t.start_time_1}` – `{t.end_time_2}` (Пер. {t.break_start}-{t.break_end})\n"
#             else:
#                 group_text += f"⚪️ **{t.pair_number} пара:** Відсутня\n"
#             group_text += "— — — — — — — — —\n"
#
#         # Розсилка студентам та старостам
#         std_res = await session.execute(
#             select(User).join(User.roles).join(Role).where(Role.name.in_(["student", "headman"])))
#         for u in std_res.unique().scalars().all():
#             try:
#                 await bot.send_message(u.user_id, group_text, parse_mode="Markdown")
#             except:
#                 continue
#
#         # Розсилка Ректору (тільки якщо він сьогодні викладає)
#         rectors_res = await session.execute(select(User).join(User.roles).join(Role).where(Role.name == "rector"))
#         for rector in rectors_res.unique().scalars().all():
#             rec_pairs = []
#             for t in times:
#                 s = changes[t.pair_number].new_subject if t.pair_number in changes else (
#                     lessons[t.pair_number].subject if t.pair_number in lessons else None)
#                 if s and s.teacher_id == rector.id:
#                     rec_pairs.append(f"👨‍🏫 **{t.pair_number} пара:** {s.name}\n⏱ `{t.start_time_1}-{t.end_time_2}`")
#
#             if rec_pairs:
#                 msg = f"👨‍🏫 **Пане Ректоре, сьогодні у Вас такі пари:**\n\n" + "\n\n".join(rec_pairs)
#                 try:
#                     await bot.send_message(rector.user_id, msg, parse_mode="Markdown")
#                 except:
#                     continue
#
#
# async def check_and_notify(bot: Bot, session_pool):
#     """Щохвилинна перевірка початку пари та внутрішньої перерви"""
#     async with session_pool() as session:
#         now_mins = datetime.now().hour * 60 + datetime.now().minute
#         today = date.today()
#         times, lessons, changes, _ = await get_daily_data(session, today)
#
#         for t in times:
#             # Знаходимо предмет для поточного слота
#             subj = changes[t.pair_number].new_subject if t.pair_number in changes else (
#                 lessons[t.pair_number].subject if t.pair_number in lessons else None)
#             if not subj: continue
#
#             # --- 1. ПОВІДОМЛЕННЯ ПРО ПОЧАТОК ПАРИ (за 5 хв) ---
#             if t.start_time_1:
#                 sh, sm = map(int, t.start_time_1.split(":"))
#                 if (sh * 60 + sm) - now_mins == 5:
#                     lecturer = get_teacher_display_name(subj)
#                     msg = (f"🔔 **{t.pair_number} ПАРА: {subj.name}**\n"
#                            f"👨‍🏫 Лектор: **{lecturer}**\n\n"
#                            f"⏱ Початок: `{t.start_time_1}`\n"
#                            f"☕️ Перерва: `{t.break_start} — {t.break_end}`\n"
#                            f"🏁 Кінець: `{t.end_time_2}`\n\n"
#                            f"🔗 [Увійти в Zoom]({subj.zoom_link})\n"
#                            f"🆔 `{subj.zoom_id or '-'}` | 🔑 `{subj.zoom_password or '-'}`")
#
#                     await broadcast_event(bot, session, msg, subj.teacher_id)
#
#             # --- 2. ПОВІДОМЛЕННЯ ПРО ВНУТРІШНЮ ПЕРЕРВУ (за 5 хв) ---
#             if t.break_start:
#                 bh, bm = map(int, t.break_start.split(":"))
#                 if (bh * 60 + bm) - now_mins == 5:
#                     # prefix = "🍏 **Велика перерва**" if t.is_big_break else f"☕️ **Перерва всередині {t.pair_number}-ї пари**"
#                     prefix = f"☕️ **Перерва всередині {t.pair_number}-ї пари**"
#                     msg = f"{prefix} розпочнеться за 5 хв!\n⏱ Час: `{t.break_start} — {t.break_end}`"
#
#                     await broadcast_event(bot, session, msg, subj.teacher_id)
#
#
# async def broadcast_event(bot: Bot, session, text: str, teacher_db_id: int = None):
#     """Універсальна розсилка студентам + лектору"""
#     # Студенти та старости отримують завжди
#     std_res = await session.execute(
#         select(User).join(User.roles).join(Role).where(Role.name.in_(["student", "headman"])))
#     for u in std_res.unique().scalars().all():
#         try:
#             await bot.send_message(u.user_id, text, parse_mode="Markdown", disable_web_page_preview=True)
#         except:
#             continue
#
#     # Лектор отримує тільки якщо він прив'язаний до пари
#     if teacher_db_id:
#         r_res = await session.execute(select(User).where(User.id == teacher_db_id))
#         rector = r_res.scalar_one_or_none()
#         if rector:
#             try:
#                 await bot.send_message(rector.user_id, text, parse_mode="Markdown")
#             except:
#                 pass
#
#
# # --- ІНІЦІАЛІЗАЦІЯ ---
#
# def setup_scheduler(bot: Bot, session_pool):
#     """Запуск шедулера"""
#     scheduler = AsyncIOScheduler(timezone="Europe/Kyiv")
#
#     # 1. Ранкова розсилка
#     scheduler.add_job(send_morning_schedule, "cron", hour=8, minute=30, args=[bot, session_pool])
#
#     # 2. Щохвилинний моніторинг
#     scheduler.add_job(check_and_notify, "interval", minutes=1, args=[bot, session_pool])
#
#     scheduler.start()
#     logging.info("APScheduler успішно запущено.")