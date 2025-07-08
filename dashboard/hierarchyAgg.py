from django.utils import timezone
from dashboard.models import Site, HierarchyDataAggregate, MeterReading
from datetime import timedelta
from tqdm import tqdm

TARGET_MEASUREMENTS = [
    "Total Active Power",
    "Total Reactive Power",
    "Active Power L1",
    "Active Power L2",
    "Active Power L3",
    "Reactive Power L1",
    "Reactive Power L2",
    "Reactive Power L3",
    "Apparent Power L1",
    "Apparent Power L2",
    "Apparent Power L3", 
    "Total Volume",
    "Air Flow"
]

def normalize_start_date(date, period_type):
    if period_type == "weekly":
        return date - timedelta(days=date.weekday())
    elif period_type == "monthly":
        return date.replace(day=1)
    elif period_type == "yearly":
        return date.replace(month=1, day=1)
    return date

def create_hierarchy_aggregate(site, period_type, start_date):
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

            for meter in area.meters.all():
                # Query first and last MeterReading within the period
                readings = MeterReading.objects.filter(
                    meter=meter,
                    timestamp__gte=start_date,
                    timestamp__lt=period_end
                ).order_by('timestamp')

                first = readings.first()
                last = readings.last()

                meter_data = {}

                for name in TARGET_MEASUREMENTS:
                    first_value = first.data.get(name, 0) if first else 0
                    last_value = last.data.get(name, 0) if last else 0
                    diff = last_value - first_value
                    meter_data[name] = diff

                    # Accumulate area total
                    area_total[name] = area_total.get(name, 0) + diff

                area_data["meters"][meter.name] = {"data": meter_data, "loadType": meter.loadType.name}

            for name, value in area_total.items():
                building_total[name] = building_total.get(name, 0) + value

            building_data["areas"][area.name] = area_data

        for name, value in building_total.items():
            site_total[name] = site_total.get(name, 0) + value

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

sites = Site.objects.all()
period_types = ["weekly", "monthly", "yearly"]

for site in tqdm(sites, desc="Sites", unit="site"):
    for period_type in tqdm(period_types, desc=f"Periods for {site.name}", unit="period", leave=False):
        raw_dates = (
            MeterReading.objects
            .filter(meter__area__building__site=site)
            .values_list('timestamp', flat=True)
            .distinct()
        )

        normalized_dates = set()
        for raw_date in raw_dates:
            norm = normalize_start_date(raw_date.date(), period_type)
            normalized_dates.add(norm)

        for norm_date in tqdm(sorted(normalized_dates), desc=f"{period_type} dates", unit="date", leave=False):
            create_hierarchy_aggregate(site, period_type, norm_date)
