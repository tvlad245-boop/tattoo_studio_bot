from __future__ import annotations

import logging
from datetime import date as date_cls
from datetime import datetime
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

from tattoo_studio_bot.config import Settings
from tattoo_studio_bot.db.database import fetch_setting
from tattoo_studio_bot.handlers.ui_media import (
    SETTING_PHOTO_ABOUT,
    SETTING_PHOTO_MAIN,
    SETTING_PHOTO_PRICE,
    present_screen,
    send_screen_from_scratch,
)
from tattoo_studio_bot.services import booking_svc, master_svc, questionnaire_svc, slot_svc
from tattoo_studio_bot.services.booking_svc import is_master_free_on_slot
from tattoo_studio_bot.services.notify_svc import notify_incoming_booking
from tattoo_studio_bot.services.price_svc import render_price_html
from tattoo_studio_bot.services.settings_svc import get_timezone
from tattoo_studio_bot.services.summary_svc import build_summary_html
from tattoo_studio_bot.utils.calendar_kb import (
    build_month_keyboard,
    parse_compact_date,
    parse_compact_month,
)
from tattoo_studio_bot.utils.callbacks import cb_client, noop_client
from tattoo_studio_bot.utils.html_format import esc

logger = logging.getLogger(__name__)

client_router = Router(name="client")


class BookingFlow(StatesGroup):
    questionnaire = State()
    questionnaire_other = State()
    questionnaire_photos = State()
    calendar = State()
    slots = State()
    masters = State()
    confirm = State()


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✍️ Записаться", callback_data=cb_client(("menu", "book"))),
                InlineKeyboardButton(text="💰 Прайс", callback_data=cb_client(("menu", "price"))),
            ],
            [
                InlineKeyboardButton(text="ℹ️ О нас", callback_data=cb_client(("menu", "about"))),
                InlineKeyboardButton(text="📋 Мои записи", callback_data=cb_client(("menu", "mine"))),
            ],
        ]
    )


def _main_menu_caption(tz: str) -> str:
    return (
        "<b>Студия татуировки</b>\n\n"
        f"Часовой пояс студии: <code>{esc(tz)}</code>\n\n"
        "<b>Выберите раздел:</b>"
    )


def _questionnaire_block_html(
    steps: list[dict[str, Any]],
    slug: str,
    step_title: str,
    extra: str = "",
) -> str:
    total = len(steps)
    idx = 1
    for i, s in enumerate(steps, start=1):
        if s["slug"] == slug:
            idx = i
            break
    intro = "<b>Зададим вам несколько вопросов о вашей татуировке.</b>"
    counter = f"<i>Вопрос {idx} из {total}</i>"
    parts = [intro, "", counter, "", f"<b>{esc(step_title)}</b>"]
    if extra.strip():
        parts.extend(["", extra])
    return "\n".join(parts)


