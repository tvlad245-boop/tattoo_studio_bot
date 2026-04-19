from __future__ import annotations

from typing import Any

import aiosqlite


async def render_price_html(conn: aiosqlite.Connection) -> str:
    async with conn.execute(
        """
        SELECT c.id, c.title AS ctitle, i.title AS ititle, i.price_rub
        FROM price_categories c
        LEFT JOIN price_items i ON i.category_id = c.id
        ORDER BY c.sort_order ASC, c.id ASC, i.sort_order ASC, i.id ASC
        """
    ) as cur:
        rows = await cur.fetchall()

    if not rows:
        return "<b>Прайс</b>\n\nПрайс будет добавлен администратором."

    lines: list[str] = ["<b>Прайс</b>", ""]
    current_cat: str | None = None
    for r in rows:
        ct = str(r["ctitle"])
        if ct != current_cat:
            lines.append(f"<b>{ct}</b>")
            current_cat = ct
        if r["ititle"] is not None:
            lines.append(f"• {r['ititle']} — {int(r['price_rub'])} ₽")
    return "\n".join(lines)
