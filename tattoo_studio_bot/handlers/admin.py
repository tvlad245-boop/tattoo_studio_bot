from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from tattoo_studio_bot.config import Settings, is_admin
from tattoo_studio_bot.db.database import set_setting
from tattoo_studio_bot.handlers.ui_media import (
    SETTING_PHOTO_ABOUT,
    SETTING_PHOTO_MAIN,
    SETTING_PHOTO_PRICE,
)
from tattoo_studio_bot.services import master_svc, slot_svc
from tattoo_studio_bot.services.settings_svc import get_timezone
from tattoo_studio_bot.utils.admin_calendar_kb import admin_calendar_hint, build_admin_month_keyboard
from tattoo_studio_bot.utils.calendar_kb import parse_compact_date, parse_compact_month
from tattoo_studio_bot.utils.callbacks import cb_admin

logger = logging.getLogger(__name__)

admin_router = Router(name="admin")

SECTION_LABEL = {
    "main": "главного меню",
    "about": "раздела «О нас»",
    "price": "раздела «Прайс»",
}

SECTION_KEY: dict[str, str] = {
    "main": SETTING_PHOTO_MAIN,
    "about": SETTING_PHOTO_ABOUT,
    "price": SETTING_PHOTO_PRICE,
}


class AdminFlow(StatesGroup):
    waiting_section_photo = State()
    master_new_name = State()
    master_new_contact = State()
    master_edit_value = State()


def _master_card_kb(mid: int, *, active: bool) -> InlineKeyboardMarkup:
    toggle_txt = "🚫 Скрыть из записи" if active else "✅ Вернуть в запись"
    toggle_act = "0" if active else "1"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Имя",
                    callback_data=cb_admin(("tm", "e", str(mid), "n")),
                ),
                InlineKeyboardButton(
                    text="📇 Контакты",
                    callback_data=cb_admin(("tm", "e", str(mid), "c")),
                ),
            ],
            [
                InlineKeyboardButton(
                    text=toggle_txt,
                    callback_data=cb_admin(("tm", "e", str(mid), toggle_act)),
                )
            ],
            [InlineKeyboardButton(text="⬅ К списку", callback_data=cb_admin(("tm",)))],
        ]
    )


async def _masters_home_payload(conn) -> tuple[str, InlineKeyboardMarkup]:
    masters = await master_svc.list_all_masters(conn)
    lines = [
        "<b>Тату-мастера</b>",
        "",
        "Клиенты видят только активных мастеров. Имена и контакты подтягиваются из этой таблицы при каждом открытии экрана записи.",
    ]
    rows: list[list[InlineKeyboardButton]] = []
    for m in masters:
        icon = "✅" if int(m["active"]) else "🚫"
        label = f'{icon} {str(m["display_name"])[:36]}'
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=cb_admin(("tm", "v", str(int(m["id"])))),
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="➕ Добавить мастера", callback_data=cb_admin(("tm", "add")))])
    rows.append([InlineKeyboardButton(text="⬅ В панель", callback_data=cb_admin(("home",)))])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


async def _master_card_payload(conn, mid: int) -> tuple[str, InlineKeyboardMarkup] | None:
    masters = await master_svc.list_all_masters(conn)
    m = next((x for x in masters if int(x["id"]) == mid), None)
    if not m:
        return None
    safe_name = html.escape(str(m["display_name"]))
    safe_contact = html.escape(str(m["contact_for_client"]))
    active = bool(int(m["active"]))
    text = (
        f"<b>Мастёр #{mid}</b>\n\n"
        f"Имя: {safe_name}\n"
        f"Контакты:\n{safe_contact}\n\n"
        f"Статус: {'в записи' if active else 'скрыт'}"
    )
    return text, _master_card_kb(mid, active=active)


