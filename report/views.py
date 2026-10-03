import base64
import binascii
import json
import logging
import os
import uuid
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.staticfiles import finders
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Min
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.text import slugify
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from dashboard.aggregation import hourly_profile, period_starts, summarize_meter_period
from dashboard.measurements import is_cumulative, order_measurements, to_number
from dashboard.models import HierarchyDataAggregate, MeterReading, MeterReadingAggregate
from dynamic.models import Measurements, Meters, Site
from utils.access import can_access_site, get_profile, get_user_site, is_admin, json_login_required, visible_sites
from utils.decorators import subscription_required
from utils.timeutils import ensure_aware, local, local_range_bounds, local_str, period_end, period_start

from .models import ReportDiagram, ReportFormat

logger = logging.getLogger('dashboard')

DIAGRAM_TYPES = ['line', 'bar', 'pie', 'table', 'heatmap', 'sankey']
PERIOD_TYPES = ['daily', 'weekly', 'monthly', '3monthly', '6monthly', 'yearly']
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_LINE_POINTS_PER_METER = 3000
MAX_TABLE_ROWS = 2000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sidebar_sites(user):
    return visible_sites(user).prefetch_related('reports').order_by('name')


def _get_report(request, report_id):
    report = get_object_or_404(ReportFormat.objects.select_related('site', 'user__user'), id=report_id)
    if not can_access_site(request.user, report.site):
        raise Http404("Report not found")
    return report


def _get_diagram(request, diagram_id):
    diagram = get_object_or_404(ReportDiagram.objects.select_related('report_format__site', 'site'), id=diagram_id)
    if not can_access_site(request.user, diagram.report_format.site):
        raise Http404("Diagram not found")
    return diagram


def _json_errors(view_func):
    def _wrapped(request, *args, **kwargs):
        try:
            return view_func(request, *args, **kwargs)
        except Http404 as exc:
            return JsonResponse({'error': str(exc) or 'Not found'}, status=404)
    _wrapped.__name__ = view_func.__name__
    return _wrapped


def _units(names):
    units = {}
    for measurement in Measurements.objects.filter(name__in=names).prefetch_related('units'):
        unit = next((u.name for u in measurement.units.all() if u.name), None)
        if unit:
            units.setdefault(measurement.name, unit)
    return units


def _diagram_days(diagram):
    start = local(diagram.date_range_start)
    end = local(diagram.date_range_end) or start
    if start is None:
        return None, None
    start_day, end_day = start.date(), end.date()
    if end_day < start_day:
        start_day, end_day = end_day, start_day
    return start_day, end_day


def _measurement_choices():
    rows = Measurements.objects.values('name').annotate(first_id=Min('id'))
    names = order_measurements(row['name'] for row in rows)
    return names


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@login_required
@subscription_required
def reports(request):
    sites = _sidebar_sites(request.user)
    meters = Meters.objects.filter(area__building__site__in=sites).select_related('area__building__site').order_by('name')
    context = {
        'sites': sites,
        'meters': meters,
        'measurement_names': _measurement_choices(),
        'default_site': get_user_site(request.user),
        'diagram_types': DIAGRAM_TYPES,
    }
    return render(request, 'reports.html', context)


def _parse_diagram(data, site):
    diagram_type = data.get('type')
    if diagram_type not in DIAGRAM_TYPES:
        raise ValueError(f"Unknown diagram type {diagram_type!r}")

    def parse_bound(value, is_end=False):
        if not value:
            return None
        if diagram_type == 'line':
            return timezone.make_aware(datetime.strptime(value, '%Y-%m-%dT%H:%M'))
        day = parse_date(value)
        if day is None:
            raise ValueError(f"Invalid date {value!r}")
        return local_range_bounds(day, day)[0]

    start = parse_bound(data.get('startDate'))
    if start is None:
        raise ValueError("Every diagram needs a start date")
    end = parse_bound(data.get('endDate')) if diagram_type != 'sankey' else start
    if end is None:
        end = start
    if end < start:
        start, end = end, start

    period = data.get('periodType') or None
    if diagram_type in ('bar', 'pie', 'sankey') and period not in PERIOD_TYPES:
        raise ValueError("Select a period type for bar, pie and sankey diagrams")
    if diagram_type == 'sankey' and period not in ('weekly', 'monthly', 'yearly'):
        raise ValueError("Sankey diagrams support weekly, monthly or yearly periods")

    meter_ids = [int(m) for m in data.get('meters') or [] if str(m).isdigit()]
    meters = list(Meters.objects.filter(id__in=meter_ids, area__building__site=site))
    if diagram_type != 'sankey' and not meters:
        raise ValueError(f"The {diagram_type} diagram needs at least one meter of {site.name}")
    if diagram_type in ('table', 'heatmap'):
        meters = meters[:1]

    names = data.get('measurements') if diagram_type == 'table' else [data.get('measurement')]
    names = [str(n) for n in (names or []) if n]
    if not names:
        raise ValueError(f"The {diagram_type} diagram needs a measurement")

    measurements = []
    for name in names:
        measurement = Measurements.objects.filter(name=name).order_by('id').first()
        if measurement is None:
            measurement = Measurements.objects.create(name=name, meter=meters[0] if meters else None)
        measurements.append(measurement)
    return {
        'diagram_type': diagram_type,
        'start': start,
        'end': end,
        'period': period,
        'meters': meters,
        'measurements': measurements,
        'description': (data.get('description') or '')[:1000],
    }


