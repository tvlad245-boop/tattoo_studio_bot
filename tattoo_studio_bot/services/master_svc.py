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


async def list_all_masters(conn: aiosqlite.Connection) -> list[dict[str, Any]]:
    async with conn.execute(
        """
        SELECT id, display_name, contact_for_client, active, sort_order
        FROM masters ORDER BY sort_order ASC, id ASC
        """
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def next_sort_order(conn: aiosqlite.Connection) -> int:
    async with conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM masters") as cur:
        row = await cur.fetchone()
    return int(row[0]) if row else 0


async def create_master(
    conn: aiosqlite.Connection,
    display_name: str,
    contact_for_client: str,
) -> int:
    so = await next_sort_order(conn)
    await conn.execute(
        """
        INSERT INTO masters (display_name, contact_for_client, active, sort_order)
        VALUES (?, ?, 1, ?)
        """,
        (display_name.strip(), contact_for_client.strip(), so),
    )
    await conn.commit()
    async with conn.execute("SELECT last_insert_rowid()") as cur:
        row = await cur.fetchone()
    return int(row[0]) if row else 0


async def update_master(
    conn: aiosqlite.Connection,
    master_id: int,
    *,
    display_name: str | None = None,
    contact_for_client: str | None = None,
    active: int | None = None,
) -> None:
    if display_name is not None:
        await conn.execute(
            "UPDATE masters SET display_name = ? WHERE id = ?",
            (display_name.strip(), master_id),
        )
    if contact_for_client is not None:
        await conn.execute(
            "UPDATE masters SET contact_for_client = ? WHERE id = ?",
            (contact_for_client.strip(), master_id),
        )
    if active is not None:
        await conn.execute("UPDATE masters SET active = ? WHERE id = ?", (int(active), master_id))
    await conn.commit()
