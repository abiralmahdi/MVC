from django.utils import timezone
from dashboard.models import Site, HierarchyDataAggregate, MeterReading, Meters
from datetime import timedelta
from tqdm import tqdm

# ✅ Define known cumulative fields for non-electric meters
CUMULATIVE_FIELDS = {
    "Total Fuel Used",
    "Total Gas Volume",
    "Total Steam",
    "Total Volume",
 }

# ✅ Define your meter types exactly like you generated them
METER_DEFINITIONS = {
    'Fuel Meter': ['Fuel Consumption Rate', 'Total Fuel Used'],
    'Gas Meter': ['Gas Flow Rate', 'Gas Pressure', 'Total Gas Volume'],
    'Humidity': ['Humidity'],
    'Pressure': ['Pressure'],
    'Steam Meter': ['Steam Flow Rate', 'Steam Pressure', 'Total Steam'],
    'Temperature': ['Temperature'],
    'Water Meter': ['Flow Rate', 'Total Volume'],
    'Air Quality': ['CO2 Level', 'PM2.5', 'PM10'],
}

def normalize_start_date(date, period_type):
    if period_type == "weekly":
        return date - timedelta(days=date.weekday())
    elif period_type == "monthly":
        return date.replace(day=1)
    elif period_type == "yearly":
        return date.replace(month=1, day=1)
    return date

def create_hierarchy_aggregate(site, period_type, start_date, meters):
    hierarchy = {
        "site_total": {},
        "buildings": {}
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
        building_data = {
            "building_total": building_total,
            "areas": {}
        }

        for area in building.areas.all():
            area_total = {}
            area_data = {
                "area_total": area_total,
                "meters": {}
            }

            for meter in area.meters.filter(id__in=[m.id for m in meters]):
                readings = MeterReading.objects.filter(
                    meter=meter,
                    timestamp__gte=start_date,
                    timestamp__lt=period_end
                ).order_by('timestamp')

                first = readings.first()
                last = readings.last()

                if not last:
                    continue

                measurement_keys = last.data.keys()

                meter_data = {}

                for key in measurement_keys:
                    if key in CUMULATIVE_FIELDS:
                        first_value = first.data.get(key, 0) if first else 0
                        last_value = last.data.get(key, 0) if last else 0
                        value = last_value - first_value
                    else:
                        # Average for instantaneous/rate
                        values = readings.values_list('data', flat=True)
                        total = 0
                        count = 0
                        for v in values:
                            val = v.get(key)
                            if val is not None:
                                total += val
                                count += 1
                        value = round(total / count, 3) if count > 0 else 0

                    meter_data[key] = value
                    area_total[key] = area_total.get(key, 0) + value

                area_data["meters"][meter.name] = {
                    "data": meter_data,
                    "loadType": meter.loadType.name if meter.loadType else "N/A"
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
        defaults={"data": hierarchy}
    )


# ============================
# Loop sites / periods / dates
# ============================

# ✅ Get only your defined meters, 3 per type
meters = []
for meter_type in METER_DEFINITIONS.keys():
    meters += list(Meters.objects.filter(meterType=meter_type)[:3])

sites = Site.objects.all()
period_types = ["weekly", "monthly", "yearly"]

for site in tqdm(sites, desc="Sites", unit="site"):
    for period_type in tqdm(period_types, desc=f"Periods for {site.name}", unit="period", leave=False):
        raw_dates = (
            MeterReading.objects
            .filter(meter__in=meters, meter__area__building__site=site)
            .values_list('timestamp', flat=True)
            .distinct()
        )

        normalized_dates = set()
        for raw_date in raw_dates:
            norm = normalize_start_date(raw_date.date(), period_type)
            normalized_dates.add(norm)
                                                                                                                        
        for norm_date in tqdm(sorted(normalized_dates), desc=f"{period_type} dates", unit="date", leave=False):
            create_hierarchy_aggregate(site, period_type, norm_date, meters)
