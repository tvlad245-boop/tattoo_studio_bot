from __future__ import annotations

from enum import Enum


class BookingStatus(str, Enum):
    draft = "draft"
    pending_confirm = "pending_confirm"
    awaiting_payment = "awaiting_payment"
    confirmed = "confirmed"
    completed = "completed"
    cancelled = "cancelled"
    no_show = "no_show"


def statuses_blocking_slot() -> tuple[BookingStatus, ...]:
    """Занятость «одно место» (§8): слот закрыт, если есть заявка в этих статусах."""
    return (
        BookingStatus.pending_confirm,
        BookingStatus.awaiting_payment,
        BookingStatus.confirmed,
    )


class QuestionnaireStepType(str, Enum):
    choice = "choice"
    choice_with_other = "choice_with_other"
    text = "text"
    photos = "photos"
