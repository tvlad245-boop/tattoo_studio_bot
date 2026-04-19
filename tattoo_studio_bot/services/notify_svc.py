from __future__ import annotations

import logging

from aiogram import Bot

from tattoo_studio_bot.db.database import fetch_setting
from tattoo_studio_bot.services.summary_svc import build_summary_html

logger = logging.getLogger(__name__)


async def notify_incoming_booking(bot: Bot, conn, booking_id: int) -> None:
    raw = await fetch_setting(conn, "booking_incoming_chat_id", "").strip()
    if not raw:
        return
    try:
        chat_id = int(raw)
    except ValueError:
        logger.error("booking_incoming_chat_id некорректный: %r", raw)
        return

    html = await build_summary_html(conn, booking_id=booking_id)
    if not html:
        return
    try:
        await bot.send_message(chat_id, html, parse_mode="HTML")
    except Exception:
        logger.exception("Не удалось отправить уведомление о заявке %s", booking_id)
