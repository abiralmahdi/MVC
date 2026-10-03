import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, ProtectedError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from connections import protocols
from dashboard.measurements import MEASUREMENT_UNITS, METER_DEFINITIONS, ORDERED_MEASUREMENTS
from home.models import GlobalConfiguration
from utils.access import superuser_required

from .models import Areas, Buildings, LoadType, Measurements, Meters, Site, Units

logger = logging.getLogger('connections')

METER_TYPES = [
    "Electricity Meter", "Water Meter", "Gas Meter", "Steam Meter", "Fuel Meter",
    "Temperature", "Pressure", "Humidity", "Air Quality", "Transmitter",
]
TREE_TYPES = ["hierarchy", "loadType", "meterType"]


@login_required
@superuser_required
def configureDashboard(request):
    return redirect('/settings/configurations')


@login_required
@superuser_required
def settings(request):
    return render(request, 'settings.html')


@login_required
@superuser_required
def hierarchy(request):
    sites = Site.objects.prefetch_related('buildings__areas__meters').annotate(
        area_count=Count('buildings__areas', distinct=True),
        meter_count=Count('buildings__areas__meters', distinct=True),
    ).order_by('name')
    buildings = Buildings.objects.select_related('site').prefetch_related('areas__meters').annotate(
        area_count=Count('areas', distinct=True),
        meter_count=Count('areas__meters', distinct=True),
    ).order_by('site__name', 'name')
    areas = Areas.objects.select_related('building__site').prefetch_related('meters__loadType').order_by('building__site__name', 'building__name', 'name')
    load_types = LoadType.objects.prefetch_related('meters__area__building__site').order_by('name')
    meters = Meters.objects.select_related('area__building__site', 'loadType').prefetch_related('gadgets').order_by('name')

    measurement_names = list(dict.fromkeys(ORDERED_MEASUREMENTS + sorted(
        set(Measurements.objects.values_list('name', flat=True)) - set(ORDERED_MEASUREMENTS)
    )))
    protocol_counts = {}
    for meter in meters:
        meter.mapping_json = json.dumps(meter.registerMapping or {}, indent=1)
        meter.point_summaries = [
            (name, protocols.describe_point(meter.protocol, point)) for name, point in (meter.registerMapping or {}).items()
        ]
        meter.public_connection = {k: ('••••••' if k == 'password' and v else v) for k, v in (meter.connection or {}).items()}
        # State for the edit form. Secrets stay on the server: an empty password field keeps the stored one.
        meter.form_state_id = f'meter-state-{meter.id}'
        meter.form_state = {
            'protocol': meter.protocol,
            'host': meter.ip or '',
            'connection': {k: ('' if k == 'password' else v) for k, v in (meter.connection or {}).items()},
            'secrets': [k for k in ('password',) if (meter.connection or {}).get(k)],
            'mapping': meter.registerMapping or {},
        }
        protocol_counts[meter.protocol] = protocol_counts.get(meter.protocol, 0) + 1

    context = {
        'sites': sites,
        'buildings': buildings,
        'areas': areas,
        'loadTypes': load_types,
        'meters': meters,
        'measurement_names': measurement_names,
        'meter_types': METER_TYPES,
        'meter_definitions': METER_DEFINITIONS,
        'protocol_catalogue': protocols.catalogue(),
        'protocol_counts': [(label, protocol_counts.get(key, 0)) for key, label in protocols.CHOICES],
    }
    return render(request, 'hierarchy.html', context)


def _back():
    return redirect("/settings/hierarchy")


@login_required
@superuser_required
@require_POST
def addSite(request):
    name = (request.POST.get('site_name') or '').strip()
    try:
        latitude = float(request.POST.get('latitude'))
        longitude = float(request.POST.get('longitude'))
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError
    except (TypeError, ValueError):
        messages.error(request, "Latitude/longitude must be valid coordinates.")
        return _back()
    if not name:
        messages.error(request, "Site name is required.")
        return _back()
    Site.objects.create(name=name, latitude=f"{latitude:.6f}", longitude=f"{longitude:.6f}")
    messages.success(request, f"Site {name} added.")
    return _back()


@login_required
@superuser_required
@require_POST
def addBuilding(request):
    name = (request.POST.get('building_name') or '').strip()
    site = Site.objects.filter(id=request.POST.get('site_id') or 0).first()
    if not name or site is None:
        messages.error(request, "Building name and site are required.")
        return _back()
    Buildings.objects.create(name=name, site=site, image=request.FILES.get('image'))
    messages.success(request, f"Building {name} added.")
    return _back()


@login_required
@superuser_required
@require_POST
def addArea(request):
    name = (request.POST.get('area_name') or '').strip()
    building = Buildings.objects.filter(id=request.POST.get('building_id') or 0).first()
    if not name or building is None:
        messages.error(request, "Area name and building are required.")
        return _back()
    Areas.objects.create(name=name, building=building)
    messages.success(request, f"Area {name} added.")
    return _back()


