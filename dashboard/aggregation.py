"""Time and hierarchy aggregation of meter readings.

Design
------
* Readings are streamed per meter and folded into *local calendar day* buckets
  (``settings.TIME_ZONE``), so a "day", "week" or "month" is the plant's day,
  not UTC's.
* Counters (see ``measurements.CUMULATIVE_FIELDS``) are converted to
  consumption by summing positive deltas between consecutive readings. The
  delta is attributed to the day of the later reading, so nothing is lost at
  period boundaries and a meter reset/replacement does not produce a negative
  consumption.
* Other quantities are averaged.
* Day buckets are rolled up to weekly (Monday start) and monthly periods,
  using the same period boundaries the dashboard views use
  (``utils.timeutils.period_start``). 3monthly, 6monthly and yearly values are
  derived from the stored monthly aggregates, so the nightly run only reads
  about five weeks of raw readings and long periods stay correct after old
  raw readings are archived.
* The hierarchy (site -> building -> area -> meter) is built from the stored
  per-meter aggregates: extensive quantities are summed, intensive ones
  (voltage, power factor, temperature, ...) are averaged.
"""
import logging
from collections import defaultdict
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from dynamic.models import Meters, Site
from utils.timeutils import ensure_aware, local_range_bounds, period_end, period_start

from .measurements import is_cumulative, is_intensive, to_number
from .models import HierarchyDataAggregate, MeterReading, MeterReadingAggregate

logger = logging.getLogger('dashboard')

TIME_PERIODS = ['weekly', 'monthly', '3monthly', '6monthly', 'yearly']
RAW_PERIODS = ['weekly', 'monthly']
DERIVED_PERIODS = ['3monthly', '6monthly', 'yearly']
HIERARCHY_PERIODS = ['weekly', 'monthly', 'yearly']


class DayBucket:
    __slots__ = ('sums', 'counts', 'deltas')

    def __init__(self):
        self.sums = defaultdict(float)
        self.counts = defaultdict(int)
        self.deltas = defaultdict(float)

    def merge(self, other):
        for key, value in other.sums.items():
            self.sums[key] += value
        for key, value in other.counts.items():
            self.counts[key] += value
        for key, value in other.deltas.items():
            self.deltas[key] += value

    def values(self, fields=None):
        result = {}
        for key, count in self.counts.items():
            if count and (fields is None or key in fields):
                result[key] = round(self.sums[key] / count, 3)
        for key, delta in self.deltas.items():
            if fields is None or key in fields:
                result[key] = round(delta, 3)
        return result


def fold_readings(rows, previous_data=None, fields=None):
    """Fold ``(timestamp, data)`` rows (ascending) into {local_date: DayBucket}.

    ``previous_data`` is the data of the reading just before the first row; it
    lets the first counter delta of the window be computed.
    """
    buckets = {}
    last_counter = {}
    for key, raw in (previous_data or {}).items():
        value = to_number(raw)
        if value is not None and is_cumulative(key):
            last_counter[key] = value

    for timestamp, data in rows:
        if not isinstance(data, dict):
            continue
        day = timezone.localtime(ensure_aware(timestamp)).date()
        bucket = buckets.get(day)
        if bucket is None:
            bucket = buckets[day] = DayBucket()
        for key, raw in data.items():
            if fields is not None and key not in fields:
                continue
            value = to_number(raw)
            if value is None:
                continue
            if is_cumulative(key):
                previous = last_counter.get(key)
                bucket.deltas[key] += 0.0
                if previous is None:
                    last_counter[key] = value
                elif value >= previous:
                    bucket.deltas[key] += value - previous
                    last_counter[key] = value
                elif value == 0:
                    # A single 0 from a meter that is powering up is a glitch, not a reset.
                    continue
                else:
                    # Counter reset / meter replaced: restart from the new value.
                    last_counter[key] = value
            else:
                bucket.sums[key] += value
                bucket.counts[key] += 1
    return buckets


def rollup(buckets, period_type):
    """{period_start_date: DayBucket} for the given period type."""
    periods = {}
    for day, bucket in buckets.items():
        start = period_start(day, period_type)
        target = periods.get(start)
        if target is None:
            target = periods[start] = DayBucket()
        target.merge(bucket)
    return periods


