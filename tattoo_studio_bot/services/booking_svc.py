from __future__ import annotations

import json
import logging
import random
import string
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from tattoo_studio_bot.db.database import fetch_setting
from tattoo_studio_bot.models.enums import BookingStatus, statuses_blocking_slot

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_public_id() -> str:
    d = datetime.now(timezone.utc).strftime("%Y%m%d")
    suffix = "".join(random.choice(string.digits) for _ in range(4))
    return f"BK-{d}-{suffix}"


async def _occupancy_single_room(conn: aiosqlite.Connection) -> bool:
    raw = await fetch_setting(conn, "occupancy_mode", "single_room")
    return raw.strip() != "per_master"


async def create_draft(conn: aiosqlite.Connection, user_id: int, version_id: int) -> int:
    pid = _make_public_id()
    now = _utcnow_iso()
    await conn.execute(
        """
        INSERT INTO bookings (user_id, public_id, status, questionnaire_version_id, answers_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, '{}', ?, ?)
        """,
        (user_id, pid, BookingStatus.draft.value, version_id, now, now),
    )
    await conn.commit()
    rowid = (await (await conn.execute("SELECT last_insert_rowid()")).fetchone())[0]
    logger.info("Создан черновик заявки booking_id=%s user_id=%s", rowid, user_id)
    return int(rowid)


