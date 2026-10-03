"""Time helpers: everything is stored in UTC and presented in settings.TIME_ZONE."""
from datetime import datetime, time, timedelta

from django.utils import timezone


def local(dt):
    """Convert an aware datetime to the plant's local time (naive values are assumed local)."""
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return dt
    return timezone.localtime(dt)


def local_str(dt, fmt='%H:%M'):
    dt = local(dt)
    return dt.strftime(fmt) if dt else ''


def local_day_bounds(day):
    """Aware [start, end) datetimes covering one local calendar day."""
    start = timezone.make_aware(datetime.combine(day, time.min))
    return start, start + timedelta(days=1)


def local_range_bounds(start_day, end_day):
    """Aware [start, end) datetimes covering local days start_day..end_day inclusive."""
    start = timezone.make_aware(datetime.combine(start_day, time.min))
    end = timezone.make_aware(datetime.combine(end_day, time.min)) + timedelta(days=1)
    return start, end


def ensure_aware(dt):
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt)
    return dt


def period_start(day, period_type):
    """First day of the aggregation period that contains ``day``."""
    if period_type == 'weekly':
        return day - timedelta(days=day.weekday())
    if period_type == 'monthly':
        return day.replace(day=1)
    if period_type == '3monthly':
        return day.replace(month=((day.month - 1) // 3) * 3 + 1, day=1)
    if period_type == '6monthly':
        return day.replace(month=1 if day.month <= 6 else 7, day=1)
    if period_type == 'yearly':
        return day.replace(month=1, day=1)
    return day


def period_end(start, period_type):
    """First day after the period that begins at ``start``."""
    if period_type == 'weekly':
        return start + timedelta(days=7)
    if period_type in ('monthly', '3monthly', '6monthly'):
        months = {'monthly': 1, '3monthly': 3, '6monthly': 6}[period_type]
        month_index = start.month - 1 + months
        return start.replace(year=start.year + month_index // 12, month=month_index % 12 + 1, day=1)
    if period_type == 'yearly':
        return start.replace(year=start.year + 1, month=1, day=1)
    return start + timedelta(days=1)
