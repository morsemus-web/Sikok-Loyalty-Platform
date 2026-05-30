from datetime import datetime, timedelta, timezone, date
from typing import Optional

from .config import settings

IST = timezone(timedelta(minutes=settings.ist_offset_minutes))


def now_ist() -> datetime:
    return datetime.now(IST)


def to_ist(dt: Optional[datetime]) -> Optional[datetime]:
    """Convert any datetime to IST. Naive values are assumed UTC (Postgres default)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST)


def ist_date(dt: Optional[datetime]) -> Optional[date]:
    ist = to_ist(dt)
    return ist.date() if ist else None


def is_same_ist_day(a: Optional[datetime], b: Optional[datetime]) -> bool:
    da, db = ist_date(a), ist_date(b)
    return da is not None and db is not None and da == db


_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def format_ist(dt: Optional[datetime]) -> str:
    """Portable IST formatter — works on Windows and POSIX. e.g. '30 May 2026, 3:47 PM IST'."""
    ist = to_ist(dt)
    if ist is None:
        return ""
    hour12 = ist.hour % 12 or 12
    ampm = "AM" if ist.hour < 12 else "PM"
    return f"{ist.day} {_MONTHS[ist.month - 1]} {ist.year}, {hour12}:{ist.minute:02d} {ampm} IST"