async def get_draft_for_user(conn: aiosqlite.Connection, user_id: int) -> dict[str, Any] | None:
    async with conn.execute(
        """
        SELECT id, public_id, status, questionnaire_version_id, answers_json, slot_id, master_id, draft_step_slug, created_at
        FROM bookings
        WHERE user_id = ? AND status = ?
        ORDER BY id DESC LIMIT 1
        """,
        (user_id, BookingStatus.draft.value),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    answers: dict[str, Any] = {}
    try:
        answers = json.loads(row["answers_json"] or "{}")
    except json.JSONDecodeError:
        answers = {}
    return {
        "id": row["id"],
        "public_id": row["public_id"],
        "questionnaire_version_id": row["questionnaire_version_id"],
        "answers": answers,
        "slot_id": row["slot_id"],
        "master_id": row["master_id"],
        "draft_step_slug": row["draft_step_slug"],
        "created_at": row["created_at"],
    }


async def reset_draft(conn: aiosqlite.Connection, booking_id: int, user_id: int) -> None:
    await conn.execute(
        "DELETE FROM bookings WHERE id = ? AND user_id = ? AND status = ?",
        (booking_id, user_id, BookingStatus.draft.value),
    )
    await conn.commit()


async def set_draft_cursor(conn: aiosqlite.Connection, booking_id: int, user_id: int, slug: str) -> None:
    now = _utcnow_iso()
    await conn.execute(
        """
        UPDATE bookings SET draft_step_slug = ?, updated_at = ?
        WHERE id = ? AND user_id = ? AND status = ?
        """,
        (slug, now, booking_id, user_id, BookingStatus.draft.value),
    )
    await conn.commit()


async def save_answers_partial(
    conn: aiosqlite.Connection,
    booking_id: int,
    user_id: int,
    answers: dict[str, Any],
    draft_step_slug: str | None,
) -> None:
    now = _utcnow_iso()
    await conn.execute(
        """
        UPDATE bookings
        SET answers_json = ?, draft_step_slug = ?, updated_at = ?
        WHERE id = ? AND user_id = ? AND status = ?
        """,
        (
            json.dumps(answers, ensure_ascii=False),
            draft_step_slug,
            now,
            booking_id,
            user_id,
            BookingStatus.draft.value,
        ),
    )
    await conn.commit()


async def _slot_blocked_statuses_placeholders() -> tuple[str, ...]:
    return tuple(s.value for s in statuses_blocking_slot())


async def is_slot_available(
    conn: aiosqlite.Connection,
    slot_id: int,
    *,
    exclude_booking_id: int | None = None,
) -> bool:
    """Вариант v1 по умолчанию: одно рабочее место — слот занят, если есть блокирующая заявка (любой мастер)."""
    single = await _occupancy_single_room(conn)
    statuses = await _slot_blocked_statuses_placeholders()

    ph = ",".join("?" for _ in statuses)
    args: list[Any] = [*statuses, slot_id]
    extra = ""
    if exclude_booking_id is not None:
        extra = " AND id <> ?"
        args.append(exclude_booking_id)

    if single:
        q = f"""
        SELECT COUNT(*) FROM bookings
        WHERE status IN ({ph}) AND slot_id = ?{extra}
        """
        async with conn.execute(q, args) as cur:
            n = int((await cur.fetchone())[0])
        return n == 0

    # per_master: слот доступен, если для выбранного master_id нет конфликта — обрабатывается на уровне выбора мастера
    return True


async def is_master_free_on_slot(
    conn: aiosqlite.Connection,
    slot_id: int,
    master_id: int,
    *,
    exclude_booking_id: int | None = None,
) -> bool:
    single = await _occupancy_single_room(conn)
    statuses = await _slot_blocked_statuses_placeholders()
    ph = ",".join("?" for _ in statuses)
    base_args: list[Any] = [*statuses, slot_id]
    extra = ""
    if exclude_booking_id is not None:
        extra = " AND id <> ?"
        base_args.append(exclude_booking_id)

    if single:
        return await is_slot_available(conn, slot_id, exclude_booking_id=exclude_booking_id)

    q = f"""
    SELECT COUNT(*) FROM bookings
    WHERE status IN ({ph}) AND slot_id = ? AND master_id = ?{extra}
    """
    args = [*base_args, master_id]
    async with conn.execute(q, args) as cur:
        n = int((await cur.fetchone())[0])
    return n == 0


async def set_draft_slot(conn: aiosqlite.Connection, booking_id: int, user_id: int, slot_id: int) -> None:
    now = _utcnow_iso()
    await conn.execute(
        """
        UPDATE bookings SET slot_id = ?, master_id = NULL, updated_at = ?
        WHERE id = ? AND user_id = ? AND status = ?
        """,
        (slot_id, now, booking_id, user_id, BookingStatus.draft.value),
    )
    await conn.commit()


async def set_draft_master(conn: aiosqlite.Connection, booking_id: int, user_id: int, master_id: int) -> None:
    now = _utcnow_iso()
    await conn.execute(
        """
        UPDATE bookings SET master_id = ?, updated_at = ?
        WHERE id = ? AND user_id = ? AND status = ?
        """,
        (master_id, now, booking_id, user_id, BookingStatus.draft.value),
    )
    await conn.commit()


async def attach_slot_and_master_draft(
    conn: aiosqlite.Connection,
    booking_id: int,
    user_id: int,
    slot_id: int,
    master_id: int,
) -> None:
    await set_draft_slot(conn, booking_id, user_id, slot_id)
    await set_draft_master(conn, booking_id, user_id, master_id)


async def finalize_booking(
    conn: aiosqlite.Connection,
    booking_id: int,
    user_id: int,
    *,
    require_payment: bool,
) -> tuple[bool, str | None]:
    """
    Перевод draft → pending_confirm или awaiting_payment.
    Возвращает (ok, error_message).
    """
    async with conn.execute(
        """
        SELECT slot_id, master_id, answers_json FROM bookings
        WHERE id = ? AND user_id = ? AND status = ?
        """,
        (booking_id, user_id, BookingStatus.draft.value),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return False, "Черновик не найден."

    slot_id = row["slot_id"]
    master_id = row["master_id"]
    if slot_id is None or master_id is None:
        return False, "Не выбраны дата/время или мастер."

    if not await is_master_free_on_slot(conn, int(slot_id), int(master_id), exclude_booking_id=booking_id):
        return False, "Это время уже занято. Выберите другой слот."

    if not await is_slot_available(conn, int(slot_id), exclude_booking_id=booking_id):
        return False, "Это время уже занято. Выберите другой слот."

    now = _utcnow_iso()
    new_status = BookingStatus.awaiting_payment if require_payment else BookingStatus.pending_confirm
    await conn.execute(
        """
        UPDATE bookings SET status = ?, updated_at = ? WHERE id = ? AND user_id = ?
        """,
        (new_status.value, now, booking_id, user_id),
    )
    await conn.commit()
    logger.info(
        "Заявка финализирована booking_id=%s status=%s require_payment=%s",
        booking_id,
        new_status.value,
        require_payment,
    )
    return True, None


async def list_user_bookings(
    conn: aiosqlite.Connection, user_id: int
) -> list[dict[str, Any]]:
    async with conn.execute(
        """
        SELECT id, public_id, status, created_at, slot_id FROM bookings
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 50
        """,
        (user_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]
