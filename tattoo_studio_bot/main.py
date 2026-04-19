from __future__ import annotations

import asyncio
import logging
import sys
import traceback

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from tattoo_studio_bot.config import load_settings
from tattoo_studio_bot.db.database import init_db
from tattoo_studio_bot.handlers.admin import admin_router
from tattoo_studio_bot.handlers.client import client_router
from tattoo_studio_bot.handlers.middlewares import DbInjectMiddleware


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )


async def main() -> None:
    _setup_logging()
    log = logging.getLogger(__name__)

    settings = load_settings()
    conn = await init_db(settings.database_path)

    bot = Bot(settings.bot_token)
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.middleware(DbInjectMiddleware(settings, conn))
    dp.callback_query.middleware(DbInjectMiddleware(settings, conn))

    dp.include_router(admin_router)
    dp.include_router(client_router)

    log.info("Бот запускается…")
    try:
        await dp.start_polling(bot)
    except Exception:
        log.exception("Фатальная ошибка polling")
        traceback.print_exc()
        raise


if __name__ == "__main__":
    asyncio.run(main())
