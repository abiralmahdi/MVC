import calendar
import logging
from collections import defaultdict
from datetime import date as date_cls, datetime, timedelta

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db.models import Min, Prefetch
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from alarms.models import Alarms
from utils.access import (
    ROLES,
    admin_required,
    can_access_site,
    get_role,
    is_admin,
    json_login_required,
    superuser_required,
    visible_sites,
)
from utils.decorators import subscription_required
from utils.timeutils import ensure_aware, local_day_bounds, local_str, period_end, period_start

from .aggregation import fold_readings, hourly_profile, meter_rows, summarize_meter_period
from .measurements import is_cumulative, is_intensive, order_measurements, to_number
from .models import (
    Areas,
    Buildings,
    Dashboard,
    Gadgets,
    GlobalConfiguration,
    HierarchyDataAggregate,
    LatestMeterReading,
    LoadType,
    Measurements,
    MeterReading,
    MeterReadingAggregate,
    Meters,
    Site,
)

logger = logging.getLogger('dashboard')

GADGET_TYPES = ["pie", "bar", "line", "table", "tool", "sankey", "heatmap", "picturemap", "multiple-meter-table", "valueCard", "machineHealth"]
PERIOD_TYPES = ["daily", "weekly", "monthly", "3monthly", "6monthly", "yearly"]
# Kept for templates that still refer to it.
ACCESS_CONSTROL = ROLES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def json_error(message, status=400):
    return JsonResponse({'error': message}, status=status)


def can_view_gadget(user, gadget):
    if user.is_superuser:
        return True
    return get_role(user) in (gadget.access or [])


def get_dashboard_for(request, dashboard_id):
    dashboard_ = get_object_or_404(Dashboard.objects.select_related('site'), id=dashboard_id)
    if not can_access_site(request.user, dashboard_.site):
        raise Http404("Dashboard not found")
    return dashboard_


def get_gadget_for(request, dashboard_id, gadget_id):
    """Gadget of a dashboard the user may see (prevents reading other sites' data by id)."""
    dashboard_ = get_dashboard_for(request, dashboard_id)
    gadget = get_object_or_404(
        Gadgets.objects.prefetch_related('meters', 'measurement'), id=gadget_id, dashboard=dashboard_
    )
    if not can_view_gadget(request.user, gadget):
        raise Http404("Gadget not found")
    return dashboard_, gadget


def gadget_endpoint(view_func):
    """JSON endpoint: login + subscription + dashboard/gadget authorisation, errors as JSON."""
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return json_error('Authentication required', 401)
        if not GlobalConfiguration.load().subscribed:
            return json_error('Subscription revoked', 403)
        try:
            return view_func(request, *args, **kwargs)
        except Http404 as exc:
            return json_error(str(exc) or 'Not found', 404)
    _wrapped.__name__ = view_func.__name__
    _wrapped.__doc__ = view_func.__doc__
    return _wrapped


def parse_iso_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def measurement_units(names):
    units = {}
    for measurement in Measurements.objects.filter(name__in=names).prefetch_related('units'):
        unit = next((u.name for u in measurement.units.all() if u.name), None)
        if unit and measurement.name not in units:
            units[measurement.name] = unit
    return units


def reading_points(meter, limit):
    """Latest ``limit`` readings of a meter, oldest first."""
    rows = list(
        MeterReading.objects.filter(meter=meter).order_by('-timestamp').values_list('timestamp', 'data')[:limit]
    )
    rows.reverse()
    return rows


def serialize_point(meter_id, timestamp, data, names=None):
    return {
        'meter_id': meter_id,
        'timestamp': local_str(timestamp, '%H:%M:%S'),
        'ts': int(timestamp.timestamp() * 1000),
        'data': {k: v for k, v in (data or {}).items() if names is None or k in names},
    }


def format_custom_date(date_obj):
    day = date_obj.day
    suffix = 'th' if 11 <= day <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
    return date_obj.strftime(f"%A - {day}{suffix} %B, %Y")


def measurement_choices():
    """One Measurements row per distinct name, in display order."""
    first_ids = Measurements.objects.values('name').annotate(first_id=Min('id'))
    by_name = {row['name']: row['first_id'] for row in first_ids}
    return [{'id': by_name[name], 'name': name} for name in order_measurements(by_name.keys())]


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@login_required
@subscription_required
def dashboard(request):
    sites = visible_sites(request.user).prefetch_related('dashboard__gadgets')
    context = {
        'sites': sites,
    }
    return render(request, 'dashboard.html', context)


