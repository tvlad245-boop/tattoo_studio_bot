from __future__ import annotations

import calendar
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from tattoo_studio_bot.utils.booking_window import date_in_booking_window
from tattoo_studio_bot.utils.callbacks import cb_admin, noop_admin


def build_admin_month_keyboard(
    year: int,
    month: int,
    tz_name: str,
    *,
    closed_dates: frozenset[str],
) -> InlineKeyboardMarkup:
    """Дни с 🔒 закрыты администратором (work_days.is_closed); нажатие переключает."""
    tz = ZoneInfo(tz_name)
    today = datetime.now(tz).date()

    header = [
        InlineKeyboardButton(text="Пн", callback_data=noop_admin()),
        InlineKeyboardButton(text="Вт", callback_data=noop_admin()),
        InlineKeyboardButton(text="Ср", callback_data=noop_admin()),
        InlineKeyboardButton(text="Чт", callback_data=noop_admin()),
        InlineKeyboardButton(text="Пт", callback_data=noop_admin()),
        InlineKeyboardButton(text="Сб", callback_data=noop_admin()),
        InlineKeyboardButton(text="Вс", callback_data=noop_admin()),
    ]

    cal = calendar.Calendar(firstweekday=0)
    weeks = cal.monthdatescalendar(year, month)

    rows: list[list[InlineKeyboardButton]] = [header]

    for week in weeks:
        row: list[InlineKeyboardButton] = []
        for d in week:
            if d.month != month:
                row.append(InlineKeyboardButton(text=" ", callback_data=noop_admin()))
                continue

            ds = d.isoformat()
            label = f"{d.day}🔒" if ds in closed_dates else str(d.day)
            compact = d.strftime("%Y%m%d")
            row.append(
                InlineKeyboardButton(
                    text=label,
                    callback_data=cb_admin(("cal", "t", compact)),
                )
            )
        rows.append(row)

    nav_row = [
        InlineKeyboardButton(
            text="◀",
            callback_data=cb_admin(("cal", "m", _shift_month(year, month, -1))),
        ),
        InlineKeyboardButton(
            text=f"{month:02d}.{year}",
            callback_data=noop_admin(),
        ),
        InlineKeyboardButton(
            text="▶",
            callback_data=cb_admin(("cal", "m", _shift_month(year, month, 1))),
        ),
    ]
    rows.append(nav_row)

    rows.append(
        [
            InlineKeyboardButton(
                text="⬅ В панель",
                callback_data=cb_admin(("home",)),
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def _shift_month(year: int, month: int, delta: int) -> str:
    m = month + delta
    y = year
    while m <= 0:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return f"{y}{m:02d}"


def admin_calendar_hint(tz_name: str) -> str:
    tz = ZoneInfo(tz_name)
    today = datetime.now(tz).date()
    in_w = date_in_booking_window(today, tz_name)
    return (
        f"<b>Дни записи</b> (часовой пояс: <code>{tz_name}</code>)\n\n"
        "🔒 — день закрыт для клиентов (не выбирается в календаре записи).\n"
        "Нажмите на число — переключить открыт/закрыт.\n\n"
        f"Окно бронирования для клиента включает «сегодня» и даты до конца следующего месяца "
        f"(сегодня в окне: {'да' if in_w else 'нет'})."
    )
