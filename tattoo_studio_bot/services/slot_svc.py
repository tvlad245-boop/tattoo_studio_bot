from __future__ import annotations

import logging
from datetime import date
from typing import Any

import aiosqlite

from tattoo_studio_bot.services.booking_svc import is_slot_available
from tattoo_studio_bot.utils.booking_window import date_in_booking_window

logger = logging.getLogger(__name__)


async def calendar_disabled_dates_for_month(
    conn: aiosqlite.Connection, year: int, month: int, tz_name: str
) -> frozenset[str]:
    """
    Дни без выбора в календаре: прошлое, вне окна бронирования, явно закрыты админом.

    Наличие слотов в БД проверяется после выбора дня (иначе без слотов все дни «закрыты»).
    """
    from calendar import monthrange
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(tz_name)
    today = datetime.now(tz).date()
    _, n_days = monthrange(year, month)
    closed = await list_closed_days_in_month(conn, year, month)

    disabled: set[str] = set()
    for dom in range(1, n_days + 1):
        d = date(year, month, dom)
        ds = d.isoformat()
        if d < today:
            disabled.add(ds)
            continue
        if not date_in_booking_window(d, tz_name):
            disabled.add(ds)
            continue
        if ds in closed:
            disabled.add(ds)
            continue

    return frozenset(disabled)


async def toggle_work_day_closed(conn: aiosqlite.Connection, d: date) -> bool:
    """Переключает признак «день закрыт админом». Возвращает новое значение is_closed."""
    ds = d.isoformat()
    async with conn.execute("SELECT is_closed FROM work_days WHERE work_date = ?", (ds,)) as cur:
        row = await cur.fetchone()
    cur_closed = bool(row and int(row[0]))
    new_val = 0 if cur_closed else 1
    await conn.execute(
        """
        INSERT INTO work_days (work_date, is_closed) VALUES (?, ?)
        ON CONFLICT(work_date) DO UPDATE SET is_closed = excluded.is_closed
        """,
        (ds, new_val),
    )
    await conn.commit()
    return bool(new_val)


async def day_closed(conn: aiosqlite.Connection, d: date) -> bool:
    ds = d.isoformat()
    async with conn.execute(
        "SELECT is_closed FROM work_days WHERE work_date = ?", (ds,)
    ) as cur:
        row = await cur.fetchone()
    return bool(row and row[0])


async def list_slots_for_day(conn: aiosqlite.Connection, d: date) -> list[dict[str, Any]]:
    ds = d.isoformat()
    async with conn.execute(
        """
        SELECT id, work_date, start_time, duration_minutes, studio_blocked
        FROM slots WHERE work_date = ?
        ORDER BY start_time ASC
        """,
        (ds,),
    ) as cur:
        rows = await cur.fetchall()

    out: list[dict[str, Any]] = []
    for r in rows:
        sid = int(r["id"])
        if r["studio_blocked"]:
            continue
        ok = await is_slot_available(conn, sid)
        if not ok:
            continue
        out.append(
            {
                "id": sid,
                "work_date": r["work_date"],
                "start_time": r["start_time"],
                "duration_minutes": int(r["duration_minutes"]),
            }
        )
    return out


async def list_closed_days_in_month(
    conn: aiosqlite.Connection, year: int, month: int
) -> frozenset[str]:
    from calendar import monthrange

    d0 = date(year, month, 1)
    d1 = date(year, month, monthrange(year, month)[1])
    async with conn.execute(
        """
        SELECT work_date FROM work_days
        WHERE is_closed = 1 AND work_date >= ? AND work_date <= ?
        """,
        (d0.isoformat(), d1.isoformat()),
    ) as cur:
        rows = await cur.fetchall()
    return frozenset(str(r[0]) for r in rows)


async def get_slot(conn: aiosqlite.Connection, slot_id: int) -> dict[str, Any] | None:
    async with conn.execute(
        "SELECT id, work_date, start_time, duration_minutes, studio_blocked FROM slots WHERE id = ?",
        (slot_id,),
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None