@login_required
@subscription_required
def siteDashbaord(request, siteID):
    site = get_object_or_404(Site, id=siteID)
    if not can_access_site(request.user, site):
        return redirect('/dashboard')
    dashboard_ = Dashboard.objects.filter(site=site).order_by('id').first()
    if dashboard_ is None:
        messages.info(request, f"No dashboard has been created for {site.name} yet.")
        return redirect('/dashboard')
    return redirect(f'/dashboard/{dashboard_.id}')


@login_required
@subscription_required
def indivDashboard(request, dashboardID):
    if not str(dashboardID).isdigit():
        raise Http404("Dashboard not found")
    dashboard_ = get_object_or_404(Dashboard.objects.select_related('site'), id=dashboardID)
    if not can_access_site(request.user, dashboard_.site):
        messages.error(request, "You are not authorized to view that dashboard.")
        return redirect('/dashboard')

    config = GlobalConfiguration.load()
    site = dashboard_.site
    sites = visible_sites(request.user).prefetch_related('dashboard', 'buildings__areas__meters')

    areas = Areas.objects.filter(building__site=site).select_related('building').prefetch_related('meters')
    meters = Meters.objects.filter(area__building__site=site).select_related('loadType', 'area__building')
    choices = measurement_choices()

    all_gadgets = Gadgets.objects.filter(dashboard=dashboard_).select_related('building').prefetch_related(
        'meters', 'measurement__units'
    ).order_by('id')
    gadgets = [g for g in all_gadgets if can_view_gadget(request.user, g)]

    gadget_configs = []
    for g in gadgets:
        names = order_measurements(m.name for m in g.measurement.all())
        g.ordered_measurements = names
        g.measurement_names = names
        g.meter_ids = [m.id for m in g.meters.all()]
        units = {}
        for m in g.measurement.all():
            unit = next((u.name for u in m.units.all() if u.name), None)
            if unit:
                units.setdefault(m.name, unit)
        gadget_configs.append({
            'id': g.id,
            'name': g.name,
            'type': g.gadget_type,
            'dashboardId': dashboard_.id,
            'siteId': site.id,
            'buildingId': g.building_id,
            'meters': [{'id': m.id, 'name': m.name, 'type': m.meterType} for m in g.meters.all()],
            'measurements': [{'id': m.id, 'name': m.name} for m in sorted(g.measurement.all(), key=lambda m: names.index(m.name))],
            'units': units,
        })

    alarms = Alarms.objects.filter(acknowledged=False, meter__in=meters).select_related(
        'meter__area__building', 'measurement'
    ).order_by('-date')[:50]
    for alarm in alarms:
        if "high" in alarm.alarmType.lower():
            alarm.color = "red"
        elif "low" in alarm.alarmType.lower():
            alarm.color = "rgb(230, 200, 40)"
        else:
            alarm.color = "white"

    load_types = LoadType.objects.prefetch_related(
        Prefetch('meters', queryset=Meters.objects.filter(area__building__site=site))
    )
    meter_types = sorted({m.meterType for m in meters if m.meterType})

    context = {
        'dashboard': dashboard_,
        'sites': sites,
        'gadgets': gadgets,
        'gadget_configs': gadget_configs,
        'areas': areas,
        'meters': meters,
        'measurements': choices,
        'gadgetTypes': GADGET_TYPES,
        'accessControl': ROLES,
        'alarms': alarms,
        'config': config,
        'globalConfig': config,
        'dateNow': format_custom_date(timezone.localdate()),
        'loadTypes': load_types,
        'meterTypes': meter_types,
        'today': timezone.localdate().isoformat(),
        'time_zone': settings.TIME_ZONE,
        'uses_echarts': any(g.gadget_type in ('sankey', 'heatmap') for g in gadgets),
    }
    return render(request, 'indivDashboard2.html', context)


