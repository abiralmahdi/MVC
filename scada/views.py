from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.http import JsonResponse
import json
from .models import *
from home.models import GlobalConfiguration
from utils.decorators import subscription_required

# Create your views here.
@subscription_required
def scada(request):
    masters = MotorMasters.objects.all()
    motors = Motor.objects.all().prefetch_related('tank')
    sites = Site.objects.all().prefetch_related('buildings')
    config = GlobalConfiguration.objects.first()
    tanks = Tank.objects.all()
    context = {
        "masters":masters,
        "motors":motors,
        "config":config,
        "sites":sites,
        "tanks":tanks
    }
    return render(request, "scada.html", context)

@subscription_required
def scadaBuilding(request, buildingID):
    masters = MotorMasters.objects.all()
    building = Buildings.objects.get(id=buildingID)
    motors = Motor.objects.filter(building=building).prefetch_related('tank')
    sites = Site.objects.all().prefetch_related('buildings')
    config = GlobalConfiguration.objects.first()
    tanks = Tank.objects.all()
    context = {
        "building":building,
        "motors":motors,
        "config":config,
        "sites":sites,
        "masters":masters,
        "tanks":tanks
    }
    return render(request, "scada.html", context)



import snap7
from snap7.util import get_int, get_bool, get_real, get_dword
from snap7.type import Areas
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from .models import Motor

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
import snap7
from snap7.util import get_bool, get_int, get_real, get_dword
from snap7.type import Areas
from .models import Motor, Tank
from pprint import pprint

def fetchMotorAndTankData(request, motorID):
    motor = get_object_or_404(Motor, id=motorID)
    tank = Tank.objects.filter(motor=motor).first()

    PLC_IP = motor.ip
    RACK = motor.rack
    SLOT = motor.slot
    DB_NUMBER = motor.dbNo
    START_BYTE = motor.startByte
    DATA_SIZE = motor.dataSize or 256

    response = {"motor": {}, "tank": {}}

    try:
        plc = snap7.client.Client()
        plc.connect(PLC_IP, RACK, SLOT)

        if not plc.get_connected():
            return JsonResponse({"error": "PLC not connected"}, status=500)

        # Read DB once
        data = plc.read_area(Areas.DB, DB_NUMBER, START_BYTE, DATA_SIZE)

        # --- Motor fields ---
        for field_name, field_info in motor.fields.items():
            dtype = field_info[0]   # "BOOL", "INT", etc.
            offset1 = int(field_info[1])  # byte offset
            offset2 = int(field_info[2])  # bit offset or 0

            try:
                if dtype == "BOOL":
                    val = int(get_bool(data, offset1, offset2))
                elif dtype == "INT":
                    val = int(get_int(data, offset1))
                elif dtype == "REAL":
                    val = float(get_real(data, offset1))
                elif dtype == "DWORD":
                    val = int(get_dword(data, offset1))
                else:
                    val = None
            except Exception as e:
                val = f"Error: {str(e)}"

            trip = get_bool(data, int(motor.tripOffset["byte"]), int(motor.tripOffset["bit"]))
            isOn = get_bool(data, int(motor.motorOnOffset["byte"]), int(motor.motorOnOffset["bit"]))

            response["motor"][field_name] = val
            response["trip"] = bool(trip)
            response["isOn"] = isOn

        # --- Tank data ---
        if tank:
            try:
                high = get_bool(data, int(tank.highByte), int(tank.highBit))
                low = get_bool(data, int(tank.lowByte), int(tank.lowBit))
                try:
                    value = get_int(data, int(tank.valueByte))
                except:
                    value = 0
                print("Success")
                
            except Exception as e:
                high, low, value = False, False, 0

            response["tank"] = {"high": high, "low": low, "value": value, "tankVolume":tank.tankVolume}


        pprint(response)
        plc.disconnect()

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse(response, safe=False)


