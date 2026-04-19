from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    database_path: Path
    default_timezone: str
    yukassa_shop_id: str | None
    yukassa_secret_key: str | None


def _parse_admin_ids(raw: str | None) -> frozenset[int]:
    if not raw:
        return frozenset()
    out: list[int] = []
    for part in raw.replace(" ", "").split(","):
        if not part:
            continue
        out.append(int(part))
    return frozenset(out)


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN не задан в окружении или .env")

    db_raw = os.getenv("DATABASE_PATH", "./data/bot.db").strip()
    database_path = Path(db_raw)
    if not database_path.is_absolute():
        database_path = Path.cwd() / database_path

    tz = os.getenv("STUDIO_TIMEZONE", "Europe/Moscow").strip() or "Europe/Moscow"

    shop = os.getenv("YUKASSA_SHOP_ID", "").strip() or None
    secret = os.getenv("YUKASSA_SECRET_KEY", "").strip() or None

    return Settings(
        bot_token=token,
        admin_ids=_parse_admin_ids(os.getenv("ADMIN_IDS")),
        database_path=database_path,
        default_timezone=tz,
        yukassa_shop_id=shop,
        yukassa_secret_key=secret,
    )


def is_admin(user_id: int, settings: Settings) -> bool:
    return user_id in settings.admin_ids