def _json_post(request, name):
    try:
        value = json.loads(request.POST.get(name) or '{}')
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _meter_from_post(request, meter=None):
    errors = []
    name = (request.POST.get('meter_name') or '').strip()
    area = Areas.objects.filter(id=request.POST.get('area_id') or 0).first()
    load = LoadType.objects.filter(id=request.POST.get('load_id') or 0).first()
    meter_type = (request.POST.get('meterType') or '').strip()
    protocol = (request.POST.get('protocol') or '').strip()

    if not name:
        errors.append("Meter name is required.")
    if area is None:
        errors.append("Select an area.")
    if not meter_type:
        errors.append("Select a meter type.")
    if protocol not in protocols.PROTOCOLS:
        return None, errors + ["Select a communication protocol."]

    raw_connection = _json_post(request, 'connection')
    raw_mapping = _json_post(request, 'register_mapping')
    if raw_connection is None or raw_mapping is None:
        return None, errors + ["The form was not submitted correctly; reload the page and try again."]

    # Secrets are never sent back to the browser: an empty password keeps the stored one.
    if meter is not None and meter.protocol == protocol:
        for field in protocols.get(protocol).connection:
            if field.type == 'secret' and not raw_connection.get(field.name):
                raw_connection[field.name] = (meter.connection or {}).get(field.name, '')

    host, connection, connection_errors = protocols.clean_connection(protocol, request.POST.get('meter_ip'), raw_connection)
    errors += connection_errors
    mapping, mapping_errors = protocols.clean_mapping(protocol, raw_mapping)
    errors += mapping_errors
    if errors:
        return None, errors

    meter = meter or Meters()
    meter.name = name
    meter.area = area
    meter.loadType = load
    meter.meterType = meter_type
    meter.protocol = protocol
    meter.ip = host
    meter.connection = connection
    meter.ecological = request.POST.get('ecological') == 'on'
    meter.registerMapping = mapping
    return meter, []


def _ensure_measurements(meter):
    """Every mapped label becomes a Measurement so it can be used in gadgets, alarms and reports."""
    existing = set(meter.measurements.values_list('name', flat=True))
    for label in (meter.registerMapping or {}):
        if label in existing:
            continue
        measurement = Measurements.objects.create(name=label, meter=meter)
        if label in MEASUREMENT_UNITS:
            Units.objects.create(name=MEASUREMENT_UNITS[label], measurement=measurement)


@login_required
@superuser_required
@require_POST
def addMeter(request):
    meter, errors = _meter_from_post(request)
    if errors:
        for error in errors:
            messages.error(request, error)
        return _back()
    with transaction.atomic():
        meter.save()
        _ensure_measurements(meter)
    messages.success(request, f"Meter {meter.name} added.")
    return _back()


@login_required
@superuser_required
@require_POST
def editMeter(request, meterID):
    meter = get_object_or_404(Meters, id=meterID)
    meter, errors = _meter_from_post(request, meter)
    if errors:
        for error in errors:
            messages.error(request, error)
        return _back()
    with transaction.atomic():
        meter.save()
        _ensure_measurements(meter)
    messages.success(request, f"Meter {meter.name} updated.")
    return _back()


@login_required
@superuser_required
@require_POST
def testMeter(request, meterID):
    """Read the meter once with its saved configuration and return the values (nothing is stored)."""
    from connections import drivers
    from connections.datastorage import poll_meter

    meter = get_object_or_404(Meters, id=meterID)
    result = poll_meter(meter, one_shot=True)
    response = {
        'meter': meter.name, 'protocol': meter.protocol_label, 'address': meter.address_summary,
        'ok': result.ok, 'data': result.data, 'errors': result.errors,
    }
    if request.POST.get('discover') == '1':
        found, discover_errors = drivers.discover(meter.protocol, meter.ip, {**(meter.connection or {}), '_one_shot': True})
        response['discovered'] = found
        response['errors'] = response['errors'] + discover_errors
    return JsonResponse(response, json_dumps_params={'default': str})


@login_required
@superuser_required
@require_POST
def addLoadType(request):
    name = (request.POST.get('load_name') or '').strip()
    if not name:
        messages.error(request, "Load type name is required.")
        return _back()
    LoadType.objects.get_or_create(name=name)
    messages.success(request, f"Load type {name} added.")
    return _back()


def _delete(request, model, object_id, label):
    obj = get_object_or_404(model, id=object_id)
    name = str(obj)
    try:
        with transaction.atomic():
            obj.delete()
    except ProtectedError:
        messages.error(request, f"{label} {name} cannot be deleted because billing records exist for its meters.")
        return _back()
    messages.success(request, f"{label} {name} deleted.")
    return _back()


@login_required
@superuser_required
@require_POST
def deleteSite(request, siteID):
    return _delete(request, Site, siteID, "Site")


@login_required
@superuser_required
@require_POST
def deleteBuilding(request, siteID):
    return _delete(request, Buildings, siteID, "Building")


@login_required
@superuser_required
@require_POST
def deleteArea(request, siteID):
    return _delete(request, Areas, siteID, "Area")


@login_required
@superuser_required
@require_POST
def deleteMeter(request, siteID):
    return _delete(request, Meters, siteID, "Meter")


@login_required
@superuser_required
@require_POST
def deleteLoadType(request, loadID):
    load = get_object_or_404(LoadType, id=loadID)
    load.meters.update(loadType=None)
    load.delete()
    messages.success(request, f"Load type {load.name} deleted; its meters now have no load type.")
    return _back()


@login_required
@superuser_required
def configurations(request):
    config = GlobalConfiguration.load()
    if request.method == "POST":
        config.report = 'report' in request.POST
        config.dashboard = 'dashboard' in request.POST
        config.alarm = 'alarm' in request.POST
        config.siteLocations = 'siteLocations' in request.POST
        config.scada = 'scada' in request.POST
        config.billing = 'billing' in request.POST
        config.machineLearning = 'machineLearning' in request.POST
        config.subscribed = 'subscribed' in request.POST
        tree_type = request.POST.get('treeType')
        if tree_type in TREE_TYPES:
            config.treeType = tree_type
        config.save()
        messages.success(request, "Configuration saved.")
        return redirect('/settings/configurations')
    return render(request, 'configurations.html', {'config': config})
