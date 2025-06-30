from django.utils import timezone
from dashboard.models import Site, HierarchyDataAggregate, MeterReadingAggregate, Measurements
from datetime import timedelta, date
from tqdm import tqdm

def normalize_start_date(date_obj, period_type):
    """
    Normalize to:
    - weekly → Monday
    - monthly → 1st of month
    - yearly → Jan 1st
    """
    if period_type == "weekly":
        return date_obj - timedelta(days=date_obj.weekday())
    elif period_type == "monthly":
        return date_obj.replace(day=1)
    elif period_type == "yearly":
        return date_obj.replace(month=1, day=1)
    else:
        raise ValueError(f"Unknown period type: {period_type}")

def get_period_end(start_date, period_type):
    """
    Compute exclusive period end date.
    """
    if period_type == "weekly":
        return start_date + timedelta(days=7)
    elif period_type == "monthly":
        if start_date.month == 12:
            return date(start_date.year + 1, 1, 1)
        else:
            return date(start_date.year, start_date.month + 1, 1)
    elif period_type == "yearly":
        return date(start_date.year + 1, 1, 1)
    else:
        raise ValueError(f"Unknown period type: {period_type}")

def create_hierarchy_aggregate(site, period_type, start_date):
    """
    Create HierarchyDataAggregate for site, period_type, start_date.
    Uses safe period window for meter aggregates.
    """
    hierarchy = {
        "site_total": {},
        "buildings": {}
    }

    site_total = {}

    period_end = get_period_end(start_date, period_type)

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
                measurement_names = Measurements.objects.filter(meterType=meter.meterType).values_list('name', flat=True)

                # ✅ Use safe window
                agg = (
                    MeterReadingAggregate.objects
                    .filter(
                        meter=meter,
                        period_type=period_type,
                        start_date__gte=start_date,
                        start_date__lt=period_end
                    )
                    .order_by('start_date')
                    .first()
                )

                if agg:
                    meter_data = {
                        name: agg.aggregateData.get(name, 0) for name in measurement_names
                    }
                else:
                    meter_data = {name: 0 for name in measurement_names}
                

                area_data["meters"][meter.name] = {"data": meter_data}

                for name, value in meter_data.items():
                    area_total[name] = area_total.get(name, 0) + value

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

# ===============================
# ✅ Main loop with tqdm
# ===============================

sites = Site.objects.all()
period_types = ["weekly", "monthly", "yearly"]

for site in tqdm(sites, desc="Sites", unit="site"):
    for period_type in tqdm(period_types, desc=f"Periods for {site.name}", unit="period", leave=False):
        raw_dates = (
            MeterReadingAggregate.objects
            .filter(meter__area__building__site=site, period_type=period_type)
            .values_list('start_date', flat=True)
            .distinct()
        )

        normalized_dates = set()
        for raw_date in raw_dates:
            normalized = normalize_start_date(raw_date, period_type)
            normalized_dates.add(normalized)

        for norm_date in tqdm(sorted(normalized_dates), desc=f"{period_type.capitalize()} dates", unit="date", leave=False):
            create_hierarchy_aggregate(site, period_type, norm_date)