@login_required
@subscription_required
@admin_required
def indivCentralDashboard(request):
    context = {
        "sites": Site.objects.all(),
        "measurement": "Total Active Power",
        "period_type": "monthly",
        "measurement_options": [
            "Energy", "Total Active Power", "Total Reactive Power", "Total Apparent Power",
            "Total Volume", "Total Gas Volume", "Total Steam", "Total Fuel Used",
            "CO2 Level", "PM2.5", "PM10",
        ],
    }
    return render(request, "indivCentralDashboard.html", context)


# ---------------------------------------------------------------------------
# JSON endpoints
# ---------------------------------------------------------------------------

@gadget_endpoint
@admin_required
def grouped_chart_data_for_site(request, site_id, measurement, period_type):
    site = get_object_or_404(Site, id=site_id)

    start_date = parse_iso_date(request.GET.get('start_date'))
    end_date = parse_iso_date(request.GET.get('end_date'))

    aggregates = HierarchyDataAggregate.objects.filter(site=site, period_type=period_type).order_by("start_date")
    if start_date:
        aggregates = aggregates.filter(start_date__gte=period_start(start_date, period_type))
    if end_date:
        aggregates = aggregates.filter(start_date__lte=end_date)

    aggregates = list(aggregates)
    buildings = sorted({b for agg in aggregates for b in (agg.data or {}).get("buildings", {})})
    labels = [str(agg.start_date) for agg in aggregates]
    building_data = {b: [] for b in buildings}
    for agg in aggregates:
        buildings_json = (agg.data or {}).get("buildings", {})
        for b in buildings:
            value = to_number(buildings_json.get(b, {}).get("building_total", {}).get(measurement))
            building_data[b].append(round(value, 3) if value is not None else 0)

    color_palette = [
        "rgba(255, 99, 132, 0.8)", "rgba(54, 162, 235, 0.8)", "rgba(255, 206, 86, 0.8)",
        "rgba(75, 192, 192, 0.8)", "rgba(153, 102, 255, 0.8)", "rgba(255, 159, 64, 0.8)",
        "rgba(199, 199, 199, 0.8)", "rgba(83, 102, 255, 0.8)",
    ]
    datasets = [
        {"label": b, "data": building_data[b], "backgroundColor": color_palette[i % len(color_palette)], "stack": 'stack1'}
        for i, b in enumerate(buildings)
    ]
    return JsonResponse({
        "labels": labels,
        "datasets": datasets,
        "site": site.name,
        "measurement": measurement,
        "unit": measurement_units([measurement]).get(measurement, ''),
    })


@gadget_endpoint
def fetchLatestReadings(request, dashboardID, gadget_id):
    """Recent history of every meter of a trend gadget (``?points=`` per meter, default 10)."""
    _, gadget = get_gadget_for(request, dashboardID, gadget_id)
    try:
        limit = max(2, min(int(request.GET.get('points', settings.LIVE_TREND_POINTS)), 500))
    except ValueError:
        limit = settings.LIVE_TREND_POINTS
    names = {m.name for m in gadget.measurement.all()}
    data = []
    for meter in gadget.meters.all():
        for timestamp, values in reading_points(meter, limit):
            data.append(serialize_point(meter.id, timestamp, values, names))
    return JsonResponse({'readingData': data})


@gadget_endpoint
def fetchDateTimeWindow(request, dashboard_id, gadget_id, datetime_str):
    """Readings in a +/- ``?minutes=`` window (default 30) around a local date-time."""
    _, gadget = get_gadget_for(request, dashboard_id, gadget_id)
    try:
        dt = timezone.make_aware(datetime.strptime(datetime_str, "%Y-%m-%dT%H:%M"))
    except ValueError:
        return json_error("Invalid datetime format")
    try:
        minutes = max(1, min(int(request.GET.get('minutes', 30)), 24 * 60))
    except ValueError:
        minutes = 30

    names = {m.name for m in gadget.measurement.all()}
    window = (dt - timedelta(minutes=minutes), dt + timedelta(minutes=minutes))
    data = []
    for meter in gadget.meters.all():
        rows = MeterReading.objects.filter(meter=meter, timestamp__range=window).order_by('timestamp')
        for timestamp, values in rows.values_list('timestamp', 'data')[:2000]:
            data.append(serialize_point(meter.id, timestamp, values, names))
    return JsonResponse({"readingData": data, "window": [local_str(window[0], '%Y-%m-%d %H:%M'), local_str(window[1], '%Y-%m-%d %H:%M')]})


