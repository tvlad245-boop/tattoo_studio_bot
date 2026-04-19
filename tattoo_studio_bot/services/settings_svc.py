from __future__ import annotations

import aiosqlite

from tattoo_studio_bot.db.database import fetch_setting, set_setting


async def get_timezone(conn: aiosqlite.Connection, default_tz: str) -> str:
    v = await fetch_setting(conn, "studio_timezone", default_tz)
    return v.strip() or default_tz
