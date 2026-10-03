"""Email notifications for alarms and machine-health alerts.

Recipients for an event at a site are: every superuser, every user with the
Administrator role, and every user assigned to that site. Emails are sent from a
background thread and never raise, so they cannot slow down or break the poller
or the scoring run. When no SMTP host is configured the console email backend is
used, so messages are printed to the server log in development.
"""
import logging
import threading

from django.conf import settings

logger = logging.getLogger('home')

ADMIN_ROLE = 'Administrator'


def _enabled():
    return getattr(settings, 'NOTIFICATIONS_ENABLED', True)


def recipients_for_site(site):
    """[(email, name)] of superusers, Administrators and users of ``site`` (de-duplicated)."""
    from accounts.models import UserModel

    site_id = getattr(site, 'pk', None)
    seen, out = set(), []
    for um in UserModel.objects.select_related('user'):
        user = um.user
        relevant = (user and user.is_superuser) or (um.role == ADMIN_ROLE) or (site_id and um.site_id == site_id)
        if not relevant:
            continue
        email = (um.email or (user.email if user else '') or (user.username if user else '')).strip()
        if '@' not in email or email.lower() in seen:
            continue
        seen.add(email.lower())
        out.append((email, um.name or email))
    return out


def _send(subject, body, recipients):
    """Send one email to the recipients from a daemon thread; swallow every error."""
    if not _enabled() or not recipients:
        return
    addresses = [email for email, _ in recipients]

    def worker():
        try:
            from django.core.mail import send_mail
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, addresses, fail_silently=True)
            logger.info('Notification sent: %s -> %d recipient(s)', subject, len(addresses))
        except Exception:
            logger.exception('Failed to send notification email: %s', subject)

    threading.Thread(target=worker, daemon=True).start()


# ---------------------------------------------------------------- alarms
def _alarm_site(alarm):
    area = getattr(alarm.meter, 'area', None)
    return area.building.site if area else None


def _alarm_location(alarm):
    area = getattr(alarm.meter, 'area', None)
    return f"{area.building.site.name} / {area.building.name} / {area.name}" if area else '—'


def notify_alarms(alarms):
    """Email the relevant authorities about newly raised alarms (grouped per site)."""
    if not _enabled() or not alarms:
        return
    by_site = {}
    for alarm in alarms:
        by_site.setdefault(_alarm_site(alarm), []).append(alarm)

    for site, site_alarms in by_site.items():
        recipients = recipients_for_site(site)
        if not recipients:
            continue
        site_name = site.name if site else 'the plant'
        subject = (f"[MarksVision] Alarm: {site_alarms[0].meter.name} - {site_alarms[0].measurement.name}"
                   if len(site_alarms) == 1 else f"[MarksVision] {len(site_alarms)} new alarms at {site_name}")
        lines = [f"New alarm(s) at {site_name}:", '']
        for a in site_alarms:
            lines.append(f"  • {a.meter.name} - {a.measurement.name}: {a.alarmType} ({a.desc})")
            lines.append(f"    value {a.value} · {_alarm_location(a)}")
        lines += ['', 'Open MarksVision > Alarms to review and acknowledge.',
                  '', 'This is an automated message from MarksVision.']
        _send(subject, '\n'.join(lines), recipients)


# ---------------------------------------------------------------- machine health
def _health_target(health):
    """(name, site, location) of the meter or motor behind a DeviceHealth row."""
    if health.meter_id:
        meter = health.meter
        area = getattr(meter, 'area', None)
        site = area.building.site if area else None
        location = f"{area.building.name} / {area.name}" if area else '—'
        return meter.name or 'Meter', site, location
    motor = health.motor
    building = getattr(motor, 'building', None)
    site = building.site if building else None
    return motor.motorName, site, (building.name if building else '—')


def notify_health(health, previous_risk=None):
    """Email the relevant authorities when a machine becomes high/medium risk."""
    if not _enabled() or health.risk not in ('high', 'medium'):
        return
    name, site, location = _health_target(health)
    recipients = recipients_for_site(site)
    if not recipients:
        return
    lifespan = None if health.health_score is None else max(0, min(100, 100 - health.health_score))
    if health.days_to_maintenance is None:
        days = 'unknown'
    elif health.days_to_maintenance >= 30:
        days = '30+ days'
    else:
        days = f"about {round(health.days_to_maintenance)} days"
    level = health.get_risk_display()
    subject = f"[MarksVision] Machine health {level}: {name}"
    lines = [
        f"The predictive-maintenance model has flagged a machine as {level.upper()} risk.",
        '',
        f"  Machine:            {name}",
        f"  Location:           {site.name if site else 'the plant'} / {location}",
        f"  Risk (next 7 days): {level}"
        + (f" ({round((health.failure_probability or 0) * 100)}% probability)" if health.failure_probability is not None else ''),
        f"  Lifespan elapsed:   {lifespan}%" if lifespan is not None else "  Lifespan elapsed:   unknown",
        f"  Estimated time to maintenance: {days}",
    ]
    if health.failure_mode:
        lines.append(f"  Likely issue:       {health.failure_mode}")
    if health.drivers:
        drivers = ', '.join(d.get('label') for d in health.drivers if d.get('label'))
        if drivers:
            lines.append(f"  Main signals:       {drivers}")
    lines += ['', 'Open MarksVision > Machine Learning to review the device.',
              '', 'This is an automated message from MarksVision.']
    _send(subject, '\n'.join(lines), recipients)
