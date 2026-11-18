from datetime import datetime

from app.models import Slot


def parse_date(text):
    """'2026-09-01' -> date object, or None if the text is not a valid date."""
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def parse_time(text):
    """'14:30' -> time object, or None if invalid."""
    try:
        return datetime.strptime(text, "%H:%M").time()
    except (TypeError, ValueError):
        return None


def parse_int(text):
    """'12' -> 12, or None if the text is not a whole number."""
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def examiner_has_clash(examiner_id, slot_date, start, end, ignore_slot_id=None):
    """True if this examiner already has a live slot overlapping the given time."""
    others = Slot.query.filter(
        Slot.examiner_id == examiner_id,
        Slot.slot_date == slot_date,
        Slot.status != "Cancelled",
    ).all()
    for other in others:
        if other.id == ignore_slot_id:
            continue
        if start < other.end_time and other.start_time < end:
            return True
    return False