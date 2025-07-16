from django.shortcuts import render, redirect, get_object_or_404
from dynamic.models import *
from dashboard.models import *
from .models import *
from django.contrib.auth.decorators import login_required
from django.contrib import messages
import json
from django.http import JsonResponse, FileResponse, Http404
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

        report_format = ReportFormat.objects.create(title=title, description=description, user=request.user)

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





from django.core.files.base import ContentFile
import uuid
import base64

@login_required
def saveDiagramImage(request, diagramID):
    if request.method == "POST":
        import json
        data = json.loads(request.body)

        image_data = data.get('image')

        if not image_data:
            return JsonResponse({"status": "error", "message": "No image provided."}, status=400)

        try:
            diagram = ReportDiagram.objects.get(id=diagramID)

            # ✅ Check if an image is already saved
            if diagram.image and diagram.image.name:
                return JsonResponse({
                    "status": "skipped",
                    "message": "Image already exists.",
                    "image_url": diagram.image.url
                }, status=200)

            # Decode the base64 image
            format, imgstr = image_data.split(';base64,')
            ext = format.split('/')[-1]  # png or jpeg

            file_name = f"diagram_{diagramID}_{uuid.uuid4()}.{ext}"
            file_content = ContentFile(base64.b64decode(imgstr), name=file_name)

            # Save to the ImageField
            diagram.image.save(file_name, file_content, save=True)

            return JsonResponse({
                "status": "success",
                "message": "Image saved.",
                "image_url": diagram.image.url
            })

        except ReportDiagram.DoesNotExist:
            return JsonResponse({"status": "error", "message": "Diagram not found."}, status=404)

    return JsonResponse({"status": "error", "message": "Invalid request method."}, status=405)






from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from django.utils import timezone
from django.conf import settings
import os
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

@login_required
def generate_pdf(request, filename, reportID):
    report = ReportFormat.objects.get(id=reportID)
    diagrams = ReportDiagram.objects.filter(report_format=report)
    
    output_path = os.path.join(settings.MEDIA_ROOT+"/generatedReports", filename)

    # Make sure the folder exists:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4

    left_margin = 50
    right_margin = width - 50
    text_width = right_margin - left_margin

    # Logo path (adjust this to your logo)
    logo_path = os.path.join(settings.BASE_DIR, 'report', 'static', 'customerLogo.png')  # ✅ Replace with your logo path
    logo_width = 1.5 * inch  # adjust size as needed

    def ordinal(n):
        if 11 <= n % 100 <= 13:
            return f"{n}th"
        else:
            return f"{n}{['th','st','nd','rd','th','th','th','th','th','th'][n % 10]}"

    def add_header_footer(page_number):
        now = timezone.now()
        day_of_week = now.strftime("%A")
        day_with_ordinal = ordinal(now.day)
        month_year = now.strftime("%B, %Y")

        # Logo on left
        if os.path.exists(logo_path):
            logo_height = 1 * inch  # match aspect ratio
            c.drawImage(
                logo_path,
                20,  # X
                height - logo_height - 5,  # Y, down from top margin
                width=logo_width,
                height=logo_height,
                preserveAspectRatio=True,
                mask='auto'
            )

        # Date on right (multiline)
        c.setFont("Helvetica", 10)
        date_x = width - 130  # adjust to align nicely
        date_y = height - 40

        c.drawString(date_x, date_y, day_of_week)
        c.drawString(date_x, date_y - 12, f"{day_with_ordinal} {month_year}")

        # Footer page number center bottom
        footer_text = f"Page {page_number}"
        footer_width = stringWidth(footer_text, "Helvetica", 10)
        c.drawString((width - footer_width) / 2, 30, footer_text)


    page_number = 1
    y = height - 80  # adjust to leave space for header

    add_header_footer(page_number)

    # Title (center aligned)
    c.setFont("Helvetica-Bold", 20)
    title_width = stringWidth(report.title, "Helvetica-Bold", 20)
    title_x = (width - title_width) / 2
    c.drawString(title_x, y, report.title)
    y -= 30

    # Description (left aligned)
    c.setFont("Helvetica", 12)
    description_lines = simpleSplit(report.description, "Helvetica", 12, text_width)
    for line in description_lines:
        c.drawString(left_margin, y, line)
        y -= 15

    y -= 20
    count = 1
    for diagram in diagrams:
        meters = ", ".join([m.name for m in diagram.meters.all()])
        measurements = ", ".join([m.name for m in diagram.measurements.all()])
        line = f"{count}. {diagram.diagram_type.title()} Chart of {meters} on {measurements}"

        # Diagram title (center aligned)
        c.setFont("Helvetica-Bold", 12)
        wrapped_lines = simpleSplit(line, "Helvetica-Bold", 12, text_width)
        for l in wrapped_lines:
            line_width = stringWidth(l, "Helvetica-Bold", 12)
            line_x = (width - line_width) / 2
            c.drawString(line_x, y, l)
            y -= 20

        # Image if exists
        if diagram.image and diagram.image.name:
            image_path = os.path.join(settings.MEDIA_ROOT, diagram.image.name)
            if os.path.exists(image_path):
                max_width = width - 100
                max_height = 4 * inch

                from PIL import Image as PILImage
                img = PILImage.open(image_path)
                img_width, img_height = img.size

                aspect = img_height / img_width

                display_width = max_width
                display_height = display_width * aspect

                if display_height > max_height:
                    display_height = max_height
                    display_width = display_height / aspect

                if y - display_height < 80:
                    c.showPage()
                    page_number += 1
                    add_header_footer(page_number)
                    y = height - 80

                c.drawImage(image_path, 50, y - display_height, width=display_width, height=display_height)
                y -= display_height + 10

        # Diagram description (left aligned)
        y -= 30
        c.setFont("Helvetica", 12)
        desc_lines = simpleSplit(diagram.description, "Helvetica", 12, text_width)
        for l in desc_lines:
            c.drawString(left_margin, y, l)
            y -= 15

        y -= 20

        c.showPage()
        page_number += 1
        add_header_footer(page_number)
        y = height - 80

        count += 1

    c.save()
    print("PDF GENERATED ✅")
    return FileResponse(open(output_path, 'rb'), as_attachment=True, filename=filename)


def savedReportsPage(request):
    context = {
        'reports':ReportFormat.objects.all()
    }
    return render(request, 'savedReportPage.html', context)

from django.views.decorators.clickjacking import xframe_options_exempt

@xframe_options_exempt
def viewSavedReports(request, reportID):
    reports =ReportFormat.objects.all() 
    report = ReportFormat.objects.get(id=reportID)
    pdf_url = f"/media/generatedReports/{report.title}.pdf"
    context = {
        'report': report,
        'pdf_url': pdf_url,
        'reports':reports
    }
    return render(request, 'savedReportView.html', context=context)



@xframe_options_exempt
def viewSavedReport(request, reportID):
    report = ReportFormat.objects.get(id=reportID)
    file_path = os.path.join(settings.MEDIA_ROOT, "generatedReports", f"{report.title}.pdf")
    if os.path.exists(file_path):
        return FileResponse(open(file_path, 'rb'), content_type='application/pdf')
    else:
        raise Http404("PDF not found.")



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
@login_required
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
@login_required
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
