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



import csv
from django.conf import settings
import os

def indivDashboard(request, dashboardID):
    dashboard_ = Dashboard.objects.get(id=dashboardID)
    gadgets = Gadgets.objects.filter(dashboard=dashboard_).prefetch_related('meters')

    site = dashboard_.site
    areas = Areas.objects.filter(building__site=site).prefetch_related('meters')
    meters = Meters.objects.filter(area__in=areas)
    measurements = Measurements.objects.filter(meter__in=meters)
    all_files = Files.objects.filter(meter__in=meters)

    # Map gadget.id -> list of associated files
    gadget_files = {}
    gadget_csv_data = {}

    for gadget in gadgets:
        gadget_meters = gadget.meters.all()
        files = all_files.filter(meter__in=gadget_meters)
        gadget_files[gadget.id] = files

        # Optional: Load only the first file for preview
        if files.exists():
            first_file = files.first()
            file_path = os.path.join(settings.MEDIA_ROOT, str(first_file.file))
            try:
                with open(file_path, newline='') as csvfile:
                    reader = csv.reader(csvfile)
                    rows = list(reader)
                    gadget_csv_data[gadget.id] = rows[:20]  # Preview first 20 rows
            except Exception as e:
                gadget_csv_data[gadget.id] = [['Error reading file:', str(e)]]

    context = {
        'sites': sites,
        'dashboard': dashboard_,
        'gadgets': gadgets,
        'areas': areas,
        'meters': meters,
        'measurements': measurements,
        'gadget_files': gadget_files,
        'gadget_csv_data': gadget_csv_data
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
        try:
            measurementID = request.POST['measurement']
            measurement = Measurements.objects.get(id=measurementID)
        except:
            measurement = Measurements.objects.all()[0]
        # Create the new gadget with the selected meters
        gadget = Gadgets.objects.create(name=name, gadget_type=gadget_type, dashboard=dashboard_, measurement=measurement)
        gadget.meters.set(meters)
        gadget.save()
    return redirect('/dashboard/'+str(dashboardID))
