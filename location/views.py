from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from dynamic.models import Site
from alarms.models import *
from django.contrib.auth.decorators import login_required

# Create your views here.
def triggerAlarm(request, siteID):
    site = get_object_or_404(Site, id=siteID)

    # Get all meters under this site:
    meters = Meters.objects.filter(area__building__site=site, ecological=True)

    # Get alarms for these meters:
    alarms = Alarms.objects.filter(meter__in=meters, acknowledged=False)
    alarm_active = alarms.exists()


    return JsonResponse({
        'alarm': alarm_active,
        'site': {
            'id': site.id,
            'name': site.name,
            'latitude': site.latitude,
            'longitude': site.longitude,
        }
    })


@login_required
def location(request):
    if request.user.is_superuser or request.user.userModel.first().role == 'Administrator':
        sites = Site.objects.all()
        context = {
            'sites': sites,
        }
        return render(request, 'location.html', context)
    else:
        return HttpResponse('You are not authorized to view this page')

