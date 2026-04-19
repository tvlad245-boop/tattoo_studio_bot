from __future__ import annotations

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


def _admin_root_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
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


@admin_router.message(Command("cancel"), StateFilter(AdminFlow.waiting_section_photo))
async def admin_cancel_upload(msg: Message, state: FSMContext, settings: Settings) -> None:
    if msg.from_user is None or not is_admin(msg.from_user.id, settings):
        return
    await state.clear()
    await msg.answer(
        "Загрузка отменена.",
        reply_markup=_admin_images_kb(),
    )


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