@login_required
@subscription_required
@require_POST
def createReportFormat(request):
    title = (request.POST.get('title') or '').strip()
    description = (request.POST.get('description') or '').strip()
    site = Site.objects.filter(id=request.POST.get('site') or 0).first() if is_admin(request.user) else get_user_site(request.user)

    errors = []
    if not title:
        errors.append("A report title is required.")
    if site is None or not can_access_site(request.user, site):
        errors.append("Select the site the report belongs to.")

    parsed = []
    if not errors:
        raw_diagrams = request.POST.getlist('diagrams[]')
        if not raw_diagrams:
            errors.append("Add at least one diagram.")
        for index, raw in enumerate(raw_diagrams, start=1):
            try:
                parsed.append(_parse_diagram(json.loads(raw), site))
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                errors.append(f"Diagram {index}: {exc}")

    logo = request.FILES.get('reportImage')
    if logo is not None and not (logo.content_type or '').startswith('image/'):
        errors.append("The report logo must be an image.")

    if errors:
        for error in errors:
            messages.error(request, error)
        return redirect('/reports')

    with transaction.atomic():
        report = ReportFormat.objects.create(
            title=title[:255], description=description, user=get_profile(request.user), site=site,
            logo=logo or '',
        )
        for item in parsed:
            diagram = ReportDiagram.objects.create(
                report_format=report,
                site=site,
                diagram_type=item['diagram_type'],
                period_type=item['period'],
                date_range_start=item['start'],
                date_range_end=item['end'],
                description=item['description'],
            )
            diagram.meters.set(item['meters'])
            diagram.measurements.set(item['measurements'])

    messages.success(request, f'Report "{title}" created.')
    return redirect(f'/reports/viewReport/{report.id}')


@login_required
@subscription_required
@require_POST
def deleteReport(request, reportID):
    report = _get_report(request, reportID)
    if not (is_admin(request.user) or (report.user and report.user.user_id == request.user.id)):
        messages.error(request, "Only administrators or the author can delete a report.")
        return redirect(f'/reports/viewReport/{report.id}')
    pdf_path = os.path.join(settings.MEDIA_ROOT, "generatedReports", f"Report-{report.id}.pdf")
    title = report.title
    report.delete()
    if os.path.exists(pdf_path):
        os.remove(pdf_path)
    messages.success(request, f'Report "{title}" deleted.')
    return redirect('/reports')


@login_required
@subscription_required
def viewReport(request, reportID):
    report = _get_report(request, reportID)
    diagrams = list(report.diagrams.prefetch_related('meters', 'measurements').order_by('id'))
    configs = []
    for diagram in diagrams:
        measurement_names = order_measurements(m.name for m in diagram.measurements.all())
        start_day, end_day = _diagram_days(diagram)
        configs.append({
            'id': diagram.id,
            'type': diagram.diagram_type,
            'period': diagram.period_type,
            'measurements': measurement_names,
            'meters': [{'id': m.id, 'name': m.name} for m in diagram.meters.all()],
            'start': local_str(diagram.date_range_start, '%Y-%m-%d %H:%M') if diagram.diagram_type == 'line' else str(start_day),
            'end': local_str(diagram.date_range_end, '%Y-%m-%d %H:%M') if diagram.diagram_type == 'line' else str(end_day),
        })
        diagram.measurement_names = measurement_names
    context = {
        'sites': _sidebar_sites(request.user),
        'individualReport': report,
        'diagrams': diagrams,
        'diagram_configs': configs,
        'uses_echarts': any(d.diagram_type in ('sankey', 'heatmap') for d in diagrams),
    }
    return render(request, 'reportView2.html', context=context)


