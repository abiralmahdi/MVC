from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from dashboard.measurements import METER_DEFINITIONS, order_measurements
from utils.access import can_access_site, is_manager, visible_sites
from utils.decorators import subscription_required

from .models import Alarms, AlarmsRange, Measurements, Meters


def _alarm_color(alarm):
    if alarm.acknowledged:
        return "#6c9f6c"
    if "high" in alarm.alarmType.lower():
        return "#ff4d4d"
    if "low" in alarm.alarmType.lower():
        return "rgb(230, 200, 40)"
    return "white"


@login_required
@subscription_required
def allAlarms(request):
    show = request.GET.get('show', 'active')
    alarms = Alarms.objects.filter(meter__area__building__site__in=visible_sites(request.user)).select_related(
        'meter__area__building__site', 'measurement', 'acknowledgedBy'
    )
    if show == 'active':
        alarms = alarms.filter(acknowledged=False)
    alarms = alarms.order_by('acknowledged', '-date')

    page = Paginator(alarms, 200).get_page(request.GET.get('page'))
    for alarm in page:
        alarm.color = _alarm_color(alarm)

    return render(request, 'activeAlarms.html', {
        "alarms": page,
        "page": page,
        "show": show,
        "active_count": Alarms.objects.filter(
            meter__area__building__site__in=visible_sites(request.user), acknowledged=False
        ).count(),
    })


def _measurement_names_for(meter):
    names = set((meter.registerMapping or {}).keys())
    names.update(meter.measurements.values_list('name', flat=True))
    if not names:
        names.update(METER_DEFINITIONS.get(meter.meterType, []))
    return order_measurements(names)


@login_required
@subscription_required
def setAlarmRange(request):
    sites = visible_sites(request.user).prefetch_related('buildings__areas__meters')
    meters = Meters.objects.filter(area__building__site__in=sites)
    ranges = {}
    for r in AlarmsRange.objects.filter(meter__in=meters).select_related('measurement'):
        ranges[(r.meter_id, r.measurement.name)] = r

    meter_rows = {}
    for meter in meters.select_related('area__building'):
        meter_rows[meter.id] = [
            {
                'name': name,
                'min': ranges.get((meter.id, name)).minValue if (meter.id, name) in ranges else None,
                'max': ranges.get((meter.id, name)).maxValue if (meter.id, name) in ranges else None,
            }
            for name in _measurement_names_for(meter)
        ]
    for site in sites:
        for building in site.buildings.all():
            for area in building.areas.all():
                for meter in area.meters.all():
                    meter.range_rows = meter_rows.get(meter.id, [])
                    meter.configured_ranges = sum(1 for row in meter.range_rows if row['min'] is not None or row['max'] is not None)

    return render(request, 'setAlarmRange.html', {
        "sites": sites,
        "can_edit": is_manager(request.user),
    })


def _parse_limit(value):
    value = (value or '').strip()
    if value == '':
        return None
    return float(value)


@login_required
@subscription_required
@require_POST
def setRange(request, meterID):
    meter = get_object_or_404(Meters.objects.select_related('area__building__site'), id=meterID)
    if not (is_manager(request.user) and can_access_site(request.user, meter.area.building.site if meter.area else None)):
        messages.error(request, "You are not authorized to change alarm limits for this meter.")
        return redirect('/alarms/setAlarmRange/')

    count = 0
    errors = []
    with transaction.atomic():
        index = 0
        while f'name_{index}' in request.POST:
            name = request.POST.get(f'name_{index}')
            try:
                min_value = _parse_limit(request.POST.get(f'min_{index}'))
                max_value = _parse_limit(request.POST.get(f'max_{index}'))
            except ValueError:
                errors.append(f"{name}: limits must be numbers.")
                index += 1
                continue
            if min_value is not None and max_value is not None and min_value >= max_value:
                errors.append(f"{name}: minimum must be lower than maximum.")
                index += 1
                continue

            existing = AlarmsRange.objects.filter(meter=meter, measurement__name=name)
            if min_value is None and max_value is None:
                existing.delete()
            else:
                measurement = (
                    Measurements.objects.filter(meter=meter, name=name).first()
                    or Measurements.objects.create(name=name, meter=meter)
                )
                range_obj = existing.first() or AlarmsRange(meter=meter, measurement=measurement)
                existing.exclude(pk=range_obj.pk).delete()
                range_obj.minValue = min_value
                range_obj.maxValue = max_value
                range_obj.save()
                count += 1
            index += 1

    for error in errors:
        messages.error(request, error)
    messages.success(request, f"Alarm limits saved for {meter.name} ({count} active).")
    return redirect('/alarms/setAlarmRange/')


@login_required
@subscription_required
@require_POST
def ackAlarm(request, alarmID):
    alarm = get_object_or_404(Alarms.objects.select_related('meter__area__building__site'), id=alarmID)
    site = alarm.meter.area.building.site if alarm.meter.area else None
    if not can_access_site(request.user, site):
        messages.error(request, "You are not authorized to acknowledge this alarm.")
    elif not alarm.acknowledged:
        alarm.acknowledged = True
        alarm.acknowledgedBy = request.user
        alarm.acknowledgedAt = timezone.now()
        alarm.save(update_fields=['acknowledged', 'acknowledgedBy', 'acknowledgedAt'])
    return redirect(request.POST.get('next') or '/alarms/allAlarms')


@login_required
@subscription_required
@require_POST
def ackAllAlarms(request):
    alarms = Alarms.objects.filter(meter__area__building__site__in=visible_sites(request.user), acknowledged=False)
    count = alarms.update(acknowledged=True, acknowledgedBy=request.user, acknowledgedAt=timezone.now())
    messages.success(request, f"{count} alarms acknowledged.")
    return redirect('/alarms/allAlarms')


@login_required
@subscription_required
@require_POST
def changeAlarmDesc(request, alarmID):
    alarm = get_object_or_404(Alarms.objects.select_related('meter__area__building__site'), id=alarmID)
    site = alarm.meter.area.building.site if alarm.meter.area else None
    if not can_access_site(request.user, site):
        messages.error(request, "You are not authorized to edit this alarm.")
    else:
        alarm.desc = (request.POST.get('desc') or '')[:1000]
        alarm.save(update_fields=['desc'])
    return redirect('/alarms/allAlarms')
