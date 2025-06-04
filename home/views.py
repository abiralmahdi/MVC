from django.shortcuts import render

# Create your views here.
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