async def _edit(ui: Message, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    try:
        await ui.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except TelegramBadRequest as e:
        low = str(e).lower()
        if "message is not modified" in low:
            return
        logger.warning("edit_text: %s", e)


async def _edit_or_reply(ui: Message, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    """Для сообщений пользователя правка невозможна — отправляем новое."""
    try:
        await ui.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except TelegramBadRequest:
        await ui.answer(text, parse_mode="HTML", reply_markup=kb)


async def _resolve_booking_id(conn, uid: int, state_data: dict[str, Any]) -> int:
    bid = int(state_data.get("booking_id") or 0)
    if bid:
        return bid
    draft = await booking_svc.get_draft_for_user(conn, uid)
    return int(draft["id"]) if draft else 0


def _next_slug(steps: list[dict[str, Any]], answers: dict[str, Any]) -> str | None:
    for s in steps:
        if s["slug"] not in answers:
            return s["slug"]
    return None


def _questionnaire_finished(steps: list[dict[str, Any]], answers: dict[str, Any]) -> bool:
    return _next_slug(steps, answers) is None


def _kb_for_step(step: dict[str, Any]) -> InlineKeyboardMarkup:
    st = step["type"]
    cfg = step["config"] or {}

    if st in ("choice", "choice_with_other"):
        row: list[InlineKeyboardButton] = []
        rows: list[list[InlineKeyboardButton]] = []
        for opt in cfg.get("options") or []:
            if not isinstance(opt, dict):
                continue
            oid = str(opt.get("id"))
            label = str(opt.get("label"))
            row.append(
                InlineKeyboardButton(
                    text=label,
                    callback_data=cb_client(("q", "o", step["slug"], oid)),
                )
            )
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([InlineKeyboardButton(text="⬅ В меню", callback_data=cb_client(("menu", "open")))])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    if st == "text":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅ В меню", callback_data=cb_client(("menu", "open")))]
            ]
        )

    if st == "photos":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="Да", callback_data=cb_client(("q", "ph", step["slug"], "yes"))),
                    InlineKeyboardButton(text="Нет", callback_data=cb_client(("q", "ph", step["slug"], "no"))),
                    InlineKeyboardButton(
                        text="Пропустить",
                        callback_data=cb_client(("q", "ph", step["slug"], "skip")),
                    ),
                ],
                [InlineKeyboardButton(text="⬅ В меню", callback_data=cb_client(("menu", "open")))],
            ]
        )

    return InlineKeyboardMarkup(inline_keyboard=[])


async def render_questionnaire_step(
    ui: Message,
    conn,
    booking_id: int,
    user_id: int,
    *,
    settings: Settings,
    state: FSMContext,
) -> None:
    draft = await booking_svc.get_draft_for_user(conn, user_id)
    if not draft:
        await _edit_or_reply(ui, "<b>Черновик не найден.</b> Нажмите /start", None)
        return

    vid = int(draft["questionnaire_version_id"])
    steps = await questionnaire_svc.load_steps_for_version(conn, vid)
    answers = draft["answers"]
    slug = _next_slug(steps, answers)
    if slug is None:
        tz = await get_timezone(conn, settings.default_timezone)
        await state.set_state(BookingFlow.calendar)
        await _render_calendar_month(ui, conn, settings, tz)
        return

    step = next(s for s in steps if s["slug"] == slug)
    await booking_svc.set_draft_cursor(conn, booking_id, user_id, slug)
    await state.set_state(BookingFlow.questionnaire)
    await state.update_data(booking_id=booking_id, q_slug=slug)

    extra = ""
    if step["type"] == "text":
        mx = int((step.get("config") or {}).get("max_length") or 500)
        extra = f"Максимум символов: <code>{mx}</code>."

    text = _questionnaire_block_html(steps, slug, step["title"], extra)

    await _edit_or_reply(ui, text, _kb_for_step(step))


async def _render_calendar_month(ui: Message, conn, settings: Settings, tz_name: str) -> None:
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo(tz_name)).date()
    disabled = await slot_svc.calendar_disabled_dates_for_month(conn, today.year, today.month, tz_name)
    kb = build_month_keyboard(today.year, today.month, tz_name, disabled_dates=disabled)
    await _edit(
        ui,
        "<b>Выберите дату</b>\n\nДни с ❌ недоступны (прошлое, нет окна записи, закрыто или нет свободных слотов).",
        kb,
    )


@client_router.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext, conn, settings: Settings) -> None:
    await state.clear()
    draft = await booking_svc.get_draft_for_user(conn, msg.from_user.id)
    tz = await get_timezone(conn, settings.default_timezone)

    kb = main_menu_kb()

    if draft:
        kb_d = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Продолжить запись",
                        callback_data=cb_client(("draft", "resume", str(draft["id"]))),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Начать заново",
                        callback_data=cb_client(("draft", "reset", str(draft["id"]))),
                    )
                ],
                [InlineKeyboardButton(text="Главное меню", callback_data=cb_client(("menu", "open")))],
            ]
        )
        await msg.answer(
            "У вас есть незавершённая заявка. Продолжить или начать заново?",
            reply_markup=kb_d,
        )
        return

    photo_id = (await fetch_setting(conn, SETTING_PHOTO_MAIN, "")).strip() or None
    await send_screen_from_scratch(
        msg.bot,
        msg.chat.id,
        text=_main_menu_caption(tz),
        reply_markup=kb,
        photo_file_id=photo_id,
    )


