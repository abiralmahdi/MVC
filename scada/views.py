import json
import logging
from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from utils.access import can_access_site, can_control_equipment, json_login_required, superuser_required, visible_sites
from utils.decorators import subscription_required

from .models import Buildings, Motor, Tank
from .plc import FIELD_TYPES, PlcError, decode_motor, decode_tank, plc_connection, read_db, write_command

logger = logging.getLogger('scada')


def _visible_motors(user):
    return Motor.objects.filter(building__site__in=visible_sites(user)).select_related('building__site').prefetch_related('tank')


def _render_scada(request, building=None):
    motors = _visible_motors(request.user)
    if building is not None:
        motors = motors.filter(building=building)
    tanks = Tank.objects.filter(motor__in=motors).select_related('motor')
    context = {
        "building": building,
        "motors": motors,
        "tanks": tanks,
        "sites": visible_sites(request.user).prefetch_related('buildings'),
        "can_control": can_control_equipment(request.user),
        "field_types": list(FIELD_TYPES.keys()),
    }
    return render(request, "scada.html", context)


@login_required
@subscription_required
def scada(request):
    return _render_scada(request)


@login_required
@subscription_required
def scadaBuilding(request, buildingID):
    building = get_object_or_404(Buildings.objects.select_related('site'), id=buildingID)
    if not can_access_site(request.user, building.site):
        messages.error(request, "You are not authorized to view that building.")
        return redirect('/scada')
    return _render_scada(request, building)


def _status_for_motors(motors):
    """Read many motors using one PLC connection per (ip, rack, slot)."""
    results = {}
    groups = defaultdict(list)
    for motor in motors:
        groups[(motor.ip, motor.rack, motor.slot)].append(motor)

    for (ip, rack, slot), group in groups.items():
        try:
            with plc_connection(ip, rack, slot) as client:
                for motor in group:
                    try:
                        data = read_db(client, motor)
                        status = decode_motor(motor, data)
                        status['tanks'] = [decode_tank(tank, data) for tank in motor.tank.all()]
                        status['tank'] = status['tanks'][0] if status['tanks'] else {}
                    except PlcError as exc:
                        status = {'error': str(exc)}
                    results[motor.id] = status
        except PlcError as exc:
            for motor in group:
                results[motor.id] = {'error': str(exc)}
    return results


@json_login_required
@subscription_required
def scadaStatus(request):
    """Status of every motor visible to the user (optionally ?building=<id>)."""
    motors = _visible_motors(request.user)
    if request.GET.get('building'):
        motors = motors.filter(building_id=request.GET['building'])
    return JsonResponse({'motors': {str(k): v for k, v in _status_for_motors(list(motors)).items()}})


@json_login_required
@subscription_required
def fetchMotorAndTankData(request, motorID):
    motor = get_object_or_404(_visible_motors(request.user), id=motorID)
    status = _status_for_motors([motor])[motor.id]
    if 'error' in status:
        return JsonResponse(status, status=502)
    return JsonResponse(status)


def _int_field(request, name, default=0, minimum=0, maximum=None):
    raw = request.POST.get(name, '')
    if raw in ('', None):
        return default
    value = int(raw)
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f'{name} must be between {minimum} and {maximum}')
    return value


@login_required
@superuser_required
@require_POST
def save_motor(request):
    building = get_object_or_404(Buildings, id=request.POST.get("building") or 0)
    try:
        fields = json.loads(request.POST.get("fields") or "{}")
        if not isinstance(fields, dict):
            raise ValueError("fields must be an object")
        for name, info in fields.items():
            if not isinstance(info, list) or len(info) < 2 or str(info[0]).upper() not in FIELD_TYPES:
                raise ValueError(f'invalid field definition for "{name}"')

        def offset(prefix):
            return {"byte": _int_field(request, f"{prefix}Byte"), "bit": _int_field(request, f"{prefix}Bit", maximum=7)}

        motor = Motor(
            motorName=(request.POST.get("motorName") or '').strip() or 'Motor',
            building=building,
            ip=(request.POST.get("ip") or '').strip(),
            dbNo=_int_field(request, "dbNo", minimum=1),
            rack=_int_field(request, "rack"),
            slot=_int_field(request, "slot"),
            startByte=_int_field(request, "startByte"),
            dataSize=_int_field(request, "dataSize", default=16, minimum=1, maximum=65535),
            motorOnOffset=offset("motorOn"),
            motorOffOffset=offset("motorOff"),
            runFeedbackOffset=offset("runFeedback"),
            tripOffset=offset("trip"),
            fields=fields,
        )
        if not motor.ip:
            raise ValueError("PLC IP address is required")

        tank_fields = ["highByte", "lowByte", "highBit", "lowBit", "valueByte", "valueBit", "tankVolume"]
        tank = None
        if any(request.POST.get(f) for f in tank_fields):
            tank = Tank(
                tankName=(request.POST.get("tankName") or '').strip() or None,
                highByte=_int_field(request, "highByte", default=None),
                lowByte=_int_field(request, "lowByte", default=None),
                highBit=_int_field(request, "highBit", default=None, maximum=7),
                lowBit=_int_field(request, "lowBit", default=None, maximum=7),
                valueByte=_int_field(request, "valueByte", default=None),
                valueBit=_int_field(request, "valueBit", default=None, maximum=7),
                tankVolume=_int_field(request, "tankVolume", default=100, minimum=1),
            )
    except ValueError as exc:
        messages.error(request, f"Motor not saved: {exc}")
        return redirect(request.META.get('HTTP_REFERER') or "/scada")

    motor.save()
    if tank is not None:
        tank.motor = motor
        tank.save()
    messages.success(request, f"Motor {motor.motorName} saved.")
    return redirect(f"/scada/building/{building.id}")


@login_required
@superuser_required
@require_POST
def delete_motor(request, motorID):
    motor = get_object_or_404(Motor, id=motorID)
    building_id = motor.building_id
    motor.delete()
    messages.success(request, "Motor deleted.")
    return redirect(f"/scada/building/{building_id}")


@json_login_required
@subscription_required
@require_POST
def control_motor(request):
    if not can_control_equipment(request.user):
        return JsonResponse({"success": False, "error": "You are not authorized to operate equipment."}, status=403)

    action = request.POST.get("action")
    if action not in ("start", "stop"):
        return JsonResponse({"success": False, "error": "Unknown action."}, status=400)
    motor = _visible_motors(request.user).filter(id=request.POST.get("motor_id") or 0).first()
    if motor is None:
        return JsonResponse({"success": False, "error": "Motor not found."}, status=404)

    logger.warning("Motor command %s -> %s (id %s, PLC %s) by %s", action, motor.motorName, motor.id, motor.ip, request.user.username)
    try:
        with plc_connection(motor.ip, motor.rack, motor.slot) as client:
            write_command(client, motor, action)
            status = decode_motor(motor, read_db(client, motor))
    except PlcError as exc:
        logger.error("Motor command failed for %s: %s", motor.motorName, exc)
        return JsonResponse({"success": False, "error": str(exc)}, status=502)

    motor.isOn = bool(status.get('isOn'))
    motor.save(update_fields=['isOn'])
    return JsonResponse({"success": True, **status})