# ---------------------------------------------------------------------------
# Diagram data (JSON)
# ---------------------------------------------------------------------------

@json_login_required
@subscription_required
@require_POST
@_json_errors
def saveDiagramImage(request, diagramID):
    diagram = _get_diagram(request, diagramID)
    try:
        payload = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Invalid JSON."}, status=400)

    image_data = payload.get('image') or ''
    header, _, encoded = image_data.partition(';base64,')
    if header not in ('data:image/png', 'data:image/jpeg') or not encoded:
        return JsonResponse({"status": "error", "message": "Only PNG or JPEG data URLs are accepted."}, status=400)
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return JsonResponse({"status": "error", "message": "Corrupt image data."}, status=400)
    if len(raw) > MAX_IMAGE_BYTES:
        return JsonResponse({"status": "error", "message": "Image too large."}, status=413)

    ext = 'png' if header.endswith('png') else 'jpg'
    if diagram.image:
        diagram.image.delete(save=False)
    diagram.image.save(f"diagram_{diagram.id}_{uuid.uuid4().hex}.{ext}", ContentFile(raw), save=True)
    return JsonResponse({"status": "success", "image_url": diagram.image.url})


@json_login_required
@subscription_required
@_json_errors
def getDiagramData(request, diagramID):
    """Bar / pie data: one value per meter per period (consumption for counters, average otherwise)."""
    diagram = _get_diagram(request, diagramID)
    measurement = diagram.measurements.order_by('id').values_list('name', flat=True).first()
    start_day, end_day = _diagram_days(diagram)
    period = diagram.period_type or 'monthly'
    if not measurement or start_day is None:
        return JsonResponse({'error': 'Diagram is missing a measurement or date range.'}, status=400)

    starts = period_starts(start_day, end_day, period)
    if period == 'daily' and len(starts) > 400:
        return JsonResponse({'error': 'Daily diagrams are limited to 400 days.'}, status=400)

    today = timezone.localdate()
    data = []
    for meter in diagram.meters.all():
        stored = {}
        if period != 'daily':
            stored = {
                agg.start_date: agg.aggregateData or {}
                for agg in MeterReadingAggregate.objects.filter(meter=meter, period_type=period, start_date__in=starts)
            }
        for start in starts:
            open_period = period in ('daily', 'weekly', 'monthly') and start <= today < period_end(start, period)
            values = stored.get(start)
            if values is None or measurement not in values or open_period:
                values = summarize_meter_period(meter, start, period, fields={measurement})
            value = to_number(values.get(measurement))
            if value is not None:
                data.append({'period': start.isoformat(), 'meter_id': meter.id, 'meter': meter.name, 'value': round(value, 3)})

    return JsonResponse({
        'data': data,
        'measurement': measurement,
        'unit': _units([measurement]).get(measurement, ''),
        'cumulative': is_cumulative(measurement),
        'period': period,
    })


