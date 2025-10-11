from django.shortcuts import render, redirect, get_object_or_404
from .models import *
from dynamic.models import *
from datetime import datetime
from django.http import JsonResponse, HttpResponse
from pprint import pprint
from datetime import timedelta
from django.utils import timezone
from django.db.models.functions import TruncHour, TruncDate
from django.contrib.auth.decorators import login_required, user_passes_test
from alarms.models import *
from utils.decorators import subscription_required

GADGET_TYPES = ["pie", "bar", "line", "table", "tool", "sankey", "heatmap"]
ACCESS_CONSTROL = ["Administrator", "Operator", "Quality Manager", "Shift Manager", "Maintenance Personnel", "Setup Technician"]
sites = Site.objects.prefetch_related(
        'buildings__areas__meters'
    ).all()


# Create your views here.
@login_required
@subscription_required
def dashboard(request):
    config = GlobalConfiguration.objects.first()
    sites = Site.objects.prefetch_related(
        'buildings__areas__meters'
    ).all()
    if request.user.is_superuser or request.user.userModel.first().role == 'Administrator':
        pass
    else:
        sites = [request.user.userModel.first().site]
    dashboards = Dashboard.objects.all()
    gadgets = Gadgets.objects.all()
    meters = Meters.objects.all()
    context = {
        'sites': sites,
        'dashboards': dashboards,
        'gadgets': gadgets,
        'meters': meters,
        'config':config,
    }
    return render(request, 'dashboard.html', context)


@login_required
@subscription_required
def siteDashbaord(request, siteID):
    site = Site.objects.get(id=siteID)
    try:
        dashboard = Dashboard.objects.filter(site=site).first()
        return redirect('/dashboard/'+str(dashboard.id))
    except:
        # If no dashboard exists for this site, redirect to create a new one
        return redirect('/dashboard')
    

def get_day_suffix(day):
    if 11 <= day <= 13:
        return 'th'
    last_digit = day % 10
    if last_digit == 1:
        return 'st'
    elif last_digit == 2:
        return 'nd'
    elif last_digit == 3:
        return 'rd'
    else:
        return 'th'

def format_custom_date(date_obj):
    day = date_obj.day
    suffix = get_day_suffix(day)
    formatted = date_obj.strftime(f"%A - {day}{suffix} %B, %Y")
    return formatted

