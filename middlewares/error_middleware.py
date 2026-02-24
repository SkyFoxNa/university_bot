import logging
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery


class ErrorMiddleware(BaseMiddleware):
    """
    Middleware перехоплює ВСІ помилки в хендлерах,
    щоб бот не падав і користувач отримував фідбек.
    """

    async def __call__(self, handler, event, data):
        try:
            return await handler(event, data)
        except Exception as e:
            logging.exception(f"Middleware caught error: {e}")

            # Якщо помилка сталася при натисканні на кнопку (CallbackQuery)
            # потрібно "закрити" годинник на кнопці, інакше він буде крутитися вічно
            if isinstance(event.event, CallbackQuery):
                try:
                    await event.event.answer(
                        "⚠️ Сталася помилка. Адміністратора повідомлено.",
                        show_alert=True
                    )
                except Exception:
                    pass

            # Можна повернути спеціальне значення, щоб перервати подальшу обробку
            return None