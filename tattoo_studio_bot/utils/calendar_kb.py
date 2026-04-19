from __future__ import annotations

import calendar
from datetime import date, datetime
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from tattoo_studio_bot.utils.callbacks import cb_client, noop_client


def build_month_keyboard(
    year: int,
    month: int,
    tz_name: str,
    *,
    disabled_dates: frozenset[str],
) -> InlineKeyboardMarkup:
    """
    Сетка месяца: шапка Пн–Вс.
    Недоступные дни — noop, подпись с ❌ (в т.ч. прошлые и дни без слотов).
    """
    tz = ZoneInfo(tz_name)
    today = datetime.now(tz).date()

    header = [
        InlineKeyboardButton(text="Пн", callback_data=noop_client()),
        InlineKeyboardButton(text="Вт", callback_data=noop_client()),
        InlineKeyboardButton(text="Ср", callback_data=noop_client()),
        InlineKeyboardButton(text="Чт", callback_data=noop_client()),
        InlineKeyboardButton(text="Пт", callback_data=noop_client()),
        InlineKeyboardButton(text="Сб", callback_data=noop_client()),
        InlineKeyboardButton(text="Вс", callback_data=noop_client()),
    ]

    cal = calendar.Calendar(firstweekday=0)
    weeks = cal.monthdatescalendar(year, month)

    rows: list[list[InlineKeyboardButton]] = [header]

    for week in weeks:
        row: list[InlineKeyboardButton] = []
        for d in week:
            if d.month != month:
                row.append(InlineKeyboardButton(text=" ", callback_data=noop_client()))
                continue

            ds = d.isoformat()
            disabled = ds in disabled_dates

            if disabled:
                row.append(
                    InlineKeyboardButton(
                        text=f"{d.day}❌",
                        callback_data=noop_client(),
                    )
                )
            else:
                compact = d.strftime("%Y%m%d")
                row.append(
                    InlineKeyboardButton(
                        text=str(d.day),
                        callback_data=cb_client(("cal", "d", compact)),
                    )
                )
        rows.append(row)

    nav_row = [
        InlineKeyboardButton(
            text="◀",
            callback_data=cb_client(("cal", "m", _shift_month(year, month, -1))),
        ),
        InlineKeyboardButton(
            text=f"{month:02d}.{year}",
            callback_data=noop_client(),
        ),
        InlineKeyboardButton(
            text="▶",
            callback_data=cb_client(("cal", "m", _shift_month(year, month, 1))),
        ),
    ]
    rows.append(nav_row)

    rows.append(
        [
            InlineKeyboardButton(
                text="⬅ Главное меню",
                callback_data=cb_client(("menu", "open")),
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


def parse_compact_month(token: str) -> tuple[int, int]:
    y = int(token[:4])
    m = int(token[4:6])
    return y, m


def parse_compact_date(token: str) -> date:
    y = int(token[:4])
    m = int(token[4:6])
    d = int(token[6:8])
    return date(y, m, d)
