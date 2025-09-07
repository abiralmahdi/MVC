from django.utils import timezone
from dashboard.models import Site, HierarchyDataAggregate, MeterReading, Meters
from datetime import timedelta
from collections import defaultdict
from tqdm import tqdm

# 📌 Shared cumulative fields (electric + non-electric)
CUMULATIVE_FIELDS = {
    "Total Active Power",
    "Total Reactive Power",
    "Total Fuel Used",
    "Total Gas Volume",
    "Total Steam",
    "Total Volume",
}

# 📌 Meter type definitions (restrict to first 3 per type if needed)
METER_DEFINITIONS = {
    "Fuel Meter": ["Fuel Consumption Rate", "Total Fuel Used"],
    "Gas Meter": ["Gas Flow Rate", "Gas Pressure", "Total Gas Volume"],
    "Humidity": ["Humidity"],
    "Pressure": ["Pressure"],
    "Steam Meter": ["Steam Flow Rate", "Steam Pressure", "Total Steam"],
    "Temperature": ["Temperature"],
    "Water Meter": ["Flow Rate", "Total Volume"],
    "Air Quality": ["CO2 Level", "PM2.5", "PM10"],
    "Electricity Meter": [
        "Voltage L1-N", "Voltage L2-N", "Voltage L3-N",
        "Voltage L1-L2", "Voltage L2-L3", "Voltage L3-L1",
        "Current L1", "Current L2", "Current L3",
        "Apparent Power L1", "Apparent Power L2", "Apparent Power L3",
        "Active Power L1", "Active Power L2", "Active Power L3",
        "Reactive Power L1", "Reactive Power L2", "Reactive Power L3",
        "Power Factor L1", "Power Factor L2", "Power Factor L3",
        "THD Voltage L1-L2", "THD Voltage L2-L3", "THD Voltage L3-L1",
        "Line Frequency", "3-Phase Average Voltage L-N", "3-Phase Average Voltage L-L",
        "3-Phase Average Current L-L", "Total Active Power",
        "Total Reactive Power", "Total Power Factor",
    ],
}

def normalize_start_date(date, period_type):
    if period_type == "weekly":
        return date - timedelta(days=date.weekday())
    elif period_type == "monthly":
        return date.replace(day=1)
    elif period_type == "yearly":
        return date.replace(month=1, day=1)
    return date

def create_hierarchy_aggregate(site, period_type, start_date, meters, meter_readings):
    hierarchy = {
        "site_total": {},
        "buildings": {},
    }
    site_total = {}

    # Determine period end
    if period_type == "weekly":
        period_end = start_date + timedelta(days=7)
    elif period_type == "monthly":
        if start_date.month == 12:
            period_end = start_date.replace(year=start_date.year + 1, month=1, day=1)
        else:
            period_end = start_date.replace(month=start_date.month + 1, day=1)
    elif period_type == "yearly":
        period_end = start_date.replace(year=start_date.year + 1, month=1, day=1)
    else:
        raise ValueError("Invalid period type!")

    for building in site.buildings.all():
        building_total = {}
        building_data = {"building_total": building_total, "areas": {}}

        for area in building.areas.all():
            area_total = {}
            area_data = {"area_total": area_total, "meters": {}}

            for meter in area.meters.all():
                if meter.id not in [m.id for m in meters]:
                    continue

                readings = meter_readings.get(meter.id, [])
                if not readings:
                    continue

                readings_sorted = sorted(readings, key=lambda r: r.timestamp)
                first = readings_sorted[0]
                last = readings_sorted[-1]

                measurement_keys = last.data.keys()
                meter_data = {}

                for key in measurement_keys:
                    if key in CUMULATIVE_FIELDS:
                        first_value = first.data.get(key, 0) if first else 0
                        last_value = last.data.get(key, 0) if last else 0
                        value = last_value - first_value
                    else:
                        total = 0
                        count = 0
                        for reading in readings_sorted:
                            val = reading.data.get(key)
                            if val is not None:
                                total += val
                                count += 1
                        value = round(total / count, 3) if count > 0 else 0

                    meter_data[key] = value
                    area_total[key] = area_total.get(key, 0) + value

                area_data["meters"][meter.name] = {
                    "data": meter_data,
                    "loadType": meter.loadType.name if meter.loadType else "N/A",
                }

            for key, value in area_total.items():
                building_total[key] = building_total.get(key, 0) + value

            building_data["areas"][area.name] = area_data

        for key, value in building_total.items():
            site_total[key] = site_total.get(key, 0) + value

        hierarchy["buildings"][building.name] = building_data

    hierarchy["site_total"] = site_total

    HierarchyDataAggregate.objects.update_or_create(
        site=site,
        period_type=period_type,
        start_date=start_date,
        defaults={"data": hierarchy},
    )

# ============================
# Main Loop
# ============================

# ✅ Option A: restrict meters to first 3 of each type
meters = []
for meter_type in METER_DEFINITIONS.keys():
    meters += list(Meters.objects.filter(meterType=meter_type)[:3])

# ✅ Option B: all meters
# meters = list(Meters.objects.all())

sites = Site.objects.prefetch_related("buildings__areas__meters__loadType").all()
period_types = ["weekly", "monthly", "yearly"]

for site in tqdm(sites, desc="Sites", unit="site"):
    for period_type in tqdm(period_types, desc=f"{site.name} Periods", leave=False):
        raw_dates = (
            MeterReading.objects.filter(meter__in=meters, meter__area__building__site=site)
            .values_list("timestamp", flat=True)
            .distinct()
        )

        normalized_dates = {normalize_start_date(d.date(), period_type) for d in raw_dates}

        for norm_date in tqdm(sorted(normalized_dates), desc=f"{period_type} dates", leave=False):
            # Batch load all readings once
            if period_type == "weekly":
                period_end = norm_date + timedelta(days=7)
            elif period_type == "monthly":
                if norm_date.month == 12:
                    period_end = norm_date.replace(year=norm_date.year + 1, month=1, day=1)
                else:
                    period_end = norm_date.replace(month=norm_date.month + 1, day=1)
            elif period_type == "yearly":
                period_end = norm_date.replace(year=norm_date.year + 1, month=1, day=1)

            readings = MeterReading.objects.filter(
                meter__in=meters,
                timestamp__gte=norm_date,
                timestamp__lt=period_end,
                meter__area__building__site=site,
            )

            meter_readings = defaultdict(list)
            for r in readings:
                meter_readings[r.meter_id].append(r)

            create_hierarchy_aggregate(site, period_type, norm_date, meters, meter_readings)
