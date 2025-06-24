from django.shortcuts import render
from .models import *
from django.shortcuts import redirect
from django.db.models import Count, Prefetch
from dashboard.models import *

# Create your views here.
def configureDashboard(request):
    return render(request, "configureDashboard.html")


def settings(request):
    return render(request, 'settings.html')

def hierarchy(request):
    site = Site.objects.all().prefetch_related(
        Prefetch(
            'buildings',
            queryset=Buildings.objects.annotate(
                area_count=Count('areas'),
                meter_count=Count('areas__meters')
            ).prefetch_related('areas')
        )
    ).annotate(area_count=Count('buildings__areas', distinct=True), meter_count=Count('buildings__areas__meters', distinct=True))


    buildings = Buildings.objects.all().prefetch_related('areas', 'site').annotate(area_count=Count('areas', distinct=True), meter_count=Count('areas__meters', distinct=True))
    areas = Areas.objects.all().prefetch_related('meters__loadType', 'building__site', 'meters')

    load_types = LoadType.objects.all().prefetch_related('meters','meters__area__building__site')
    meters = Meters.objects.all().prefetch_related('gadgets', 'area__building__site', 'loadType')
    context = {
        'sites': site,
        'buildings': buildings,
        'areas': areas,
        'loadTypes': load_types,
        'meters': meters,
    }
    return render(request, 'hierarchy.html', context)

def addSite(request):
    if request.method == 'POST':
        Site.objects.create(name=request.POST.get('site_name'))
        return redirect("/settings/hierarchy")
    
def addBuilding(request):
    if request.method == 'POST':
        name = request.POST['building_name']
        site_id = request.POST['site_id']
        site = Site.objects.get(id=site_id)

        Buildings.objects.create(name=name, site=site)
        return redirect("/settings/hierarchy")
    
def addArea(request):
    if request.method == 'POST':
        name = request.POST['area_name']
        building_id = request.POST['building_id']
        building = Buildings.objects.get(id=building_id)

        Areas.objects.create(name=name, building=building)
        return redirect("/settings/hierarchy")
    

def addMeter(request):
    if request.method == 'POST':
        name = request.POST['meter_name']
        area_id = request.POST['area_id']
        area = Areas.objects.get(id=area_id)
        load_id = request.POST['load_id']
        load = LoadType.objects.get(id=load_id)
        meterType = request.POST['meterType']
        
        Meters.objects.create(name=name, area=area, loadType=load, meterType=meterType)
        return redirect("/settings/hierarchy")
    
def addLoadType(request):
    if request.method == 'POST':
        name = request.POST['load_name']
        LoadType.objects.create(name=name)
        return redirect("/settings/hierarchy")