def period_values(meter, measurement, selected_date, period_type):
    """Value of one measurement for one meter and period.

    * daily, and weekly/monthly periods that are still running, are computed
      from the raw readings so today's data is included;
    * closed periods use the nightly aggregates;
    * if an aggregate is missing (aggregation not run yet) the value is
      computed from raw readings and cached for 10 minutes.
    """
    if period_type == 'daily':
        return to_number(summarize_meter_period(meter, selected_date, 'daily', fields={measurement}).get(measurement))

    start = period_start(selected_date, period_type)
    today = timezone.localdate()
    period_is_open = start <= today < period_end(start, period_type)
    if not (period_is_open and period_type in ('weekly', 'monthly')):
        agg = MeterReadingAggregate.objects.filter(meter=meter, period_type=period_type, start_date=start).first()
        if agg and measurement in (agg.aggregateData or {}):
            return to_number(agg.aggregateData[measurement])

    cache_key = f"period-value:{meter.id}:{period_type}:{start}:{measurement}"
    value = cache.get(cache_key, 'missing')
    if value == 'missing':
        value = to_number(summarize_meter_period(meter, start, period_type, fields={measurement}).get(measurement))
        cache.set(cache_key, value, 60 if period_is_open else 600)
    return value


@gadget_endpoint
def getData(request, dashboard_id, gadget_id, measurement, date, period):
    _, gadget = get_gadget_for(request, dashboard_id, gadget_id)
    selected_date = parse_iso_date(date)
    if selected_date is None:
        return json_error('Invalid date format. Use YYYY-MM-DD')
    if period not in PERIOD_TYPES:
        return json_error('Invalid period')

    meter_data = []
    for meter in gadget.meters.all():
        value = period_values(meter, measurement, selected_date, period)
        if value is not None:
            meter_data.append({"meter": meter.name, "value": round(value, 2)})
    return JsonResponse({
        "data": meter_data,
        "unit": measurement_units([measurement]).get(measurement, ''),
        "cumulative": is_cumulative(measurement),
        "period_start": str(period_start(selected_date, period) if period != 'daily' else selected_date),
    })


