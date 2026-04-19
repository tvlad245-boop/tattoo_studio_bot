from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS questionnaire_versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 0,
  title TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS questionnaire_steps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  version_id INTEGER NOT NULL REFERENCES questionnaire_versions(id) ON DELETE CASCADE,
  slug TEXT NOT NULL,
  step_type TEXT NOT NULL,
  title TEXT NOT NULL,
  config TEXT NOT NULL DEFAULT '{}',
  sort_order INTEGER NOT NULL DEFAULT 0,
  required INTEGER NOT NULL DEFAULT 1,
  is_enabled INTEGER NOT NULL DEFAULT 1,
  UNIQUE(version_id, slug)
);

CREATE TABLE IF NOT EXISTS masters (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  display_name TEXT NOT NULL,
  contact_for_client TEXT,
  schedule_chat_id INTEGER,
  schedule_message_id INTEGER,
  active INTEGER NOT NULL DEFAULT 1,
  sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS work_days (
  work_date TEXT PRIMARY KEY,
  is_closed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS slots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  work_date TEXT NOT NULL,
  start_time TEXT NOT NULL,
  duration_minutes INTEGER NOT NULL DEFAULT 60,
  studio_blocked INTEGER NOT NULL DEFAULT 0,
  UNIQUE(work_date, start_time)
);

CREATE TABLE IF NOT EXISTS bookings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  public_id TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL,
  questionnaire_version_id INTEGER REFERENCES questionnaire_versions(id),
  answers_json TEXT NOT NULL DEFAULT '{}',
  slot_id INTEGER REFERENCES slots(id),
  master_id INTEGER REFERENCES masters(id),
  draft_step_slug TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  admin_comment TEXT,
  payment_external_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings(user_id);
CREATE INDEX IF NOT EXISTS idx_bookings_slot_status ON bookings(slot_id, status);
CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status);

CREATE TABLE IF NOT EXISTS price_categories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sort_order INTEGER NOT NULL DEFAULT 0,
  title TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category_id INTEGER NOT NULL REFERENCES price_categories(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  price_rub INTEGER NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS about_photos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_id TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  caption TEXT
);

CREATE TABLE IF NOT EXISTS payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  booking_id INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
  provider TEXT NOT NULL DEFAULT 'yukassa',
  external_id TEXT NOT NULL UNIQUE,
  amount_minor INTEGER NOT NULL,
  currency TEXT NOT NULL DEFAULT 'RUB',
  status TEXT NOT NULL,
  payload TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


async def init_db(db_path: Path) -> aiosqlite.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SCHEMA)
    await conn.commit()
    await _seed_if_needed(conn)
    await conn.commit()
    logger.info("База данных готова: %s", db_path)
    return conn


async def _seed_if_needed(conn: aiosqlite.Connection) -> None:
    async with conn.execute("SELECT COUNT(*) FROM questionnaire_versions") as cur:
        row = await cur.fetchone()
        if row and row[0] > 0:
            return

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()

    await conn.execute(
        "INSERT INTO questionnaire_versions (created_at, is_active, title) VALUES (?, 1, ?)",
        (now, "Начальная версия"),
    )
    vid = (await (await conn.execute("SELECT last_insert_rowid()")).fetchone())[0]

    steps = [
        (
            vid,
            "tattoo_type",
            "choice_with_other",
            "Тип татуировки",
            json.dumps(
                {
                    "options": [
                        {"id": "new", "label": "Новая"},
                        {"id": "fix", "label": "Исправление"},
                        {"id": "restoration", "label": "Реставрация"},
                        {"id": "cover", "label": "Перекрытие (cover-up)"},
                        {"id": "other", "label": "Другой вариант", "other": True},
                    ]
                },
                ensure_ascii=False,
            ),
            10,
            1,
        ),
        (
            vid,
            "placement",
            "choice_with_other",
            "Место нанесения",
            json.dumps(
                {
                    "options": [
                        {"id": "arm", "label": "Рука…"},
                        {"id": "leg", "label": "Нога…"},
                        {"id": "back", "label": "Спина…"},
                        {"id": "chest", "label": "Грудь…"},
                        {"id": "belly", "label": "Живот…"},
                        {"id": "other", "label": "Другой вариант", "other": True},
                    ]
                },
                ensure_ascii=False,
            ),
            20,
            1,
        ),
        (
            vid,
            "detail_level",
            "choice",
            "Степень детализации",
            json.dumps(
                {
                    "options": [
                        {"id": "l1", "label": "Минимальная"},
                        {"id": "l2", "label": "Средняя"},
                        {"id": "l3", "label": "Высокая"},
                        {"id": "l4", "label": "Высокодетализированная"},
                    ]
                },
                ensure_ascii=False,
            ),
            30,
            1,
        ),
        (
            vid,
            "sketch_ready",
            "choice",
            "Есть готовый эскиз",
            json.dumps(
                {
                    "options": [
                        {"id": "no", "label": "Нет"},
                        {"id": "yes", "label": "Да"},
                        {"id": "consult", "label": "Нужна консультация"},
                    ]
                },
                ensure_ascii=False,
            ),
            40,
            1,
        ),
        (
            vid,
            "size",
            "choice_with_other",
            "Размер",
            json.dumps(
                {
                    "options": [
                        {"id": "u5", "label": "до 5 см"},
                        {"id": "5_10", "label": "5–10 см"},
                        {"id": "10_15", "label": "10–15 см"},
                        {"id": "20p", "label": "от 20 см"},
                        {"id": "other", "label": "Другой вариант", "other": True},
                    ]
                },
                ensure_ascii=False,
            ),
            50,
            1,
        ),
        (
            vid,
            "refs_photos",
            "photos",
            "Есть фото-референсы",
            json.dumps({"max_files": 5, "max_mb": 5}, ensure_ascii=False),
            60,
            0,
        ),
    ]

    await conn.executemany(
        """
        INSERT INTO questionnaire_steps
        (version_id, slug, step_type, title, config, sort_order, required, is_enabled)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        """,
        steps,
    )

    await conn.executemany(
        "INSERT INTO settings (key, value) VALUES (?, ?)",
        [
            ("studio_timezone", "Europe/Moscow"),
            ("studio_contact_html", "<b>Студия</b>\nСвяжитесь с нами в Telegram"),
            ("booking_incoming_chat_id", ""),
            ("about_text_html", "<b>О студии</b>\nМы делаем тату."),
            (
                "occupancy_mode",
                "single_room",
            ),  # single_room | per_master (§8, для v1 — single_room)
            ("payment_bank_details_html", "Оплата по реквизитам (указать в админке)."),
        ],
    )

    await conn.execute(
        "INSERT INTO masters (display_name, contact_for_client, active, sort_order) VALUES (?, ?, 1, 0)",
        ("Мастер по умолчанию", "@master_contact"),
    )


async def fetch_setting(conn: aiosqlite.Connection, key: str, default: str = "") -> str:
    async with conn.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
        row = await cur.fetchone()
        if not row:
            return default
        return str(row[0])


async def set_setting(conn: aiosqlite.Connection, key: str, value: str) -> None:
    await conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
