import logging
from aiogram import Router, types
from aiogram.types import ErrorEvent

router = Router()

@router.errors()
async def global_error_handler(event: ErrorEvent):
    """
    Глобальний перехоплювач помилок aiogram.
    Якщо хендлер впав — бот НЕ зупиняється.
    """
    # Логуємо помилку в консоль/файл
    logging.error(f"🚨 Виникла помилка: {event.exception}", exc_info=True)

    # Намагаємося повідомити користувача, що щось пішло не так
    try:
        if event.update.callback_query:
            await event.update.callback_query.answer(
                "⚠️ Вибачте, сталася внутрішня помилка. Спробуйте пізніше.",
                show_alert=True
            )
        elif event.update.message:
            await event.update.message.answer(
                "❌ Щось пішло не так при обробці запиту. Адміністратори вже в курсі."
            )
    except Exception as e:
        logging.error(f"Не вдалося надіслати повідомлення про помилку: {e}")

    return True