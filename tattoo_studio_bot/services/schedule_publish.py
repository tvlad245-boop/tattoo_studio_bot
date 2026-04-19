"""
Публикация расписания в группу мастера (§3.4).

Идемпотентность: хранить schedule_message_id на паре (master_id, schedule_chat_id);
при ошибке редактирования отправлять новое сообщение и обновлять id.

Реализация подключается из воркера/cron после стабилизации заявок и слотов.
"""

from __future__ import annotations


async def publish_master_schedule_stub(*_args: object, **_kwargs: object) -> None:
    """Заглушка: логика вынесена в сервис, хендлеры остаются тонкими."""
    return None