@gadget_endpoint
def getMultiYearBarData(request, dashboard_id, gadget_id, measurement, date, period):
    _, gadget = get_gadget_for(request, dashboard_id, gadget_id)
    selected_date = parse_iso_date(date)
    if selected_date is None:
        return json_error('Invalid date format')
    if period not in PERIOD_TYPES:
        return json_error('Invalid period')
    selected_year = selected_date.year

    if period == "monthly":
        labels = [calendar.month_abbr[m] for m in range(1, 13)]
    elif period == "yearly":
        labels = [str(selected_year)]
    elif period == "weekly":
        labels = [f"W{i}" for i in range(1, 54)]
    elif period == "3monthly":
        labels = ["Jan-Mar", "Apr-Jun", "Jul-Sep", "Oct-Dec"]
    elif period == "6monthly":
        labels = ["Jan-Jun", "Jul-Dec"]
    else:
        days_in_month = calendar.monthrange(selected_year, selected_date.month)[1]
        labels = [str(day) for day in range(1, days_in_month + 1)]

    def parse_period_value(value):
        if not value:
            return None
        try:
            if period == 'daily':
                return datetime.strptime(value, "%Y-%m-%d").date()
            if period == 'weekly':
                year_str, week_str = value.split("-W")
                return date_cls.fromisocalendar(int(year_str), int(week_str), 1)
            if period == 'monthly':
                return datetime.strptime(value, "%Y-%m").date().replace(day=1)
        except (ValueError, TypeError):
            return None
        return None

    start_val = parse_period_value(request.GET.get('start'))
    end_val = parse_period_value(request.GET.get('end'))

    years_to_fetch = [selected_year - 1, selected_year]
    if period == 'yearly':
        labels = ["Year"]

    def label_index(dt):
        if period == "monthly":
            return dt.month - 1
        if period == "weekly":
            return dt.isocalendar()[1] - 1
        if period == "3monthly":
            return (dt.month - 1) // 3
        if period == "6monthly":
            return 0 if dt.month <= 6 else 1
        if period == "daily":
            return dt.day - 1
        return 0

    data = []
    for meter in gadget.meters.all():
        year_values = {}
        for year in years_to_fetch:
            values = [0] * len(labels)
            if period == 'daily':
                month_start = selected_date.replace(year=year, day=1)
                days = calendar.monthrange(year, month_start.month)[1]
                start, end = local_day_bounds(month_start)[0], local_day_bounds(month_start.replace(day=days))[1]
                rows, previous = meter_rows(meter, start, end)
                for day, bucket in fold_readings(rows, previous, {measurement}).items():
                    value = bucket.values().get(measurement)
                    if value is not None and 0 <= day.day - 1 < len(values):
                        values[day.day - 1] = round(value, 2)
            else:
                if period == 'weekly':
                    # ISO weeks: the Monday of week 1 can fall in the previous calendar year.
                    aggs = MeterReadingAggregate.objects.filter(
                        meter=meter, period_type=period,
                        start_date__gte=date_cls(year, 1, 1) - timedelta(days=6), start_date__lte=date_cls(year, 12, 31),
                    )
                else:
                    aggs = MeterReadingAggregate.objects.filter(meter=meter, period_type=period, start_date__year=year)
                for agg in aggs:
                    if period == 'weekly' and agg.start_date.isocalendar()[0] != year:
                        continue
                    idx = label_index(agg.start_date)
                    value = to_number((agg.aggregateData or {}).get(measurement))
                    if 0 <= idx < len(values) and value is not None:
                        values[idx] = round(value, 2)
                # The running period is not aggregated until tonight: compute it live.
                today = timezone.localdate()
                if year == today.year and period in ('weekly', 'monthly'):
                    current = period_start(today, period)
                    live = period_values(meter, measurement, current, period)
                    idx = label_index(current)
                    if live is not None and 0 <= idx < len(values):
                        values[idx] = round(live, 2)
            year_values[str(year)] = values
        data.append({"meter": meter.name, "values": year_values})

    # Optional range filter (?start=&end=): keep only the selected slice of labels.
    if start_val and end_val and period in ('daily', 'weekly', 'monthly'):
        lo, hi = sorted((label_index(start_val), label_index(end_val)))
        labels = labels[lo:hi + 1]
        for entry in data:
            entry["values"] = {year: values[lo:hi + 1] for year, values in entry["values"].items()}

    return JsonResponse({
        "labels": labels,
        "data": data,
        "years": [str(y) for y in years_to_fetch],
        "unit": measurement_units([measurement]).get(measurement, ''),
    })


@gadget_endpoint
def fetchLatestToolData(request, dashboard_id, gadget_id):
    _, gadget = get_gadget_for(request, dashboard_id, gadget_id)
    meter = gadget.meters.first()
    if meter is None:
        return json_error('No meter configured for this gadget', 404)
    latest = LatestMeterReading.objects.filter(meter=meter).first()
    if not latest:
        return json_error('No reading received from this meter yet', 404)
    return JsonResponse({'reading': {
        'meter_id': meter.id,
        'meter_name': meter.name,
        'timestamp': local_str(latest.timestamp, '%Y-%m-%d %H:%M:%S'),
        'data': latest.data,
    }})


@gadget_endpoint
def fetchLatestMultipleMeterTableData(request, dashboard_id, gadget_id):
    _, gadget = get_gadget_for(request, dashboard_id, gadget_id)
    meters = list(gadget.meters.all())
    latest_by_meter = {r.meter_id: r for r in LatestMeterReading.objects.filter(meter__in=meters)}
    readings = []
    for meter in meters:
        latest = latest_by_meter.get(meter.id)
        readings.append({
            "meter_id": meter.id,
            "meter_name": meter.name,
            "meter_type": meter.meterType,
            "timestamp": local_str(latest.timestamp, '%Y-%m-%d %H:%M:%S') if latest else None,
            "data": latest.data if latest else {},
        })
    return JsonResponse({
        "readings": readings,
        "measurements": order_measurements(m.name for m in gadget.measurement.all()),
    })


