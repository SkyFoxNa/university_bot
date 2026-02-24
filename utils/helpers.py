from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_start_bot_kb(bot_username: str) -> types.InlineKeyboardMarkup:
    """Кнопка-посилання на бота, якщо він не може написати першим"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 Запустити бота в ЛС", url=f"https://t.me/{bot_username}?start=start")
    return builder.as_markup()


async def universal_answer(event: types.CallbackQuery | types.Message, text: str,
                           reply_markup: types.InlineKeyboardMarkup = None):
    """
    Універсальний помічник:
    - Якщо ЛС: редагує або надсилає повідомлення.
    - Якщо група: надсилає в ЛС і повідомляє про це в групі.
    """
    user_id = event.from_user.id
    bot = event.bot
    message = event.message if isinstance(event, types.CallbackQuery) else event

    if message.chat.type == "private":
        # У ЛС просто редагуємо або відповідаємо
        if isinstance(event, types.CallbackQuery):
            await event.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown",
                                          disable_web_page_preview=True)
        else:
            await event.answer(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        # У ГРУПІ:
        try:
            # 1. Намагаємось ТИХО надіслати в ЛС
            await bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup, parse_mode="Markdown")

            # 2. Якщо вдалося — підтверджуємо в групі
            if isinstance(event, types.CallbackQuery):
                await event.answer("Відповів у приватні повідомлення! 📥")
            else:
                await event.reply("Надіслав меню тобі в особисті! 😉")

        except Exception:
            # 3. Якщо НЕ вдалося (користувач не заблокував/не стартував) — показуємо кнопку
            bot_info = await bot.get_me()
            kb = get_start_bot_kb(bot_info.username)
            error_text = "⚠️ **Я не можу написати вам!**\nБудь ласка, натисніть кнопку нижче, щоб дозволити мені писати вам."

            if isinstance(event, types.CallbackQuery):
                await event.message.answer(error_text, reply_markup=kb)
                await event.answer()
            else:
                await event.answer(error_text, reply_markup=kb)