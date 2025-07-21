from django.shortcuts import render, redirect
from dynamic.models import *

# Create your views here.

def introPage(request):
    if request.user.is_superuser or request.user.userModel.first().role == 'Administrator':
        return redirect('/location')
    else:
        return redirect('/dashboard/siteDashboard/'+str(request.user.userModel.first().site.id))


def energyCostComparison(request):
    return render(request, 'energyCostComparison.html')

def plantSummary(request):
    return render(request, 'plantSummary.html')

def allUtilities(request):
    return render(request, 'allUtilities.html')

def plantHeatMaps(request):
    return render(request, "plantHeatMaps.html")

def sankeyDiagram(request):
    return render(request, 'sankeyDiagram.html')

def statusTable(request):
    return render(request, 'plantStatusTable.html')

def trends(request):
    return render(request, 'trends.html')

def activeAlarms(request):
    return render(request, 'activeAlarms.html')

def incidents(request):
    return render(request, 'incidents.html')

def addReport(request):
    return render(request, 'addReport.html')

def savedReports(request):
    return render(request, "savedReports.html")