def meter_rows(meter, start=None, end=None):
    """Stream a meter's readings in time order, plus the data of the reading before ``start``."""
    queryset = MeterReading.objects.filter(meter=meter)
    previous_data = None
    if start is not None:
        previous = queryset.filter(timestamp__lt=start).order_by('-timestamp').values_list('data', flat=True).first()
        previous_data = previous
        queryset = queryset.filter(timestamp__gte=start)
    if end is not None:
        queryset = queryset.filter(timestamp__lt=end)
    rows = queryset.order_by('timestamp').values_list('timestamp', 'data').iterator(chunk_size=5000)
    return rows, previous_data


def summarize_meter_days(meter, start_day, end_day, fields=None):
    """{local_date: DayBucket} for local days start_day..end_day (inclusive)."""
    start, end = local_range_bounds(start_day, end_day)
    rows, previous = meter_rows(meter, start, end)
    return fold_readings(rows, previous, fields)


def summarize_meter_period(meter, start_day, period_type, fields=None):
    """Aggregated values of one meter for one period (works for 'daily' too)."""
    if period_type == 'daily':
        last_day = start_day
    else:
        start_day = period_start(start_day, period_type)
        last_day = period_end(start_day, period_type) - timedelta(days=1)
    merged = DayBucket()
    for bucket in summarize_meter_days(meter, start_day, last_day, fields).values():
        merged.merge(bucket)
    return merged.values(fields)


def _window_start(since):
    """Earliest local day whose raw-built periods can have changed since ``since``."""
    if since is None:
        return None
    return min(period_start(since, period) for period in RAW_PERIODS)


def combine_months(values_list):
    """One meter's monthly aggregates -> a longer period: counters summed, other quantities averaged."""
    sums, counts = defaultdict(float), defaultdict(int)
    for values in values_list:
        for key, raw in (values or {}).items():
            value = to_number(raw)
            if value is None:
                continue
            sums[key] += value
            counts[key] += 1
    return {
        key: round(sums[key], 3) if is_cumulative(key) else round(sums[key] / counts[key], 3)
        for key in sums
    }


def derive_long_periods(meter, month_starts=None):
    """Rebuild 3monthly/6monthly/yearly aggregates of ``meter`` from its monthly aggregates.

    ``month_starts`` limits the work to the long periods containing those months
    (default: every period that has monthly data).
    """
    monthly = dict(
        MeterReadingAggregate.objects.filter(meter=meter, period_type='monthly')
        .values_list('start_date', 'aggregateData')
    )
    months = monthly.keys() if month_starts is None else month_starts
    targets = {(period, period_start(month, period)) for month in months for period in DERIVED_PERIODS}
    written = 0
    for period_type, start_date in sorted(targets):
        end_date = period_end(start_date, period_type)
        values = [data for month, data in monthly.items() if start_date <= month < end_date]
        if not values:
            continue
        MeterReadingAggregate.objects.update_or_create(
            meter=meter,
            period_type=period_type,
            start_date=start_date,
            defaults={'aggregateData': combine_months(values)},
        )
        written += 1
    return written


def run_time_aggregation(since=None, meters=None):
    """(Re)build MeterReadingAggregate. ``since`` (a date) limits the work to periods touching it."""
    window_start = _window_start(since)
    start = local_range_bounds(window_start, window_start)[0] if window_start else None
    meters = list(meters if meters is not None else Meters.objects.all())
    written = 0

    for meter in meters:
        rows, previous = meter_rows(meter, start)
        buckets = fold_readings(rows, previous)
        if not buckets:
            continue
        with transaction.atomic():
            month_starts = set()
            for period_type in RAW_PERIODS:
                for start_date, bucket in rollup(buckets, period_type).items():
                    if window_start and start_date < period_start(window_start, period_type):
                        continue
                    MeterReadingAggregate.objects.update_or_create(
                        meter=meter,
                        period_type=period_type,
                        start_date=start_date,
                        defaults={'aggregateData': bucket.values()},
                    )
                    written += 1
                    if period_type == 'monthly':
                        month_starts.add(start_date)
            written += derive_long_periods(meter, month_starts)
    logger.info("Time aggregation wrote %d rows for %d meters", written, len(meters))
    return written


def _unique_names(objects):
    """Map object -> display name, disambiguating duplicates so JSON keys never collide."""
    counts = defaultdict(int)
    for obj in objects:
        counts[obj.name] += 1
    return {obj.pk: (obj.name if counts[obj.name] == 1 else f"{obj.name} (#{obj.pk})") for obj in objects}