@client_router.callback_query(F.data.startswith("c|"))
async def client_dispatch(cb: CallbackQuery, state: FSMContext, conn, settings: Settings) -> None:
    parts = cb.data.split("|")
    if parts[0] != "c":
        await cb.answer()
        return

    kind = parts[1]

    if kind == "noop":
        await cb.answer()
        return

    if kind == "menu":
        await _handle_menu(cb, state, conn, settings, parts)
        return

    if kind == "draft":
        await _handle_draft(cb, state, conn, settings, parts)
        return

    if kind == "q":
        await _handle_question(cb, state, conn, settings, parts)
        return

    if kind == "cal":
        await _handle_calendar(cb, state, conn, settings, parts)
        return

    if kind == "sl":
        await _handle_slot_pick(cb, state, conn, settings, parts)
        return

    if kind == "ms":
        await _handle_master_pick(cb, state, conn, settings, parts)
        return

    if kind == "cf":
        await _handle_confirm(cb, state, conn, settings, parts, cb.bot)
        return

    await cb.answer()


async def _handle_menu(
    cb: CallbackQuery,
    state: FSMContext,
    conn,
    settings: Settings,
    parts: list[str],
) -> None:
    action = parts[2]
    tz = await get_timezone(conn, settings.default_timezone)

    if action == "open":
        await state.clear()
        kb = main_menu_kb()
        photo_id = (await fetch_setting(conn, SETTING_PHOTO_MAIN, "")).strip() or None
        await present_screen(
            cb.bot,
            cb.message,
            text=_main_menu_caption(tz),
            reply_markup=kb,
            photo_file_id=photo_id,
        )
        await cb.answer()
        return

    if action == "price":
        html = await render_price_html(conn)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅ В меню", callback_data=cb_client(("menu", "open")))]
            ]
        )
        photo_id = (await fetch_setting(conn, SETTING_PHOTO_PRICE, "")).strip() or None
        await present_screen(cb.bot, cb.message, text=html, reply_markup=kb, photo_file_id=photo_id)
        await cb.answer()
        return

    if action == "about":
        text = await fetch_setting(conn, "about_text_html", "<b>О студии</b>")
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅ В меню", callback_data=cb_client(("menu", "open")))]
            ]
        )
        photo_id = (await fetch_setting(conn, SETTING_PHOTO_ABOUT, "")).strip() or None
        await present_screen(cb.bot, cb.message, text=text, reply_markup=kb, photo_file_id=photo_id)
        async with conn.execute(
            "SELECT file_id FROM about_photos ORDER BY sort_order ASC, id ASC LIMIT 10"
        ) as cur:
            rows = await cur.fetchall()
        if rows:
            media = [InputMediaPhoto(media=r[0]) for r in rows]
            try:
                await cb.message.answer_media_group(media=media)
            except TelegramBadRequest:
                logger.exception("Не удалось отправить галерею «О нас»")
        await cb.answer()
        return

    if action == "mine":
        rows = await booking_svc.list_user_bookings(conn, cb.from_user.id)
        lines = ["<b>Мои записи</b>", ""]
        active = {"draft", "pending_confirm", "awaiting_payment", "confirmed"}
        for r in rows[:20]:
            st = str(r["status"])
            bucket = "активные" if st in active else "архив"
            lines.append(f"{esc(r['public_id'])} — <code>{esc(st)}</code> ({bucket})")
        if len(lines) == 2:
            lines.append("Пока нет записей.")
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅ В меню", callback_data=cb_client(("menu", "open")))]
            ]
        )
        await _edit(cb.message, "\n".join(lines), kb)
        await cb.answer()
        return

    if action == "book":
        vid = await questionnaire_svc.get_active_version_id(conn)
        if not vid:
            await cb.answer("Анкета не настроена.", show_alert=True)
            return

        draft = await booking_svc.get_draft_for_user(conn, cb.from_user.id)
        if draft:
            booking_id = int(draft["id"])
        else:
            booking_id = await booking_svc.create_draft(conn, cb.from_user.id, vid)

        await state.clear()
        await state.update_data(booking_id=booking_id)
        await render_questionnaire_step(cb.message, conn, booking_id, cb.from_user.id, settings=settings, state=state)
        await cb.answer()
        return