@gadget_endpoint
def fetchValueCardData(request, dashboard_id, site_id, measurement_id):
    """Site total of a measurement: current period aggregate, or the sum of the latest readings."""
    dashboard_ = get_dashboard_for(request, dashboard_id)
    site = get_object_or_404(Site, id=site_id)
    if site.id != dashboard_.site_id:
        return json_error('Site does not belong to this dashboard', 404)
    measurement = get_object_or_404(Measurements, id=measurement_id).name
    unit = measurement_units([measurement]).get(measurement, '')
    period = request.GET.get('period', 'monthly')

    agg = HierarchyDataAggregate.objects.filter(site=site, period_type=period).order_by("-start_date").first()
    if agg and measurement in (agg.data or {}).get("site_total", {}):
        return JsonResponse({
            "site": site.name,
            "measurement": measurement,
            "unit": unit,
            "latest_date": str(agg.start_date),
            "source": f"{period} total",
            "value": to_number(agg.data["site_total"][measurement]),
        })

    values = [
        to_number((r.data or {}).get(measurement))
        for r in LatestMeterReading.objects.filter(meter__area__building__site=site)
    ]
    values = [v for v in values if v is not None]
    value = None
    if values:
        value = sum(values) / len(values) if is_intensive(measurement) else sum(values)
    return JsonResponse({
        "site": site.name,
        "measurement": measurement,
        "unit": unit,
        "latest_date": str(timezone.localdate()),
        "source": "live",
        "value": value,
        "message": None if values else "No data available",
    })


@gadget_endpoint
def fetchTableData(request, dashboard_id, gadget_id):
    _, gadget = get_gadget_for(request, dashboard_id, gadget_id)
    meter = gadget.meters.first()
    if meter is None:
        return JsonResponse({"rows": []})
    rows = []
    for timestamp, values in MeterReading.objects.filter(meter=meter).order_by('-timestamp').values_list('timestamp', 'data')[:20]:
        row = {'Timestamp': local_str(timestamp, "%H:%M:%S")}
        for key in order_measurements((values or {}).keys()):
            row[key] = values[key]
        rows.append(row)
    return JsonResponse({"rows": rows, "meter": meter.name})


@gadget_endpoint
def hierarchyAggView(request, dashboard_id, site_id, measurement, period_type, start_date):
    dashboard_ = get_dashboard_for(request, dashboard_id)
    site = get_object_or_404(Site, id=site_id)
    if site.id != dashboard_.site_id:
        return json_error('Site does not belong to this dashboard', 404)
    requested = parse_iso_date(start_date) or timezone.localdate()
    requested = period_start(requested, period_type)

    queryset = HierarchyDataAggregate.objects.filter(site=site, period_type=period_type)
    aggregate = queryset.filter(start_date=requested).first()
    exact = aggregate is not None
    if aggregate is None:
        aggregate = queryset.filter(start_date__lte=requested).order_by('-start_date').first() or queryset.order_by('-start_date').first()
    if aggregate is None:
        return json_error(f'No {period_type} aggregate has been calculated for {site.name} yet.', 404)

    return JsonResponse({
        "site": {"id": site.id, "name": site.name},
        "period_type": period_type,
        "start_date": str(aggregate.start_date),
        "requested_date": str(requested),
        "exact": exact,
        "hierarchy_data": aggregate.data,
        "measurement": measurement,
        "unit": measurement_units([measurement]).get(measurement, ''),
    })


@gadget_endpoint
def heatmap_data(request, dashboard_id, meter_id, start_date, end_date, measurement):
    """Hourly profile: consumption for counters, average for everything else."""
    dashboard_ = get_dashboard_for(request, dashboard_id)
    meter = get_object_or_404(Meters, id=meter_id, area__building__site=dashboard_.site)
    start_day, end_day = parse_iso_date(start_date), parse_iso_date(end_date)
    if not start_day or not end_day:
        return json_error('Invalid dates')
    if end_day < start_day:
        start_day, end_day = end_day, start_day
    if (end_day - start_day).days > 366:
        return json_error('Please select at most one year')

    data, mode = hourly_profile(meter, start_day, end_day, measurement)
    return JsonResponse({
        'measurement': measurement,
        'meter': meter.name,
        'mode': mode,
        'unit': measurement_units([measurement]).get(measurement, ''),
        'start': start_day.isoformat(),
        'end': end_day.isoformat(),
        'data': data,
    })


