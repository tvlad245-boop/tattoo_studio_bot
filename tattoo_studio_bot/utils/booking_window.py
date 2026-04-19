from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def _last_day_of_month(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def booking_window_bounds(tz_name: str) -> tuple[date, date]:
    """
    Окно бронирования v1 (формула из ТЗ §5.1):

    От «сегодня» по календарю студии до конца следующего календарного месяца включительно.

    Пример: если сегодня 15 марта 2026 в TZ студии — доступны даты с 15.03.2026 по последний день
    апреля 2026 включительно.
    """
    tz = ZoneInfo(tz_name)
    today = datetime.now(tz).date()

    ty, tm = today.year, today.month
    nm = tm + 1
    ny = ty
    if nm > 12:
        nm = 1
        ny += 1

    last = _last_day_of_month(ny, nm)
    return today, last


def date_in_booking_window(d: date, tz_name: str) -> bool:
    first, last = booking_window_bounds(tz_name)
    return first <= d <= last
