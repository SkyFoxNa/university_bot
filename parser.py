import pandas as pd
import os
import requests
import re
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select

from config import DATABASE_URL
from db.models import Subject

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

# Словник жорстких замін (пишемо ключі в нижньому регістрі для уніфікації)
HARD_REPLACEMENTS = {
    "твсгп": "технологія виробництва сільськогосподарської продукції",
    # Можна додати інші, наприклад:
    # "інженерна механіка (теоретична механіка)": "інженерна механіка",
}


def download_excel_from_google_sheets(url, output_name):
    try:
        if "/edit" in url:
            export_url = re.sub(r'/edit.*', '/export?format=xlsx', url)
        else:
            file_id_match = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
            if file_id_match:
                file_id = file_id_match.group(1)
                export_url = f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=xlsx"
            else:
                return False

        print(f"📡 Завантаження файлу з Google Sheets...")
        response = requests.get(export_url)
        if response.status_code == 200:
            with open(output_name, 'wb') as f:
                f.write(response.content)
            print(f"✅ Файл збережено: {output_name}")
            return True
        return False
    except Exception as e:
        print(f"❌ Помилка завантаження: {e}")
        return False


def normalize_subject_name(name):
    """Прибирає зайве, замінює абревіатури та переводить у нижній регістр"""
    if not name or name == "nan":
        return ""

    # Переводимо в нижній регістр для порівняння
    name = name.strip().lower()

    # 1. Жорстка заміна за словником
    if name in HARD_REPLACEMENTS:
        name = HARD_REPLACEMENTS[name]

    # 2. Прибираємо (л), (пр) та інше в дужках
    name = re.sub(r'\s*\(.*\)\s*', '', name)

    return name.strip()


async def get_subjects_from_db():
    """Отримує предмети та створює словник з нормалізованими ключами"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Subject))
        subjects = result.scalars().all()
        # Ключ у словнику — теж нормалізована назва в нижньому регістрі
        return {normalize_subject_name(s.name): s for s in subjects}


def parse_schedule(file_path):
    try:
        df = pd.read_excel(file_path, header=None, engine='openpyxl')
        df = df.iloc[5:].reset_index(drop=True)
    except Exception as e:
        print(f"❌ Помилка при читанні файлу: {e}")
        return []

    current_day = "Не визначено"
    last_pair_number = None
    extracted_data = []

    for index, row in df.iterrows():
        day_raw = str(row[1]).strip()
        if day_raw != "nan" and any(d in day_raw for d in ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця"]):
            current_day = day_raw

        try:
            pair_raw = str(row[2]).strip()
            current_pair = str(int(float(pair_raw)))
            last_pair_number = current_pair
        except:
            current_pair = last_pair_number

        if not current_pair:
            continue

        subject_name = str(row[3]).strip()
        if not subject_name or subject_name == "nan":
            continue

        # Шукаємо посилання безпосередньо в рядку таблиці
        table_link = "—"
        for col_idx in range(4, 8):
            cell_content = str(row[col_idx]).strip()
            if "https:" in cell_content:
                table_link = cell_content
                break

        extracted_data.append({
            "day": current_day,
            "pair": current_pair,
            "original_name": subject_name,
            "normalized_name": normalize_subject_name(subject_name),
            "table_link": table_link
        })
    return extracted_data


def display_results(results, db_subjects):
    """Вивід порівняння посилань таблиці та бази"""
    # Збільшуємо ширину таблиці для двох посилань
    header = f"{'ДЕНЬ':<10} | {'№':<1} | {'ПРЕДМЕТ (ТАБЛИЦЯ)':<35} | {'СТАТУС':<7} | {'LINK (ТАБЛИЦЯ)':<30} | {'LINK (БАЗА)'}"
    print("\n" + "=" * 160)
    print(header)
    print("-" * 160)

    for item in results:
        norm_name = item['normalized_name']
        db_match = db_subjects.get(norm_name)

        status = "✅ OK" if db_match else "❌ MISS"
        db_link = db_match.zoom_link if db_match and db_match.zoom_link else "—"

        # Обрізаємо для компактності в терміналі
        display_name = (item['original_name'][:32] + '..') if len(item['original_name']) > 32 else item['original_name']
        t_link_short = (item['table_link'][:27] + '..') if len(item['table_link']) > 27 else item['table_link']
        db_link_short = (db_link[:50] + '..') if len(db_link) > 50 else db_link

        print(
            f"{item['day']:<10} | {item['pair']:<1} | {display_name:<35} | {status:<7} | {t_link_short:<30} | {db_link_short}")

    print("=" * 160 + "\n")


async def main():
    sheet_url = "https://docs.google.com/spreadsheets/d/1UKq4fqAUUostw9TKjzZcmv8Tl4gqgJc9KHorvUyzGKQ/edit?usp=drive_link"
    local_file = "schedule_tmp.xlsx"

    if download_excel_from_google_sheets(sheet_url, local_file):
        try:
            db_subjects = await get_subjects_from_db()
            schedule_data = parse_schedule(local_file)
            if schedule_data:
                display_results(schedule_data, db_subjects)
        except Exception as e:
            print(f"❌ Помилка роботи з базою: {e}")


if __name__ == "__main__":
    asyncio.run(main())