@gadget_endpoint
def building_heatmap(request, dashboard_id, buildingID, measurement):
    dashboard_ = get_dashboard_for(request, dashboard_id)
    building = get_object_or_404(Buildings.objects.select_related('site'), id=buildingID, site=dashboard_.site)
    areas = building.areas.prefetch_related(Prefetch('meters', to_attr='prefetched_meters')).order_by('id')

    agg = (
        HierarchyDataAggregate.objects.filter(site=building.site, period_type='monthly')
        .order_by('-start_date').first()
    )
    area_json = {}
    if agg:
        building_json = (agg.data or {}).get('buildings', {})
        # Names may have been disambiguated with " (#id)" when duplicated.
        area_json = (building_json.get(building.name) or building_json.get(f"{building.name} (#{building.id})") or {}).get('areas', {})

    result_areas = []
    for area in areas:
        area_data = area_json.get(area.name) or area_json.get(f"{area.name} (#{area.id})") or {}
        meters_data = area_data.get('meters', {})
        meters_list = []
        for meter in area.prefetched_meters:
            meter_json = meters_data.get(meter.name) or meters_data.get(f"{meter.name} (#{meter.id})")
            if meter_json is None:
                continue
            value = to_number(meter_json.get('data', {}).get(measurement))
            meters_list.append({"name": meter.name, "value": round(value or 0, 2)})
        area_total = to_number(area_data.get('area_total', {}).get(measurement))
        result_areas.append({"name": area.name, "value": round(area_total or 0, 2), "meters": meters_list})

    if not result_areas:
        return json_error('This building has no areas configured', 404)

    return JsonResponse({
        "building": building.name,
        "period": str(agg.start_date) if agg else None,
        "unit": measurement_units([measurement]).get(measurement, ''),
        "areas": result_areas,
        "message": None if agg else "No monthly aggregate available yet",
    })


@gadget_endpoint
def weather(request, dashboard_id):
    """Server-side proxy for weatherapi.com so the API key never reaches the browser."""
    dashboard_ = get_dashboard_for(request, dashboard_id)
    site = dashboard_.site
    api_key = getattr(settings, 'WEATHER_API_KEY', '')
    if not api_key:
        return json_error('Weather service is not configured', 503)
    location = f"{site.latitude},{site.longitude}" if site.latitude and site.longitude else "Dhaka"
    cache_key = f"weather:{location}"
    payload = cache.get(cache_key)
    if payload is None:
        try:
            response = requests.get(
                "https://api.weatherapi.com/v1/forecast.json",
                params={"key": api_key, "q": location, "days": 7, "aqi": "no", "alerts": "no"},
                timeout=8,
            )
            response.raise_for_status()
            raw = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Weather lookup failed: %s", exc)
            return json_error('Weather unavailable', 502)
        payload = {
            "location": raw.get("location", {}).get("name", ""),
            "current": {
                "temp_c": raw.get("current", {}).get("temp_c"),
                "text": raw.get("current", {}).get("condition", {}).get("text", ""),
                "icon": raw.get("current", {}).get("condition", {}).get("icon", ""),
            },
            "forecast": [
                {
                    "date": day.get("date"),
                    "avgtemp_c": day.get("day", {}).get("avgtemp_c"),
                    "text": day.get("day", {}).get("condition", {}).get("text", ""),
                    "icon": day.get("day", {}).get("condition", {}).get("icon", ""),
                }
                for day in raw.get("forecast", {}).get("forecastday", [])
            ],
        }
        cache.set(cache_key, payload, 15 * 60)
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# Dashboard / gadget management
# ---------------------------------------------------------------------------

@login_required
@superuser_required
@require_POST
def newDashboard(request):
    title = (request.POST.get('title') or '').strip()
    site = Site.objects.filter(id=request.POST.get('site') or 0).first()
    if not title or site is None:
        messages.error(request, "A dashboard needs a title and a site.")
        return redirect("/dashboard")
    dashboard_ = Dashboard.objects.create(title=title, site=site)
    return redirect(f"/dashboard/{dashboard_.id}")


