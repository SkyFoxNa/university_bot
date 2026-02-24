from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession
from utils.scheduler import get_daily_data, get_teacher_display_name


async def get_today_schedule_text(session: AsyncSession, target_date: date):
    times, lessons, changes, color = await get_daily_data(session, target_date)

    day_name_en = target_date.strftime("%A")
    ua_days = {
        "Monday": "Понеділок", "Tuesday": "Вівторок", "Wednesday": "Середа",
        "Thursday": "Четвер", "Friday": "П'ятниця", "Saturday": "Субота", "Sunday": "Неділя"
    }

    color_emoji = {"green": "🟢", "red": "🔴", "common": "⚪️"}
    emoji = color_emoji.get(color.lower(), "⚪️")
    day_name_ua = ua_days.get(day_name_en, day_name_en)

    if day_name_en in ["Saturday", "Sunday"] and not lessons and not changes:
        return None

    text = f"📅 **Розклад на сьогодні — {day_name_ua}** {emoji}\n"
    text += "━━━━━━━━━━━━━━━━━━\n\n"

    has_lessons = False
    for t in times:
        subj = None
        prefix = ""

        # Перевірка замін та основних пар
        if t.pair_number in changes:
            subj = changes[t.pair_number].new_subject
            prefix = "🔄 [ЗАМІНА] "
        elif t.pair_number in lessons:
            subj = lessons[t.pair_number].subject

        if subj:
            has_lessons = True
            lecturer = get_teacher_display_name(subj)

            # Основна інформація про пару
            text += f"🔹 **{t.pair_number} пара:** {prefix}*{subj.name}*\n"
            text += f"👨‍🏫 {lecturer}\n"
            text += f"⏱ `{t.start_time_1}-{t.end_time_2}`\n"

            # Додаємо посилання та реквізити, якщо вони є
            if subj.zoom_link:
                text += f"🔗 [Приєднатися до заняття]({subj.zoom_link})\n"

            # Виводимо ID та пароль в один рядок для економії місця
            auth_info = []
            if subj.zoom_id:
                auth_info.append(f"🆔 `{subj.zoom_id}`")
            if subj.zoom_password:
                auth_info.append(f"🔑 `{subj.zoom_password}`")

            if auth_info:
                text += " ".join(auth_info) + "\n"

            text += "— — — — — — — — —\n"

    return text if has_lessons else f"🎓 На сьогодні ({day_name_ua}) занять не знайдено."


# async def get_today_schedule_text(session: AsyncSession, target_date: date):
#     # Отримуємо дані (в get_daily_data у нас вже є логіка фільтрації за кольором тижня)
#     times, lessons, changes, color = await get_daily_data(session, target_date)
#
#     # Назва дня для фільтрації в БД
#     day_name_en = target_date.strftime("%A")
#
#     # Словник для красивого виводу користувачу
#     ua_days = {
#         "Monday": "Понеділок", "Tuesday": "Вівторок", "Wednesday": "Середа",
#         "Thursday": "Четвер", "Friday": "П'ятниця", "Saturday": "Субота", "Sunday": "Неділя"
#     }
#
#     # Мапа емодзі для кольорів
#     color_emoji = {
#         "green": "🟢",
#         "red": "🔴",
#         "common": "⚪️"
#     }
#     emoji = color_emoji.get(color.lower(), "⚪️")
#
#     day_name_ua = ua_days.get(day_name_en, day_name_en)
#
#     # Якщо це вихідний і немає ні занять, ні замін
#     if day_name_en in ["Saturday", "Sunday"] and not lessons and not changes:
#         return None
#
#     text = f"📅 **Розклад на сьогодні — {day_name_ua}** {emoji}\n\n"
#
#     has_lessons = False
#     for t in times:
#         subj = None
#         prefix = ""
#
#         # Перевіряємо заміни або основні лекції
#         if t.pair_number in changes:
#             subj = changes[t.pair_number].new_subject
#             prefix = "🔄 [ЗАМІНА] "
#         elif t.pair_number in lessons:
#             subj = lessons[t.pair_number].subject
#
#         if subj:
#             has_lessons = True
#             lecturer = get_teacher_display_name(subj)
#             text += f"🔹 **{t.pair_number} пара:** {prefix}{subj.name}\n"
#             text += f"👨‍🏫 {lecturer}\n"
#             text += f"⏱ `{t.start_time_1}-{t.end_time_2}`\n"
#             text += "— — — — — — —\n"
#
#     return text if has_lessons else f"🎓 На сьогодні ({day_name_ua}) занять не знайдено."