@require_POST
def save_motor(request):
    # --- Extract Motor fields ---
    motorName = request.POST.get("motorName")
    building_id = request.POST.get("building")
    ip = request.POST.get("ip")
    dbNo = request.POST.get("dbNo")
    rack = request.POST.get("rack")
    slot = request.POST.get("slot")
    startByte = request.POST.get("startByte")
    dataSize = request.POST.get("dataSize")
    tankName = request.POST.get("tankName")
    motorOnOffset = {
        "byte": int(request.POST.get("motorOnByte", 0)),
        "bit": int(request.POST.get("motorOnBit", 0))
    }
    motorOffOffset = {
        "byte": int(request.POST.get("motorOffByte", 0)),
        "bit": int(request.POST.get("motorOffBit", 1))
    }

    runFeedbackOffset = {
        "byte": int(request.POST.get("runFeedbackByte", 0)),
        "bit": int(request.POST.get("runFeedbackBit", 1))
    }

    tripOffset = {
        "byte": int(request.POST.get("tripByte", 0)),
        "bit": int(request.POST.get("tripBit", 1))
    }

    fields_raw = request.POST.get("fields", "{}")
    try:
        fields_data = json.loads(fields_raw)
    except json.JSONDecodeError:
        fields_data = {}

    building = get_object_or_404(Buildings, id=building_id)

    # --- Create Motor ---
    motor = Motor.objects.create(
        motorName=motorName,
        building=building,
        ip=ip,
        dbNo=int(dbNo) if dbNo else 0,
        rack=int(rack) if rack else 0,
        slot=int(slot) if slot else 0,
        startByte=int(startByte) if startByte else 0,
        dataSize=int(dataSize) if dataSize else 0,
        motorOnOffset=motorOnOffset,
        motorOffOffset=motorOffOffset,
        runFeedbackOffset=runFeedbackOffset,
        fields=fields_data,
        tripOffset=tripOffset
    )

    # --- Check if any Tank-related field is filled ---
    tank_fields = ["highByte", "lowByte", "highBit", "lowBit", "valueByte", "valueBit", "tankVolume"]
    if any(request.POST.get(f) for f in tank_fields):
        Tank.objects.create(
            motor=motor,
            highByte=request.POST.get("highByte", None),
            lowByte=request.POST.get("lowByte", None),
            highBit=request.POST.get("highBit", None),
            lowBit=request.POST.get("lowBit", None),
            valueByte=request.POST.get("valueByte", None),
            valueBit=request.POST.get("valueBit", None),
            tankVolume=request.POST.get("tankVolume", None),
            tankName=tankName
        )

    return redirect("/scada")

# views.py
import snap7
from snap7.util import set_bool, get_bool
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from .models import Motor

@csrf_exempt
@require_POST
def control_motor(request):
    PLC_CLIENT = snap7.client.Client()
    motor_id = request.POST.get("motor_id")
    action = request.POST.get("action")  # start / stop
    motor = Motor.objects.get(id=motor_id)

    try:
        PLC_CLIENT.connect(motor.ip, motor.rack, motor.slot)

        # Read DB block
        data = PLC_CLIENT.read_area(Areas.DB, motor.dbNo, motor.startByte, motor.dataSize)

        if action == "start":
            set_bool(data, motor.motorOnOffset["byte"], motor.motorOnOffset["bit"], True)
            set_bool(data, motor.motorOffOffset["byte"], motor.motorOffOffset["bit"], False)
        elif action == "stop":
            set_bool(data, motor.motorOnOffset["byte"], motor.motorOnOffset["bit"], False)
            set_bool(data, motor.motorOffOffset["byte"], motor.motorOffOffset["bit"], True)

        # Write modified data
        PLC_CLIENT.write_area(Areas.DB, motor.dbNo, motor.startByte, data)

        # Read back to update model
        data = PLC_CLIENT.read_area(Areas.DB, motor.dbNo, motor.startByte, motor.dataSize)
        i_motor_on = int(get_bool(data, motor.motorOnOffset["byte"], motor.motorOnOffset["bit"]))
        i_motor_off = int(get_bool(data, motor.motorOffOffset["byte"], motor.motorOffOffset["bit"]))
        run_feedback = get_bool(data, motor.runFeedbackOffset["byte"], motor.runFeedbackOffset["bit"])
        
        print(i_motor_off)
        print(i_motor_on)
        motor.isOn = bool(i_motor_on and not i_motor_off)
        # motor.isOn = run_feedback
        motor.save()

        return JsonResponse({"success": True, "isOn": bool(i_motor_on and not i_motor_off)})
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})
    finally:
        if PLC_CLIENT.get_connected():
            PLC_CLIENT.disconnect()


"""
import random
from scada.models import MotorMasters, Motor
from dynamic.models import Buildings

# fetch all existing areas
areas = list(Buildings.objects.all())

# create motor masters
master1 = MotorMasters.objects.create(masterType="Siemens S7-1200", ip="192.168.0.101", port=102)
master2 = MotorMasters.objects.create(masterType="Allen-Bradley PLC", ip="192.168.0.102", port=502)

# motor sample data
motor_data = [
    {"motorName": "Conveyor Motor 1", "rpm": 1450, "totalRunHour": 1200, "temperature": 45.2},
    {"motorName": "Conveyor Motor 2", "rpm": 1475, "totalRunHour": 980, "temperature": 46.7},
    {"motorName": "Hydraulic Pump Motor", "rpm": 1780, "totalRunHour": 3000, "temperature": 52.5},
    {"motorName": "Cooling Fan Motor", "rpm": 960, "totalRunHour": 1500, "temperature": 38.3},
    {"motorName": "Boiler Motor", "rpm": 1200, "totalRunHour": 2100, "temperature": 55.1},
    {"motorName": "Elevator Motor", "rpm": 1600, "totalRunHour": 500, "temperature": 41.9},
]

# randomly assign motors to masters and areas
for data in motor_data:
    master = random.choice([master1, master2])
    area = random.choice(areas)
    Motor.objects.create(
        motorName=data["motorName"],
        motorMaster=master,
        rpm=data["rpm"],
        totalRunHour=data["totalRunHour"],
        temperature=data["temperature"],
        building=area
    )


"""