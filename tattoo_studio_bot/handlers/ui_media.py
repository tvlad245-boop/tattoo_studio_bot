from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, InputMediaPhoto, Message

logger = logging.getLogger(__name__)

CAPTION_MAX = 1024

# Ключи в таблице settings (file_id Telegram)
SETTING_PHOTO_MAIN = "section_photo_main"
SETTING_PHOTO_ABOUT = "section_photo_about"
SETTING_PHOTO_PRICE = "section_photo_price"


async def present_screen(
    bot: Bot,
    message: Message,
    *,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
    photo_file_id: str | None,
) -> None:
    """
    Показ экрана с опциональной картинкой.
    При смене типа (фото→текст или наоборот) сообщение заменяется через delete+send.
    """
    cap = text if len(text) <= CAPTION_MAX else text[: CAPTION_MAX - 1] + "…"

    if photo_file_id:
        media = InputMediaPhoto(media=photo_file_id, caption=cap, parse_mode="HTML")
        try:
            if message.photo:
                await bot.edit_message_media(
                    media,
                    chat_id=message.chat.id,
                    message_id=message.message_id,
                    reply_markup=reply_markup,
                )
            else:
                await message.delete()
                await bot.send_photo(
                    message.chat.id,
                    photo_file_id,
                    caption=cap,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
        except TelegramBadRequest:
            try:
                await message.delete()
            except TelegramBadRequest:
                logger.debug("present_screen: delete old message failed")
            await bot.send_photo(
                message.chat.id,
                photo_file_id,
                caption=cap,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        return

    try:
        await message.edit_text(cap, parse_mode="HTML", reply_markup=reply_markup)
    except TelegramBadRequest:
        try:
            if message.photo:
                await message.delete()
            else:
                await message.edit_text(cap, parse_mode="HTML", reply_markup=reply_markup)
                return
        except TelegramBadRequest:
            pass
        await bot.send_message(message.chat.id, cap, parse_mode="HTML", reply_markup=reply_markup)


async def send_screen_from_scratch(
    bot: Bot,
    chat_id: int,
    *,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
    photo_file_id: str | None,
) -> None:
    """Первое сообщение (/start без колбэка)."""
    cap = text if len(text) <= CAPTION_MAX else text[: CAPTION_MAX - 1] + "…"
    if photo_file_id:
        await bot.send_photo(chat_id, photo_file_id, caption=cap, parse_mode="HTML", reply_markup=reply_markup)
    else:
        await bot.send_message(chat_id, cap, parse_mode="HTML", reply_markup=reply_markup)
