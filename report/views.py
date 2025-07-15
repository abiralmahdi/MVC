from django.shortcuts import render, redirect, get_object_or_404
from dynamic.models import *
from dashboard.models import *
from .models import *
from django.contrib.auth.decorators import login_required
from django.contrib import messages
import json
from django.http import JsonResponse
from django.db.models.functions import TruncDate, TruncMonth, TruncYear, TruncHour
from datetime import timedelta, datetime
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import csrf_protect, csrf_exempt





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
            diagram_type = data['type']

            start_date_raw = data.get('startDate')
            end_date_raw = data.get('endDate')
            start_dt = None
            end_dt = None

            if diagram_type == 'line':
                if start_date_raw:
                    start_dt = datetime.strptime(start_date_raw, '%Y-%m-%dT%H:%M')
                if end_date_raw:
                    end_dt = datetime.strptime(end_date_raw, '%Y-%m-%dT%H:%M')
            elif diagram_type == 'sankey':
                start_dt = parse_date(start_date_raw)
                end_dt = start_dt
            else:
                start_dt = parse_date(start_date_raw)
                end_dt = parse_date(end_date_raw)

            diagram = ReportDiagram.objects.create(
                report_format=report_format,
                diagram_type=diagram_type,
                period_type=data.get('periodType'),
                date_range_start=start_dt,
                date_range_end=end_dt, 
                description=data.get('description')
            )

            if diagram_type == 'table':
                diagram.measurements.set(data.get('measurements', []))
                if data.get('meters'):
                    diagram.meters.set(data.get('meters')[:1])  # Only single
            else:
                diagram.measurements.set([data.get('measurement')]) if data.get('measurement') else None
                if diagram_type != 'sankey' and data.get('meters'):
                    diagram.meters.set(data.get('meters'))

        messages.success(request, "Report format created successfully.")
        return redirect('/reports')

    return redirect('/reports')


@login_required
def viewReport(request, reportID):
    reports = ReportFormat.objects.all()
    individualReport = ReportFormat.objects.get(id=reportID)
    diagrams = individualReport.diagrams.all()

    context = {
        'reports': reports,
        'individualReport': individualReport,
        'diagrams': diagrams
    }
    return render(request, 'reportView2.html', context=context)


def get_period_start(date, period_type):
    if period_type == "weekly":
        return date - timedelta(days=date.weekday())
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
    measurement = diagram.measurements.first().name if diagram.measurements.exists() else None
    start = diagram.date_range_start
    end = diagram.date_range_end
    period_type = diagram.period_type

    readings = MeterReadingAggregate.objects.filter(
        meter__in=meters,
        start_date__gte=start,
        start_date__lte=end,
        period_type=period_type
    ).order_by('start_date')

    data = []
    for reading in readings:
        data.append({
            'period': reading.start_date.strftime('%Y-%m-%d'),
            'meter_id': reading.meter.id,
            'value': reading.aggregateData.get(measurement, 0) if measurement else None
        })

    return JsonResponse({'data': data})



@csrf_exempt
def getLineDiagramData(request, diagramID):
    diagram = get_object_or_404(ReportDiagram, id=diagramID)
    meters = diagram.meters.all()
    measurement = diagram.measurements.first().name if diagram.measurements.exists() else None
    start = diagram.date_range_start
    end = diagram.date_range_end

    if not measurement:
        return JsonResponse({'error': 'No measurement selected.'}, status=400)

    readings = MeterReading.objects.filter(
        meter__in=meters,
        timestamp__gte=start,
        timestamp__lte=end
    ).order_by('timestamp')

    data = []
    for reading in readings:
        data.append({
            'timestamp': reading.timestamp.strftime('%Y-%m-%d %H:%M'),
            'meter_id': reading.meter.id,
            'value': reading.data.get(measurement, 0)
        })

    return JsonResponse({'data': data})



@login_required
def getTableData(request, diagramID):
    diagram = get_object_or_404(ReportDiagram, id=diagramID)
    meters = diagram.meters.all()
    measurements = diagram.measurements.all()
    start = diagram.date_range_start
    end = diagram.date_range_end

    data = MeterReading.objects.filter(
        meter__in=meters,
        timestamp__date__gte=start,
        timestamp__date__lte=end
    ).order_by('-timestamp')

    rows = []
    for instance in data:
        row = {
            'Timestamp': instance.timestamp.strftime("%Y-%m-%d %H:%M"),
            'Meter': instance.meter.name
        }
        for m in measurements:
            row[m.name] = instance.data.get(m.name, 0)
        rows.append(row)

    return JsonResponse({"rows": rows})


@login_required
def heatmap_data(request, diagramID):
    diagram = get_object_or_404(ReportDiagram, id=diagramID)
    measurement = diagram.measurements.first().name if diagram.measurements.exists() else None
    start = diagram.date_range_start
    end = diagram.date_range_end
    meters = diagram.meters.all()

    if not meters.exists():
        return JsonResponse({'error': 'No meters attached to diagram'}, status=400)

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
        val = r.data.get(measurement, 0) if measurement else 0
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


@login_required
def sankey_data(request, diagramID):
    diagram = get_object_or_404(ReportDiagram, id=diagramID)
    site = diagram.site  # You must ensure ReportFormat → Site relation exists
    period_type = diagram.period_type
    date = diagram.date_range_start

    hierarchy_entry = HierarchyDataAggregate.objects.filter(
        site=site,
        period_type=period_type,
        start_date=date
    ).first()
    print('----------------------------------------')
    print(hierarchy_entry)

    if not hierarchy_entry:
        return JsonResponse({'error': 'No hierarchy data found for this date/period.'}, status=404)

    return JsonResponse({'hierarchy': hierarchy_entry.data})