async def _restore_booking_flow(cb: CallbackQuery, state: FSMContext, conn, settings: Settings, booking_id: int) -> None:
    uid = cb.from_user.id
    draft = await booking_svc.get_draft_for_user(conn, uid)
    if not draft or int(draft["id"]) != booking_id:
        await cb.answer("Черновик устарел.", show_alert=True)
        return

    vid = int(draft["questionnaire_version_id"])
    steps = await questionnaire_svc.load_steps_for_version(conn, vid)
    answers = draft["answers"]

    if not _questionnaire_finished(steps, answers):
        await state.update_data(booking_id=booking_id)
        await render_questionnaire_step(cb.message, conn, booking_id, uid, settings=settings, state=state)
        await cb.answer()
        return

    if draft["slot_id"] is None:
        tz = await get_timezone(conn, settings.default_timezone)
        await state.set_state(BookingFlow.calendar)
        await state.update_data(booking_id=booking_id)
        await _render_calendar_month(cb.message, conn, settings, tz)
        await cb.answer()
        return

    if draft["master_id"] is None:
        await state.set_state(BookingFlow.masters)
        await state.update_data(booking_id=booking_id)
        await _render_masters(cb.message, conn, settings, booking_id, uid)
        await cb.answer()
        return

    await state.set_state(BookingFlow.confirm)
    await state.update_data(booking_id=booking_id)
    await _render_confirm(cb.message, conn, settings, booking_id)
    await cb.answer()


async def _handle_draft(
    cb: CallbackQuery,
    state: FSMContext,
    conn,
    settings: Settings,
    parts: list[str],
) -> None:
    action = parts[2]
    bid = int(parts[3])
    if action == "reset":
        await booking_svc.reset_draft(conn, bid, cb.from_user.id)
        await state.clear()
        tz = await get_timezone(conn, settings.default_timezone)
        kb = main_menu_kb()
        photo_id = (await fetch_setting(conn, SETTING_PHOTO_MAIN, "")).strip() or None
        await present_screen(
            cb.bot,
            cb.message,
            text=_main_menu_caption(tz),
            reply_markup=kb,
            photo_file_id=photo_id,
        )
        await cb.answer("Черновик удалён.")
        return

    if action == "resume":
        await _restore_booking_flow(cb, state, conn, settings, bid)
        return