def combine(values_list):
    """Roll several measurement dicts into one: sum extensive quantities, average intensive ones."""
    sums, counts = defaultdict(float), defaultdict(int)
    for values in values_list:
        for key, raw in values.items():
            value = to_number(raw)
            if value is None:
                continue
            sums[key] += value
            counts[key] += 1
    return {
        key: round(sums[key] / counts[key], 3) if is_intensive(key) else round(sums[key], 3)
        for key in sums
    }


def build_hierarchy(site, period_type, start_date):
    aggregates = {
        agg.meter_id: agg.aggregateData or {}
        for agg in MeterReadingAggregate.objects.filter(
            meter__area__building__site=site, period_type=period_type, start_date=start_date
        )
    }
    if not aggregates:
        return None

    buildings = list(site.buildings.all())
    building_names = _unique_names(buildings)
    hierarchy = {"site_total": {}, "buildings": {}}
    site_meter_values = []

    for building in buildings:
        areas = list(building.areas.all())
        area_names = _unique_names(areas)
        building_meter_values = []
        building_data = {"building_total": {}, "areas": {}}

        for area in areas:
            meters = list(area.meters.all())
            meter_names = _unique_names(meters)
            area_meter_values = []
            area_data = {"area_total": {}, "meters": {}}
            for meter in meters:
                values = aggregates.get(meter.pk)
                if not values:
                    continue
                area_meter_values.append(values)
                area_data["meters"][meter_names[meter.pk]] = {
                    "data": values,
                    "loadType": meter.loadType.name if meter.loadType else "N/A",
                }
            area_data["area_total"] = combine(area_meter_values)
            building_meter_values.extend(area_meter_values)
            building_data["areas"][area_names[area.pk]] = area_data

        building_data["building_total"] = combine(building_meter_values)
        site_meter_values.extend(building_meter_values)
        hierarchy["buildings"][building_names[building.pk]] = building_data

    hierarchy["site_total"] = combine(site_meter_values)
    return hierarchy


def run_hierarchy_aggregation(since=None):
    """(Re)build HierarchyDataAggregate from the per-meter aggregates."""
    window_start = _window_start(since)
    sites = Site.objects.prefetch_related('buildings__areas__meters__loadType')
    written = 0
    for period_type in HIERARCHY_PERIODS:
        starts = MeterReadingAggregate.objects.filter(period_type=period_type)
        if window_start:
            starts = starts.filter(start_date__gte=period_start(window_start, period_type))
        start_dates = sorted(set(starts.values_list('start_date', flat=True)))
        for site in sites:
            for start_date in start_dates:
                hierarchy = build_hierarchy(site, period_type, start_date)
                if hierarchy is None:
                    continue
                HierarchyDataAggregate.objects.update_or_create(
                    site=site, period_type=period_type, start_date=start_date,
                    defaults={"data": hierarchy},
                )
                written += 1
    logger.info("Hierarchy aggregation wrote %d rows", written)
    return written


def hourly_profile(meter, start_day, end_day, measurement):
    """[{day, hour, value}] for local days start_day..end_day.

    Counters give the consumption within each hour, other quantities the hourly average.
    """
    start, end = local_range_bounds(start_day, end_day)
    rows, previous = meter_rows(meter, start, end)
    cumulative = is_cumulative(measurement)
    totals = defaultdict(float)
    counts = defaultdict(int)
    last_value = to_number((previous or {}).get(measurement))
    for timestamp, values in rows:
        value = to_number((values or {}).get(measurement))
        if value is None:
            continue
        local_ts = timezone.localtime(ensure_aware(timestamp))
        key = (local_ts.date().isoformat(), local_ts.hour)
        counts[key] += 1
        if cumulative:
            if last_value is not None and value >= last_value:
                totals[key] += value - last_value
            if value != 0 or last_value is None:
                last_value = value
        else:
            totals[key] += value
    data = [
        {'day': day, 'hour': hour, 'value': round(totals[(day, hour)] if cumulative else totals[(day, hour)] / counts[(day, hour)], 3)}
        for (day, hour) in sorted(counts)
    ]
    return data, ('consumption' if cumulative else 'average')


def period_starts(start_day, end_day, period_type):
    """Start dates of every period of ``period_type`` overlapping start_day..end_day."""
    starts = []
    current = start_day if period_type == 'daily' else period_start(start_day, period_type)
    while current <= end_day and len(starts) < 1000:
        starts.append(current)
        current = period_end(current, period_type)
    return starts
