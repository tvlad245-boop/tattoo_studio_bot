from __future__ import annotations

import json
from typing import Any

import aiosqlite

async def get_active_version_id(conn: aiosqlite.Connection) -> int | None:
    async with conn.execute(
        "SELECT id FROM questionnaire_versions WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
    ) as cur:
        row = await cur.fetchone()
        return int(row[0]) if row else None


async def load_steps_for_version(
    conn: aiosqlite.Connection, version_id: int
) -> list[dict[str, Any]]:
    async with conn.execute(
        """
        SELECT id, slug, step_type, title, config, sort_order, required, is_enabled
        FROM questionnaire_steps
        WHERE version_id = ? AND is_enabled = 1
        ORDER BY sort_order ASC, id ASC
        """,
        (version_id,),
    ) as cur:
        rows = await cur.fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        cfg = {}
        if r["config"]:
            try:
                cfg = json.loads(r["config"])
            except json.JSONDecodeError:
                cfg = {}
        out.append(
            {
                "id": r["id"],
                "slug": r["slug"],
                "type": r["step_type"],
                "title": r["title"],
                "config": cfg,
                "sort_order": r["sort_order"],
                "required": bool(r["required"]),
            }
        )
    return out


def validate_choice_config(step_type: str, config: dict[str, Any]) -> str | None:
    if step_type in ("choice", "choice_with_other"):
        opts = config.get("options")
        if not isinstance(opts, list) or len(opts) < 1:
            return "Нужен список options."
        others = [o for o in opts if isinstance(o, dict) and o.get("other")]
        if step_type == "choice_with_other":
            if len(others) != 1:
                return "Для choice_with_other должна быть ровно одна опция other."
        return None
    if step_type == "text":
        if int(config.get("max_length") or 500) < 1:
            return "Некорректный max_length."
        return None
    if step_type == "photos":
        mf = int(config.get("max_files") or 5)
        mb = int(config.get("max_mb") or 5)
        if mf < 1 or mf > 5:
            return "max_files должен быть 1..5."
        if mb < 1:
            return "max_mb должен быть > 0."
        return None
    return "Неизвестный тип шага."
