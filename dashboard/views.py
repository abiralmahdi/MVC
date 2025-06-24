from django.shortcuts import render, redirect, get_object_or_404
from .models import *
from dynamic.models import *
from datetime import datetime
from django.http import JsonResponse
from pprint import pprint
from datetime import timedelta
from django.utils import timezone

sites = Site.objects.prefetch_related(
        'buildings__areas__meters'
    ).all()

# Create your views here.
def dashboard(request):
    dashboards = Dashboard.objects.all()
    gadgets = Gadgets.objects.all()
    meters = Meters.objects.all()
    context = {
        'sites': sites,
        'dashboards': dashboards,
        'gadgets': gadgets,
        'meters': meters,
    }
    return render(request, 'dashboard.html', context)



import csv
from django.conf import settings
import os


'''
def indivDashboard(request, dashboardID):
    dashboard_ = Dashboard.objects.get(id=dashboardID)
    gadgets = Gadgets.objects.filter(dashboard=dashboard_).prefetch_related('meters')

    site = dashboard_.site
    areas = Areas.objects.filter(building__site=site).prefetch_related('meters')
    meters = Meters.objects.filter(area__in=areas)
    measurements = Measurements.objects.filter(meter__in=meters)
    all_files = Files.objects.filter(meter__in=meters)

    # Map gadget.id -> list of associated files
    gadget_files = {}
    gadget_csv_data = {}

    for gadget in gadgets:
        gadget_meters = gadget.meters.all()
        files = all_files.filter(meter__in=gadget_meters)
        gadget_files[gadget.id] = files

        # Optional: Load only the first file for preview
        if files.exists():
            first_file = files.first()
            file_path = os.path.join(settings.MEDIA_ROOT, str(first_file.file))
            try:
                with open(file_path, newline='') as csvfile:
                    reader = csv.reader(csvfile)
                    rows = list(reader)
                    gadget_csv_data[gadget.id] = rows[:20]  # Preview first 20 rows
            except Exception as e:
                gadget_csv_data[gadget.id] = [['Error reading file:', str(e)]]


    context = {
        'sites': sites,
        'dashboard': dashboard_,
        'gadgets': gadgets,
        'areas': areas,
        'meters': meters,
        'measurements': measurements,
        'gadget_files': gadget_files,
        'gadget_csv_data': gadget_csv_data
    }

    return render(request, 'indivDashboard2.html', context)
    '''

def indivDashboard(request, dashboardID):
    dashboard_ = get_object_or_404(Dashboard, id=dashboardID)
    gadgets = Gadgets.objects.filter(dashboard=dashboard_).prefetch_related('meters', 'measurement')

    site = dashboard_.site
    areas = Areas.objects.filter(building__site=site).prefetch_related('meters')
    meters = Meters.objects.filter(area__in=areas)
    measurements = Measurements.objects.filter(meter__in=meters)

    # Preload readings once for all meters
    meter_readings = LatestMeterReading.objects.filter(meter__in=meters)

    readingArray = []
    for reading in meter_readings:
        readingArray.append({
            'meter_id': reading.meter.id,
            'timestamp': reading.timestamp.strftime('%H:%M'),
            'data': reading.data
        })

    context = {
        'dashboard': dashboard_,
        'sites': [site],
        'gadgets': gadgets,
        'areas': areas,
        'meters': meters,
        'measurements': measurements,
        'readingData':readingArray
        
    }

    return render(request, 'indivDashboard2.html', context)


def fetchLatestReadings(request, dashboardID, gadget_id):
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
    
from django.utils import timezone
from django.http import JsonResponse
from datetime import datetime, timedelta
from .models import MeterReading, Gadgets

def fetchDateTimeWindow(request, dashboard_id, gadget_id, datetime_str):
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







def getPieData(request, dashboard_id, gadget_id, measurement, date):
    try:
        selected_date = datetime.strptime(date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=400)

    try:
        gadget = Gadgets.objects.get(id=gadget_id)
    except Gadgets.DoesNotExist:
        return JsonResponse({'error': 'Gadget not found'}, status=404)

    meters = gadget.meters.all()
    start_datetime = datetime.combine(selected_date, datetime.min.time())
    end_datetime = datetime.combine(selected_date, datetime.max.time())

    meter_data = []

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






def getPieData2(request, dashboard_id, gadget_id, measurement, interval):
    time_ranges = {
        'today': timezone.now().replace(hour=0, minute=0, second=0, microsecond=0),
        '1w': timezone.now() - timedelta(weeks=1),
        '1m': timezone.now() - timedelta(days=30),
        '3m': timezone.now() - timedelta(days=90),
        '6m': timezone.now() - timedelta(days=180),
        '1y': timezone.now() - timedelta(days=365),
    }

    if interval not in time_ranges:
        return JsonResponse({'error': 'Invalid interval'}, status=400)

    gadget = Gadgets.objects.get(id=gadget_id)
    meters = gadget.meters.all()

    start_time = time_ranges[interval]

    # Prepare aggregated data
    meter_data = []
    for meter in meters:
        readings = MeterReading.objects.filter(meter=meter, timestamp__gte=start_time)
        values = [r.data.get(measurement, 0) for r in readings if r.data.get(measurement) is not None]
        avg_val = sum(values) / len(values) if values else 0
        meter_data.append({'meter': meter.name, 'value': avg_val})

    return JsonResponse({'data': meter_data})





def fetchLatestToolData(request, dashboard_id, gadget_id):
    try:
        gadget = Gadgets.objects.prefetch_related('meters', 'measurement').get(id=gadget_id)
        meter = gadget.meters.first()
        measurements = gadget.measurement.all()
        latest_reading = LatestMeterReading.objects.filter(meter=meter).first()

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





def newDashboard(request):
    if request.method=='POST':
        title = request.POST['title']
        siteID = request.POST['site']
        site = Site.objects.get(id=siteID)
        Dashboard.objects.create(title=title, site=site).save()
    return redirect("/dashboard")

def newGadget(request, dashboardID):
    if request.method == 'POST':
        name = request.POST['name']
        gadget_type = request.POST['gadget_type']
        dashboard_ = get_object_or_404(Dashboard, id=dashboardID)

        # Get selected meters
        meters_ids = request.POST.getlist('meters')
        meters = Meters.objects.filter(id__in=meters_ids)

        # Get measurements based on gadget type
        measurement_ids = request.POST.getlist('measurement')
        if not measurement_ids:
            # Fallback in case no measurement is selected
            measurement_ids = [Measurements.objects.first().id]

        measurements = Measurements.objects.filter(id__in=measurement_ids)

        # Create the gadget
        gadget = Gadgets.objects.create(
            name=name,
            gadget_type=gadget_type,
            dashboard=dashboard_
        )
        gadget.meters.set(meters)
        gadget.measurement.set(measurements)
        gadget.save()

    return redirect(f'/dashboard/{dashboardID}')

# NO URLs YET
def deleteGadget(request, gadgetID):
    gadget = Gadgets.objects.get(id=gadgetID)
    dashboardID = gadget.dashboard.id
    gadget.delete()
    return redirect('/dashboard/'+str(dashboardID))

