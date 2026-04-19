from __future__ import annotations

"""
Telegram callback_data лимит 64 байта.
Префиксы клиента 'c|' и админа 'a|' не пересекаются (§9).
"""

CLIENT_PREFIX = "c|"
ADMIN_PREFIX = "a|"


def cb_client(parts: tuple[str, ...]) -> str:
    raw = CLIENT_PREFIX + "|".join(parts)
    encoded = raw.encode("utf-8")
    if len(encoded) > 64:
        raise ValueError(f"callback_data слишком длинная: {len(encoded)} байт")
    return raw


def cb_admin(parts: tuple[str, ...]) -> str:
    raw = ADMIN_PREFIX + "|".join(parts)
    encoded = raw.encode("utf-8")
    if len(encoded) > 64:
        raise ValueError(f"callback_data слишком длинная: {len(encoded)} байт")
    return raw


def noop_client() -> str:
    return cb_client(("noop",))


def noop_admin() -> str:
    return cb_admin(("noop",))