async def _handle_question(
    cb: CallbackQuery,
    state: FSMContext,
    conn,
    settings: Settings,
    parts: list[str],
) -> None:
    sub = parts[2]
    data = await state.get_data()
    uid = cb.from_user.id
    booking_id = await _resolve_booking_id(conn, uid, data)
    if booking_id == 0:
        await cb.answer("Сессия устарела. Откройте /start", show_alert=True)
        return
    await state.update_data(booking_id=booking_id)

    if sub == "o":
        slug = parts[3]
        opt = parts[4]
        draft = await booking_svc.get_draft_for_user(conn, uid)
        if not draft:
            await cb.answer("Сессия устарела.", show_alert=True)
            return

        steps = await questionnaire_svc.load_steps_for_version(conn, int(draft["questionnaire_version_id"]))
        step = next(s for s in steps if s["slug"] == slug)
        cfg = step.get("config") or {}
        other_opt = None
        for o in cfg.get("options") or []:
            if isinstance(o, dict) and str(o.get("id")) == opt and o.get("other"):
                other_opt = o
                break

        answers = dict(draft["answers"])
        if other_opt is not None:
            await state.set_state(BookingFlow.questionnaire_other)
            await state.update_data(booking_id=booking_id, other_slug=slug)
            otext = _questionnaire_block_html(
                steps,
                slug,
                step["title"],
                "Опишите ваш вариант одним сообщением.",
            )
            await _edit(
                cb.message,
                otext,
                InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="⬅ В меню", callback_data=cb_client(("menu", "open")))]
                    ]
                ),
            )
            await cb.answer()
            return

        answers[slug] = opt
        await booking_svc.save_answers_partial(conn, booking_id, uid, answers, slug)
        await render_questionnaire_step(cb.message, conn, booking_id, uid, settings=settings, state=state)
        await cb.answer()
        return

    if sub == "ph":
        slug = parts[3]
        mode = parts[4]
        draft = await booking_svc.get_draft_for_user(conn, uid)
        if not draft:
            await cb.answer("Сессия устарела.", show_alert=True)
            return
        steps = await questionnaire_svc.load_steps_for_version(conn, int(draft["questionnaire_version_id"]))
        step = next(s for s in steps if s["slug"] == slug)
        cfg = step.get("config") or {}
        max_files = int(cfg.get("max_files") or 5)

        answers = dict(draft["answers"])

        if mode == "skip":
            answers[slug] = []
            await booking_svc.save_answers_partial(conn, booking_id, uid, answers, slug)
            await render_questionnaire_step(cb.message, conn, booking_id, uid, settings=settings, state=state)
            await cb.answer()
            return

        if mode == "no":
            answers[slug] = []
            await booking_svc.save_answers_partial(conn, booking_id, uid, answers, slug)
            await render_questionnaire_step(cb.message, conn, booking_id, uid, settings=settings, state=state)
            await cb.answer()
            return

        if mode == "yes":
            await state.set_state(BookingFlow.questionnaire_photos)
            await state.update_data(
                booking_id=booking_id,
                photo_slug=slug,
                photo_items=[],
                photo_max=max_files,
            )
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Готово",
                            callback_data=cb_client(("q", "ph", slug, "done")),
                        )
                    ],
                    [InlineKeyboardButton(text="⬅ В меню", callback_data=cb_client(("menu", "open")))],
                ]
            )
            ptext = _questionnaire_block_html(
                steps,
                slug,
                step["title"],
                f"Пришлите до {max_files} фото (JPEG, PNG, WebP).\nПосле загрузки нажмите «Готово».",
            )
            await _edit(cb.message, ptext, kb)
            await cb.answer()
            return

        if mode == "done":
            pdata = await state.get_data()
            items = list(pdata.get("photo_items") or [])
            answers[slug] = items
            await booking_svc.save_answers_partial(conn, booking_id, uid, answers, slug)
            await state.set_state(BookingFlow.questionnaire)
            await render_questionnaire_step(cb.message, conn, booking_id, uid, settings=settings, state=state)
            await cb.answer()
            return


