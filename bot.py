import asyncio
import logging
from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from db.session import AsyncSessionLocal, engine
from db.models import Base, Role
from db.middleware import DbSessionMiddleware
from sqlalchemy import select

from handlers import routers
from utils.scheduler import setup_scheduler

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)

async def init_db():
    """Створення таблиць та початкових ролей"""
    async with engine.begin() as conn:
        # ОБЕРЕЖНО: drop_all видаляє всі дані при кожному запуску!
        # await conn.run_sync(Base.metadata.drop_all) #-- тільки для тестів
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        for role_name in ["user", "admin", "student", "rector", "headman", "head", "homework"]:
            stmt = select(Role).where(Role.name == role_name)
            res = await session.execute(stmt)
            if not res.scalar_one_or_none():
                session.add(Role(name=role_name))
        await session.commit()

async def main():
    # 1. Створюємо базу даних
    await init_db()

    # 2. Ініціалізуємо бота та диспетчер ОДИН РАЗ поза циклом
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    # --- ЗАПУСК ШЕДУЛЕРА ---
    # Запускаємо один раз при старті додатка
    setup_scheduler(bot, AsyncSessionLocal)
    # -----------------------

    # 3. Реєструємо Middleware (теж один раз)
    dp.update.middleware(DbSessionMiddleware(AsyncSessionLocal))

    # 4. Підключаємо роутери (теж один раз)
    for r in routers:
        dp.include_router(r)

    # 5. Глобальний обробник помилок
    @dp.error()
    async def global_error_handler(event):
        logging.exception(f"Unhandled error: {event.exception}")
        return True

    # 6. Цикл стабільності: перезапускаємо тільки процес прослуховування (polling)
    while True:
        try:
            logging.info("Бот запускається...")
            # Використовуємо close_bot_session=True для коректного перепідключення
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        except Exception as e:
            logging.critical(f"Критична помилка, рестарт через 10 сек: {e}")
            # Закриваємо сесію бота перед паузою, щоб уникнути конфліктів з'єднання
            await bot.session.close()
            await asyncio.sleep(10)
            # Створюємо новий об'єкт бота для чистого перепідключення
            bot = Bot(token=BOT_TOKEN)

        # print("Бот остановлен...")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот вимкнений користувачем")