@login_required
@subscription_required
def indivDashboard(request, dashboardID):
    globalConfig = GlobalConfiguration.objects.first()
    dateNow = format_custom_date(datetime.now())
    config = GlobalConfiguration.objects.first()
    dashboard_ = get_object_or_404(Dashboard, id=dashboardID)

    # Load sites depending on role
    sites = Site.objects.prefetch_related(
        'buildings__areas__meters', 'buildings'
    ).all()
    if not (request.user.is_superuser or request.user.userModel.first().role == 'Administrator'):
        sites = [request.user.userModel.first().site]

    # Only allow access to site admins/superusers
    if not (
        request.user.is_superuser
        or request.user.userModel.first().site.id == dashboard_.site.id
        or request.user.userModel.first().role == 'Administrator'
    ):
        return redirect('/dashboard')

    # --- Master measurement order ---
    ORDERED_MEASUREMENTS = [
        "Voltage L1N", "Voltage L2N", "Voltage L3N",
        "Voltage L1-L2", "Voltage L2-L3", "Voltage L3-L1",
        "3-Phase Average Voltage L-N", "3-Phase Average Voltage L-L",

        "Current L1", "Current L2", "Current L3",
        "3-Phase Average Current L-L",

        "Line Frequency",

        "Power Factor L1", "Power Factor L2", "Power Factor L3",
        "Power Factor",

        "Active Power L1", "Active Power L2", "Active Power L3",
        "Total Active Power",

        "Reactive Power L1", "Reactive Power L2", "Reactive Power L3",
        "Total Reactive Power",

        "Apparent Power L1", "Apparent Power L2", "Apparent Power L3",
        "Total Apparent Power",

        "THD Voltage L1-L2", "THD Voltage L2-L3", "THD Voltage L3-L1",

        "Energy",

        # 💧 Water Meter
        "Flow Rate", "Total Volume",

        # 🔥 Gas Meter
        "Gas Flow Rate", "Gas Pressure", "Total Gas Volume",

        # 🌡️ Steam Meter
        "Steam Flow Rate", "Steam Pressure", "Total Steam",

        # ⛽ Fuel Meter
        "Fuel Consumption Rate", "Total Fuel Used",

        # 🌡️ Temperature & Humidity
        "Temperature", "Humidity", "Pressure",

        # 🌬️ Air Quality
        "CO2 Level", "PM2.5", "PM10",
    ]

    # --- Gadgets ---
    gadgets = Gadgets.objects.filter(dashboard=dashboard_).prefetch_related('meters', 'measurement')
    for g in gadgets:
        measurement_names = [m.name for m in g.measurement.all()]
        g.ordered_measurements = [m for m in ORDERED_MEASUREMENTS if m in measurement_names]

    site = dashboard_.site
    areas = Areas.objects.filter(building__site=site).prefetch_related('meters')
    meters = Meters.objects.filter(area__in=areas).select_related('loadType')
    measurements = Measurements.objects.all()

    # --- Alarms ---
    alarms = Alarms.objects.filter(acknowledged=False, meter__in=meters)
    for alarm in alarms:
        if alarm.acknowledged:
            alarm.color = "green"
        elif "high" in alarm.alarmType.lower():
            alarm.color = "red"
        elif "low" in alarm.alarmType.lower():
            alarm.color = "rgb(179, 179, 21)"
        else:
            alarm.color = "white"

    # --- Latest Readings ---
    meter_readings = LatestMeterReading.objects.filter(meter__in=meters)
    readingArray = [
        {
            'meter_id': r.meter.id,
            'timestamp': r.timestamp.strftime('%H:%M'),
            'data': r.data,
        }
        for r in meter_readings
    ]

    # --- Load Types & Meter Types for new trees ---
    loadTypes = LoadType.objects.prefetch_related('meters').all()
    meterTypes = sorted(list(set(m.meterType for m in meters)))

    context = {
        'dashboard': dashboard_,
        'sites': sites,
        'gadgets': gadgets,
        'areas': areas,
        'meters': meters,
        'measurements': measurements,
        'readingData': readingArray,
        'gadgetTypes': GADGET_TYPES,
        'accessControl': ACCESS_CONSTROL,
        'alarms': alarms,
        'config': config,
        'dateNow': dateNow,
        'globalConfig':globalConfig,
        # new:
        'loadTypes': loadTypes,
        'meterTypes': meterTypes,
    }

    return render(request, 'indivDashboard2.html', context)

    

from django.shortcuts import render
from django.http import JsonResponse
from collections import defaultdict
from .models import HierarchyDataAggregate, Site

@login_required
@subscription_required
def indivCentralDashboard(request):
    if request.user.is_superuser or request.user.userModel.first().role == 'Administrator':
        # You can customize which sites to show
        config = GlobalConfiguration.objects.first()
        sites = Site.objects.all()
        measurement = "CO2 Level"  # or pass via GET param
        period_type = "monthly"  # or weekly/yearly

        context = {
            "sites": sites,
            "measurement": measurement,
            "period_type": period_type,
            'config':config
        }
        return render(request, "indivCentralDashboard.html", context)
    else:
        return HttpResponse("You are not authorized to enter this page.")



from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from .models import Dashboard, Site, HierarchyDataAggregate
from django.utils.dateparse import parse_date

