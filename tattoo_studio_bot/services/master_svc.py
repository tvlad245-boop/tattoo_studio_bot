from __future__ import annotations

from typing import Any

import aiosqlite


async def list_active_masters(conn: aiosqlite.Connection) -> list[dict[str, Any]]:
    async with conn.execute(
        """
        SELECT id, display_name, contact_for_client, active, sort_order
        FROM masters WHERE active = 1
        ORDER BY sort_order ASC, id ASC
        """
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_master(conn: aiosqlite.Connection, master_id: int) -> dict[str, Any] | None:
    async with conn.execute(
        "SELECT id, display_name, contact_for_client FROM masters WHERE id = ?", (master_id,)
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None