async def _handle_calendar(
    cb: CallbackQuery,
    state: FSMContext,
    conn,
    settings: Settings,
    parts: list[str],
) -> None:
    sub = parts[2]
    tz = await get_timezone(conn, settings.default_timezone)

    if sub == "m":
        ym = parts[3]
        y, m = parse_compact_month(ym)
        disabled = await slot_svc.calendar_disabled_dates_for_month(conn, y, m, tz)
        kb = build_month_keyboard(y, m, tz, disabled_dates=disabled)
        await _edit(
            cb.message,
            "<b>Выберите дату</b>\n\nДни с ❌ недоступны (прошлое, нет окна записи, закрыто или нет свободных слотов).",
            kb,
        )
        await cb.answer()
        return

    if sub == "d":
        compact = parts[3]
        picked = parse_compact_date(compact)
        disabled = await slot_svc.calendar_disabled_dates_for_month(conn, picked.year, picked.month, tz)
        if picked.isoformat() in disabled:
            await cb.answer("Эта дата недоступна.", show_alert=True)
            return

        data = await state.get_data()
        booking_id = await _resolve_booking_id(conn, cb.from_user.id, data)
        if booking_id == 0:
            await cb.answer("Сессия устарела. /start", show_alert=True)
            return
        await state.update_data(booking_id=booking_id)

        slots = await slot_svc.list_slots_for_day(conn, picked)
        await state.set_state(BookingFlow.slots)
        await state.update_data(picked_date=picked.isoformat())

        rows_btn: list[list[InlineKeyboardButton]] = []
        row: list[InlineKeyboardButton] = []
        for s in slots:
            row.append(
                InlineKeyboardButton(
                    text=str(s["start_time"]),
                    callback_data=cb_client(("sl", str(s["id"]))),
                )
            )
            if len(row) == 3:
                rows_btn.append(row)
                row = []
        if row:
            rows_btn.append(row)

        rows_btn.append(
            [
                InlineKeyboardButton(
                    text="◀ К месяцу",
                    callback_data=cb_client(("cal", "m", f"{picked.year}{picked.month:02d}")),
                )
            ]
        )
        rows_btn.append(
            [InlineKeyboardButton(text="⬅ В меню", callback_data=cb_client(("menu", "open")))]
        )

        kb = InlineKeyboardMarkup(inline_keyboard=rows_btn)
        if not slots:
            await _edit(
                cb.message,
                "<b>Нет свободных слотов</b> на этот день.\nВыберите другую дату.",
                kb,
            )
        else:
            await _edit(
                cb.message,
                f"<b>Время на {picked.isoformat()}</b>\nВыберите слот.",
                kb,
            )
        await cb.answer()
        return


async def _handle_slot_pick(
    cb: CallbackQuery,
    state: FSMContext,
    conn,
    settings: Settings,
    parts: list[str],
) -> None:
    slot_id = int(parts[2])
    data = await state.get_data()
    uid = cb.from_user.id
    booking_id = await _resolve_booking_id(conn, uid, data)
    if booking_id == 0:
        await cb.answer("Сессия устарела. /start", show_alert=True)
        return
    await state.update_data(booking_id=booking_id)

    await booking_svc.set_draft_slot(conn, booking_id, uid, slot_id)
    await state.set_state(BookingFlow.masters)
    await _render_masters(cb.message, conn, settings, booking_id, uid)
    await cb.answer()


async def _render_masters(
    ui: Message,
    conn,
    settings: Settings,
    booking_id: int,
    user_id: int,
) -> None:
    draft = await booking_svc.get_draft_for_user(conn, user_id)
    if not draft or int(draft["id"]) != booking_id or draft["slot_id"] is None:
        await _edit_or_reply(ui, "<b>Ошибка черновика.</b> /start", None)
        return

    slot_id = int(draft["slot_id"])
    sl = await slot_svc.get_slot(conn, slot_id)
    if not sl:
        await _edit_or_reply(ui, "<b>Слот не найден.</b>", None)
        return

    picked = date_cls.fromisoformat(str(sl["work_date"]))
    date_compact = picked.strftime("%Y%m%d")

    masters = await master_svc.list_active_masters(conn)

    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []

    single_place = (await fetch_setting(conn, "occupancy_mode", "single_room")).strip() != "per_master"

    for m in masters:
        mid = int(m["id"])
        free = True
        if not single_place:
            free = await is_master_free_on_slot(conn, slot_id, mid, exclude_booking_id=booking_id)

        if free:
            row.append(
                InlineKeyboardButton(
                    text=f"{m['display_name']} ✓",
                    callback_data=cb_client(("ms", str(mid))),
                )
            )
        else:
            row.append(
                InlineKeyboardButton(
                    text=f"{m['display_name']} (занят)",
                    callback_data=noop_client(),
                )
            )

        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    if not single_place:
        any_free = any(
            await is_master_free_on_slot(conn, slot_id, int(m["id"]), exclude_booking_id=booking_id)
            for m in masters
        )
    else:
        any_free = bool(masters)

    rows.append(
        [
            InlineKeyboardButton(
                text="Без разницы",
                callback_data=cb_client(("ms", "any")),
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="◀ К слотам",
                callback_data=cb_client(("cal", "d", date_compact)),
            )
        ]
    )

    rows.append([InlineKeyboardButton(text="⬅ В меню", callback_data=cb_client(("menu", "open")))])

    kb = InlineKeyboardMarkup(inline_keyboard=rows)

    if not any_free:
        await _edit(
            ui,
            "<b>Нет свободных мастеров</b> на это время.\nВернитесь к выбору слота.",
            kb,
        )
        return

    await _edit_or_reply(ui, "<b>Выберите мастера</b>", kb)


