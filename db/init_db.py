import asyncio
from sqlalchemy import select, text
from db.session import AsyncSessionLocal, engine
from db.models import Base, WeekType


async def setup_db():
    async with engine.begin() as conn:
        # 1. Створюємо нові таблиці (наприклад, саму schedule_changes, якщо її ще не було)
        await conn.run_sync(Base.metadata.create_all)

        # Допоміжна функція для безпечного додавання колонок
        async def add_column_if_not_exists(table_name, column_name, column_type):
            result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
            columns = [row[1] for row in result.fetchall()]
            if column_name not in columns:
                print(f"🛠 Оновлення {table_name}: додавання колонки {column_name}...")
                await conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))
                print(f"✅ Колонку {column_name} додано.")
            else:
                print(f"ℹ️ Колонка {column_name} у таблиці {table_name} вже існує.")

        # --- Оновлення таблиці subjects ---
        await add_column_if_not_exists("subjects", "zoom_id", "VARCHAR(100)")
        await add_column_if_not_exists("subjects", "teacher_id",
                                       "INTEGER REFERENCES users(id) ON DELETE SET NULL")

        # --- Оновлення таблиці lessons ---
        await add_column_if_not_exists("lessons", "lesson_type", "VARCHAR(50)")

        # --- Оновлення таблиці users ---
        await add_column_if_not_exists("users", "viber", "VARCHAR(255)")
        await add_column_if_not_exists("users", "telegram_contact", "VARCHAR(255)")
        await add_column_if_not_exists("users", "email", "VARCHAR(255)")
        await add_column_if_not_exists("users", "phone", "VARCHAR(50)")

        # --- Оновлення таблиці homeworks ---
        await add_column_if_not_exists("homeworks", "photo_ids", "TEXT")

        # --- Оновлення таблиці schedule_changes (ДЛЯ ЗАМІН) ---
        # Додаємо поле дати
        await add_column_if_not_exists("schedule_changes", "change_date", "DATE")
        # Якщо хочете зберігати тип пари на заміні (Лекція/Практика)
        await add_column_if_not_exists("schedule_changes", "new_type", "VARCHAR(50)")

    # 3. Заповнюємо початкові дані для тижнів
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(WeekType))
        weeks = result.scalars().all()

        if not weeks:
            print("🌱 Ініціалізація типів тижня...")
            green = WeekType(name="green", is_active=True)
            red = WeekType(name="red", is_active=False)
            session.add_all([green, red])
            await session.commit()
            print("✅ Типи тижня додані.")
        else:
            print("ℹ️ Типи тижнів вже існують.")


if __name__ == "__main__":
    asyncio.run(setup_db())