@gadget_endpoint
def machineHealthData(request, dashboard_id, gadget_id):
    """Machines of this dashboard's site that the ML model flags as close to needing maintenance."""
    from django.db.models import Q

    from ml.models import DeviceHealth

    dashboard_ = get_dashboard_for(request, dashboard_id)
    get_object_or_404(Gadgets, id=gadget_id, dashboard=dashboard_)
    site = dashboard_.site

    scored = (DeviceHealth.objects.filter(status=DeviceHealth.OK)
              .filter(Q(meter__area__building__site=site) | Q(motor__building__site=site))
              .select_related('meter__area__building', 'motor__building'))
    rank = {'high': 0, 'medium': 1}
    machines = []
    for h in scored:
        if h.risk not in rank:
            continue
        if h.meter_id:
            area = h.meter.area
            location = f"{area.building.name} / {area.name}" if area else ''
            name, kind = (h.meter.name or 'Meter'), 'meter'
        else:
            location = h.motor.building.name if h.motor.building_id else ''
            name, kind = h.motor.motorName, 'motor'
        lifespan = max(0, min(100, 100 - h.health_score)) if h.health_score is not None else None
        days = None
        if h.days_to_maintenance is not None:
            days = 30 if h.days_to_maintenance >= 30 else round(h.days_to_maintenance)
        machines.append({
            'name': name, 'kind': kind, 'location': location, 'risk': h.risk,
            'lifespan': lifespan, 'days': days, 'failure_mode': h.failure_mode,
            'probability': round((h.failure_probability or 0) * 100),
            'drivers': [d.get('label') for d in (h.drivers or [])[:2] if d.get('label')],
        })
    machines.sort(key=lambda m: (rank.get(m['risk'], 9), -(m['lifespan'] or 0)))
    return JsonResponse({
        'machines': machines,
        'at_risk': len(machines),
        'scored': scored.count(),
    })


def _save_gadget_from_post(request, dashboard_, gadget=None):
    name = (request.POST.get('name') or '').strip()
    gadget_type = request.POST.get('gadget_type')
    if not name or gadget_type not in GADGET_TYPES:
        messages.error(request, "Please provide a gadget name and a valid gadget type.")
        return None

    site = dashboard_.site
    meters = Meters.objects.filter(id__in=request.POST.getlist('meters'), area__building__site=site)
    measurements = Measurements.objects.filter(id__in=request.POST.getlist('measurement'))
    building = Buildings.objects.filter(id=request.POST.get('building') or 0, site=site).first()
    access = [role for role in request.POST.getlist('access') if role in ROLES]

    if gadget_type in ('picturemap',) and building is None:
        messages.error(request, "Select the building to show in the picture map.")
        return None
    if gadget_type in ('valueCard', 'picturemap', 'sankey', 'machineHealth'):
        meters = Meters.objects.none()
    elif not meters.exists():
        messages.error(request, "Select at least one meter of this site.")
        return None
    if gadget_type in ('table', 'machineHealth'):
        measurements = Measurements.objects.none()
    elif not measurements.exists():
        messages.error(request, "Select at least one measurement.")
        return None
    if gadget_type in ('tool', 'table', 'heatmap') and meters.count() > 1:
        meters = meters.order_by('id')[:1]
        meters = Meters.objects.filter(id__in=[m.id for m in meters])
    if gadget_type in ('pie', 'bar', 'sankey', 'heatmap', 'picturemap', 'valueCard') and measurements.count() > 1:
        measurements = Measurements.objects.filter(id=measurements.order_by('id').first().id)

    if gadget is None:
        gadget = Gadgets(dashboard=dashboard_)
    gadget.name = name
    gadget.gadget_type = gadget_type
    gadget.access = access
    gadget.building = building
    gadget.save()
    gadget.meters.set(meters)
    gadget.measurement.set(measurements)
    return gadget


@login_required
@superuser_required
@require_POST
def newGadget(request, dashboardID):
    dashboard_ = get_object_or_404(Dashboard, id=dashboardID)
    if _save_gadget_from_post(request, dashboard_):
        messages.success(request, "Gadget created.")
    return redirect(f'/dashboard/{dashboardID}')


@login_required
@superuser_required
@require_POST
def deleteGadget(request, dashboardID, gadgetID):
    gadget = get_object_or_404(Gadgets, id=gadgetID, dashboard_id=dashboardID)
    gadget.delete()
    messages.success(request, "Gadget deleted.")
    return redirect('/dashboard/' + str(dashboardID))


@login_required
@superuser_required
@require_POST
def editGadget(request, dashboardID, gadgetID):
    gadget = get_object_or_404(Gadgets, id=gadgetID, dashboard_id=dashboardID)
    if _save_gadget_from_post(request, gadget.dashboard, gadget):
        messages.success(request, "Gadget updated.")
    return redirect(f'/dashboard/{dashboardID}')