async def _handle_master_pick(
    cb: CallbackQuery,
    state: FSMContext,
    conn,
    settings: Settings,
    parts: list[str],
) -> None:
    pick = parts[2]
    data = await state.get_data()
    uid = cb.from_user.id
    booking_id = await _resolve_booking_id(conn, uid, data)
    if booking_id == 0:
        await cb.answer("Сессия устарела. /start", show_alert=True)
        return
    await state.update_data(booking_id=booking_id)
    draft = await booking_svc.get_draft_for_user(conn, uid)
    if not draft or draft["slot_id"] is None:
        await cb.answer("Ошибка.", show_alert=True)
        return

    slot_id = int(draft["slot_id"])

    masters = await master_svc.list_active_masters(conn)

    async def pick_first_free() -> int | None:
        single_place = (await fetch_setting(conn, "occupancy_mode", "single_room")).strip() != "per_master"
        for m in sorted(masters, key=lambda x: int(x["id"])):
            mid = int(m["id"])
            if single_place:
                return mid
            if await is_master_free_on_slot(conn, slot_id, mid, exclude_booking_id=booking_id):
                return mid
        return None

    if pick == "any":
        mid = await pick_first_free()
        if mid is None:
            await cb.answer("Нет свободных мастеров.", show_alert=True)
            return
    else:
        mid = int(pick)

    await booking_svc.set_draft_master(conn, booking_id, uid, mid)
    await state.set_state(BookingFlow.confirm)
    await _render_confirm(cb.message, conn, settings, booking_id)
    await cb.answer()


async def _render_confirm(ui: Message, conn, settings: Settings, booking_id: int) -> None:
    html = await build_summary_html(conn, booking_id=booking_id)
    if not html:
        html = "Не удалось построить сводку."
    require_pay = bool(settings.yukassa_shop_id and settings.yukassa_secret_key)
    pay_hint = await fetch_setting(conn, "payment_bank_details_html", "")
    if require_pay:
        html += "\n\n<i>Онлайн-оплата: интерфейс подготовлен, провайдер требует настройки webhook в v1+.</i>"
    elif pay_hint.strip():
        html += "\n\n<b>Оплата</b>\n" + pay_hint

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подтвердить", callback_data=cb_client(("cf", "yes")))],
            [InlineKeyboardButton(text="◀ Назад", callback_data=cb_client(("cf", "back")))],
            [InlineKeyboardButton(text="⬅ В меню", callback_data=cb_client(("menu", "open")))],
        ]
    )
    await _edit(ui, html, kb)


