from django.shortcuts import render, redirect, get_object_or_404
from dynamic.models import *
from dashboard.models import *
from .models import *
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_protect
from django.contrib import messages
import json
from django.http import JsonResponse
from django.db.models.functions import TruncDate, TruncMonth, TruncYear, TruncHour
from datetime import timedelta, datetime
   


# Create your views here.
@login_required
def reports(request):
    reports = ReportFormat.objects.all()
    meters = Meters.objects.all()
    measurements = Measurements.objects.all()
    context = {
        'reports':reports,
        'gadgets':Gadgets.objects.all(),
        'meters':meters,
        'measurements':measurements
    }
    return render(request, 'reports.html', context)


@login_required
@csrf_protect
def createReportFormat(request):
    if request.method == 'POST':
        title = request.POST.get('title')
        description = request.POST.get('description')
        diagrams_raw = request.POST.getlist('diagrams[]')

        if not title or not diagrams_raw:
            messages.error(request, "Title and at least one diagram are required.")
            return redirect(request.path)

        report_format = ReportFormat.objects.create(title=title, description=description)

        for diagram_json in diagrams_raw:
            data = json.loads(diagram_json)
            diagram = ReportDiagram.objects.create(
                report_format=report_format,
                diagram_type=data['type'],
                measurement_id=data['measurement'],
                period_type=data['periodType'],
                date_range_start=data['startDate'],
                date_range_end=data['endDate']
            )
            diagram.meters.set(data['meters'])

        messages.success(request, "Report format created successfully.")
        return redirect('/reports')

    meters = Meters.objects.all()
    measurements = Measurements.objects.all()
    return redirect('/reports')

def viewReport(request, reportID):
    reports = ReportFormat.objects.all()
    individualReport = ReportFormat.objects.get(id=reportID)
    diagrams = individualReport.diagrams.all()

    
    context = {
        'reports':reports,
        'report':individualReport,
        'diagrams': diagrams

    }
    return render(request, 'reportView.html', context=context)


# API to get aggregated data for a diagram
from django.views.decorators.csrf import csrf_exempt


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


@csrf_exempt
def getDiagramData(request, diagramID):
    diagram = get_object_or_404(ReportDiagram, id=diagramID)
    meters = diagram.meters.all()
    measurement = diagram.measurement.name
    start = diagram.date_range_start
    end = diagram.date_range_end
    period_type = diagram.period_type

    readings = MeterReadingAggregate.objects.filter(
        meter__in=meters,
        start_date__gte=start,
        start_date__lte=end,
        period_type=period_type
    ).order_by('start_date')

    # Prepare data for JS
    data = []
    for reading in readings:
        data.append({
            'period': reading.start_date.strftime('%Y-%m-%d'),
            'meter_id': reading.meter.id,
            'value': reading.aggregateData.get(measurement, 0)
        })

    return JsonResponse({'data': data})



@login_required
def getTableData(request, diagramID):
    diagram = get_object_or_404(ReportDiagram, id=diagramID)
    meters = diagram.meters.all()
    measurement = diagram.measurement.name
    start = diagram.date_range_start
    end = diagram.date_range_end

    # Filter MeterReading by meters and date range
    data = MeterReading.objects.filter(
        meter__in=meters,
        timestamp__date__gte=start,
        timestamp__date__lte=end
    ).order_by('-timestamp') # Limit for safety

    rows = []
    for instance in data:
        row = {
            'Timestamp': instance.timestamp.strftime("%Y-%m-%d %H:%M"),
            'Meter': instance.meter.name
        }
        row[measurement] = instance.data.get(measurement, 0)
        rows.append(row)

    return JsonResponse({"rows": rows})





@login_required
def heatmap_data(request, diagramID):
    from datetime import datetime

    diagram = get_object_or_404(ReportDiagram, id=diagramID)
    measurement = diagram.measurement.name
    start = diagram.date_range_start
    end = diagram.date_range_end
    meters = diagram.meters.all()

    if not meters.exists():
        return JsonResponse({'error': 'No meters attached to diagram'}, status=400)

    # For now pick first meter
    meter_id = meters.first().id

    readings = (
        MeterReading.objects
        .filter(
            meter_id=meter_id,
            timestamp__date__gte=start,
            timestamp__date__lte=end
        )
        .annotate(day=TruncDate('timestamp'), hour=TruncHour('timestamp'))
    )

    hourly_totals = {}
    for r in readings:
        key = (r.day.isoformat(), r.hour.hour)
        val = r.data.get(measurement, 0)
        hourly_totals[key] = hourly_totals.get(key, 0) + val

    data = [
        {'day': day, 'hour': hour, 'value': round(total, 2)}
        for (day, hour), total in hourly_totals.items()
    ]

    return JsonResponse({
        'measurement': measurement,
        'meter_id': meter_id,
        'data': data
    })