async def _render_admin_calendar(cb: CallbackQuery, conn, settings: Settings, ym_token: str | None) -> None:
    tz = await get_timezone(conn, settings.default_timezone)
    if ym_token:
        year, month = parse_compact_month(ym_token)
    else:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        today = datetime.now(ZoneInfo(tz)).date()
        year, month = today.year, today.month

    closed = await slot_svc.list_closed_days_in_month(conn, year, month)
    kb = build_admin_month_keyboard(year, month, tz, closed_dates=closed)
    body = admin_calendar_hint(tz)
    await cb.message.edit_text(body, parse_mode="HTML", reply_markup=kb)


async def _route_admin_calendar(
    cb: CallbackQuery,
    conn,
    settings: Settings,
    parts: list[str],
) -> None:
    if len(parts) == 2:
        await _render_admin_calendar(cb, conn, settings, None)
        await cb.answer()
        return

    if len(parts) >= 4 and parts[2] == "m":
        ym = parts[3]
        await _render_admin_calendar(cb, conn, settings, ym)
        await cb.answer()
        return

    if len(parts) >= 4 and parts[2] == "t":
        compact = parts[3]
        picked = parse_compact_date(compact)
        now_closed = await slot_svc.toggle_work_day_closed(conn, picked)
        ym_token = f"{picked.year}{picked.month:02d}"
        await _render_admin_calendar(cb, conn, settings, ym_token)
        await cb.answer("🔒 Закрыто" if now_closed else "✓ Открыто")
        return

    await cb.answer()


async def _route_admin_masters(
    cb: CallbackQuery,
    state: FSMContext,
    conn,
    settings: Settings,
    parts: list[str],
) -> None:
    if len(parts) == 2:
        await state.clear()
        text, kb = await _masters_home_payload(conn)
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await cb.answer()
        return

    if len(parts) >= 3 and parts[2] == "add":
        await state.set_state(AdminFlow.master_new_name)
        await state.update_data()
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅ Отмена", callback_data=cb_admin(("tm",)))],
            ]
        )
        await cb.message.edit_text(
            "<b>Новый мастер</b>\n\nВведите отображаемое имя (как увидят клиенты).\n<b>/cancel</b> — отмена.",
            parse_mode="HTML",
            reply_markup=kb,
        )
        await cb.answer()
        return

    if len(parts) >= 4 and parts[2] == "v":
        mid = int(parts[3])
        payload = await _master_card_payload(conn, mid)
        if payload is None:
            await cb.answer("Не найден.", show_alert=True)
            return
        text, kb = payload
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await cb.answer()
        return

    if len(parts) >= 5 and parts[2] == "e":
        mid = int(parts[3])
        kind = parts[4]
        if kind in ("0", "1"):
            await master_svc.update_master(conn, mid, active=int(kind))
            payload = await _master_card_payload(conn, mid)
            if payload is None:
                await cb.answer("Не найден.", show_alert=True)
                return
            text, kb = payload
            await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
            await cb.answer("Сохранено.")
            return

        if kind == "n":
            await state.set_state(AdminFlow.master_edit_value)
            await state.update_data(edit_mid=mid, edit_field="name")
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅ Отмена", callback_data=cb_admin(("tm", "v", str(mid))))],
                ]
            )
            await cb.message.edit_text(
                "<b>Имя мастера</b>\n\nВведите новое значение.\n<b>/cancel</b> — отмена.",
                parse_mode="HTML",
                reply_markup=kb,
            )
            await cb.answer()
            return

        if kind == "c":
            await state.set_state(AdminFlow.master_edit_value)
            await state.update_data(edit_mid=mid, edit_field="contact")
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅ Отмена", callback_data=cb_admin(("tm", "v", str(mid))))],
                ]
            )
            await cb.message.edit_text(
                "<b>Контакты для клиента</b>\n\nМожно HTML и ссылки.\n<b>/cancel</b> — отмена.",
                parse_mode="HTML",
                reply_markup=kb,
            )
            await cb.answer()
            return

    await cb.answer()