def grouped_chart_data_for_site(request, site_id, measurement, period_type):
    if not (request.user.is_superuser or request.user.userModel.first().role == 'Administrator'):
        return JsonResponse({"error": "Unauthorized"}, status=403)

    site = get_object_or_404(Site, id=site_id)

    # Parse date filters from GET params
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    start_date = parse_date(start_date_str) if start_date_str else None
    end_date = parse_date(end_date_str) if end_date_str else None

    aggregates = HierarchyDataAggregate.objects.filter(
        site=site, period_type=period_type
    ).order_by("start_date")

    # Apply date range filtering if provided
    if start_date:
        aggregates = aggregates.filter(start_date__gte=start_date)
    if end_date:
        aggregates = aggregates.filter(start_date__lte=end_date)

    # Collect all unique building names
    building_set = set()
    for agg in aggregates:
        data = agg.data
        for b in data.get("buildings", {}):
            building_set.add(b)
    buildings = sorted(list(building_set))

    # Initialize data holders
    labels = []  # X-axis (start_date of each period)
    building_data = {b: [] for b in buildings}  # Y values per building

    for agg in aggregates:
        labels.append(str(agg.start_date))  # X-axis label
        data = agg.data
        buildings_json = data.get("buildings", {})

        for b in buildings:
            # Safely get building_total[measurement], default to 0
            val = buildings_json.get(b, {}).get("building_total", {}).get(measurement, 0)
            building_data[b].append(val)

    # Define distinct colors
    color_palette = [
        "rgba(255, 99, 132, 0.8)",
        "rgba(54, 162, 235, 0.8)",
        "rgba(255, 206, 86, 0.8)",
        "rgba(75, 192, 192, 0.8)",
        "rgba(153, 102, 255, 0.8)",
        "rgba(255, 159, 64, 0.8)",
        "rgba(199, 199, 199, 0.8)",
        "rgba(83, 102, 255, 0.8)",
    ]

    # Build dataset list for Chart.js
    datasets = []
    for i, b in enumerate(buildings):
        datasets.append({
            "label": b,
            "data": building_data[b],
            "backgroundColor": color_palette[i % len(color_palette)],
            "stack": 'stack1'
        })

    return JsonResponse({
        "labels": labels,
        "datasets": datasets,
        "site": site.name,
        "measurement": measurement
    })





@login_required
def fetchLatestReadings(request, dashboardID, gadget_id):
    dashboard_ = get_object_or_404(Dashboard, id=dashboardID)
    if request.user.is_superuser or request.user.userModel.first().site.id == dashboard_.site.id or request.user.userModel.first().role == 'Administrator':
        try:
            gadget = Gadgets.objects.prefetch_related('meters', 'measurement').get(id=gadget_id)
            meters = gadget.meters.all()
            measurements = gadget.measurement.all()
            measurement_names = [m.name for m in measurements]
            
            readings = LatestMeterReading.objects.filter(meter__in=meters).order_by('timestamp')
            data = []
            for reading in readings:
                entry = {
                    'meter_id': reading.meter.id,
                    'timestamp': reading.timestamp.strftime('%H:%M'),
                    'data': {k: v for k, v in reading.data.items() if k in measurement_names}
                }
                data.append(entry)
                

            return JsonResponse({'readingData': data})

        except Gadgets.DoesNotExist:
            return JsonResponse({'error': 'Gadget not found'}, status=404)
    else:
        return redirect('/dashboard')
    
    
from django.utils import timezone
from django.http import JsonResponse
from datetime import datetime, timedelta
from .models import MeterReading, Gadgets
@login_required
def fetchDateTimeWindow(request, dashboard_id, gadget_id, datetime_str):
    dashboard_ = get_object_or_404(Dashboard, id=dashboard_id)
    if request.user.is_superuser or request.user.userModel.first().site.id == dashboard_.site.id or request.user.userModel.first().role == 'Administrator':
        try:
            dt = timezone.make_aware(datetime.strptime(datetime_str, "%Y-%m-%dT%H:%M"))
        except ValueError:
            return JsonResponse({"error": "Invalid datetime format"}, status=400)

        try:
            gadget = Gadgets.objects.get(id=gadget_id)
        except Gadgets.DoesNotExist:
            return JsonResponse({"error": "Gadget not found"}, status=404)

        meters = gadget.meters.all()
        readingData = []

        for meter in meters:
            # Filter readings for this meter around the datetime
            readings = MeterReading.objects.filter(
                meter=meter,
                timestamp__range=(dt - timedelta(minutes=15), dt + timedelta(minutes=15))
            ).order_by("timestamp")

            # Find index of closest timestamp
            surrounding = list(readings)
            idx = next(
                (i for i, r in enumerate(surrounding) if abs((r.timestamp - dt).total_seconds()) < 60),
                None
            )

            if idx is None:
                continue  # Skip this meter if no close match

            start = max(idx - 5, 0)
            end = idx + 5

            selected_readings = surrounding[start:end]

            for r in selected_readings:
                readingData.append({
                    'meter_id': r.meter.id,
                    'timestamp': r.timestamp.strftime('%H:%M'),
                    'data': r.data
                })

        if not readingData:
            return JsonResponse({"error": "No readings found for any meter"}, status=404)

        return JsonResponse({"readingData": readingData})
    else:
        return redirect('/dashboard')


