from django.shortcuts import render, HttpResponse, redirect
from .models import *

# Create your views here.
def allAlarms(request):
    alarms = Alarms.objects.all()

    # Add a color property to each alarm
    for alarm in alarms:
        if alarm.acknowledged:
            alarm.color = "green"
        elif "high" in alarm.alarmType.lower():
            alarm.color = "red"
        elif "low" in alarm.alarmType.lower():
            alarm.color = "rgb(179, 179, 21)"
        else:
            alarm.color = "white"

    context = {
        "alarms": alarms
    }
    return render(request, 'activeAlarms.html', context)


def setAlarmRange(request):
    meters = Meters.objects.all().prefetch_related('alarms')
    measurements = {}
    for meter in meters:
        measurements[meter] = Measurements.objects.filter(meterType=meter.meterType)

    sites = Site.objects.all().prefetch_related('buildings')
    areas = Areas.objects.all().prefetch_related('meters')
    buildings = Buildings.objects.all().prefetch_related('areas')

    # Build alarmsRange lookup as a dict with a string key: "meterID-measurementID"
    alarmsRange_qs = AlarmsRange.objects.all()
    alarmsRange = {}
    for r in alarmsRange_qs:
        alarmsRange[f"{r.meter.id}-{r.measurement.id}"] = r

    context = {
        "meters": meters,
        "measurements": measurements,
        "alarmsRange": alarmsRange,
        "sites": sites,
        "areas": areas,
        "buildings": buildings,
    }

    return render(request, 'setAlarmRange.html', context)

def setRange(request, meterID):
    if request.method == 'POST':
        for key in request.POST:
            if key.startswith('min_value_'):
                measurementID = key.split('_')[2]
                minVal = request.POST.get(f'min_value_{measurementID}')
                maxVal = request.POST.get(f'max_value_{measurementID}')

                if minVal == '' or maxVal == '':
                    continue  # skip if blank

                rangeVal, created = AlarmsRange.objects.get_or_create(
                    measurement=Measurements.objects.get(id=measurementID),
                    meter=Meters.objects.get(id=meterID)
                )
                rangeVal.minValue = float(minVal)
                rangeVal.maxValue = float(maxVal)
                rangeVal.save()

        return redirect('/alarms/setAlarmRange')


def ackAlarm(request, alarmID):
    try:
        alarm = Alarms.objects.get(id=alarmID)
        alarm.acknowledged = True
        alarm.save()
        return redirect('/alarms/allAlarms')
    except Alarms.DoesNotExist:
        return HttpResponse("Alarm not found", status=404)
    except Exception as e:
        return HttpResponse(f"An error occurred: {e}", status=500)
    

def changeAlarmDesc(request, meterID):
    if request.method == 'POST':
        new_desc = request.POST.get('desc-'+str(meterID))
        try:
            meter = Meters.objects.get(id=meterID)
            alarms = Alarms.objects.filter(meter=meter)
            for alarm in alarms:
                alarm.desc = new_desc
                alarm.save()
            return redirect('/alarms/allAlarms')
        except Alarms.DoesNotExist:
            return HttpResponse("Alarm not found", status=404)
        except Exception as e:
            return HttpResponse(f"An error occurred: {e}", status=500)
    else:
        return HttpResponse("Invalid request method", status=405)