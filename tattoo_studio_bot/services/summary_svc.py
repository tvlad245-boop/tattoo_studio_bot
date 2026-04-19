from __future__ import annotations

import json
from typing import Any

import aiosqlite

from tattoo_studio_bot.services.master_svc import get_master
from tattoo_studio_bot.services.questionnaire_svc import load_steps_for_version
from tattoo_studio_bot.services.slot_svc import get_slot
from tattoo_studio_bot.utils.html_format import esc


async def build_summary_html(
    conn: aiosqlite.Connection,
    *,
    booking_id: int,
) -> str | None:
    async with conn.execute(
        """
        SELECT id, public_id, questionnaire_version_id, answers_json, slot_id, master_id, status
        FROM bookings WHERE id = ?
        """,
        (booking_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None

    vid = row["questionnaire_version_id"]
    answers: dict[str, Any] = {}
    try:
        answers = json.loads(row["answers_json"] or "{}")
    except json.JSONDecodeError:
        answers = {}

    steps = await load_steps_for_version(conn, int(vid)) if vid else []

    lines: list[str] = [
        f"<b>Заявка</b> {esc(row['public_id'])}",
        "",
        "<b>Анкета</b>",
    ]

    for s in steps:
        slug = s["slug"]
        if slug not in answers:
            continue
        raw_val = answers[slug]
        title = esc(s["title"])
        rendered = _render_answer(s, raw_val)
        lines.append(f"{title}: {rendered}")

    slot_id = row["slot_id"]
    if slot_id:
        sl = await get_slot(conn, int(slot_id))
        if sl:
            lines.append("")
            lines.append(f"<b>Дата и время:</b> {esc(sl['work_date'])} {esc(sl['start_time'])}")

    mid = row["master_id"]
    if mid:
        m = await get_master(conn, int(mid))
        if m:
            lines.append("")
            lines.append(f"<b>Мастер:</b> {esc(m['display_name'])}")
            if m.get("contact_for_client"):
                lines.append(esc(m["contact_for_client"]))

    lines.append("")
    lines.append(f"<b>Статус:</b> {esc(row['status'])}")
    return "\n".join(lines)


def _render_answer(step: dict[str, Any], raw_val: Any) -> str:
    st = step["type"]
    cfg = step.get("config") or {}

    if st in ("choice", "choice_with_other"):
        if isinstance(raw_val, dict) and raw_val.get("other"):
            return esc(str(raw_val.get("text") or ""))
        if isinstance(raw_val, dict) and "value" in raw_val:
            inner = raw_val["value"]
        else:
            inner = raw_val
        oid = str(inner)
        opts = {str(o.get("id")): o.get("label") for o in (cfg.get("options") or []) if isinstance(o, dict)}
        return esc(opts.get(oid, oid))

    if st == "text":
        return esc(str(raw_val))

    if st == "photos":
        if isinstance(raw_val, list):
            return esc(f"фото: {len(raw_val)} шт.")
        return "—"

    return esc(str(raw_val))