async def _handle_confirm(
    cb: CallbackQuery,
    state: FSMContext,
    conn,
    settings: Settings,
    parts: list[str],
    bot: Bot,
) -> None:
    action = parts[2]
    data = await state.get_data()
    uid = cb.from_user.id
    booking_id = await _resolve_booking_id(conn, uid, data)
    if booking_id == 0:
        await cb.answer("Сессия устарела. /start", show_alert=True)
        return
    await state.update_data(booking_id=booking_id)

    if action == "back":
        await state.set_state(BookingFlow.masters)
        await _render_masters(cb.message, conn, settings, booking_id, uid)
        await cb.answer()
        return

    if action == "yes":
        require_pay = bool(settings.yukassa_shop_id and settings.yukassa_secret_key)
        ok, err = await booking_svc.finalize_booking(conn, booking_id, uid, require_payment=require_pay)
        if not ok:
            await cb.answer(err or "Ошибка", show_alert=True)
            return
        await notify_incoming_booking(bot, conn, booking_id)
        await state.clear()
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="В меню", callback_data=cb_client(("menu", "open")))]
            ]
        )
        await _edit(
            cb.message,
            "<b>Заявка отправлена.</b>\n\nСтудия свяжется с вами после обработки.",
            kb,
        )
        await cb.answer("Готово.")


@client_router.message(StateFilter(BookingFlow.questionnaire_other), F.text)
async def question_other_text(msg: Message, state: FSMContext, conn, settings: Settings) -> None:
    data = await state.get_data()
    booking_id = int(data["booking_id"])
    slug = str(data.get("other_slug"))
    uid = msg.from_user.id

    draft = await booking_svc.get_draft_for_user(conn, uid)
    if not draft:
        await msg.answer("Сессия устарела. /start")
        await state.clear()
        return

    answers = dict(draft["answers"])
    answers[slug] = {"other": True, "text": msg.text.strip()}
    await booking_svc.save_answers_partial(conn, booking_id, uid, answers, slug)

    await state.set_state(BookingFlow.questionnaire)
    await render_questionnaire_step(msg, conn, booking_id, uid, settings=settings, state=state)


@client_router.message(StateFilter(BookingFlow.questionnaire), F.text)
async def question_plain_text(msg: Message, state: FSMContext, conn, settings: Settings) -> None:
    data = await state.get_data()
    booking_id = int(data["booking_id"])
    slug = str(data.get("q_slug"))
    uid = msg.from_user.id

    draft = await booking_svc.get_draft_for_user(conn, uid)
    if not draft:
        await msg.answer("Сессия устарела. /start")
        await state.clear()
        return

    steps = await questionnaire_svc.load_steps_for_version(conn, int(draft["questionnaire_version_id"]))
    step = next(s for s in steps if s["slug"] == slug)
    if step["type"] != "text":
        await msg.answer("Используйте кнопки под сообщением анкеты.")
        return

    mx = int((step.get("config") or {}).get("max_length") or 500)
    text = msg.text.strip()
    if len(text) > mx:
        await msg.answer(f"Слишком длинно. Максимум {mx} символов.")
        return

    answers = dict(draft["answers"])
    answers[slug] = text
    await booking_svc.save_answers_partial(conn, booking_id, uid, answers, slug)
    await render_questionnaire_step(msg, conn, booking_id, uid, settings=settings, state=state)


@client_router.message(StateFilter(BookingFlow.questionnaire_photos), F.photo)
async def question_photo_collect(msg: Message, state: FSMContext, conn, settings: Settings) -> None:
    data = await state.get_data()
    booking_id = int(data["booking_id"])
    slug = str(data.get("photo_slug"))
    max_n = int(data.get("photo_max") or 5)
    items: list[str] = list(data.get("photo_items") or [])

    photo = msg.photo[-1]
    size = int(photo.file_size or 0)
    if size > 5 * 1024 * 1024:
        await msg.answer("Файл больше 5 MB. Пришлите другое фото.")
        return

    if len(items) >= max_n:
        await msg.answer("Достигнут лимит фото для этого шага.")
        return

    items.append(photo.file_id)
    await state.update_data(photo_items=items)
    await msg.answer(f"Фото добавлено ({len(items)}/{max_n}). Нажмите «Готово», когда закончите.")