def _admin_root_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📅 Дни записи", callback_data=cb_admin(("cal",)))],
            [InlineKeyboardButton(text="✍️ Тату-мастера", callback_data=cb_admin(("tm",)))],
            [InlineKeyboardButton(text="🖼 Картинки разделов", callback_data=cb_admin(("img",)))],
        ]
    )


def _admin_images_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🏠 Главное меню",
                    callback_data=cb_admin(("img", "m", "main")),
                )
            ],
            [
                InlineKeyboardButton(
                    text="ℹ️ О нас",
                    callback_data=cb_admin(("img", "m", "about")),
                )
            ],
            [
                InlineKeyboardButton(
                    text="💰 Прайс",
                    callback_data=cb_admin(("img", "m", "price")),
                )
            ],
            [InlineKeyboardButton(text="⬅ В панель", callback_data=cb_admin(("home",)))],
        ]
    )


@admin_router.message(Command("admin"))
async def admin_entry(msg: Message, settings: Settings, state: FSMContext) -> None:
    if msg.from_user is None:
        return
    if not is_admin(msg.from_user.id, settings):
        await msg.answer("Нет доступа.")
        return

    await state.clear()
    await msg.answer(
        "<b>Админ-панель</b>\n\nВыберите раздел:",
        parse_mode="HTML",
        reply_markup=_admin_root_kb(),
    )


@admin_router.message(
    Command("cancel"),
    StateFilter(
        AdminFlow.waiting_section_photo,
        AdminFlow.master_new_name,
        AdminFlow.master_new_contact,
        AdminFlow.master_edit_value,
    ),
)
async def admin_cancel_any(msg: Message, state: FSMContext, settings: Settings, conn) -> None:
    if msg.from_user is None or not is_admin(msg.from_user.id, settings):
        return
    snap = await state.get_state()
    await state.clear()
    if snap == AdminFlow.waiting_section_photo.state:
        await msg.answer("Загрузка отменена.", reply_markup=_admin_images_kb())
        return
    if snap in (
        AdminFlow.master_new_name.state,
        AdminFlow.master_new_contact.state,
        AdminFlow.master_edit_value.state,
    ):
        text, kb = await _masters_home_payload(conn)
        await msg.answer(
            "Отменено.\n\n" + text,
            parse_mode="HTML",
            reply_markup=kb,
        )
        return


@admin_router.callback_query(F.data.startswith("a|"))
async def admin_dispatch(cb: CallbackQuery, state: FSMContext, conn, settings: Settings) -> None:
    if cb.from_user is None or not is_admin(cb.from_user.id, settings):
        await cb.answer("Нет доступа.", show_alert=True)
        return

    parts = cb.data.split("|")
    if parts[0] != "a":
        await cb.answer()
        return

    if parts[1] == "noop":
        await cb.answer()
        return

    if parts[1] == "home":
        await state.clear()
        await cb.message.edit_text(
            "<b>Админ-панель</b>\n\nВыберите раздел:",
            parse_mode="HTML",
            reply_markup=_admin_root_kb(),
        )
        await cb.answer()
        return

    if parts[1] == "cal":
        await _route_admin_calendar(cb, conn, settings, parts)
        return

    if parts[1] == "tm":
        await _route_admin_masters(cb, state, conn, settings, parts)
        return

    if parts[1] == "img" and len(parts) == 2:
        await state.clear()
        await cb.message.edit_text(
            "<b>Картинки экранов</b>\n\n"
            "Выберите раздел — бот попросит фото. Пришлите <b>одно изображение</b>.\n\n"
            "Можно сбросить картинку кнопкой «Сбросить» на шаге ожидания или командой после выбора.",
            parse_mode="HTML",
            reply_markup=_admin_images_kb(),
        )
        await cb.answer()
        return

    if parts[1] == "img" and parts[2] == "m" and len(parts) >= 4:
        section = parts[3]
        if section not in SECTION_KEY:
            await cb.answer("Неизвестный раздел.", show_alert=True)
            return
        await state.set_state(AdminFlow.waiting_section_photo)
        await state.update_data(photo_setting_key=SECTION_KEY[section])
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🗑 Сбросить эту картинку",
                        callback_data=cb_admin(("img", "x", section)),
                    )
                ],
                [InlineKeyboardButton(text="⬅ Назад", callback_data=cb_admin(("img",)))],
            ]
        )
        await cb.message.edit_text(
            f"<b>Фото для {SECTION_LABEL[section]}</b>\n\n"
            "Пришлите изображение.\n"
            "<b>/cancel</b> — отменить.",
            parse_mode="HTML",
            reply_markup=kb,
        )
        await cb.answer()
        return

    if parts[1] == "img" and parts[2] == "x" and len(parts) >= 4:
        section = parts[3]
        if section not in SECTION_KEY:
            await cb.answer()
            return
        key = SECTION_KEY[section]
        await set_setting(conn, key, "")
        await state.clear()
        await cb.message.edit_text(
            f"Картинка для {SECTION_LABEL[section]} удалена из настроек.",
            parse_mode="HTML",
            reply_markup=_admin_images_kb(),
        )
        await cb.answer("Готово.")
        return

    await cb.answer()