@json_login_required
@subscription_required
@_json_errors
def getLineDiagramData(request, diagramID):
    diagram = _get_diagram(request, diagramID)
    measurement = diagram.measurements.order_by('id').values_list('name', flat=True).first()
    if not measurement:
        return JsonResponse({'error': 'No measurement selected.'}, status=400)
    start = ensure_aware(diagram.date_range_start)
    end = ensure_aware(diagram.date_range_end) or start

    data = []
    for meter in diagram.meters.all():
        rows = MeterReading.objects.filter(meter=meter, timestamp__gte=start, timestamp__lte=end).order_by('timestamp')
        total = rows.count()
        step = max(1, -(-total // MAX_LINE_POINTS_PER_METER))
        for index, (timestamp, values) in enumerate(rows.values_list('timestamp', 'data').iterator(chunk_size=5000)):
            if index % step:
                continue
            value = to_number((values or {}).get(measurement))
            if value is None:
                continue
            data.append({
                'ts': int(timestamp.timestamp() * 1000),
                'timestamp': local_str(timestamp, '%Y-%m-%d %H:%M'),
                'meter_id': meter.id,
                'value': value,
            })
    return JsonResponse({'data': data, 'measurement': measurement, 'unit': _units([measurement]).get(measurement, '')})


@json_login_required
@subscription_required
@_json_errors
def getTableData(request, diagramID):
    diagram = _get_diagram(request, diagramID)
    names = [n for n in order_measurements(diagram.measurements.values_list('name', flat=True)) if n != 'Timestamp']
    start_day, end_day = _diagram_days(diagram)
    if start_day is None:
        return JsonResponse({'rows': [], 'columns': []})
    start, end = local_range_bounds(start_day, end_day)

    rows = []
    queryset = MeterReading.objects.filter(
        meter__in=diagram.meters.all(), timestamp__gte=start, timestamp__lt=end
    ).select_related('meter').order_by('-timestamp')
    truncated = queryset.count() > MAX_TABLE_ROWS
    for reading in queryset[:MAX_TABLE_ROWS]:
        row = {'Timestamp': local_str(reading.timestamp, "%Y-%m-%d %H:%M"), 'Meter': reading.meter.name}
        for name in names:
            row[name] = (reading.data or {}).get(name)
        rows.append(row)
    return JsonResponse({"rows": rows, "columns": ['Timestamp', 'Meter'] + names, "truncated": truncated})


@json_login_required
@subscription_required
@_json_errors
def heatmap_data(request, diagramID):
    diagram = _get_diagram(request, diagramID)
    measurement = diagram.measurements.order_by('id').values_list('name', flat=True).first()
    meter = diagram.meters.first()
    start_day, end_day = _diagram_days(diagram)
    if meter is None or not measurement or start_day is None:
        return JsonResponse({'error': 'Diagram needs a meter, a measurement and a date range.'}, status=400)
    if (end_day - start_day).days > 366:
        return JsonResponse({'error': 'Heat maps are limited to one year.'}, status=400)
    data, mode = hourly_profile(meter, start_day, end_day, measurement)
    return JsonResponse({
        'measurement': measurement,
        'meter_id': meter.id,
        'meter': meter.name,
        'mode': mode,
        'unit': _units([measurement]).get(measurement, ''),
        'start': str(start_day),
        'end': str(end_day),
        'data': data,
    })


@json_login_required
@subscription_required
@_json_errors
def sankey_data(request, diagramID):
    diagram = _get_diagram(request, diagramID)
    site = diagram.site or diagram.report_format.site
    period_type = diagram.period_type or 'monthly'
    start_day, _ = _diagram_days(diagram)
    if site is None or start_day is None:
        return JsonResponse({'error': 'Diagram needs a site and a date.'}, status=400)
    requested = period_start(start_day, period_type)

    queryset = HierarchyDataAggregate.objects.filter(site=site, period_type=period_type)
    entry = queryset.filter(start_date=requested).first()
    exact = entry is not None
    if entry is None:
        entry = queryset.filter(start_date__lte=requested).order_by('-start_date').first()
    if entry is None:
        return JsonResponse({'error': f'No {period_type} hierarchy aggregate for {site.name} on or before {requested}.'}, status=404)

    measurement = diagram.measurements.order_by('id').values_list('name', flat=True).first()
    return JsonResponse({
        'hierarchy': entry.data,
        'site': site.name,
        'measurement': measurement,
        'unit': _units([measurement]).get(measurement, '') if measurement else '',
        'start_date': str(entry.start_date),
        'requested_date': str(requested),
        'exact': exact,
    })


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def _report_pdf_path(report):
    return os.path.join(settings.MEDIA_ROOT, "generatedReports", f"Report-{report.id}.pdf")


def build_report_pdf(report):
    from PIL import Image as PILImage
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import inch
    from reportlab.lib.utils import simpleSplit
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas

    diagrams = list(report.diagrams.prefetch_related('meters', 'measurements').order_by('id'))
    output_path = _report_pdf_path(report)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    pdf = canvas.Canvas(output_path, pagesize=A4)
    pdf.setTitle(report.title)
    width, height = A4
    left_margin, right_margin = 50, width - 50
    text_width = right_margin - left_margin

    logo_path = None
    if report.logo and report.logo.name:
        candidate = os.path.join(settings.MEDIA_ROOT, report.logo.name)
        if os.path.exists(candidate):
            logo_path = candidate
    if logo_path is None:
        logo_path = finders.find('customerLogo.png')

    author = ''
    if report.user:
        author = (report.user.user.get_full_name() if report.user.user else '') or report.user.name or report.user.email
    generated = timezone.localtime()

    def header_footer(page_number):
        if logo_path:
            try:
                pdf.drawImage(logo_path, 20, height - inch - 5, width=1.5 * inch, height=inch, preserveAspectRatio=True, mask='auto')
            except Exception:
                logger.warning("Could not draw report logo %s", logo_path)
        pdf.setFont("Helvetica", 10)
        pdf.drawString(width - 150, height - 40, generated.strftime("%A"))
        pdf.drawString(width - 150, height - 52, generated.strftime("%d %B %Y, %H:%M"))
        footer = f"Page {page_number}"
        pdf.drawString((width - stringWidth(footer, "Helvetica", 10)) / 2, 30, footer)
        if author:
            for i, line in enumerate(reversed(["Report generated by:", author])):
                pdf.drawString(right_margin - stringWidth(line, "Helvetica", 10), 30 + i * 12, line)

    page = 1
    y = height - 90
    header_footer(page)

    def new_page():
        nonlocal page, y
        pdf.showPage()
        page += 1
        header_footer(page)
        y = height - 90

    pdf.setFont("Helvetica-Bold", 20)
    for line in simpleSplit(report.title, "Helvetica-Bold", 20, text_width):
        pdf.drawString((width - stringWidth(line, "Helvetica-Bold", 20)) / 2, y, line)
        y -= 24
    y -= 6
    pdf.setFont("Helvetica", 12)
    for line in simpleSplit(report.description or '', "Helvetica", 12, text_width):
        if y < 80:
            new_page()
        pdf.drawString(left_margin, y, line)
        y -= 15
    y -= 20

    for index, diagram in enumerate(diagrams, start=1):
        meters = ", ".join(m.name for m in diagram.meters.all()) or (diagram.site.name if diagram.site else "site")
        measurements = ", ".join(order_measurements(m.name for m in diagram.measurements.all()))
        start_day, end_day = _diagram_days(diagram)
        span = f"{start_day}" if start_day == end_day else f"{start_day} to {end_day}"
        title = f"{index}. {diagram.diagram_type.title()} chart of {meters} on {measurements} ({span})"

        pdf.setFont("Helvetica-Bold", 12)
        lines = simpleSplit(title, "Helvetica-Bold", 12, text_width)

        image_path, display_width, display_height = None, 0, 0
        if diagram.image and diagram.image.name:
            candidate = os.path.join(settings.MEDIA_ROOT, diagram.image.name)
            if os.path.exists(candidate):
                image_path = candidate
                with PILImage.open(image_path) as img:
                    img_width, img_height = img.size
                aspect = img_height / img_width if img_width else 1
                display_width = width - 100
                display_height = display_width * aspect
                max_height = 4.5 * inch
                if display_height > max_height:
                    display_height = max_height
                    display_width = display_height / aspect

        # Keep the heading together with its chart.
        if y - 18 * len(lines) - display_height - 10 < 80:
            new_page()
        pdf.setFont("Helvetica-Bold", 12)
        for line in lines:
            pdf.drawString((width - stringWidth(line, "Helvetica-Bold", 12)) / 2, y, line)
            y -= 18

        if image_path:
            pdf.drawImage(image_path, (width - display_width) / 2, y - display_height, width=display_width, height=display_height)
            y -= display_height + 10
        else:
            pdf.setFont("Helvetica-Oblique", 10)
            pdf.drawString(left_margin, y, "(Chart image not captured - open the report and use \"Save PDF\".)")
            y -= 15

        y -= 10
        pdf.setFont("Helvetica", 11)
        for line in simpleSplit(diagram.description or '', "Helvetica", 11, text_width):
            if y < 80:
                new_page()
            pdf.drawString(left_margin, y, line)
            y -= 14
        y -= 20

    pdf.save()
    return output_path


@login_required
@subscription_required
def generate_pdf(request, reportID, filename=None):
    report = _get_report(request, reportID)
    output_path = build_report_pdf(report)
    download_name = f"{slugify(report.title) or 'report'}-{report.id}.pdf"
    return FileResponse(open(output_path, 'rb'), as_attachment=True, filename=download_name)


@login_required
@subscription_required
def savedReportsPage(request):
    return render(request, 'savedReportPage.html', {'sites': _sidebar_sites(request.user)})


@login_required
@subscription_required
def viewSavedReports(request, reportID):
    report = _get_report(request, reportID)
    pdf_path = _report_pdf_path(report)
    pdf_exists = os.path.exists(pdf_path)
    context = {
        'report': report,
        'pdf_exists': pdf_exists,
        'pdf_generated_at': timezone.localtime(timezone.make_aware(datetime.fromtimestamp(os.path.getmtime(pdf_path)))) if pdf_exists else None,
        'sites': _sidebar_sites(request.user),
    }
    return render(request, 'savedReportView.html', context=context)


@xframe_options_sameorigin
@login_required
@subscription_required
def viewSavedReport(request, reportID):
    report = _get_report(request, reportID)
    file_path = _report_pdf_path(report)
    if not os.path.exists(file_path):
        raise Http404("PDF not generated yet.")
    return FileResponse(open(file_path, 'rb'), content_type='application/pdf')
