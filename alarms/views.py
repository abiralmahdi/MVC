from django.shortcuts import render, HttpResponse, redirect
from .models import *
from django.contrib.auth.decorators import login_required

# Create your views here.
@login_required
def allAlarms(request):
    config = GlobalConfiguration.objects.first()
    if request.user.is_superuser or request.user.userModel.first().role == 'Administrator':
        alarms = Alarms.objects.all().order_by('-date')
    else:
        alarms = Alarms.objects.filter(meter__area__building__site=request.user.userModel.first().site)

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
        "alarms": alarms,
        'config':config
    }
    return render(request, 'activeAlarms.html', context)

@login_required
def setAlarmRange(request):
    config = GlobalConfiguration.objects.first()
    if request.user.is_superuser or request.user.userModel.first().role == 'Administrator':
        meters = Meters.objects.all().prefetch_related('alarms')
        sites = Site.objects.all().prefetch_related('buildings')
        areas = Areas.objects.all().prefetch_related('meters')
        buildings = Buildings.objects.all().prefetch_related('areas')
    else:
        meters = Meters.objects.filter(area__building__site=request.user.userModel.first().site).prefetch_related('alarms')
        sites = Site.objects.filter(id=request.user.userModel.first().site.id).prefetch_related('buildings')
        areas = Areas.objects.filter(building__site=request.user.userModel.first().site).prefetch_related('meters')
        buildings = Buildings.objects.filter(site=request.user.userModel.first().site).prefetch_related('areas')

    measurements = {}
    for meter in meters:
        measurements[meter] = Measurements.objects.filter(meterType=meter.meterType)

    

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
        'config':config
    }

    return render(request, 'setAlarmRange.html', context)
@login_required
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

@login_required
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
    
@login_required
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
    