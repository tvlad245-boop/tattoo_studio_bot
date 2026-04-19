from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

import aiosqlite
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from tattoo_studio_bot.config import Settings


class DbInjectMiddleware(BaseMiddleware):
    """Передаёт в хендлер settings и общее соединение SQLite."""

    def __init__(self, settings: Settings, conn: aiosqlite.Connection) -> None:
        self.settings = settings
        self.conn = conn
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        data["settings"] = self.settings
        data["conn"] = self.conn
        return await handler(event, data)