def get_period_start(date, period_type):
    from datetime import date as dt

    if period_type == "weekly":
        return date - timedelta(days=date.weekday())  # Monday
    elif period_type == "monthly":
        return date.replace(day=1)
    elif period_type == "3monthly":
        month = ((date.month - 1) // 3) * 3 + 1
        return date.replace(month=month, day=1)
    elif period_type == "6monthly":
        month = 1 if date.month <= 6 else 7
        return date.replace(month=month, day=1)
    elif period_type == "yearly":
        return date.replace(month=1, day=1)
    else:
        return date


@login_required
def getData(request, dashboard_id, gadget_id, measurement, date, period):
    dashboard_ = get_object_or_404(Dashboard, id=dashboard_id)
    if request.user.is_superuser or request.user.userModel.first().site.id == dashboard_.site.id or request.user.userModel.first().role == 'Administrator':
        period_type = period  # optional query param: daily, weekly, monthly, etc.

        try:
            selected_date = datetime.strptime(date, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=400)

        try:
            gadget = Gadgets.objects.get(id=gadget_id)
        except Gadgets.DoesNotExist:
            return JsonResponse({'error': 'Gadget not found'}, status=404)

        meters = gadget.meters.all()
        meter_data = []

        if period_type and period_type != "daily":
            selected_date = get_period_start(selected_date, period_type)
            for meter in meters:
                agg = MeterReadingAggregate.objects.filter(
                    meter=meter,
                    period_type=period_type,
                    start_date=selected_date
                ).first()
                print(agg)

                if agg and measurement in agg.aggregateData:
                    meter_data.append({
                        "meter": meter.name,
                        "value": round(agg.aggregateData[measurement], 2)
                    })
        else:
            # Daily average mode
            start_datetime = datetime.combine(selected_date, datetime.min.time())
            end_datetime = datetime.combine(selected_date, datetime.max.time())

            for meter in meters:
                readings = MeterReading.objects.filter(
                    meter=meter,
                    timestamp__range=(start_datetime, end_datetime)
                )

                values = [r.data.get(measurement) for r in readings if r.data.get(measurement) is not None]
                if values:
                    avg = sum(values) / len(values)
                    meter_data.append({
                        "meter": meter.name,
                        "value": round(avg, 2)
                    })

        return JsonResponse({"data": meter_data})
    else:
        return redirect('/dashboard')



from collections import defaultdict

@login_required
def getMultiYearBarData(request, dashboard_id, gadget_id, measurement, date, period):
    
    dashboard_ = get_object_or_404(Dashboard, id=dashboard_id)
    if request.user.is_superuser or request.user.userModel.first().site.id == dashboard_.site.id or request.user.userModel.first().role == 'Administrator':
        try:
            selected_date = datetime.strptime(date, "%Y-%m-%d").date()
        except Exception:
            return JsonResponse({'error': 'Invalid date format'}, status=400)

        selected_year = selected_date.year

        try:
            gadget = Gadgets.objects.get(id=gadget_id)
        except Gadgets.DoesNotExist:
            return JsonResponse({'error': 'Gadget not found'}, status=404)

        meters = gadget.meters.all()

        def get_period_labels(year, period):
            import calendar
            labels = []
            if period == "monthly":
                labels = [calendar.month_abbr[m] for m in range(1,13)]
            elif period == "yearly":
                labels = [str(year)]
            elif period == "weekly":
                labels = [f"W{i}" for i in range(1,53)]
            elif period == "3monthly":
                labels = ["Jan-Mar","Apr-Jun","Jul-Sep","Oct-Dec"]
            elif period == "6monthly":
                labels = ["Jan-Jun","Jul-Dec"]
            elif period == "daily":
                days_in_month = calendar.monthrange(year, selected_date.month)[1]
                labels = [str(day) for day in range(1, days_in_month+1)]
            return labels

        labels = get_period_labels(selected_year, period)

        # Parse optional start/end parameters from query params
        start_param = request.GET.get('start', None)
        end_param = request.GET.get('end', None)

        # Helper function to convert start/end strings to dates or weeks or months
        # For daily: parse date strings
        # For weekly: parse ISO week strings "YYYY-Www"
        # For monthly: parse "YYYY-MM"

        def parse_period_value(value, period):
            if not value:
                return None
            if period == 'daily':
                try:
                    return datetime.strptime(value, "%Y-%m-%d").date()
                except:
                    return None
            elif period == 'weekly':
                # value format: "YYYY-Www"
                try:
                    year_str, week_str = value.split("-W")
                    year_i = int(year_str)
                    week_i = int(week_str)
                    # Get Monday date of the week
                    from isoweek import Week
                    return Week(year_i, week_i).monday()
                except:
                    return None
            elif period == 'monthly':
                try:
                    return datetime.strptime(value, "%Y-%m").date().replace(day=1)
                except:
                    return None
            else:
                return None

        start_val = parse_period_value(start_param, period)
        end_val = parse_period_value(end_param, period)

        # Filter years to fetch - always current year and previous year
        years_to_fetch = [selected_year-1, selected_year]

        meter_year_values = defaultdict(lambda: defaultdict(lambda: [None]*len(labels)))

        def get_label_index(dt, period, labels):
            if period == "monthly":
                return dt.month - 1
            elif period == "yearly":
                return 0
            elif period == "weekly":
                return dt.isocalendar()[1] - 1  # zero-based week number
            elif period == "3monthly":
                return (dt.month - 1) // 3
            elif period == "6monthly":
                return 0 if dt.month <= 6 else 1
            elif period == "daily":
                return dt.day - 1
            else:
                return 0

        for meter in meters:
            for year in years_to_fetch:
                aggs = MeterReadingAggregate.objects.filter(
                    meter=meter,
                    period_type=period,
                    start_date__year=year
                )

                # If start_val and end_val are set, filter aggs accordingly
                if start_val and end_val:
                    aggs = aggs.filter(start_date__gte=start_val, start_date__lte=end_val)

                for agg in aggs:
                    idx = get_label_index(agg.start_date, period, labels)
                    if 0 <= idx < len(labels) and measurement in agg.aggregateData:
                        meter_year_values[meter.name][year][idx] = round(agg.aggregateData[measurement], 2)

        data = []
        for meter_name, year_dict in meter_year_values.items():
            for y in years_to_fetch:
                year_values = year_dict[y]
                year_dict[y] = [v if v is not None else 0 for v in year_values]
            data.append({
                "meter": meter_name,
                "values": {
                    str(y): year_dict[y] for y in years_to_fetch
                }
            })

        return JsonResponse({
            "labels": labels,
            "data": data,
            "years": [str(y) for y in years_to_fetch]
        })
    else:
        return redirect('/dashboard')




@login_required
def fetchLatestToolData(request, dashboard_id, gadget_id):
    dashboard_ = get_object_or_404(Dashboard, id=dashboard_id)
    if request.user.is_superuser or request.user.userModel.first().site.id == dashboard_.site.id or request.user.userModel.first().role == 'Administrator':
        try:
            gadget = Gadgets.objects.prefetch_related('meters', 'measurement').get(id=gadget_id)
            meter = gadget.meters.first()
            measurements = gadget.measurement.all()
            latest_reading = LatestMeterReading.objects.filter(meter=meter).order_by('-timestamp').first()

            if not latest_reading:
                return JsonResponse({'error': 'No reading found'}, status=404)

            data = {
                'meter_id': meter.id,
                'timestamp': latest_reading.timestamp.strftime('%H:%M'),
                'data': latest_reading.data,
            }

            return JsonResponse({'reading': data})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    else:
        return redirect('/dashboard')


@login_required
def fetchLatestMultipleMeterTableData(request, dashboard_id, gadget_id):
    dashboard_ = get_object_or_404(Dashboard, id=dashboard_id)

    if (
        request.user.is_superuser
        or request.user.userModel.first().site.id == dashboard_.site.id
        or request.user.userModel.first().role == "Administrator"
    ):
        try:
            gadget = Gadgets.objects.prefetch_related("meters", "measurement").get(id=gadget_id)
            meters = gadget.meters.all()
            measurements = gadget.measurement.all()

            # ✅ Define the master measurement order
            ordered_measurements = [
                # 🔌 Electricity Meter
                "Voltage L1N", "Voltage L2N", "Voltage L3N",
                "Voltage L1-L2", "Voltage L2-L3", "Voltage L3-L1",
                "3-Phase Average Voltage L-N", "3-Phase Average Voltage L-L",

                "Current L1", "Current L2", "Current L3",
                "3-Phase Average Current L-L",
                
                "Line Frequency",
                
                "Power Factor L1", "Power Factor L2", "Power Factor L3",
                "Power Factor",

                "Active Power L1", "Active Power L2", "Active Power L3",
                "Total Active Power",
                
                "Reactive Power L1", "Reactive Power L2", "Reactive Power L3",
                "Total Reactive Power",
                
                "Apparent Power L1", "Apparent Power L2", "Apparent Power L3",
                "Total Apparent Power",

                "THD Voltage L1-L2", "THD Voltage L2-L3", "THD Voltage L3-L1",
                
                "Energy",

                # 💧 Water Meter
                "Flow Rate", "Total Volume",

                # 🔥 Gas Meter
                "Gas Flow Rate", "Gas Pressure", "Total Gas Volume",

                # 🌡️ Steam Meter
                "Steam Flow Rate", "Steam Pressure", "Total Steam",

                # ⛽ Fuel Meter
                "Fuel Consumption Rate", "Total Fuel Used",

                # 🌡️ Temperature & Humidity
                "Temperature", "Humidity", "Pressure",

                # 🌬️ Air Quality
                "CO2 Level", "PM2.5", "PM10",
            ]

            # ✅ Keep only the gadget’s measurements but ordered
            measurement_names = [m.name for m in measurements]
            sorted_measurements = [m for m in ordered_measurements if m in measurement_names]

            readings = []
            for meter in meters:
                if not LatestMeterReading.objects.filter(meter=meter):
                    continue
                latest_reading = (
                    LatestMeterReading.objects.filter(meter=meter)
                    .order_by("-timestamp")
                    .first()
                )
                if latest_reading:
                    readings.append(
                        {
                            "meter_id": meter.id,
                            "meter_name": meter.name,
                            "timestamp": latest_reading.timestamp.strftime("%H:%M"),
                            "data": latest_reading.data,
                        }
                    )
            pprint(LatestMeterReading.objects.filter(meter=meter).order_by("-timestamp").first().data)
            if not readings:
                return JsonResponse({"error": "No readings found"}, status=404)

            return JsonResponse(
                {
                    "readings": readings,
                    "measurements": sorted_measurements,  # ✅ Always ordered
                }
            )
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    else:
        return redirect("/dashboard")




def fetchValueCardData(request, dashboard_id, site_id, measurement_id):
    """
    Returns the latest total value (site_total) of a given measurement for the specified site.
    Example: latest total Voltage L1N for site_id=1
    """
    # Authorization check
    if not (request.user.is_superuser or request.user.userModel.first().role == 'Administrator'):
        return JsonResponse({"error": "Unauthorized"}, status=403)

    # Get site object
    site = get_object_or_404(Site, id=site_id)

    # Fetch the most recent aggregate record for this site (any period type)
    latest_agg = (
        HierarchyDataAggregate.objects.filter(site=site)
        .order_by("-start_date")
        .first()
    )
    measurement = Measurements.objects.get(id=measurement_id).name

    if not latest_agg:
        return JsonResponse({
            "site": site.name,
            "measurement": measurement,
            "value": None,
            "message": "No data available"
        })

    # Access the measurement value safely
    site_total = latest_agg.data.get("site_total", {})
    latest_value = site_total.get(measurement, 0)

    # Return JSON response
    return JsonResponse({
        "site": site.name,
        "measurement": measurement,
        "latest_date": str(latest_agg.start_date),
        "value": latest_value
    })




@login_required
def fetchTableData(request, dashboard_id, gadget_id):
    dashboard_ = get_object_or_404(Dashboard, id=dashboard_id)
    if request.user.is_superuser or request.user.userModel.first().site.id == dashboard_.site.id or request.user.userModel.first().role == 'Administrator':
        gadget = Gadgets.objects.get(id=gadget_id)
        meter = gadget.meters.first()
        data = LatestMeterReading.objects.filter(meter=meter).order_by('-timestamp')[:20]  # Get last 20 rows for example

        rows = []
        for instance in data:
            row = {'Timestamp': instance.timestamp.strftime("%H:%M")}
            row.update(instance.data)
            rows.append(row)

        return JsonResponse({"rows": rows})
    else:
        return redirect('/dashboard')


@login_required
def hierarchyAggView(request, dashboard_id, site_id, measurement, period_type, start_date):
    dashboard_ = get_object_or_404(Dashboard, id=dashboard_id)
    if request.user.is_superuser or request.user.userModel.first().site.id == dashboard_.site.id or request.user.userModel.first().role == 'Administrator':
        site = get_object_or_404(Site, id=site_id)
        aggregate = get_object_or_404(
            HierarchyDataAggregate,
            site=site,
            period_type=period_type,
            start_date=start_date
        )
        context = {
            "site": site.id,
            "period_type": period_type,
            "start_date": start_date,
            "data": aggregate.data,
            "hierarchy_data": aggregate.data,
            "measurement": measurement
        }
        return JsonResponse(context)
    else:
        return redirect('/dashboard')

@login_required
def heatmap_data(request, dashboard_id, meter_id, start_date, end_date, measurement):
    dashboard_ = get_object_or_404(Dashboard, id=dashboard_id)
    if request.user.is_superuser or request.user.userModel.first().site.id == dashboard_.site.id or request.user.userModel.first().role == 'Administrator':
        try:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        except:
            return JsonResponse({'error': 'Invalid dates'}, status=400)

        readings = (
            MeterReading.objects
            .filter(
                meter_id=meter_id,
                timestamp__date__gte=start_dt,
                timestamp__date__lte=end_dt
            )
            .annotate(day=TruncDate('timestamp'), hour=TruncHour('timestamp'))
        )

        hourly_totals = {}
        for r in readings:
            key = (r.timestamp.date().isoformat(), r.timestamp.hour)
            val = r.data.get(measurement, 0)
            hourly_totals[key] = hourly_totals.get(key, 0) + val

        data = [
            {'day': day, 'hour': hour, 'value': round(total, 2)}
            for (day, hour), total in hourly_totals.items()
        ]

        return JsonResponse({
            'measurement': measurement,
            'data': data
        })
    else:
        return redirect('/dashboard')



from pprint import pprint
from django.db.models import Prefetch
@login_required
def building_heatmap(request, dashboard_id, buildingID, measurement):
    building = get_object_or_404(Buildings.objects.select_related('site'), id=buildingID)
    site = building.site

    # Prefetch only necessary related objects (areas + meters)
    areas = (
        building.areas.prefetch_related(
            Prefetch('meters', to_attr='prefetched_meters')
        )
    )

    # Fetch the latest aggregate record in a single query
    agg = (
        HierarchyDataAggregate.objects
        .filter(site=site, period_type='monthly')
        .only('data')  # fetch only JSON field
        .order_by('-start_date')
        .first()
    )

    if not agg:
        return JsonResponse({'error': 'No aggregate data found'}, status=404)

    data = agg.data.get('buildings', {}).get(building.name, {}).get('areas', {})
    area_values = {}

    # Loop through all areas once
    for area in areas:
        area_data = data.get(area.name, {})
        area_total = float(
            area_data.get('area_total', {}).get(measurement, 0) or 0
        )
        meters_data = area_data.get('meters', {})

        # Precompute all meter values quickly using list comprehension
        meters_list = [
            {
                "name": meter.name,
                "value": round(
                    float(meters_data.get(meter.name, {})
                          .get('data', {})
                          .get(measurement, 0) or 0),
                    2
                )
            }
            for meter in area.prefetched_meters
            if meter.name in meters_data  # Skip non-existent meters
        ]

        area_values[area.name] = {
            "value": round(area_total, 2),
            "meters": meters_list
        }

    if not area_values:
        return JsonResponse({'error': 'No data for this building'}, status=404)

    return JsonResponse({
        "building": building.name,
        "areas": [
            {"name": k, "value": v["value"], "meters": v["meters"]}
            for k, v in area_values.items()
        ]
    })



@login_required
@user_passes_test(lambda u: u.is_superuser)
def newDashboard(request):
    if request.method == 'POST':
        title = request.POST['title']
        siteID = request.POST['site']
        site = get_object_or_404(Site, id=siteID)
        Dashboard.objects.create(title=title, site=site)

    return redirect("/dashboard")

@login_required
@user_passes_test(lambda u: u.is_superuser)
def newGadget(request, dashboardID):
    if request.method == 'POST':
        name = request.POST['name']
        gadget_type = request.POST['gadget_type']
        dashboard_ = get_object_or_404(Dashboard, id=dashboardID)

        # Get selected meters
        meters_ids = request.POST.getlist('meters')
        meters = Meters.objects.filter(id__in=meters_ids)

        building = request.POST['building']

        # Get measurements based on gadget type
        measurement_ids = request.POST.getlist('measurement')
        if not measurement_ids:
            # Fallback in case no measurement is selected
            measurement_ids = [Measurements.objects.first().id]

        measurements = Measurements.objects.filter(id__in=measurement_ids)

        access = request.POST.getlist('access')

        # Create the gadget
        gadget = Gadgets.objects.create(
            name=name,
            gadget_type=gadget_type,
            dashboard=dashboard_,
            access=access,
            building=Buildings.objects.get(id=int(building))
        )
        gadget.meters.set(meters)
        gadget.measurement.set(measurements)
        gadget.save()

    return redirect(f'/dashboard/{dashboardID}')

# NO URLs YET
@login_required
@user_passes_test(lambda u: u.is_superuser)
def deleteGadget(request, dashboardID, gadgetID):
    gadget = Gadgets.objects.get(id=gadgetID)
    gadget.delete()
    return redirect('/dashboard/'+str(dashboardID))


@login_required
@user_passes_test(lambda u: u.is_superuser)
def editGadget(request, dashboardID, gadgetID):
    gadget = get_object_or_404(Gadgets, id=gadgetID, dashboard_id=dashboardID)

    if request.method == 'POST':
        name = request.POST.get('name')
        gadget_type = request.POST.get('gadget_type')

        # Multiple select fields
        meters = request.POST.getlist('meters')
        measurements = request.POST.getlist('measurement')
        access = request.POST.getlist('access')

        building = request.POST['building']

        # Update gadget fields
        gadget.name = name
        gadget.gadget_type = gadget_type
        gadget.access = access  # JSONField will store list as JSON
        gadget.building = Buildings.objects.get(id=int(building))

        # Update M2M relationships
        gadget.meters.set(meters)
        gadget.measurement.set(measurements)

        gadget.save()

        return redirect(f'/dashboard/{dashboardID}')  # Adjust redirect as needed

    return redirect(f'/dashboard/{dashboardID}')