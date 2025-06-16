from django.shortcuts import render, redirect
from .models import *
from dynamic.models import *
from datetime import datetime

sites = Site.objects.prefetch_related(
        'buildings__areas__meters'
    ).all()

# Create your views here.
def dashboard(request):
    dashboards = Dashboard.objects.all()
    gadgets = Gadgets.objects.all()
    meters = Meters.objects.all()
    context = {
        'sites': sites,
        'dashboards': dashboards,
        'gadgets': gadgets,
        'meters': meters,
    }
    return render(request, 'dashboard.html', context)

def indivDashboard(request, dashboardID):
    dashboard_ = Dashboard.objects.get(id=dashboardID)
    gadgets = Gadgets.objects.filter(dashboard=dashboard_).prefetch_related('meters')
    
    
    site = dashboard_.site
    # Get areas for this site
    areas = Areas.objects.filter(building__site=site).prefetch_related('meters')

    # Extract all meters in those areas
    meters = Meters.objects.filter(area__in=areas)

    # Get measurements of those meters
    measurements = Measurements.objects.filter(meter__in=meters)
    
    if not gadgets.exists():
        gadgets = None  # set to None if no gadgets found
    context = {
        'sites': sites,
        'dashboard': dashboard_,
        'gadgets': gadgets,
        'areas': areas,
        'meters':meters,
        'measurements':measurements
    }

    return render(request, 'indivDashboard.html', context)

def newDashboard(request):
    if request.method=='POST':
        title = request.POST['title']
        siteID = request.POST['site']
        site = Site.objects.get(id=siteID)
        Dashboard.objects.create(title=title, site=site).save()
    return redirect("/dashboard")

def newGadget(request, dashboardID):
    if request.method == 'POST':
        name = request.POST['name']
        gadget_type = request.POST['gadget_type']
        dashboard_ = Dashboard.objects.get(id=dashboardID)
        meters_ids = request.POST.getlist('meters')  # Get selected meter IDs from the form
        meters = Meters.objects.filter(id__in=meters_ids)  # Filter meters based on selected IDs
        measurementID = request.POST['measurement']
        measurement = Measurements.objects.get(id=measurementID)
        # Create the new gadget with the selected meters
        gadget = Gadgets.objects.create(name=name, gadget_type=gadget_type, dashboard=dashboard_, measurement=measurement)
        gadget.meters.set(meters)
        gadget.save()
        
    return redirect('/dashboard/'+str(dashboardID))