@admin_router.message(StateFilter(AdminFlow.waiting_section_photo), F.photo)
async def admin_receive_photo(msg: Message, state: FSMContext, conn, settings: Settings) -> None:
    if msg.from_user is None or not is_admin(msg.from_user.id, settings):
        return
    data = await state.get_data()
    key = str(data.get("photo_setting_key") or "")
    if not key:
        await state.clear()
        await msg.answer("Состояние сброшено. Откройте /admin.")
        return

    file_id = msg.photo[-1].file_id
    await set_setting(conn, key, file_id)
    await state.clear()
    await msg.answer(
        "✅ Картинка сохранена. Проверьте в клиентском меню.",
        reply_markup=_admin_images_kb(),
    )


@admin_router.message(StateFilter(AdminFlow.master_new_name), F.text & ~F.text.startswith("/"))
async def admin_receive_master_name(msg: Message, state: FSMContext, conn, settings: Settings) -> None:
    if msg.from_user is None or not is_admin(msg.from_user.id, settings):
        return
    raw = (msg.text or "").strip()
    if not raw:
        await msg.answer("Введите непустое имя.")
        return
    await state.update_data(new_master_name=raw)
    await state.set_state(AdminFlow.master_new_contact)
    await msg.answer(
        "Контакты для клиента (можно HTML):\n<b>/cancel</b> — отмена.",
        parse_mode="HTML",
    )


@admin_router.message(StateFilter(AdminFlow.master_new_contact), F.text & ~F.text.startswith("/"))
async def admin_receive_master_contact(msg: Message, state: FSMContext, conn, settings: Settings) -> None:
    if msg.from_user is None or not is_admin(msg.from_user.id, settings):
        return
    data = await state.get_data()
    name = str(data.get("new_master_name") or "").strip()
    contact = (msg.text or "").strip()
    await master_svc.create_master(conn, name, contact)
    await state.clear()
    text, kb = await _masters_home_payload(conn)
    await msg.answer("✅ Мастер добавлен.", parse_mode="HTML")
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)


@admin_router.message(StateFilter(AdminFlow.master_edit_value), F.text & ~F.text.startswith("/"))
async def admin_receive_master_edit(msg: Message, state: FSMContext, conn, settings: Settings) -> None:
    if msg.from_user is None or not is_admin(msg.from_user.id, settings):
        return
    data = await state.get_data()
    mid = int(data.get("edit_mid") or 0)
    field = str(data.get("edit_field") or "")
    val = (msg.text or "").strip()
    if field == "name":
        await master_svc.update_master(conn, mid, display_name=val)
    elif field == "contact":
        await master_svc.update_master(conn, mid, contact_for_client=val)
    await state.clear()
    payload = await _master_card_payload(conn, mid)
    if payload is None:
        await msg.answer("Сохранено.")
        return
    text, kb = payload
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)
